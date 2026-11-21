"""An integer dispatch model with exact empirical inventory-cost epigraphs."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp  # type: ignore[import-untyped]
from scipy.sparse import coo_matrix  # type: ignore[import-untyped]

from rolling_inventory.environment import carbon, validate
from rolling_inventory.planning import path_cost, solve

Record = dict[str, Any]
Schedule = list[list[list[int]]]
Weights = dict[int, float]
Row = tuple[Weights, float, float]
INF = float("inf")


class PlannerMismatch(ValueError):
    """The reference and the unrestricted planning problem disagree."""


class SolveFailure(RuntimeError):
    """A solver did not prove optimality or infeasibility."""


class AuditFailure(SolveFailure):
    """A consistency failure requires immediate termination."""

    def __init__(self, message: str, diagnostics: Record | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


RETRY_OUTCOMES = ("presolve_retry_recovered", "presolve_retry_confirmed")


def solve_counts(counts: Counter[str]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {name: {} for name in ("solves", *RETRY_OUTCOMES)}
    for key, count in counts.items():
        group, separator, label = key.partition("/")
        if separator:
            summary[group][label] = count
        else:
            summary["solves"][group] = count
    return summary


def tolerance(value: float) -> float:
    return 1e-7 + 1e-6 * abs(value)


def window(obs: Record) -> int:
    return min(int(obs["public"]["horizon"]), len(obs["forecast"]))


def allowance(obs: Record) -> float:
    return float(obs["carbon_remaining"] * window(obs) / (obs["public"]["periods"] - obs["t"]))


def scenarios(obs: Record) -> Any:
    p = obs["public"]
    h = window(obs)
    rng = np.random.default_rng(p["scenario_seed"] + obs["t"])
    return rng.poisson(obs["forecast"][:h], size=(p["scenarios"], h, len(p["mass"])))


def feasible_plan(obs: Record, plan: Any, *, first: bool = False) -> bool:
    p = obs["public"]
    h = window(obs)
    if not isinstance(plan, list) or len(plan) != (1 if first else h):
        return False
    emission = 0
    for u, action in enumerate(plan):
        if not isinstance(action, list) or len(action) != len(p["mass"]):
            return False
        for row in action:
            if not isinstance(row, list) or len(row) != len(p["lead"]):
                return False
            if any(type(q) is not int or q < 0 or q > max(p["capacity"]) for q in row):
                return False
            if any(q and u + lead >= h for q, lead in zip(row, p["lead"])):
                return False
        try:
            validate(action, dict(obs, t=obs["t"] + u))
        except ValueError:
            return False
        emission += carbon(action, p)
    return bool(emission <= allowance(obs) + 1e-9)


def physical_cost(obs: Record, plan: Schedule, demands: Any) -> float:
    return float(np.mean([path_cost(obs, plan, path) for path in demands]))


def original(obs: Record, demands: Any, counts: Counter[str], label: str) -> tuple[Schedule, float]:
    counts[label] += 1
    try:
        plan, info = solve(obs, demands)
    except ValueError as exc:
        raise SolveFailure(str(exc)) from exc
    return plan, float(info["objective"])


@dataclass
class Model:
    obs: Record
    demands: Any
    counts: Counter[str] = field(default_factory=Counter)

    def __post_init__(self) -> None:
        p = self.obs["public"]
        s, self.h, self.n = (int(length) for length in self.demands.shape)
        self.r = len(p["lead"])
        self.nq = self.h * self.n * self.r
        self.size = self.nq + self.h * self.n
        self.ub = [INF] * self.size
        self.objective: Weights = {}
        self.rows: list[Row] = []
        masses = p["mass"]
        self.loads = [{self.q(0, i, j): float(masses[i]) for i in range(self.n)}
                      for j in range(self.r)]
        self.flags = [{self.q(0, i, j): 1.0 for j in range(self.r)} for i in range(self.n)]
        self.emission = {k: v * p["emissions"][j] for j, load in enumerate(self.loads)
                         for k, v in load.items()}
        carbon_row: Weights = {}
        cumulative = np.cumsum(self.demands, axis=1)
        net = np.subtract(self.obs["stock"], self.obs["backlog"]).astype(float)
        for u in range(self.h):
            t = self.obs["t"] + u
            net += self.obs["pipeline"][t]
            for j, lead in enumerate(p["lead"]):
                load = {self.q(u, i, j): float(masses[i]) for i in range(self.n)}
                self.rows.append((load, -INF, p["capacity"][j]))
                for k, mass in load.items():
                    self.ub[k] = p["capacity"][j] // mass if u + lead < self.h else 0
                    carbon_row[k] = mass * p["emissions"][j]
                    self.objective[k] = mass * p["freight"][j] + carbon_row[k] * p["carbon_price"]
            for i in range(self.n):
                cost = self.nq + u * self.n + i
                self.objective[cost] = 1.0
                a = p["holding"][i]
                b = p["backlog"][i] + (p["terminal_backlog"][i] if t == p["periods"] - 1 else 0)
                required = np.sort(cumulative[:, u, i] - net[i])
                prefix = np.r_[0.0, np.cumsum(required)]
                delivered = [self.q(v, i, j) for j, lead in enumerate(p["lead"])
                             for v in range(u - lead + 1)]
                # Expected asymmetric inventory loss is the maximum of these affine pieces.
                for k in range(s + 1):
                    if 0 < k < s and required[k - 1] == required[k]:
                        continue
                    slope = (a * k - b * (s - k)) / s
                    intercept = (b * (prefix[-1] - prefix[k]) - a * prefix[k]) / s
                    terms = {q: -slope for q in delivered}
                    terms[cost] = 1.0
                    self.rows.append((terms, float(intercept), INF))
        self.rows.append((carbon_row, -INF, allowance(self.obs)))

    def q(self, u: int, i: int, j: int) -> int:
        return (u * self.n + i) * self.r + j

    def optimize(self, label: str, extra: tuple[Row, ...] = (), target: Weights | None = None,
                 binaries: int = 0, *, endpoint: tuple[str, float] | None = None) -> Schedule | None:
        size = self.size + binaries
        c = np.zeros(size)
        for k, value in (self.objective if target is None else target).items():
            c[k] = value
        row_ids, cols, values = [], [], []
        lb, ub = [], []
        for idx, (terms, low, high) in enumerate((*self.rows, *extra)):
            for k, weight in terms.items():
                row_ids.append(idx)
                cols.append(k)
                values.append(weight)
            lb.append(low)
            ub.append(high)
        mat = coo_matrix((values, (row_ids, cols)), shape=(len(lb), size)).tocsc()
        integrality = np.r_[np.ones(self.nq), np.zeros(self.size - self.nq), np.ones(binaries)]
        bounds = Bounds(np.zeros(size), self.ub + [1.0] * binaries)
        constraints = LinearConstraint(mat, lb, ub)
        options = {"time_limit": 30.0, "mip_rel_gap": 0.0}
        self.counts[label] += 1
        res = milp(c, integrality=integrality, bounds=bounds, constraints=constraints, options=options.copy())
        statuses = [int(res.status)]
        if res.status == 2:
            self.counts[label] += 1
            res = milp(c, integrality=integrality, bounds=bounds, constraints=constraints,
                       options=dict(options, presolve=False))
            statuses.append(int(res.status))
            if res.status == 0 and res.x is not None:
                self.counts[f"presolve_retry_recovered/{label}"] += 1
            elif res.status == 2:
                self.counts[f"presolve_retry_confirmed/{label}"] += 1

        def fail(message: str, plan: Schedule | None = None, cost: float | None = None) -> SolveFailure:
            if endpoint is not None:
                name, ceiling = endpoint
                return AuditFailure(message, {
                    "endpoint": name, "statuses": statuses, "solver_message": str(res.message),
                    "plan": plan, "model_objective": None if res.fun is None else float(res.fun),
                    "physical_cost": cost, "ceiling": ceiling,
                })
            if label == "exclude_action":
                return AuditFailure(message, {"statuses": statuses, "solver_message": str(res.message),
                                              "plan": plan})
            return SolveFailure(message)

        if res.status == 2:
            if endpoint is not None:
                raise fail("face endpoint infeasible after presolve-off retry")
            return None
        if res.status != 0 or res.x is None:
            raise fail(f"{label}: {res.status} {res.message}")
        raw = res.x[:self.nq]
        rounded = np.rint(raw)
        if np.max(np.abs(raw - rounded)) > 1e-5:
            raise fail(f"{label}: noninteger dispatch")
        plan: Schedule = rounded.astype(int).reshape(self.h, self.n, self.r).tolist()
        if not feasible_plan(self.obs, plan):
            raise fail(f"{label}: infeasible returned schedule", plan)
        if target is None:
            value = physical_cost(self.obs, plan, self.demands)
            if abs(value - res.fun) > tolerance(value):
                raise PlannerMismatch(f"{label}: physical={value}, model={res.fun}")
        if endpoint is not None:
            cost = self.value(plan)
            if cost > endpoint[1]:
                raise fail("face endpoint replay above ceiling", plan, cost)
        return plan

    def value(self, plan: Schedule) -> float:
        return physical_cost(self.obs, plan, self.demands)

    def exclude(self, action: list[list[int]]) -> tuple[tuple[Row, ...], int]:
        rows: list[Row] = []
        switches: Weights = {}
        for k, gold in enumerate(q for sku in action for q in sku):
            hi = self.ub[k]
            if gold:
                flag = self.size + len(switches)
                switches[flag] = 1.0
                big = hi - gold + 1
                rows.append(({k: 1.0, flag: big}, -INF, hi))
            if gold < hi:
                flag = self.size + len(switches)
                switches[flag] = 1.0
                big = gold + 1
                rows.append(({k: 1.0, flag: -big}, 0, INF))
        rows.append((switches, 1, INF))
        return tuple(rows), len(switches)

    def audit(self, gold: Schedule, optimum: float) -> Record:
        free = self.optimize("unrestricted")
        if free is None:
            raise PlannerMismatch("unrestricted model infeasible")
        new_value = self.value(free)
        if abs(new_value - optimum) > tolerance(optimum):
            raise PlannerMismatch(f"original={optimum}, new={new_value}")
        ceiling = optimum + tolerance(optimum)
        opposite = []
        for i, terms in enumerate(self.flags):
            row: Row = (terms, 0, 0) if any(gold[0][i]) else (terms, 1, INF)
            other = self.optimize("opposite_flag", (row,))
            opposite.append(other is not None and self.value(other) <= ceiling)
        ranges = []
        quantities = [(f"load.{j}", load) for j, load in enumerate(self.loads)]
        for name, quantity in (*quantities, ("emission", self.emission)):
            ends = []
            for sign, direction in ((1, "min"), (-1, "max")):
                extreme = self.optimize("face_endpoint", ((self.objective, -INF, ceiling),),
                                        {k: sign * weight for k, weight in quantity.items()},
                                        endpoint=(f"{name}.{direction}", ceiling))
                assert extreme is not None
                flat = np.asarray(extreme[0]).ravel()
                ends.append(int(sum(weight * flat[k] for k, weight in quantity.items())))
            ranges.append(ends)
        rows, binaries = self.exclude(gold[0])
        alternate = self.optimize("exclude_action", rows, binaries=binaries)
        if alternate is not None and alternate[0] == gold[0]:
            raise AuditFailure("action exclusion failed", {"plan": alternate})
        return {"new_objective": new_value, "opposite_flags": opposite,
                "load_ranges": ranges[:-1], "emission_range": ranges[-1],
                "other_action": alternate is not None and self.value(alternate) <= ceiling}

