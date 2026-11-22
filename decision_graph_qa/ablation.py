"""Select current dispatches with one information intervention at a time."""
from __future__ import annotations

from collections import Counter
from math import floor

from .planner import (
    AuditFailure,
    Model,
    Record,
    Schedule,
    SolveFailure,
    feasible_plan,
    scenarios,
)

ABLATIONS = ("I1", "I2", "I3", "I4", "I5", "H")
SKU_PARAMETERS = ("mass", "base_mean", "holding", "backlog", "terminal_backlog", "initial_inventory")
SKU_VECTORS = ("stock", "backlog", "arrivals", "served_old")
SKU_HISTORIES = ("pipeline", "history", "forecast")


def substitute(obs: Record, item: str) -> Record:
    """Replace one observation input while leaving all other values intact."""
    p = obs["public"]
    if item == "I1":
        return dict(obs, pipeline=[[0 for _ in row] for row in obs["pipeline"]])
    if item == "I2":
        return dict(obs, backlog=[0 for _ in obs["backlog"]])
    if item == "I3":
        return dict(obs, forecast=[list(p["base_mean"]) for _ in obs["forecast"]])
    if item == "I4":
        remaining_periods = p["periods"] - obs["t"]
        return dict(obs, carbon_remaining=p["carbon_budget"] * remaining_periods / p["periods"])
    raise ValueError(f"unknown observation substitution: {item}")


def split_by_sku(obs: Record) -> list[Record]:
    """Project the planning inputs and allocate route capacity and carbon by SKU."""
    p = obs["public"]
    weights = [demand * mass for demand, mass in zip(p["base_mean"], p["mass"])]
    total = sum(weights)
    if total <= 0:
        raise ValueError("SKU allocation requires positive total mean demand mass")
    independent: list[Record] = []
    for i, weight in enumerate(weights):
        share = weight / total
        own = dict(obs)
        own["public"] = dict(p, capacity=[floor(limit * share) for limit in p["capacity"]],
                             initial_pipeline=[[row[i]] for row in p["initial_pipeline"]])
        for key in SKU_PARAMETERS:
            own["public"][key] = [p[key][i]]
        for key in SKU_VECTORS:
            own[key] = [obs[key][i]]
        for key in SKU_HISTORIES:
            own[key] = [[row[i]] for row in obs[key]]
        # The planner paces this remainder over the same number of periods.
        own["carbon_remaining"] = obs["carbon_remaining"] * share
        independent.append(own)
    return independent


def _solve_ablation(model: Model, item: str) -> Schedule:
    plan = model.optimize(f"ablation_{item}")
    if plan is None:
        raise SolveFailure(f"ablation_{item}: unexpectedly infeasible with zero dispatch available")
    return plan


def ablation_action(graph: Record, item: str, counts: Counter[str]) -> list[list[int]]:
    """Return a first action to be evaluated with the original observation."""
    if item == "H":
        action: list[list[int]] = graph["hindsight"]["first_action_with_known_demand"]
        return action
    obs = graph["observation"]
    if item != "I5":
        altered = substitute(obs, item)
        return _solve_ablation(Model(altered, scenarios(altered), counts), item)[0]

    # Each separate model sees its own slice of the same demand scenario draws.
    demands = scenarios(obs)
    plans = [_solve_ablation(Model(projected, demands[:, :, i:i + 1], counts), item)
             for i, projected in enumerate(split_by_sku(obs))]
    combined = [[row[0] for row in period] for period in zip(*plans)]
    if not feasible_plan(obs, combined):
        raise AuditFailure("ablation_I5: combined schedule violates the original constraints")
    return combined[0]
