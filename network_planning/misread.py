"""What a wrong reading of a notice's scope costs once the plan meets what really happens.

Two different quantities are kept apart:

- the difference between the optimum of the scenario the planner believed and the optimum of the scenario that
  occurred. Each is the best plan for its own scenario, so this difference is not a loss;
- regret: the plan made under the wrong reading is carried out in the scenario that occurred. Dispatches before the
  planner learns the truth, and the season's air reservation, stay as decided; later dispatches are re-optimised,
  which is the adjustment the model already allows (``solve(fixed_first_stage=...)``). Regret is the cost of that
  outcome minus the cost of the best plan for what occurred.

A plan can differ from the best plan without any regret when several plans are equally good, so the regret of a
favourable tie-break is reported as well.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any

from .accounting import evaluate
from .analysis import _lower, lane_loads
from .data import Network, Scenario
from .model import Plan, solve


def with_lane_capacity(net: Network, lane_id: str, capacity_kg: float) -> Network:
    """The same network with one lane's weekly capacity changed; nothing else moves."""
    if lane_id not in net.lanes:
        raise ValueError(f"unknown lane '{lane_id}'; known: {sorted(net.lanes)}")
    if capacity_kg < 0:
        raise ValueError("capacity_kg cannot be negative")
    lanes = dict(net.lanes)
    lanes[lane_id] = dataclasses.replace(lanes[lane_id], capacity_kg=float(capacity_kg))
    return dataclasses.replace(net, lanes=lanes)


def flow_table(net: Network, plan: Plan) -> dict[str, list[float]]:
    """Kilograms dispatched per lane and week (week 1 first)."""
    loads = lane_loads(net, plan)
    return {lane_id: [round(loads.get((lane_id, week), 0.0), 3) for week in range(1, net.weeks + 1)]
            for lane_id in net.lanes}


def flow_differences(net: Network, a: Plan, b: Plan, before_week: int | None = None) -> dict[str, Any]:
    """Where two single-scenario plans dispatch differently; ``before_week`` limits the comparison to earlier weeks."""
    last = net.weeks if before_week is None else before_week - 1
    ship_a, ship_b = a.solution["ship"], b.solution["ship"]
    keys = {key for key in set(ship_a) | set(ship_b) if key[3] < last}
    units = [abs(ship_a.get(key, 0.0) - ship_b.get(key, 0.0)) for key in keys]
    table_a, table_b = flow_table(net, a), flow_table(net, b)
    lane_weeks = [{"lane": lane_id, "week": week + 1, "kg_a": table_a[lane_id][week], "kg_b": table_b[lane_id][week]}
                  for lane_id in net.lanes for week in range(last)
                  if abs(table_a[lane_id][week] - table_b[lane_id][week]) > 1e-3]
    reserve = {lane_id: [round(a.solution["reserve"].get(lane_id, 0.0), 3),
                         round(b.solution["reserve"].get(lane_id, 0.0), 3)]
               for lane_id in a.solution["reserve"]
               if abs(a.solution["reserve"].get(lane_id, 0.0) - b.solution["reserve"].get(lane_id, 0.0)) > 1e-3}
    return {"shipment_variables_differing": sum(u > 1e-6 for u in units),
            "shipment_variables_compared": len(keys), "largest_difference_units": round(max(units, default=0.0), 4),
            "lane_weeks_differing": lane_weeks, "reservation_kg_differing": reserve}


def outcome(net: Network, plan: Plan) -> dict[str, Any]:
    """What a single-scenario plan costs and delivers, from the independent accounting."""
    kpis = plan.metrics
    return {"status": plan.status, "total_cost_usd": round(plan.objective_usd, 2),
            "lower_bound_usd": round(_lower(plan), 2), "emissions_t": round(kpis["emissions_t"], 4),
            "service_level": round(kpis["service_level"], 5),
            "backlog_unit_weeks": round(kpis["backlog_unit_weeks"], 3),
            "terminal_shortfall_units": round(kpis["terminal_shortfall_units"], 3),
            "air_share_kg": round(kpis["air_share_kg"], 4),
            "cost_breakdown_usd": {key: round(value, 2) for key, value in kpis["cost_breakdown_usd"].items()},
            "lane_kg": {lane_id: round(sum(row), 1) for lane_id, row in flow_table(net, plan).items()},
            "reservation_kg": {lane_id: round(kg, 1) for lane_id, kg in plan.solution["reserve"].items()},
            "issues": list(plan.issues)}


