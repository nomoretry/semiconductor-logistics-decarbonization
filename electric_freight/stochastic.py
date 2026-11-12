"""Two-stage stochastic planning of charging equipment and grid access for the corridor (model v2).

First stage, decided before the scenario is known and shared by all scenarios: sites, connectors per power tier,
connection upgrades, which substation each site is wired to, substation expansions and leasing a truck for the season.
Second stage, decided once the scenario is known: cargo, week types, truck schedules and charging.

Two ways to solve it are kept side by side:

- ``deterministic_equivalent``: one MILP with every scenario's second stage and one shared first stage;
- ``decompose``: solve every scenario with perfect information (wait-and-see), collect their first stages and the
  deterministic plan's first stage as candidates, and evaluate every candidate in every scenario with the first stage
  fixed. The best candidate is a stochastic plan whose expected cost is an upper bound on the true optimum (RP); the
  wait-and-see value is a lower bound on it.

Reported quantities, all with intervals from the MIP gaps:
    WS   expected cost with perfect information;
    RP   expected cost of the best first stage found (two-stage plan);
    EEV  expected cost of the deterministic plan's first stage (planned for the normal scenario);
    VSS = EEV - RP, EVPI = RP - WS.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from .fleet import Scenario, make_scenario, solve


def scenario_set(config: dict[str, Any], spec: dict[str, Any], instance: str = "base") -> list[Scenario]:
    total = sum(item["probability"] for item in spec.values())
    return [make_scenario(config, name, item["probability"] / total, overrides=item.get("overrides"),
                          weekly_plan=item.get("weekly_plan", "normal"),
                          congested_weeks=item.get("congested_weeks", ()), instance=instance)
            for name, item in spec.items()]


def key(first_stage: dict[str, Any]) -> str:
    """A canonical text form of a first stage, so equal decisions compare equal."""
    plant = first_stage.get("plant", {})
    parts = {"lease": {k: v for k, v in sorted(first_stage.get("lease", {}).items()) if v}}
    for group in ("open", "n", "up", "conn", "exp"):
        parts[group] = {k: v for k, v in sorted(plant.get(group, {}).items()) if v}
    return json.dumps(parts, sort_keys=True)


def lower(value: float, bound: float | None) -> float:
    """The lower end of a minimisation solved to a gap: the dual bound, never above the incumbent."""
    return value if bound is None else min(bound, value)


def _solve_job(job: tuple[Any, ...]) -> dict[str, Any]:
    config, scenario, fixed, options = job
    result = solve(config, [scenario], mode="joint", fixed_first_stage=fixed, **options)
    keep = {k: result.get(k) for k in ("status", "objective_usd", "first_stage", "first_stage_cost_usd")}
    keep["stats"] = result["stats"]
    keep["second_stage_usd"] = (None if result.get("objective_usd") is None
                                else result["objective_usd"] - result["first_stage_cost_usd"])
    keep["solution"] = result.get("solution")
    return keep


def decompose(config: dict[str, Any], scenarios: Sequence[Scenario], *, deterministic: str = "normal",
              workers: int = 6, options: dict[str, Any] | None = None,
              log: Callable[[str], None] = print) -> dict[str, Any]:
    options = options or {"time_limit": 900, "mip_gap": 1e-3}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        wait_and_see = dict(zip([s.name for s in scenarios],
                                pool.map(_solve_job, [(config, s, None, options) for s in scenarios]), strict=True))
        for name, r in wait_and_see.items():
            log(f"perfect information {name}: {r['status']} {r.get('objective_usd')} gap {r['stats']['mip_gap']}")
        candidates: dict[str, dict[str, Any]] = {}
        for r in wait_and_see.values():
            if r.get("first_stage"):
                candidates.setdefault(key(r["first_stage"]), r["first_stage"])
        if deterministic not in wait_and_see or not wait_and_see[deterministic].get("first_stage"):
            raise ValueError(f"the deterministic scenario '{deterministic}' has no plan")
        deterministic_key = key(wait_and_see[deterministic]["first_stage"])
        jobs, labels = [], []
        for ck, first in candidates.items():
            for s in scenarios:
                origin = [n for n, r in wait_and_see.items() if r.get("first_stage") and key(r["first_stage"]) == ck]
                if s.name in origin:
                    continue  # already solved: this scenario's own optimum
                jobs.append((config, s, first, options))
                labels.append((ck, s.name))
        table: dict[str, dict[str, Any]] = {ck: {} for ck in candidates}
        for ck in candidates:
            for name, r in wait_and_see.items():
                if r.get("first_stage") and key(r["first_stage"]) == ck:
                    table[ck][name] = r
        for (ck, name), r in zip(labels, pool.map(_solve_job, jobs), strict=True):
            table[ck][name] = r
            log(f"candidate {list(candidates).index(ck)} in {name}: {r['status']} {r.get('objective_usd')}")
    probability = {s.name: s.probability for s in scenarios}

    def expected(ck: str) -> dict[str, Any]:
        rows = table[ck]
        if any(rows[s.name].get("objective_usd") is None for s in scenarios):
            return {"status": "infeasible in " + ", ".join(s.name for s in scenarios
                                                            if rows[s.name].get("objective_usd") is None)}
        value = sum(probability[n] * rows[n]["objective_usd"] for n in probability)
        low = sum(probability[n] * lower(rows[n]["objective_usd"], rows[n]["stats"]["dual_bound"])
                  for n in probability)
        return {"status": "ok", "expected_usd": value, "interval": [low, value],
                "per_scenario": {n: rows[n]["objective_usd"] for n in probability},
                "first_stage_usd": rows[scenarios[0].name]["first_stage_cost_usd"]}

    evaluated = {ck: expected(ck) for ck in candidates}
    feasible = {ck: e for ck, e in evaluated.items() if e["status"] == "ok"}
    best = min(feasible, key=lambda ck: feasible[ck]["expected_usd"]) if feasible else None
    ws_value = sum(probability[n] * r["objective_usd"] for n, r in wait_and_see.items())
    ws_low = sum(probability[n] * lower(r["objective_usd"], r["stats"]["dual_bound"])
                 for n, r in wait_and_see.items())
    out: dict[str, Any] = {
        "scenarios": {s.name: s.probability for s in scenarios},
        "wait_and_see": {n: {"objective_usd": r.get("objective_usd"), "status": r["status"],
                             "mip_gap": r["stats"]["mip_gap"], "dual_bound": r["stats"]["dual_bound"],
                             "first_stage": r.get("first_stage")} for n, r in wait_and_see.items()},
        "WS": {"value": ws_value, "interval": [ws_low, ws_value]},
        "candidates": [{"key": ck, "first_stage": candidates[ck], "origin":
                        [n for n, r in wait_and_see.items() if r.get("first_stage") and key(r["first_stage"]) == ck],
                        **evaluated[ck]} for ck in candidates],
        "deterministic_candidate": deterministic_key}
    eev = evaluated[deterministic_key]
    out["EEV"] = eev
    if best is not None:
        rp = feasible[best]
        out["RP"] = {"candidate": best, **rp}
        out["EVPI"] = {"value": rp["expected_usd"] - ws_value,
                       "interval": [rp["interval"][0] - ws_value, rp["expected_usd"] - ws_low]}
        if eev["status"] == "ok":
            out["VSS"] = {"value": eev["expected_usd"] - rp["expected_usd"],
                          "interval": [eev["interval"][0] - rp["expected_usd"],
                                       eev["expected_usd"] - rp["interval"][0]]}
        else:
            out["VSS"] = {"value": None, "note": f"the deterministic plan's equipment is {eev['status']}"}
    out["table"] = {ck: {n: {"objective_usd": r.get("objective_usd"), "status": r["status"],
                             "mip_gap": r["stats"]["mip_gap"], "dual_bound": r["stats"]["dual_bound"],
                             "solve_seconds": r["stats"]["solve_seconds"]} for n, r in rows.items()}
                    for ck, rows in table.items()}
    return out


def deterministic_equivalent(config: dict[str, Any], scenarios: Sequence[Scenario], *, time_limit: float = 3600,
                             mip_gap: float = 1e-3, start: dict[str, float] | None = None) -> dict[str, Any]:
    """All scenarios in one MILP with one first stage."""
    result = solve(config, scenarios, mode="joint", time_limit=time_limit, mip_gap=mip_gap, start=start)
    return {k: result.get(k) for k in ("status", "objective_usd", "first_stage", "first_stage_cost_usd", "stats")}
