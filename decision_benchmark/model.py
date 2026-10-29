"""Public physical model; no sampled hidden world is needed for planning.

One known integer order is due in week three. All parts depart in week zero.
Air arrives in week one; the announced unresolved ocean delay makes ocean
arrive in week two or four. This is a deliberately small decision benchmark,
not a demand forecast or a model of a real company's operations.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math


SOLVERS = ("solve_nominal", "solve_robust", "solve_bayes")
QUERIES = ("query_status", "request_clarification")
TOOLS = QUERIES + SOLVERS + ("commit_plan", "handoff")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def physical_outcome(context: dict, ocean_units: int, theta: int) -> dict:
    """Independently replay integer dispatches and all physical accounting.

    ``theta`` is either possible public state, never implicitly read from an
    environment. A policy can enumerate both possible states without access to
    the actual sampled one. There are no solver-reported inventories to trust.
    """
    if type(theta) is not int or theta not in (0, 2):
        raise ValueError("Ocean delay must be zero or two weeks")
    order = context["committed_order"]
    quantity = order["quantity"]
    if type(ocean_units) is not int or not 0 <= ocean_units <= quantity:
        raise ValueError("Dispatch quantities must be nonnegative integers summing to the order")
    air = quantity - ocean_units
    routes = context["routes"]
    air_arrival = routes["air"]["lead_weeks"]
    ocean_arrival = routes["ocean"]["lead_weeks"] + theta
    horizon, due = context["horizon_weeks"], order["due_week"]
    arrivals = [0] * (horizon + 1)
    arrivals[air_arrival] += air
    arrivals[ocean_arrival] += ocean_units
    inventory, backlog, net = [], [], 0
    for week in range(horizon + 1):
        net += arrivals[week] - (quantity if week == due else 0)
        inventory.append(max(net, 0))
        backlog.append(max(-net, 0))
    mass = context["mass_kg_per_unit"]
    freight = mass * (air * routes["air"]["freight_usd_per_kg"]
                      + ocean_units * routes["ocean"]["freight_usd_per_kg"])
    holding = sum(inventory) * context["holding_usd_per_unit_week"]
    emissions = mass * (air * routes["air"]["kgco2e_per_kg"]
                        + ocean_units * routes["ocean"]["kgco2e_per_kg"])
    emissions += sum(inventory) * context["warehouse_kgco2e_per_unit_week"]
    on_time = air * int(air_arrival <= due) + ocean_units * int(ocean_arrival <= due)
    return {
        "dispatch": {"air_units": air, "ocean_units": ocean_units,
                     "dispatch_week": 0},
        "arrivals_by_week": arrivals, "inventory_by_week": inventory,
        "backlog_by_week": backlog, "freight_usd": float(freight),
        "holding_usd": float(holding), "logistics_cost_usd": float(freight + holding),
        "emissions_kgco2e": float(emissions), "late_units": quantity - on_time,
        "backlog_unit_weeks": sum(backlog), "on_time_fill_rate": on_time / quantity,
        "all_committed_orders_delivered": backlog[-1] == 0,
        "quantity_conservation": sum(arrivals) == quantity,
    }


def score_outcome(context: dict, physical: dict) -> dict:
    """Public goal scalarization in dollars, alongside separate service success."""
    goal = context["goal"]
    lateness = physical["backlog_unit_weeks"] * goal["late_unit_week_penalty_usd"]
    carbon = physical["emissions_kgco2e"] * goal["carbon_price_usd_per_kgco2e"]
    excess = max(0.0, physical["emissions_kgco2e"] - goal["carbon_budget_kgco2e"])
    carbon_excess = excess * goal["carbon_excess_penalty_usd_per_kgco2e"]
    return {
        "shipping_loss_usd": physical["logistics_cost_usd"] + lateness + carbon + carbon_excess,
        "lateness_penalty_usd": float(lateness), "carbon_price_usd": float(carbon),
        "carbon_excess_penalty_usd": float(carbon_excess),
        "service_success": physical["on_time_fill_rate"] + 1e-12 >= goal["minimum_on_time_fill_rate"],
        "carbon_budget_met": excess <= 1e-9,
    }


def loss_table(context: dict) -> tuple[tuple[float, float], ...]:
    return tuple(tuple(score_outcome(context, physical_outcome(context, q, theta))["shipping_loss_usd"]
                       for theta in (0, 2))
                 for q in range(context["committed_order"]["quantity"] + 1))


def candidate_for_solver(context: dict, posterior: float, solver: str) -> int:
    if solver not in SOLVERS:
        raise ValueError("Unknown public solver option")
    table = loss_table(context)
    if solver == "solve_nominal":
        objective = lambda q: table[q][0]
    elif solver == "solve_robust":
        objective = lambda q: max(table[q])
    else:
        objective = lambda q: (1 - posterior) * table[q][0] + posterior * table[q][1]
    # A public deterministic tie break makes candidates reproducible.
    return min(range(len(table)), key=lambda q: (objective(q), q))


def screen_branches(context: dict, posterior: float):
    model = context["query_model"]
    sensitivity, specificity = model["sensitivity"], model["specificity"]
    positive = posterior * sensitivity + (1 - posterior) * (1 - specificity)
    branches = []
    if positive > 0:
        branches.append((positive, posterior * sensitivity / positive, True))
    if positive < 1:
        branches.append((1 - positive, posterior * (1 - sensitivity) / (1 - positive), False))
    return branches


def updated_posterior(context: dict, prior: float, positive: bool) -> float:
    return next(p for _, p, response in screen_branches(context, prior) if response == positive)


def validate_context(context: dict) -> None:
    """Reject unsupported models instead of silently changing the public oracle."""
    if context.get("synthetic") is not True:
        raise ValueError("Only synthetic development tasks are supported")
    order = context["committed_order"]
    if (type(order["quantity"]) is not int or order["quantity"] < 1
            or order["due_week"] != 3 or context["horizon_weeks"] != 5):
        raise ValueError("Unsupported known-order shape")
    if context["routes"]["air"]["lead_weeks"] != 1 or context["routes"]["ocean"]["lead_weeks"] != 2:
        raise ValueError("Unsupported public lead times")
    if isinstance(context["prior_severe_delay"], bool) or not 0 <= context["prior_severe_delay"] <= 1:
        raise ValueError("Invalid public prior")
    for key in ("sensitivity", "specificity"):
        if not 0 < context["query_model"][key] < 1:
            raise ValueError("Screen likelihoods must be strictly between zero and one")
    if set(context["tool_fees_usd"]) != set(TOOLS):
        raise ValueError("Every supported tool must have a disclosed fee")
    for value in context["tool_fees_usd"].values():
        if isinstance(value, bool) or not math.isfinite(value) or value < 0:
            raise ValueError("Tool fees must be finite and nonnegative")
    if context["tool_fees_usd"]["commit_plan"] != 0 or context["tool_fees_usd"]["handoff"] != 0:
        raise ValueError("This finite oracle supports free terminal actions only")
    for key in ("max_steps", "max_solver_calls", "max_queries", "tool_budget_usd"):
        if type(context["budgets"][key]) is not int or context["budgets"][key] < 1:
            raise ValueError("Tool budgets must be positive integers")
    numeric = [context["mass_kg_per_unit"], context["holding_usd_per_unit_week"],
               context["warehouse_kgco2e_per_unit_week"], context["invalid_action_fee_usd"],
               context["unshipped_order_loss_usd"]]
    numeric += [route[key] for route in context["routes"].values()
                for key in ("freight_usd_per_kg", "kgco2e_per_kg")]
    numeric += [context["goal"][key] for key in ("late_unit_week_penalty_usd", "carbon_price_usd_per_kgco2e",
                "carbon_budget_kgco2e", "carbon_excess_penalty_usd_per_kgco2e", "minimum_on_time_fill_rate")]
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value < 0 for value in numeric):
        raise ValueError("Physical and goal coefficients must be finite and nonnegative")
    if context["mass_kg_per_unit"] <= 0 or context["unshipped_order_loss_usd"] <= 0:
        raise ValueError("Mass and unshipped-order loss must be positive")
    if context["goal"]["minimum_on_time_fill_rate"] > 1:
        raise ValueError("Service target must lie in [0, 1]")


def clone(value):
    return copy.deepcopy(value)