def carried_out(net: Network, believed_plan: Plan, actual: Scenario) -> dict[str, Any]:
    """The believed plan executed to the end without any re-planning, costed in what occurred."""
    decisions = {key: value for key, value in believed_plan.solution.items() if key not in ("inv", "back")}
    result = evaluate(net, [actual.with_probability(1.0)], decisions)
    kpis = result["expected"]
    return {"total_cost_usd": round(result["objective"], 2), "emissions_t": round(kpis["emissions_t"], 4),
            "service_level": round(kpis["service_level"], 5),
            "backlog_unit_weeks": round(kpis["backlog_unit_weeks"], 3),
            "terminal_shortfall_units": round(kpis["terminal_shortfall_units"], 3),
            "violated": list(result["issues"]), "feasible": not result["issues"]}


def misread_case(net: Network, actual: Scenario, believed: Scenario, reveal_weeks: Sequence[int], *,
                 mip_gap: float = 1e-7, time_limit: float = 120.0, tie_break_weight: float = 1e-4,
                 tolerance_usd: float = 1.0) -> dict[str, Any]:
    """Plan under ``believed``, live through ``actual``; one record with every commitment horizon asked for."""
    settings: dict[str, Any] = dict(mip_gap=mip_gap, time_limit=time_limit)
    actual, believed = actual.with_probability(1.0), believed.with_probability(1.0)
    best = solve(net, [actual], **settings)
    planned = solve(net, [believed], **settings)
    if not (best.feasible and planned.feasible):
        return {"status": "infeasible", "best_plan_status": best.status, "believed_plan_status": planned.status}
    record: dict[str, Any] = {
        "status": "ok", "best_plan": outcome(net, best), "believed_plan_as_planned": outcome(net, planned),
        "optimum_difference_usd": round(planned.objective_usd - best.objective_usd, 2),
        "optimum_difference_note": "believed optimum minus actual optimum; two different scenarios, not a loss",
        "plans_differ": flow_differences(net, best, planned),
        "flows_best_plan_kg": flow_table(net, best), "flows_believed_plan_kg": flow_table(net, planned),
        "no_replanning": carried_out(net, planned, actual), "commitments": []}
    # A plan that breaks a constraint in what occurred cannot be carried out, so its cost is not a regret.
    record["no_replanning"]["regret_usd"] = round(
        record["no_replanning"]["total_cost_usd"] - best.objective_usd, 2) if record["no_replanning"]["feasible"] else None
    first_window = min((d.start_week for sc in (actual, believed) for d in sc.disruptions), default=net.weeks)
    for reveal in reveal_weeks:
        done = solve(net, [actual], reveal_week=reveal, fixed_first_stage=planned.first_stage(reveal), **settings)
        row: dict[str, Any] = {"reveal_week": reveal, "status": done.status,
                               "fixed": f"dispatches in weeks 1-{reveal - 1} and the air reservation"}
        if not done.feasible:
            row["violated"] = carried_out(net, planned, actual)["violated"]
            record["commitments"].append(row)
            continue
        regret = done.objective_usd - best.objective_usd
        row.update(outcome=outcome(net, done), regret_usd=round(regret, 2),
                   regret_interval_usd=[round(_lower(done) - best.objective_usd, 2),
                                        round(done.objective_usd - _lower(best), 2)],
                   emissions_difference_t=round(done.metrics["emissions_t"] - best.metrics["emissions_t"], 4),
                   service_difference=round(done.metrics["service_level"] - best.metrics["service_level"], 5),
                   committed_differences=flow_differences(net, best, planned, before_week=reveal),
                   executed_differences=flow_differences(net, best, done))
        if reveal <= first_window:
            # Among the plans that are (almost) equally good under the wrong reading, take the one that does best in
            # what occurred: regret that survives this is not an accident of which optimum the solver returned.
            pair = [believed.with_probability(1 - tie_break_weight), actual.with_probability(tie_break_weight)]
            shared = solve(net, pair, reveal_week=reveal, **settings)
            if shared.feasible:
                kind = solve(net, [actual], reveal_week=reveal, fixed_first_stage=shared.first_stage(reveal),
                             **settings)
                believed_cost = shared.per_scenario[believed.name]["total_cost_usd"]
                if kind.feasible:
                    row["favourable_tie_break"] = {
                        "regret_usd": round(kind.objective_usd - best.objective_usd, 2),
                        "believed_cost_given_up_usd": round(believed_cost - planned.objective_usd, 2),
                        "weight_on_actual": tie_break_weight}
        row["distinguishable"] = bool(row["regret_interval_usd"][0] > tolerance_usd)
        record["commitments"].append(row)
    return record


