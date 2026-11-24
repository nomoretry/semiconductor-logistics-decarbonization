"""Answer a dispatch question from its statement text alone.

This module reads nothing but the text of a prompt. It does not import the reference planner, the simulator
or the dataset, and it states the problem in its own variables, so agreement with the reference answers shows
that the text carries everything they depend on.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp  # type: ignore[import-untyped]
from scipy.sparse import coo_matrix  # type: ignore[import-untyped]

from .rules import RULES, SCENARIO_LABEL

STATE_FIELDS = ("t", "public", "stock", "backlog", "arrivals", "served_old", "pipeline", "carbon_remaining",
                "history", "forecast")
STATE_LINE = re.compile(r"^[^\n()]+ \((\w+)\) = (.+)$", re.MULTILINE)
SCENARIO_LINE = re.compile(rf"^{re.escape(SCENARIO_LABEL)} = (.+)$", re.MULTILINE)

Plan = list[list[list[int]]]


class StatementError(ValueError):
    """The text does not state the planning problem."""


class InfeasibleDispatch(ValueError):
    """No plan that satisfies the constraints starts with the given dispatch."""


@dataclass(frozen=True)
class Problem:
    state: dict[str, Any]
    demand: list[list[list[float]]]  # scenario, offset, SKU

    @property
    def public(self) -> dict[str, Any]:
        result: dict[str, Any] = self.state["public"]
        return result

    @property
    def window(self) -> int:
        return int(min(self.public["horizon"], self.public["periods"] - self.state["t"]))


@dataclass(frozen=True)
class Reading:
    """How the rules are read. The defaults are the stated rules; each change is one other reading."""

    demand: str = "scenarios"
    paced_emissions: bool = True
    emissions_charge: bool = True
    terminal_backlog: bool = True
    starting_backlog: bool = True
    scheduled_receipts: bool = True
    freight_per_kilogram: bool = True
    receipt_delay: int = 0
    capacity: str = "dispatch"
    arrivals_added_again: bool = False
    earlier_dispatches_emit: bool = False
    terminal_replaces_backlog: bool = False


MEAN_FORECAST = "mean forecast used instead of the scenarios"
MISREADINGS = {
    "emissions limit not paced over the remaining periods": Reading(paced_emissions=False),
    "no emissions charge in the cost": Reading(emissions_charge=False),
    "no extra cost for backlog at the end of the episode": Reading(terminal_backlog=False),
    "outstanding backlog ignored": Reading(starting_backlog=False),
    "scheduled receipts ignored": Reading(scheduled_receipts=False),
    "freight charged per unit instead of per kilogram": Reading(freight_per_kilogram=False),
    "receipts arrive one offset later": Reading(receipt_delay=1),
    MEAN_FORECAST: Reading(demand="forecast"),
    "average of the scenarios used as one path": Reading(demand="average"),
    "first scenario only": Reading(demand="first"),
}
# Wordings that the independent reading of the questions found open to another reading; other sentences exclude it.
ALTERNATIVES = {
    "earlier dispatches still under way use route capacity": Reading(capacity="under way"),
    "pipeline arrivals use slow-route capacity as well": Reading(capacity="under way and pipeline"),
    "current arrivals are added once more": Reading(arrivals_added_again=True),
    "earlier dispatches that arrive in the window count as emissions": Reading(earlier_dispatches_emit=True),
    "terminal cost replaces the backlog cost": Reading(terminal_replaces_backlog=True),
}


def parse(text: str) -> Problem:
    """Take the rules, the ten state fields and the demand scenarios from a prompt."""
    if not text.startswith(f"{RULES}\n\n"):
        raise StatementError("the planning rules are not stated")
    body = text[len(RULES) + 2:]
    blocks = body.split("\n\n")
    found = STATE_LINE.findall(blocks[0])
    if tuple(name for name, _ in found) != STATE_FIELDS or len(found) != len(blocks[0].split("\n")):
        raise StatementError("the state fields are not stated")
    scenarios = SCENARIO_LINE.findall(blocks[1])
    if len(scenarios) != 1 or blocks[1].count("\n"):
        raise StatementError("the demand scenarios are not stated")
    problem = Problem({name: json.loads(value) for name, value in found}, json.loads(scenarios[0]))
    skus = len(problem.public["mass"])
    if len(problem.demand) != problem.public["scenarios"] or any(
            len(path) != problem.window or any(len(period) != skus for period in path) for path in problem.demand):
        raise StatementError("the demand scenarios do not fit the window")
    return problem


def _demand(problem: Problem, reading: Reading) -> list[list[list[float]]]:
    if reading.demand == "scenarios":
        return problem.demand
    if reading.demand == "first":
        return problem.demand[:1]
    if reading.demand == "average":
        return [np.mean(np.asarray(problem.demand, dtype=float), axis=0).tolist()]
    return [problem.state["forecast"][:problem.window]]


def optimize(problem: Problem, reading: Reading | None = None,
             first: list[list[int]] | None = None) -> tuple[Plan, float]:
    """Solve the stated integer program with one stock and one shortage variable per scenario, offset and SKU.

    With ``first`` the current dispatch is fixed; an infeasible dispatch raises InfeasibleDispatch.
    """
    reading = reading or Reading()
    p, t, h = problem.public, problem.state["t"], problem.window
    pipeline = problem.state["pipeline"]
    demand = _demand(problem, reading)
    n, r, s = len(p["mass"]), len(p["lead"]), len(demand)
    nq, cells = h * n * r, s * h * n

    def ship(u: int, i: int, j: int) -> int:
        return (u * n + i) * r + j

    def surplus(k: int, u: int, i: int) -> int:
        return nq + (k * h + u) * n + i

    cost = np.zeros(nq + 2 * cells)
    upper = np.full(nq + 2 * cells, np.inf)
    entries: list[tuple[int, int, float]] = []
    low: list[float] = []
    high: list[float] = []

    def add(terms: list[tuple[int, float]], lower: float, bound: float) -> None:
        entries.extend((len(low), column, value) for column, value in terms)
        low.append(lower)
        high.append(bound)

    charge = p["carbon_price"] if reading.emissions_charge else 0.0
    emissions: list[tuple[int, float]] = []
    for u in range(h):
        for j in range(r):
            for i in range(n):
                q = ship(u, i, j)
                freight = p["freight"][j] * (p["mass"][i] if reading.freight_per_kilogram else 1)
                cost[q] = freight + charge * p["mass"][i] * p["emissions"][j]
                emissions.append((q, float(p["mass"][i] * p["emissions"][j])))
                if u + p["lead"][j] >= h:
                    upper[q] = 0
            earliest = u if reading.capacity == "dispatch" else max(0, u - p["lead"][j] + 1)
            room = p["capacity"][j]
            if reading.capacity == "under way and pipeline" and j == 0:
                room -= sum(p["mass"][i] * pipeline[t + w][i] for w in range(u + 1, p["lead"][0])
                            if t + w < p["periods"] for i in range(n))
            add([(ship(v, i, j), float(p["mass"][i])) for v in range(earliest, u + 1) for i in range(n)],
                -np.inf, max(0, room))
    limit = problem.state["carbon_remaining"]
    if reading.paced_emissions:
        limit = limit * h / (p["periods"] - t)
    if reading.earlier_dispatches_emit:
        limit = max(0, limit - sum(p["mass"][i] * p["emissions"][0] * pipeline[t + w][i]
                                   for w in range(1, h) for i in range(n)))
    add(emissions, -np.inf, limit)
    if first is not None:
        for i in range(n):
            for j in range(r):
                add([(ship(0, i, j), 1.0)], first[i][j], first[i][j])
    for i in range(n):
        start = problem.state["stock"][i] - (problem.state["backlog"][i] if reading.starting_backlog else 0)
        start += problem.state["arrivals"][i] if reading.arrivals_added_again else 0
        for u in range(h):
            due = range(u + 1) if reading.scheduled_receipts else range(0)
            received = sum(pipeline[t + v][i] for v in due)
            delivered = [(ship(v, i, j), -1.0) for v in range(h) for j in range(r)
                         if v + p["lead"][j] + reading.receipt_delay <= u]
            shortage_rate = p["backlog"][i]
            if reading.terminal_backlog and t + u == p["periods"] - 1:
                shortage_rate = p["terminal_backlog"][i] + (0 if reading.terminal_replaces_backlog else shortage_rate)
            for k in range(s):
                over = surplus(k, u, i)
                cost[over] = p["holding"][i] / s
                cost[over + cells] = shortage_rate / s
                net = start + received - sum(demand[k][v][i] for v in range(u + 1))
                add([(over, 1.0), (over + cells, -1.0), *delivered], net, net)
    index, columns, values = zip(*entries, strict=True)
    matrix = coo_matrix((values, (index, columns)), shape=(len(low), len(cost))).tocsr()
    result = milp(cost, integrality=np.r_[np.ones(nq), np.zeros(2 * cells)], bounds=Bounds(np.zeros(len(cost)), upper),
                  constraints=LinearConstraint(matrix, low, high),
                  options={"presolve": False, "mip_rel_gap": 0.0, "time_limit": 60.0})
    if result.status == 2 and first is not None:
        raise InfeasibleDispatch("the current dispatch has no feasible plan")
    if result.status != 0 or result.x is None:
        raise StatementError(f"no optimal plan: {result.status} {result.message}")
    rounded = np.rint(result.x[:nq])
    if np.max(np.abs(result.x[:nq] - rounded)) > 1e-5:
        raise StatementError("noninteger dispatch")
    plan: Plan = rounded.astype(int).reshape(h, n, r).tolist()
    return plan, float(result.fun)


def optimal_under(problem: Problem, reading: Reading, dispatch: list[list[int]], best: float) -> bool:
    """Whether a current dispatch is optimal under a reading whose optimum is ``best``."""
    try:
        value = optimize(problem, reading, dispatch)[1]
    except InfeasibleDispatch:
        return False
    return value - best <= 1e-6 * max(1.0, abs(best))


def _exact(value: float) -> Fraction:
    return Fraction(str(value))


def exact_cost(problem: Problem, plan: Plan) -> Fraction:
    """Check the stated constraints and add up the stated cost of a plan in exact arithmetic."""
    p, t, h = problem.public, problem.state["t"], problem.window
    skus, routes = range(len(p["mass"])), range(len(p["lead"]))
    total = emitted = Fraction(0)
    for u in range(h):
        for j in routes:
            kilograms = sum(p["mass"][i] * plan[u][i][j] for i in skus)
            if kilograms > p["capacity"][j] or any(plan[u][i][j] < 0 for i in skus):
                raise StatementError("route capacity")
            if u + p["lead"][j] >= h and kilograms:
                raise StatementError("arrival after the window")
            emitted += kilograms * _exact(p["emissions"][j])
            total += kilograms * (_exact(p["freight"][j]) + _exact(p["carbon_price"]) * _exact(p["emissions"][j]))
    if emitted > _exact(problem.state["carbon_remaining"]) * h / (p["periods"] - t):
        raise StatementError("window emissions")
    inventory = Fraction(0)
    for path in problem.demand:
        for i in skus:
            net = problem.state["stock"][i] - problem.state["backlog"][i]
            for u in range(h):
                net += problem.state["pipeline"][t + u][i]
                net += sum(plan[u - p["lead"][j]][i][j] for j in routes if u >= p["lead"][j])
                net -= int(path[u][i])
                rate = _exact(p["holding"][i]) if net > 0 else _exact(p["backlog"][i])
                if net < 0 and t + u == p["periods"] - 1:
                    rate += _exact(p["terminal_backlog"][i])
                inventory += rate * abs(net)
    return total + inventory / len(problem.demand)


def answers(problem: Problem, plan: Plan) -> dict[str, Any]:
    """Answer the planning and dispatch questions from one plan."""
    p = problem.public
    skus, routes = range(len(p["mass"])), range(len(p["lead"]))
    loads = [sum(p["mass"][i] * plan[0][i][j] for i in skus) for j in routes]
    reply: dict[str, Any] = {f"P3.ship.{i}": any(plan[0][i]) for i in skus}
    reply.update({f"P3.load.{j}": loads[j] for j in routes})
    emission = sum(load * rate for load, rate in zip(loads, p["emissions"], strict=True))
    reply.update({"P3.emission": int(emission), "B": plan[0], "M": plan})
    return reply
