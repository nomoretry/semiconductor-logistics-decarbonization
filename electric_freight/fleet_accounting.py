"""Recompute a model-v2 plan from its decisions alone and list every violated rule.

Inputs are the decisions: which week type every week takes, how every order travels, each round trip (truck,
departure, dwell), charging power and connector time per truck, site and hour, and the first stage. Truck positions,
energy, connector use, site and substation load, costs and emissions are recomputed here; nothing is read from a
solver constraint or objective. Costs per week type are counted once for every week that takes it.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import pairwise
from math import isclose
from typing import Any

from .data import capital_share
from .fleet import Scenario, departure_cost, diesel_litres, leg, windows_of
from .model import ROAD_CHANNELS, dispatch_windows

TOL = 1e-4


def verify_cost(account: dict[str, Any], objective: float, label: str) -> None:
    """Accounting returns USD to four decimals. Keep raw differences and reject discrepancies over half a cent."""
    total = account.get("total_cost_usd")
    if account["issues"] or total is None or not isclose(total, objective, rel_tol=0, abs_tol=0.005):
        message = (f"ACCOUNTING FAILURE {label}: independent total {total}, objective {objective}, "
                   f"issues {account['issues']}")
        print(message, flush=True)
        raise ValueError(message)


def audit_plan(config: dict[str, Any], sc: Scenario, result: dict[str, Any], mode: str) -> dict[str, Any]:
    account = evaluate(config, sc, result["first_stage"], result["solution"][sc.name], mode=mode)
    verify_cost(account, result["objective_usd"], f"{sc.name}/{mode}")
    return account


def evaluate_horizon(config: dict[str, Any], sc: Scenario, result: dict[str, Any],
                     week_types: dict[str, str]) -> dict[str, Any]:
    """Audit the unbroken horizon, paying the first stage only in the free-equipment comparison."""
    cfg, ops, stage = sc.config, result["operations"], result["first_stage"]
    weeks = len(sc.conditions)
    issues: list[str] = []
    cost: dict[str, float] = defaultdict(float)
    capacity = _first_stage(config, stage["plant"], cost, issues)
    cost["lease"] = sum(cfg["fleet"]["lease"][k]["usd_per_week"] * weeks * v for k, v in stage["lease"].items())
    windows = [window for w in range(weeks) for window in windows_of(cfg, sc.instance, 168 * w)]
    target = [int(week_types[str(w + 1)].split("|")[1]) for w in range(weeks)]
    record = _trip_record(cfg, ops, sc.conditions, windows, target, stage["lease"], issues, "horizon")
    energy = _energy(cfg, stage["plant"], capacity, ops, record, "joint", issues, "horizon")
    cost["trips"], cost["waiting"], cost["energy"] = record["trip_cost"], record["waiting_cost"], energy["bill"]
    cost["carbon"] = sum(cfg["carbon"]["price_usd_per_t"] / 1000 * cfg["sites"][j]["grid_kg_co2e_per_kwh"] * kwh
                         for j, kwh in energy["kwh"].items())
    cost["demand_charge"] = sum(cfg["sites"][j]["demand_usd_per_kw_month"] * peak for j, peak in energy["peak"].items()
                                ) * weeks / cfg["finance"]["weeks_per_month"]
    total = sum(v for k, v in cost.items() if result["free_first_stage"] or k not in ("equipment", "lease"))
    account = {"total_cost_usd": round(total, 4), "cost_usd": dict(cost), "peak_kw": energy["peak"], "issues": issues}
    verify_cost(account, result["objective_usd"], f"{sc.name}/horizon")
    return account


def evaluate(config: dict[str, Any], sc: Scenario, first_stage: dict[str, Any], solution: dict[str, Any], *,
             mode: str) -> dict[str, Any]:
    cfg = sc.config
    weeks = len(sc.conditions)
    issues: list[str] = []
    cost: dict[str, float] = defaultdict(float)
    emissions: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for w, typ in solution["week_types"].items():
        condition = typ.split("|")[0]
        if condition != sc.conditions[int(w) - 1]:
            issues.append(f"week {w}: type {typ} does not match the crossing condition")
        counts[typ] += 1
    if len(solution["week_types"]) != weeks:
        issues.append("not every week has a week type")
    _cargo(cfg, sc, solution, counts, cost, emissions, issues)
    lease = first_stage.get("lease", {})
    cost["lease"] = sum(cfg["fleet"]["lease"][k]["usd_per_week"] * weeks * v for k, v in lease.items())
    plant = first_stage.get("plant")
    capacity: dict[str, float] = {}
    if mode == "joint":
        if plant is None:
            issues.append("no first stage")
            return {"issues": issues}
        capacity = _first_stage(config, plant, cost, issues)
    peak: dict[str, float] = defaultdict(float)
    kwh: dict[str, float] = defaultdict(float)
    carbon = float(cfg["carbon"]["price_usd_per_t"]) / 1000
    for typ, n_weeks in counts.items():
        ops = solution["types"].get(typ)
        if ops is None:
            issues.append(f"week type {typ} is used but has no operations")
            continue
        condition, extra = typ.split("|")[0], int(typ.split("|")[1])
        record = _trips(cfg, sc, ops, condition, extra, lease, issues, typ)
        cost["trips"] += n_weeks * record["trip_cost"]
        cost["waiting"] += n_weeks * record["waiting_cost"]
        if mode == "diesel":
            litres = len(ops["trips"]) * diesel_litres(cfg, condition)
            cost["diesel"] += n_weeks * litres * cfg["diesel"]["price_usd_per_litre"]
            cost["carbon"] += carbon * n_weeks * litres * cfg["diesel"]["kg_co2e_per_litre"]
            emissions["diesel"] += n_weeks * litres * cfg["diesel"]["kg_co2e_per_litre"]
            continue
        energy = _energy(cfg, plant if mode == "joint" else None, capacity, ops, record, mode, issues, typ)
        for j, value in energy["kwh"].items():
            kwh[j] += n_weeks * value
        for j, value in energy["peak"].items():
            peak[j] = max(peak[j], value)
        cost["energy"] += n_weeks * energy["bill"]
    if mode == "joint":
        months = weeks / float(cfg["finance"]["weeks_per_month"])
        cost["demand_charge"] = sum(cfg["sites"][j]["demand_usd_per_kw_month"] * months * peak[j] for j in peak)
        for j, value in kwh.items():
            emissions["electricity"] += cfg["sites"][j]["grid_kg_co2e_per_kwh"] * value
            cost["carbon"] += carbon * cfg["sites"][j]["grid_kg_co2e_per_kwh"] * value
    elif mode == "relaxed":
        emissions["electricity_unassigned"] = 0.0
    total = sum(cost.values())
    return {"total_cost_usd": round(total, 4), "cost_usd": {k: round(v, 4) for k, v in cost.items()},
            "total_emissions_kg": round(sum(emissions.values()), 3),
            "emissions_kg": {k: round(v, 3) for k, v in emissions.items()},
            "energy_kwh": {j: round(v, 3) for j, v in kwh.items()},
            "peak_kw": {j: round(v, 3) for j, v in peak.items()},
            "week_type_counts": dict(counts), "issues": issues}


def _cargo(cfg: dict[str, Any], sc: Scenario, solution: dict[str, Any], counts: dict[str, int],
           cost: dict[str, float], emissions: dict[str, float], issues: list[str]) -> None:
    carrier = cfg["carrier"]
    holding = float(cfg["cargo"].get("holding_multiplier", 1.0))
    carbon = float(cfg["carbon"]["price_usd_per_t"]) / 1000
    orders = {o.id: o for o in sc.orders}
    windows = {o.id: dict(dispatch_windows(o, cfg, sc.conditions)) for o in sc.orders}
    served: dict[str, float] = defaultdict(float)
    load: dict[tuple[int, str], float] = defaultdict(float)
    for item in solution["shipments"]:
        order, week, channel, units = orders[item["order"]], int(item["week"]), item["channel"], float(item["units"])
        if channel not in ROAD_CHANNELS or week not in windows[order.id]:
            issues.append(f"{order.id}: week {week} or channel {channel} not allowed")
            continue
        early = windows[order.id][week]
        served[order.id] += units
        load[week, channel] += units * order.mass_kg
        cost["holding"] += holding * order.holding_usd_per_unit_week * max(early, 0) * units
        cost["backlog"] += order.backlog_usd_per_unit_week * max(-early, 0) * units
        if channel == "premium":
            cost["displaced_cargo"] += carrier["premium_usd_per_kg"] * order.mass_kg * units
    flown: dict[int, float] = defaultdict(float)
    for item in solution["air"]:
        order = orders[item["order"]]
        served[order.id] += float(item["units"])
        flown[order.due_week] += float(item["units"]) * order.mass_kg
        cost["air_freight"] += sc.air["spot_usd_per_kg"] * order.mass_kg * float(item["units"])
        cost["carbon"] += carbon * sc.air["kg_co2e_per_kg"] * order.mass_kg * float(item["units"])
        emissions["air_freight"] += sc.air["kg_co2e_per_kg"] * order.mass_kg * float(item["units"])
    for oid, order in orders.items():
        if abs(served[oid] - order.units) > TOL * max(1.0, order.units):
            issues.append(f"{oid}: {served[oid]:.4f} of {order.units:.4f} units delivered")
    for week, kg in flown.items():
        if kg > sc.air["available_kg"][week - 1] + TOL:
            issues.append(f"week {week}: {kg:.2f} kg by air above the space left")
    factor = float(cfg["congestion"]["consolidation_factor"])
    for w, typ in solution["week_types"].items():
        week = int(w)
        scale = factor if sc.conditions[week - 1] == "congested" else 1.0
        limits = {"consolidated": carrier["weekly_consolidation_kg"] * scale,
                  "premium": carrier["premium_kg_per_week"] * scale,
                  "extra_trip": carrier["extra_trip_chip_capacity_kg"] * int(typ.split("|")[1])}
        for channel, limit in limits.items():
            if load[week, channel] > limit + TOL * max(1.0, limit):
                issues.append(f"week {week}: {load[week, channel]:.2f} kg on {channel} above {limit:.2f}")


def _first_stage(config: dict[str, Any], plant: dict[str, Any], cost: dict[str, float],
                 issues: list[str]) -> dict[str, float]:
    share = capital_share(config, int(config["horizon"]["weeks"]))
    capacity = {}
    for j, site in config["sites"].items():
        opened = plant["open"].get(j, 0)
        connectors = {q: plant["n"].get(f"{j}|{q}", 0) for q in site["tiers"]}
        if sum(connectors.values()) > site["max_connectors"] * opened:
            issues.append(f"{j}: connectors at a closed site or above its limit")
        ups = [u for u in site["upgrades"] if plant["up"].get(f"{j}|{u['id']}", 0)]
        wires = [s for s in site["connections"] if plant["conn"].get(f"{j}|{s}", 0)]
        if len(ups) > opened or len(wires) != opened:
            issues.append(f"{j}: upgrades or connections do not match the opening decision")
        capacity[j] = site["base_kw"] * opened + sum(u["kw"] for u in ups)
        cost["equipment"] += share * (site["open_capex_usd"] * opened
                                      + sum(site["tiers"][q]["capex_usd"] * n for q, n in connectors.items())
                                      + sum(u["capex_usd"] for u in ups)
                                      + sum(site["connections"][s] for s in wires))
    for s, sub in config["substations"].items():
        for x in sub["expansions"]:
            if plant["exp"].get(f"{s}|{x['id']}", 0):
                cost["equipment"] += share * x["capex_usd"]
    return capacity


def _trips(cfg: dict[str, Any], sc: Scenario, ops: dict[str, Any], condition: str, extra: int,
           lease: dict[str, int], issues: list[str], typ: str) -> dict[str, Any]:
    return _trip_record(cfg, ops, [condition], windows_of(cfg, sc.instance), [extra], lease, issues, typ)


def _trip_record(cfg: dict[str, Any], ops: dict[str, Any], conditions: list[str], windows: list[list[int]],
                 extra: list[int], lease: dict[str, int], issues: list[str], typ: str) -> dict[str, Any]:
    corridor = cfg["corridor"]
    h_min, h_max = int(corridor["sg_min_dwell_hours"]), int(corridor["sg_max_dwell_hours"])
    turnaround = int(corridor["my_min_turnaround_hours"])
    slots = 168 * len(conditions)
    served = [0] * len(windows)
    extras = [0] * len(conditions)
    trip_cost = waiting = 0.0
    by_truck: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trip in ops["trips"]:
        s, h = int(trip["depart"]), int(trip["dwell"])
        condition = conditions[s // 168]
        outbound, out_kwh = leg(cfg, condition)
        back = s + outbound + h
        inbound, back_kwh = leg(cfg, conditions[min(back // 168, len(conditions) - 1)])
        if not h_min <= h <= h_max:
            issues.append(f"{typ}/{trip['truck']}: dwell {h} h outside {h_min}-{h_max}")
        if back + inbound >= slots:
            issues.append(f"{typ}/{trip['truck']}: trip leaving at {s} returns outside the horizon")
        if trip["truck"] in lease and not lease[trip["truck"]]:
            issues.append(f"{typ}/{trip['truck']}: trip by a truck that is not leased")
        kind = trip["kind"]
        if kind.startswith("task"):
            b = int(kind[4:])
            if s not in windows[b]:
                issues.append(f"{typ}: background trip {b} leaves at {s}, outside its window")
            served[b] += 1
        else:
            extras[s // 168] += 1
        trip_cost += departure_cost(cfg, s, condition)
        waiting += corridor["waiting_usd_per_hour"] * (h - h_min)
        by_truck[trip["truck"]].append({"s": s, "arrive": s + outbound, "back": back, "home": back + inbound,
                                        "out_kwh_per_hour": out_kwh / outbound,
                                        "back_kwh_per_hour": back_kwh / inbound})
    if served != [1] * len(windows):
        issues.append(f"{typ}: background trips served {served}")
    if extras != extra:
        issues.append(f"{typ}: {extras} extra trips, type says {extra}")
    for k, trips in by_truck.items():
        trips.sort(key=lambda t: t["s"])
        for before, after in pairwise(trips):
            if after["s"] < before["home"] + turnaround:
                issues.append(f"{typ}/{k}: leaves at {after['s']} before loading after coming home at {before['home']}")
    return {"trip_cost": trip_cost, "waiting_cost": waiting, "by_truck": by_truck, "slots": slots}


def _energy(cfg: dict[str, Any], plant: dict[str, Any] | None, capacity: dict[str, float], ops: dict[str, Any],
            record: dict[str, Any], mode: str, issues: list[str], typ: str) -> dict[str, Any]:
    truck = cfg["truck"]
    slots = record["slots"]
    site_power: dict[str, list[float]] = defaultdict(lambda: [0.0] * slots)
    site_plugs: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0] * slots)
    bill = 0.0
    trucks = set(ops["energy_kwh"]) | set(record["by_truck"])
    for k in trucks:
        trips = record["by_truck"].get(k, [])
        place = ["MY"] * slots
        drive = [0.0] * slots
        settled = [0] * slots  # hours already spent at the destination
        for trip in trips:
            for t in range(trip["s"], trip["arrive"]):
                place[t], drive[t] = "road", trip["out_kwh_per_hour"]
            for t in range(trip["arrive"], trip["back"]):
                place[t], settled[t] = "SG", t - trip["arrive"]
            for t in range(trip["back"], trip["home"]):
                place[t], drive[t] = "road", trip["back_kwh_per_hour"]
        level = truck["battery_usable_kwh"] if cfg["truck"]["week_boundary"] == "full" else ops["energy_kwh"][k][0]
        start = level
        powers = ops["power_kw"].get(k, {})
        plugs = ops["occupancy"].get(k, {})
        for t in range(slots):
            charged = 0.0
            for j, series in powers.items():
                p = float(series.get(str(t), 0.0))
                if p <= TOL:
                    continue
                side = "MY" if mode == "relaxed" and j == "MY" else ("SG" if mode == "relaxed" else
                                                                       cfg["sites"][j]["side"])
                if place[t] != side:
                    issues.append(f"{typ}/{k}: charges at {j} in hour {t} while {place[t]}")
                if mode == "joint":
                    site = cfg["sites"][j]
                    if t % 24 in {h % 24 for h in site["unavailable_hours_of_day"]}:
                        issues.append(f"{typ}/{k}: charges at {j} in a closed hour {t}")
                    if side == "SG" and settled[t] < site["access_delay_hours"]:
                        issues.append(f"{typ}/{k}: charges at {j} before it can be reached ({t})")
                    rating = sum(site["tiers"][q]["kw"] * float(plugs.get(j, {}).get(q, {}).get(str(t), 0.0))
                                 for q in site["tiers"])
                    if p > rating + TOL:
                        issues.append(f"{typ}/{k}: {p:.2f} kW at {j} in hour {t} above its connector time")
                    for q in site["tiers"]:
                        site_plugs[j, q][t] += float(plugs.get(j, {}).get(q, {}).get(str(t), 0.0))
                    bill += site["energy_usd_per_kwh"] * p
                else:
                    bill += cfg["planning"]["energy_usd_per_kwh"] * p
                site_power[j][t] += p
                charged += p
            if charged > truck["vehicle_max_charge_kw"] + TOL:
                issues.append(f"{typ}/{k}: {charged:.1f} kW above the vehicle limit in hour {t}")
            level += truck["charging_efficiency"] * charged - drive[t]
            if not truck["min_energy_kwh"] - TOL <= level <= truck["battery_usable_kwh"] + TOL:
                issues.append(f"{typ}/{k}: energy {level:.2f} kWh out of bounds after hour {t}")
                break
        if level < start - TOL:
            issues.append(f"{typ}/{k}: ends the week at {level:.2f} kWh, below its start {start:.2f}")
    peak = {j: max(series) for j, series in site_power.items()}
    kwh = {j: sum(series) for j, series in site_power.items()}
    if mode == "joint" and plant is not None:
        for (j, q), series in site_plugs.items():
            if max(series) > plant["n"].get(f"{j}|{q}", 0) + TOL:
                built = plant["n"].get(f"{j}|{q}", 0)
                issues.append(f"{typ}/{j}: {max(series):.3f} {q} connectors in use, {built} built")
        for j, series in site_power.items():
            if max(series) > capacity.get(j, 0) + TOL:
                issues.append(f"{typ}/{j}: {max(series):.1f} kW above its connection of {capacity.get(j, 0):.1f} kW")
        load: dict[str, list[float]] = defaultdict(lambda: [0.0] * slots)
        for j, series in site_power.items():
            wired = [s for s in cfg["sites"][j]["connections"] if plant["conn"].get(f"{j}|{s}", 0)]
            if len(wired) != 1:
                issues.append(f"{typ}/{j}: draws power but is wired to {wired}")
                continue
            for t, value in enumerate(series):
                load[wired[0]][t] += value
        for s, series in load.items():
            sub = cfg["substations"][s]
            limit = sub["headroom_kw"] + sum(x["kw"] for x in sub["expansions"]
                                             if plant["exp"].get(f"{s}|{x['id']}", 0))
            if max(series) > limit + TOL:
                issues.append(f"{typ}/{s}: {max(series):.1f} kW above its headroom {limit:.1f} kW")
    return {"bill": bill, "peak": peak, "kwh": kwh}