def scope_value(net: Network, narrow: Scenario, broad: Scenario, priors: Sequence[float], reveal_week: int, *,
                mip_gap: float = 1e-7, time_limit: float = 120.0) -> dict[str, Any]:
    """What confirming a notice's scope before week 1 is worth when the truth otherwise shows at ``reveal_week``.

    The planner does not know whether the notice covers ``narrow`` or ``broad``; ``priors`` are probabilities of
    ``broad``. Without confirmation the planner can assume either reading or hedge with a two-stage plan. With
    confirmation the planner plans for what is true. The differences are what a confirmation may cost at most.
    """
    settings: dict[str, Any] = dict(mip_gap=mip_gap, time_limit=time_limit)
    narrow, broad = narrow.with_probability(1.0), broad.with_probability(1.0)
    best = {sc.name: solve(net, [sc], **settings) for sc in (narrow, broad)}
    wrong = {  # the plan for one reading, carried into the other until the reveal
        narrow.name: solve(net, [broad], reveal_week=reveal_week,
                           fixed_first_stage=best[narrow.name].first_stage(reveal_week), **settings),
        broad.name: solve(net, [narrow], reveal_week=reveal_week,
                          fixed_first_stage=best[broad.name].first_stage(reveal_week), **settings)}
    plans = [*best.values(), *wrong.values()]
    if not all(plan.feasible for plan in plans):
        return {"status": "infeasible", "reveal_week": reveal_week, "statuses": [plan.status for plan in plans]}
    cost_n, cost_b = best[narrow.name].objective_usd, best[broad.name].objective_usd
    under, over = wrong[narrow.name], wrong[broad.name]
    record: dict[str, Any] = {
        "status": "ok", "reveal_week": reveal_week,
        "best_if_narrow": outcome(net, best[narrow.name]), "best_if_broad": outcome(net, best[broad.name]),
        "assumed_narrow_but_broad": {"regret_usd": round(under.objective_usd - cost_b, 2),
                                     "regret_interval_usd": [round(_lower(under) - cost_b, 2),
                                                             round(under.objective_usd - _lower(best[broad.name]), 2)],
                                     "outcome": outcome(net, under)},
        "assumed_broad_but_narrow": {"regret_usd": round(over.objective_usd - cost_n, 2),
                                     "regret_interval_usd": [round(_lower(over) - cost_n, 2),
                                                             round(over.objective_usd - _lower(best[narrow.name]), 2)],
                                     "outcome": outcome(net, over)},
        "first_stage_differs": flow_differences(net, best[narrow.name], best[broad.name], before_week=reveal_week),
        "priors": []}
    for prior in priors:
        pair = [narrow.with_probability(1 - prior), broad.with_probability(prior)]
        hedge = solve(net, pair, reveal_week=reveal_week, **settings)
        confirmed = (1 - prior) * cost_n + prior * cost_b
        confirmed_lower = (1 - prior) * _lower(best[narrow.name]) + prior * _lower(best[broad.name])
        row: dict[str, Any] = {"probability_broad": prior, "confirmed_usd": round(confirmed, 2),
                               "assume_narrow_usd": round((1 - prior) * cost_n + prior * under.objective_usd, 2),
                               "assume_broad_usd": round((1 - prior) * over.objective_usd + prior * cost_b, 2),
                               "hedge_status": hedge.status}
        if hedge.feasible:
            row.update(hedge_usd=round(hedge.objective_usd, 2),
                       value_of_confirming_usd=round(hedge.objective_usd - confirmed, 2),
                       value_interval_usd=[round(_lower(hedge) - confirmed, 2),
                                           round(hedge.objective_usd - confirmed_lower, 2)],
                       hedge_service_if_narrow=round(hedge.per_scenario[narrow.name]["service_level"], 5),
                       hedge_service_if_broad=round(hedge.per_scenario[broad.name]["service_level"], 5))
        row["value_over_assuming_narrow_usd"] = round(row["assume_narrow_usd"] - confirmed, 2)
        row["value_over_assuming_broad_usd"] = round(row["assume_broad_usd"] - confirmed, 2)
        record["priors"].append(row)
    return record
