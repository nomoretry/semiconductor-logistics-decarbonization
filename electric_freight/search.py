"""Fix-and-optimize search around a saved plan of model v2 (a large-neighbourhood search).

At the fleet instance the full joint MILP stops at its starting plan within the time limit. This search improves a
saved plan step by step: in each step every trip outside one part of the schedule (one truck, or the departures of a
48-hour window) is fixed to the current plan, and the rest (those trips, cargo, the first stage and charging) is
solved again, starting from the current plan, so a step can only keep or lower the cost. The same parts, rounds and
time limits serve plan B* (with the step-1 transport cap) and plan C, so neither gets more search than the other.

A step's dual bound is only a bound of its restricted problem; the lower bound of the plan remains the full solve's.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from .fleet import Scenario, solve, trucks_of


def default_parts(config: dict[str, Any], instance: str, *, window_hours: int = 48,
                  step_hours: int = 24) -> list[dict[str, Any]]:
    """Each truck alone, then every window of ``window_hours`` starting each ``step_hours`` (all trucks)."""
    own, leasable = trucks_of(config, instance)
    parts: list[dict[str, Any]] = [{"trucks": [k]} for k in own + leasable]
    parts += [{"window": [a, a + window_hours]} for a in range(0, 168, step_hours)]
    return parts


def improve(config: dict[str, Any], scenarios: Sequence[Scenario], trips: dict[str, Any], *,
            parts: list[dict[str, Any]], transport_cap: float | None = None, sub_time_limit: float = 120.0,
            mip_gap: float = 1e-3, rounds: int = 2, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Start from the saved ``trips`` ({scenario: {week type: [trip, ...]}}), re-solve everything else with those trips
    fixed, then free one part at a time; a round with no gain ends the search."""
    started = time.perf_counter()

    def step(hood: dict[str, Any], start: dict[str, float] | None) -> dict[str, Any]:
        return solve(config, scenarios, mode="joint", neighbourhood=hood, start=start, transport_cap=transport_cap,
                     time_limit=sub_time_limit, mip_gap=mip_gap)

    current = step({"trips": trips, "free": []}, None)
    history: list[dict[str, Any]] = [{"round": 0, "free": "saved trips fixed", "status": current["status"],
                                      "objective_usd": current.get("objective_usd"),
                                      "seconds": current["stats"]["solve_seconds"]}]
    log(f"saved trips fixed: {current['status']} {current.get('objective_usd')}")
    if "values" not in current:
        return {**current, "search": {"history": history, "seconds": round(time.perf_counter() - started, 1)}}
    first = float(current["objective_usd"])
    for r in range(1, rounds + 1):
        better = False
        for part in parts:
            trial = step({"values": current["values"], "free": [part]}, current["values"])
            value = trial.get("objective_usd")
            gain = None if value is None else float(current["objective_usd"]) - float(value)
            history.append({"round": r, "free": part, "status": trial["status"], "objective_usd": value,
                            "gain_usd": gain, "mip_gap": trial["stats"]["mip_gap"],
                            "seconds": trial["stats"]["solve_seconds"]})
            log(f"round {r} {part}: {trial['status']} {value} gain {gain}")
            if gain is not None and gain > 1e-6 * abs(float(current["objective_usd"])) + 1e-6:
                current, better = trial, True
        if not better:
            break
    return {**current, "search": {"history": history, "saved_trips_usd": first,
                                  "seconds": round(time.perf_counter() - started, 1)}}
