"""Replay frozen observations and evaluate one dispatch on the realized demand path."""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Iterator
from copy import deepcopy
from typing import cast

from rolling_inventory.environment import Environment
from rolling_inventory.planning import base_stock, decide

from .dataset import POLICIES
from .planner import Record, SolveFailure, feasible_plan
from .scoring import answer_map

Action = list[list[int]]
ActionKey = tuple[tuple[int, ...], ...]
COST_COMPONENTS = ("freight", "carbon", "holding", "backlog", "terminal_backlog")
METRICS = ("cost", "fill_rate", "emissions")


class ReplayMismatch(ValueError):
    """Replay did not reproduce a frozen decision state."""


class ContinuationFailure(SolveFailure):
    """A continuation solve or its dispatch validation failed."""

    def __init__(self, message: str, evidence: Record, *, cached: bool = False) -> None:
        super().__init__(message)
        self.evidence = evidence
        self.cached = cached


def _check_observation(env: Environment, graph: Record) -> Record:
    observation: Record = env.observe()  # type: ignore[no-untyped-call]
    expected: Record = graph["observation"]
    if observation != expected:
        fields = sorted(key for key in expected.keys() | observation.keys()
                        if key not in expected or key not in observation or expected[key] != observation[key])
        raise ReplayMismatch(f"{graph['id']}: observation replay differs in {', '.join(fields)}")
    return observation


def replay_trajectory(task: Record, policy: str, graphs: Iterable[Record]) -> Iterator[tuple[Record, Environment]]:
    """Restore each pre-dispatch state using the frozen trajectory's original actions."""
    if policy not in POLICIES:
        raise ReplayMismatch(f"{task['id']}: unknown trajectory policy {policy}")
    env = Environment(task)  # type: ignore[no-untyped-call]
    for t, graph in enumerate(graphs):
        graph_id = f"{task['id']}/{policy}/{t}"
        identity = (graph["id"], graph["split"], graph["profile"], graph["seed"], graph["policy"])
        if identity != (graph_id, task["split"], task["profile"], task["seed"], policy):
            raise ReplayMismatch(f"{graph_id}: found graph {graph['id']} with mismatched identity")
        observation = _check_observation(env, graph)
        yield graph, deepcopy(env)
        if policy == "mpc_scenarios":
            action = answer_map(graph)["B"]
        else:
            action, _ = base_stock(observation, 0.0)  # type: ignore[no-untyped-call]
        env.step(action)  # type: ignore[no-untyped-call]


def _totals(periods: list[Record]) -> Record:
    demand = sum(sum(row["demand"]) for row in periods)
    filled = sum(sum(row["filled_new"]) for row in periods)
    return {"cost": math.fsum(row["cost"] for row in periods), "fill_rate": filled / demand if demand else 1.0,
            "emissions": sum(row["emissions"] for row in periods)}


def _delta(actual: Record, reference: Record) -> Record:
    return {metric: actual[metric] - reference[metric] for metric in METRICS}


class Consequences:
    """Evaluate and cache feasible dispatch rollouts within one graph."""

    def __init__(self, env: Environment, graph: Record, counts: Counter[str]) -> None:
        self._env = env
        self._obs = _check_observation(env, graph)
        self._graph_id: str = graph["id"]
        self._counts = counts
        self._reference: Action = answer_map(graph)["B"]
        if not feasible_plan(self._obs, [self._reference], first=True):
            raise ReplayMismatch(f"{self._graph_id}: frozen reference action is infeasible")
        self._cache: dict[ActionKey, Record] = {}
        self._failures: dict[ActionKey, tuple[str, Record]] = {}
        self.cache_hits = 0

    def _rollout(self, first_action: Action) -> Record:
        env = deepcopy(self._env)
        periods: list[Record] = []
        start = self._obs["t"]
        for t in range(start, self._obs["public"]["periods"]):
            if t == start:
                row: Record = env.step(first_action)  # type: ignore[no-untyped-call]
            else:
                self._counts["continuation"] += 1
                try:
                    observation: Record = env.observe()  # type: ignore[no-untyped-call]
                    action, _ = decide(observation, "mpc_scenarios")  # type: ignore[no-untyped-call]
                    row = env.step(action)  # type: ignore[no-untyped-call]
                except ValueError as exc:
                    raise ContinuationFailure(f"{self._graph_id} continuation at {t}: {exc}", {
                        "first_action": first_action, "failed_period": t, "periods": periods,
                    }) from exc
            periods.append({"t": t, "action": row["action"], "demand": row["demand"],
                            "filled_new": row["filled_new"], "emissions": row["emissions"],
                            "costs": row["costs"], "cost": row["cost"]})
        return {**_totals(periods), "periods": periods}

    def _outcome(self, action: Action, *, count_hit: bool = True) -> Record:
        key = tuple(tuple(route_counts) for route_counts in action)
        if key in self._cache:
            self.cache_hits += int(count_hit)
            return self._cache[key]
        if key in self._failures:
            self.cache_hits += int(count_hit)
            message, evidence = self._failures[key]
            raise ContinuationFailure(message, evidence, cached=True)
        try:
            outcome = self._rollout(action)
        except ContinuationFailure as exc:
            self._failures[key] = (str(exc), exc.evidence)
            raise
        self._cache[key] = outcome
        return outcome

    def compare(self, action: object) -> Record:
        if not feasible_plan(self._obs, [action], first=True):
            return {"status": "violation", "reference": None, "actual": None, "delta": None}
        reference = self._outcome(self._reference, count_hit=False)
        actual = self._outcome(cast(Action, action))
        return {"status": "ok", "reference": reference, "actual": actual, "delta": _delta(actual, reference)}


def verify_comparison(comparison: Record, *, start_period: int | None = None, end_period: int | None = None) -> None:
    """Recompute branch totals and the paired differences from the saved period ledgers."""
    reference, actual = comparison["reference"], comparison["actual"]
    if comparison["status"] == "violation":
        if any(value is not None for value in (reference, actual, comparison["delta"])):
            raise ValueError("violation contains executed consequence evidence")
        return
    if comparison["status"] != "ok" or reference is None or actual is None:
        raise ValueError("missing paired consequence evidence")

    totals = []
    for branch in (reference, actual):
        periods = branch["periods"]
        if not periods:
            raise ValueError("missing consequence periods")
        start = periods[0]["t"]
        if start_period is not None and start != start_period:
            raise ValueError("consequence begins outside the decision period")
        if end_period is not None and start + len(periods) - 1 != end_period:
            raise ValueError("consequence does not reach the episode end")
        for t, row in enumerate(periods, start=start):
            if row["t"] != t or set(row["costs"]) != set(COST_COMPONENTS):
                raise ValueError("invalid consequence periods or cost components")
            if row["cost"] != sum(row["costs"][name] for name in COST_COMPONENTS):
                raise ValueError("period cost does not match its components")
            if len(row["filled_new"]) != len(row["demand"]) or any(
                not 0 <= filled <= demand for filled, demand in zip(row["filled_new"], row["demand"])
            ):
                raise ValueError("invalid immediate fulfillment")
        result = _totals(periods)
        if any(branch[key] != value for key, value in result.items()):
            raise ValueError("consequence totals disagree with period evidence")
        totals.append(result)
    if ([(row["t"], row["demand"]) for row in reference["periods"]]
            != [(row["t"], row["demand"]) for row in actual["periods"]]):
        raise ValueError("branches do not share one demand path")
    if comparison["delta"] != _delta(totals[1], totals[0]):
        raise ValueError("consequence differences disagree with branch totals")
