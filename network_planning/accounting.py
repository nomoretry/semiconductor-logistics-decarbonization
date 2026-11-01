"""Independent accounting for planning solutions.

Recomputes flows, inventory, costs and emissions from the decisions alone
(shipments, air reserved/spot split, lane activations, order flags and air
reservations) plus the scenario data. It never reads the solver objective or
the solver's inventory variables to compute a number; the solver objective
must agree with this recomputation and any violated constraint is reported.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

COST_KEYS = ("freight", "transit_capital", "holding", "backlog", "terminal_shortfall",
             "fixed", "order_fees", "air_reservation")


def evaluate(net, scenarios, solution, *, carbon_price=0.0, sku_order_fee=0.0, carbon_cap_kg=None,
             service_level=None, terminal_hard=False) -> dict:
    S, T = len(net.skus), net.weeks
    mass = np.array([s.mass_kg for s in net.skus])
    value = np.array([s.value_usd for s in net.skus])
    penalty = np.array([s.backlog_usd for s in net.skus])
    reserve = solution.get("reserve", {})
    reservation = sum(net.reservation_usd_per_kg_week * T * kg for kg in reserve.values())
    issues, per = [], {}
    for k, sc in enumerate(scenarios):
        demand = net.demand_for(sc)
        arrivals = np.zeros((S, T))
        load = defaultdict(float)
        mode_kg = defaultdict(float)
        cost = dict.fromkeys(COST_KEYS, 0.0)
        cost["air_reservation"] = reservation
        transport_kg = 0.0
        for (kk, s, lane_id, t), units in solution["ship"].items():
            if kk != k or units <= 0:
                continue
            lane, week = net.lanes[lane_id], t + 1
            lead = sc.lead(lane, week)
            if t + lead < T:
                arrivals[s, t + lead] += units
            kg = mass[s] * units
            load[lane_id, t] += kg
            mode_kg[lane.mode] += kg
            cost["transit_capital"] += value[s] * net.carry_rate_week * lead * units
            transport_kg += kg / 1000 * sc.distance(lane, week) * lane.ef_kg_per_tkm
            if not lane.is_air:
                cost["freight"] += lane.freight_usd_per_kg * sc.cost_factor(lane, week) * kg
            if sku_order_fee and not solution.get("order", {}).get((k, s, lane_id, t)):
                issues.append(f"{sc.name}: shipment of SKU {s} on {lane_id} week {week} without an order flag")
        cost["order_fees"] = sku_order_fee * sum(1 for key, v in solution.get("order", {}).items()
                                                 if key[0] == k and v)
        for lane_id, lane in net.lanes.items():
            for t in range(T):
                week, kg = t + 1, load.get((lane_id, t), 0.0)
                active = solution["act"].get((k, lane_id, t), 0)
                cost["fixed"] += lane.fixed_usd * active
                tolerance = 1e-5 * max(1.0, kg)
                if lane.is_air:
                    res = solution["air_res"].get((k, lane_id, t), 0.0)
                    spot = solution["air_spot"].get((k, lane_id, t), 0.0)
                    cost["freight"] += lane.freight_usd_per_kg * (
                        res + net.air_spot_premium * sc.cost_factor(lane, week) * spot)
                    if abs(res + spot - kg) > tolerance:
                        issues.append(f"{sc.name}: air split {res + spot:.3f} != load {kg:.3f} on {lane_id} week {week}")
                    if res > reserve.get(lane_id, 0.0) + 1e-6:
                        issues.append(f"{sc.name}: reserved air use exceeds reservation on {lane_id} week {week}")
                    if spot > sc.capacity(lane, week) + 1e-6:
                        issues.append(f"{sc.name}: air spot capacity exceeded on {lane_id} week {week}")
                elif kg > sc.capacity(lane, week) + tolerance:
                    issues.append(f"{sc.name}: capacity exceeded on {lane_id} week {week}")
                if kg > 1e-9 and not active:
                    issues.append(f"{sc.name}: shipment on inactive lane {lane_id} week {week}")
        position = net.initial_inventory.astype(float).copy()
        inv, back = np.zeros((S, T)), np.zeros((S, T))
        for t in range(T):
            position = position + arrivals[:, t] + net.pipeline[:, t] - demand[:, t]
            inv[:, t], back[:, t] = np.maximum(position, 0), np.maximum(-position, 0)
        if "inv" in solution:
            solver_position = solution["inv"][k] - solution["back"][k]
            gap = float(np.abs(solver_position - (inv - back)).max(initial=0.0))
            if gap > 1e-4:
                issues.append(f"{sc.name}: solver inventory differs from recomputed balance by {gap:.6f}")
        cost["holding"] = float(((value * net.carry_rate_week + net.warehouse_usd)[:, None] * inv).sum())
        cost["backlog"] = float((penalty[:, None] * back).sum())
        shortfall = np.maximum(net.terminal_target - (inv[:, -1] - back[:, -1]), 0)
        if terminal_hard:
            if shortfall.max(initial=0.0) > 1e-6:
                issues.append(f"{sc.name}: hard terminal stock target violated")
        else:
            cost["terminal_shortfall"] = float((penalty * net.terminal_penalty_weeks * shortfall).sum())
        warehouse_kg = net.warehouse_kg * float(inv.sum())
        shipped = sum(mode_kg.values())
        per[sc.name] = {
            "probability": sc.probability,
            "total_cost_usd": sum(cost.values()),
            "cost_breakdown_usd": cost,
            "emissions_t": (transport_kg + warehouse_kg) / 1000,
            "transport_emissions_t": transport_kg / 1000,
            "warehouse_emissions_t": warehouse_kg / 1000,
            "shipped_kg": shipped,
            "mode_kg": dict(mode_kg),
            "air_share_kg": mode_kg.get("air", 0.0) / shipped if shipped else 0.0,
            "backlog_unit_weeks": float(back.sum()),
            "demand_units": float(demand.sum()),
            "service_level": 1 - float(back.sum()) / max(1.0, float(demand.sum())),
            "terminal_shortfall_units": float(shortfall.sum()),
        }
    expected = _expected(per)
    expected["carbon_tax_usd"] = carbon_price * expected["emissions_t"]
    if carbon_cap_kg is not None and expected["emissions_t"] * 1000 > carbon_cap_kg * (1 + 1e-6) + 1e-6:
        issues.append("expected emissions exceed the carbon cap")
    if service_level is not None:
        ratio = sum(p["probability"] * p["backlog_unit_weeks"] for p in per.values()) / max(
            1.0, sum(p["probability"] * p["demand_units"] for p in per.values()))
        if ratio > 1 - service_level + 1e-6:
            issues.append("expected backorder ratio exceeds the service limit")
    return {"expected": expected, "per_scenario": per, "issues": issues,
            "objective": expected["total_cost_usd"] + expected["carbon_tax_usd"]}


def _expected(per: dict) -> dict:
    result: dict = {}
    for p in per.values():
        w = p["probability"]
        for key, value in p.items():
            if key == "probability":
                continue
            if isinstance(value, dict):
                bucket = result.setdefault(key, {})
                for name, v in value.items():
                    bucket[name] = bucket.get(name, 0.0) + w * v
            else:
                result[key] = result.get(key, 0.0) + w * value
    shipped = result.get("shipped_kg", 0.0)
    result["air_share_kg"] = result.get("mode_kg", {}).get("air", 0.0) / shipped if shipped else 0.0
    return result
