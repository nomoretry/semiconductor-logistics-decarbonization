"""Decision analyses on top of the planning model.

* scenario_impact: perfect-information plan per scenario versus normal.
* carbon_frontier: epsilon-constraint cost-emissions frontier, marginal
  abatement cost (finite differences) and LP shadow prices of the cap.
* carbon_price_sweep: plans under a carbon price instead of a cap.
* stochastic_value: RP, EEV, WS, VSS and EVPI with intervals that account
  for the remaining MIP gap (dual bounds).
* scale_benchmark: model size and HiGHS solve time as the portfolio grows.
* explain_plan: binding capacities, mode mix and cost drivers of a plan.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from .data import Network, build_network
from .model import Plan, solve


def plan_row(plan: Plan, **extra: Any) -> dict[str, Any]:
    row = dict(extra)
    row.update(status=plan.status, solve_seconds=plan.stats.get("solve_seconds"), mip_gap=plan.stats.get("mip_gap"))
    if plan.feasible:
        k = plan.metrics
        row.update(total_cost_usd=round(k["total_cost_usd"], 2), emissions_t=round(k["emissions_t"], 4),
                   air_share_kg=round(k["air_share_kg"], 4), service_level=round(k["service_level"], 5),
                   backlog_unit_weeks=round(k["backlog_unit_weeks"], 2),
                   terminal_shortfall_units=round(k["terminal_shortfall_units"], 2))
    return row


def scenario_impact(net: Network, names: Sequence[str] | None = None, *, mip_gap: float = 1e-3,
                    time_limit: float = 60) -> list[dict[str, Any]]:
    names = names or list(net.scenario_specs)
    plans = {n: solve(net, [net.scenario(n, 1.0)], mip_gap=mip_gap, time_limit=time_limit) for n in names}
    base = plans.get("normal") or solve(net, mip_gap=mip_gap, time_limit=time_limit)
    rows = []
    for name, plan in plans.items():
        row = plan_row(plan, scenario=name)
        if plan.feasible and base.feasible:
            k, b = plan.metrics, base.metrics
            row["cost_change_pct"] = round(100 * (k["total_cost_usd"] / b["total_cost_usd"] - 1), 3)
            row["emissions_change_pct"] = round(100 * (k["emissions_t"] / b["emissions_t"] - 1), 3)
        rows.append(row)
    return rows


def carbon_frontier(net: Network, scenario: str = "normal",
                    levels: Sequence[float] = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3), *,
                    service_level: float | None = 0.98, mip_gap: float = 1e-3,
                    time_limit: float = 60) -> dict[str, Any]:
    sc = net.scenario(scenario, 1.0)
    common: dict[str, Any] = dict(service_level=service_level, terminal_hard=True, mip_gap=mip_gap,
                                  time_limit=time_limit)
    base = solve(net, [sc], **common)
    if not base.feasible:
        return {"scenario": scenario, "status": base.status, "points": []}
    e0, c0 = base.metrics["emissions_t"], base.metrics["total_cost_usd"]
    points = [plan_row(base, level=1.0, cap_t=None)]
    previous = points[0]
    for level in levels:
        plan = solve(net, [sc], carbon_cap_kg=level * e0 * 1000, duals=True, **common)
        row = plan_row(plan, level=level, cap_t=round(level * e0, 4))
        if plan.feasible:
            row["cost_increase_pct"] = round(100 * (plan.metrics["total_cost_usd"] / c0 - 1), 3)
            row["mac_vs_baseline_usd_per_t"] = _slope(c0, plan.metrics["total_cost_usd"], e0,
                                                      plan.metrics["emissions_t"])
            row["mac_step_usd_per_t"] = _slope(previous["total_cost_usd"], plan.metrics["total_cost_usd"],
                                               previous["emissions_t"], plan.metrics["emissions_t"])
            row["shadow_price_usd_per_t"] = _round(plan.duals.get("carbon_usd_per_t"))
            previous = row
        points.append(row)
    floor = solve(net, [sc], objective="emissions", **common)
    return {"scenario": scenario, "service_level": service_level, "baseline_cost_usd": round(c0, 2),
            "baseline_emissions_t": round(e0, 4), "points": points,
            "min_emissions_t": round(floor.metrics["emissions_t"], 4) if floor.feasible else None,
            "min_emissions_cost_usd": round(floor.metrics["total_cost_usd"], 2) if floor.feasible else None,
            "max_reduction_pct": round(100 * (1 - floor.metrics["emissions_t"] / e0), 2) if floor.feasible else None}


def carbon_price_sweep(net: Network, scenario: str = "normal",
                       prices: Sequence[float] = (0, 50, 100, 200, 400, 800, 1600, 3200), *,
                       mip_gap: float = 1e-3, time_limit: float = 60) -> list[dict[str, Any]]:
    sc = net.scenario(scenario, 1.0)
    rows = []
    for price in prices:
        plan = solve(net, [sc], carbon_price=price, mip_gap=mip_gap, time_limit=time_limit)
        row = plan_row(plan, carbon_price_usd_per_t=price)
        if plan.feasible:
            row["carbon_tax_usd"] = round(plan.metrics["carbon_tax_usd"], 2)
        rows.append(row)
    return rows


def stochastic_value(net: Network, names: Sequence[str] | None = None,
                     probabilities: Sequence[float | None] | None = None, *, reveal_week: int = 3,
                     nominal: str = "normal", mip_gap: float = 1e-3, time_limit: float = 120) -> dict[str, Any]:
    scenarios = net.scenarios(names, probabilities)
    settings: dict[str, Any] = dict(mip_gap=mip_gap, time_limit=time_limit)
    rp = solve(net, scenarios, reveal_week=reveal_week, **settings)
    ws_plans = {sc.name: solve(net, [sc.with_probability(1.0)], **settings) for sc in scenarios}
    nominal_plan = ws_plans.get(nominal) or solve(net, [net.scenario(nominal, 1.0)], **settings)
    eev = solve(net, scenarios, reveal_week=reveal_week, fixed_first_stage=nominal_plan.first_stage(reveal_week),
                **settings)
    plans = [rp, eev, nominal_plan, *ws_plans.values()]
    if not all(p.feasible for p in plans):
        return {"status": "infeasible", "statuses": {p.status for p in plans}}
    ws_ub = sum(sc.probability * ws_plans[sc.name].objective_usd for sc in scenarios)
    ws_lb = sum(sc.probability * _lower(ws_plans[sc.name]) for sc in scenarios)
    rp_lb, eev_lb = _lower(rp), _lower(eev)
    per = {sc.name: {"probability": round(sc.probability, 4),
                     "stochastic_plan_usd": round(rp.per_scenario[sc.name]["total_cost_usd"], 2),
                     "nominal_plan_usd": round(eev.per_scenario[sc.name]["total_cost_usd"], 2),
                     "perfect_information_usd": round(ws_plans[sc.name].objective_usd, 2),
                     "stochastic_service_level": round(rp.per_scenario[sc.name]["service_level"], 5),
                     "nominal_service_level": round(eev.per_scenario[sc.name]["service_level"], 5)}
           for sc in scenarios}
    return {
        "network": net.name, "reveal_week": reveal_week, "nominal": nominal,
        "scenarios": [{"name": sc.name, "probability": round(sc.probability, 4)} for sc in scenarios],
        "RP": round(rp.objective_usd, 2), "EEV": round(eev.objective_usd, 2), "WS": round(ws_ub, 2),
        "VSS": round(eev.objective_usd - rp.objective_usd, 2), "EVPI": round(rp.objective_usd - ws_ub, 2),
        "VSS_interval": [round(eev_lb - rp.objective_usd, 2), round(eev.objective_usd - rp_lb, 2)],
        "EVPI_interval": [round(rp_lb - ws_ub, 2), round(rp.objective_usd - ws_lb, 2)],
        "VSS_pct_of_RP": round(100 * (eev.objective_usd - rp.objective_usd) / rp.objective_usd, 3),
        "EVPI_pct_of_RP": round(100 * (rp.objective_usd - ws_ub) / rp.objective_usd, 3),
        "per_scenario": per,
        "first_stage": {"stochastic": _first_stage_summary(net, rp, reveal_week),
                        "nominal": _first_stage_summary(net, nominal_plan, reveal_week)},
        "mip_gap_setting": mip_gap,
        "solve_seconds": round(sum(p.stats["solve_seconds"] for p in plans), 2),
        "plans": {"stochastic": rp, "nominal_evaluated": eev, "nominal": nominal_plan},
    }


SCALE_VARIANTS: tuple[tuple[str, dict[str, Any], tuple[int, ...]], ...] = (
    ("continuous_flows", {}, (10, 25, 50, 100, 200, 400)),
    ("integer_units", {"integer_shipments": True}, (10, 25, 50, 100)),
    ("disaggregated_links", {"tighten": True}, (10, 25, 50, 100, 200, 400)),
    ("sku_order_fee", {"sku_order_fee": 25.0}, (10, 25, 50, 100)),
)


def scale_benchmark(network: str = "asml",
                    variants: Sequence[tuple[str, dict[str, Any], Sequence[int]]] = SCALE_VARIANTS, *,
                    weeks: int = 16, time_limit: float = 60, mip_gap: float = 1e-3,
                    seed: int = 7) -> list[dict[str, Any]]:
    """Model size and solve time per formulation variant; each variant lists its own SKU counts."""
    rows = []
    for label, options, sizes in variants:
        for size in sizes:
            net = build_network(network, size, weeks, seed)
            plan = solve(net, time_limit=time_limit, mip_gap=mip_gap, **options)
            rows.append({"network": network, "variant": label, "skus": size, "weeks": weeks,
                         "variables": plan.stats["variables"], "integer_variables": plan.stats["integer_variables"],
                         "binary_variables": plan.stats["binary_variables"], "constraints": plan.stats["constraints"],
                         "build_seconds": plan.stats["build_seconds"], "solve_seconds": plan.stats["solve_seconds"],
                         "status": plan.status, "mip_gap": plan.stats["mip_gap"],
                         "objective_usd": round(plan.objective_usd, 2) if plan.feasible else None})
    return rows


def lane_loads(net: Network, plan: Plan, k: int = 0) -> dict[tuple[str, int], float]:
    loads: defaultdict[tuple[str, int], float] = defaultdict(float)
    for (kk, s, lane_id, t), units in plan.solution["ship"].items():
        if kk == k:
            loads[lane_id, t + 1] += net.skus[s].mass_kg * units
    return loads


def explain_plan(net: Network, plan: Plan, scenario: str | None = None, top: int = 6) -> dict[str, Any]:
    if not plan.feasible:
        return {"status": plan.status, "message": "No feasible plan to explain."}
    k = plan.scenario_names.index(scenario) if scenario else max(
        range(len(plan.scenarios)), key=lambda i: plan.scenarios[i].probability)
    sc, loads = plan.scenarios[k], lane_loads(net, plan, k)
    utilisation: list[dict[str, Any]] = []
    mix: defaultdict[int, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))
    for lane_id, lane in net.lanes.items():
        for week in range(1, net.weeks + 1):
            kg = loads.get((lane_id, week), 0.0)
            mix[week][lane.mode] += kg
            capacity = sc.capacity(lane, week) + (plan.solution["reserve"].get(lane_id, 0.0) if lane.is_air else 0.0)
            if kg > 1e-6 and capacity > 0 and kg / capacity >= 0.95:
                utilisation.append({"lane": lane_id, "week": week, "load_kg": round(kg, 1),
                                    "capacity_kg": round(capacity, 1), "utilisation": round(kg / capacity, 3)})
    per = plan.per_scenario[sc.name]
    costs = sorted(per["cost_breakdown_usd"].items(), key=lambda item: -item[1])
    total = per["total_cost_usd"]
    result: dict[str, Any] = {
        "scenario": sc.name, "status": plan.status,
        "binding_capacity": sorted(utilisation, key=lambda r: -r["utilisation"])[:top],
        "cost_drivers": [{"item": name, "usd": round(v, 2), "share": round(v / total, 4)}
                         for name, v in costs if v > 0][:top],
        "mode_kg_by_week": [{"week": w, **{m: round(v, 1) for m, v in mix[w].items()}} for w in sorted(mix)],
        "air_reservation_kg_per_week": {lane_id: round(v, 1) for lane_id, v in plan.solution["reserve"].items()},
        "service_level": round(per["service_level"], 5),
        "backlog_unit_weeks": round(per["backlog_unit_weeks"], 2),
    }
    cap = plan.settings.get("carbon_cap_kg")
    if cap is not None:
        result["carbon_cap_t"] = round(cap / 1000, 4)
        result["carbon_cap_binding"] = bool(plan.metrics["emissions_t"] * 1000 >= 0.999 * cap)
    if plan.duals.get("status") == "optimal":
        result["shadow_prices"] = {"carbon_usd_per_t": _round(plan.duals.get("carbon_usd_per_t")),
                                   "top_capacity_usd_per_kg": plan.duals.get("capacity_usd_per_kg", [])[:top]}
    return result


def _first_stage_summary(net: Network, plan: Plan, reveal_week: int) -> dict[str, Any]:
    stage = plan.first_stage(reveal_week)
    units: defaultdict[str, int] = defaultdict(int)
    kg: defaultdict[str, float] = defaultdict(float)
    for (s, lane_id, _t), value in stage["ship"].items():
        units[lane_id] += value
        kg[lane_id] += value * net.skus[s].mass_kg
    return {"air_reservation_kg_per_week": {lane_id: round(v, 1) for lane_id, v in stage["reserve"].items()},
            "early_shipments_units": dict(units),
            "early_shipments_kg": {lane_id: round(v, 1) for lane_id, v in kg.items()}}


def _lower(plan: Plan) -> float:
    bound = plan.stats.get("dual_bound")
    return plan.objective_usd if bound is None else min(bound, plan.objective_usd)


def _slope(cost_a: float, cost_b: float, emissions_a: float, emissions_b: float) -> float | None:
    reduction = emissions_a - emissions_b
    return round((cost_b - cost_a) / reduction, 2) if reduction > 1e-9 else None


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)
