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

  Order of the solves, so that every free solve starts from a feasible plan: (1) the deterministic scenario with
  perfect information; (2) its first stage in every other scenario (these make the EEV); (3) every other scenario
  with perfect information, started from (2); (4) every new candidate in the scenarios it did not come from.
  Every scenario is solved on its own with probability one; the probabilities weight the results afterwards.

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
from dataclasses import replace
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
    config, scenario, fixed, options, start = job
    alone = replace(scenario, probability=1.0)  # weighted by its probability afterwards
    result = solve(config, [alone], mode="joint", fixed_first_stage=fixed, start=start, **options)
    keep = {k: result.get(k) for k in ("status", "objective_usd", "first_stage", "first_stage_cost_usd", "values")}
    keep["stats"] = result["stats"]
    keep["second_stage_usd"] = (None if result.get("objective_usd") is None
                                else result["objective_usd"] - result["first_stage_cost_usd"])
    return keep


def decompose(config: dict[str, Any], scenarios: Sequence[Scenario], *, deterministic: str = "normal",
              workers: int = 4, options: dict[str, Any] | None = None, start: dict[str, float] | None = None,
              log: Callable[[str], None] = print) -> dict[str, Any]:
    """Wait-and-see, candidate first stages and their evaluation in every scenario; see the module docstring.

    ``start`` is a starting solution for the deterministic scenario's perfect-information solve (for example the
    better of plans B and B*). The result carries ``start_for_equivalent``: the best candidate's solutions in every
    scenario, a feasible start for ``deterministic_equivalent``."""
    options = options or {"time_limit": 900, "mip_gap": 1e-3}
    names = [s.name for s in scenarios]
    if deterministic not in names:
        raise ValueError(f"the deterministic scenario '{deterministic}' is not among the scenarios")
    by_name = {s.name: s for s in scenarios}
    others = [s for s in scenarios if s.name != deterministic]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        det = pool.submit(_solve_job, (config, by_name[deterministic], None, options, start)).result()
        log(f"perfect information {deterministic}: {det['status']} {det.get('objective_usd')} "
            f"gap {det['stats']['mip_gap']}")
        if not det.get("first_stage"):
            raise ValueError(f"the deterministic scenario '{deterministic}' has no plan")
        det_first = det["first_stage"]
        evaluated_det = dict(zip([s.name for s in others], pool.map(
            _solve_job, [(config, s, det_first, options, None) for s in others]), strict=True))
        for name, r in evaluated_det.items():
            log(f"deterministic plan in {name}: {r['status']} {r.get('objective_usd')}")
        wait_and_see = {deterministic: det}
        wait_and_see.update(zip([s.name for s in others], pool.map(
            _solve_job, [(config, s, None, options, evaluated_det[s.name].get("values")) for s in others]),
            strict=True))
        for name in names:
            r = wait_and_see[name]
            log(f"perfect information {name}: {r['status']} {r.get('objective_usd')} gap {r['stats']['mip_gap']}")
        candidates: dict[str, dict[str, Any]] = {}
        origin: dict[str, list[str]] = {}
        for name in names:
            r = wait_and_see[name]
            if r.get("first_stage"):
                ck = key(r["first_stage"])
                candidates.setdefault(ck, r["first_stage"])
                origin.setdefault(ck, []).append(name)
        deterministic_key = key(det_first)
        table: dict[str, dict[str, Any]] = {ck: {n: wait_and_see[n] for n in origin[ck]} for ck in candidates}
        for name, r in evaluated_det.items():
            table[deterministic_key].setdefault(name, r)
        jobs, labels = [], []
        for ck, first in candidates.items():
            for s in scenarios:
                if s.name not in table[ck]:
                    jobs.append((config, s, first, options, None))
                    labels.append((ck, s.name))
        for (ck, name), r in zip(labels, pool.map(_solve_job, jobs), strict=True):
            table[ck][name] = r
            log(f"candidate {list(candidates).index(ck)} in {name}: {r['status']} {r.get('objective_usd')}")
    probability = {s.name: s.probability for s in scenarios}

    def expected(ck: str) -> dict[str, Any]:
        rows = table[ck]
        missing = [n for n in names if rows[n].get("objective_usd") is None]
        if missing:
            return {"status": "infeasible or unsolved in " + ", ".join(missing),
                    "per_scenario": {n: rows[n]["status"] for n in names}}
        value = sum(probability[n] * rows[n]["objective_usd"] for n in names)
        low = sum(probability[n] * lower(rows[n]["objective_usd"], rows[n]["stats"]["dual_bound"]) for n in names)
        return {"status": "ok", "expected_usd": value, "interval": [low, value],
                "per_scenario": {n: rows[n]["objective_usd"] for n in names},
                "first_stage_usd": rows[names[0]]["first_stage_cost_usd"]}

    evaluated = {ck: expected(ck) for ck in candidates}
    feasible = {ck: e for ck, e in evaluated.items() if e["status"] == "ok"}
    best = min(feasible, key=lambda ck: feasible[ck]["expected_usd"]) if feasible else None
    ws_value = sum(probability[n] * wait_and_see[n]["objective_usd"] for n in names)
    ws_low = sum(probability[n] * lower(wait_and_see[n]["objective_usd"], wait_and_see[n]["stats"]["dual_bound"])
                 for n in names)
    out: dict[str, Any] = {
        "scenarios": dict(probability),
        "wait_and_see": {n: {"objective_usd": r.get("objective_usd"), "status": r["status"],
                             "mip_gap": r["stats"]["mip_gap"], "dual_bound": r["stats"]["dual_bound"],
                             "first_stage": r.get("first_stage")} for n, r in wait_and_see.items()},
        "WS": {"value": ws_value, "interval": [ws_low, ws_value]},
        "candidates": [{"key": ck, "first_stage": candidates[ck], "origin": origin[ck], **evaluated[ck]}
                       for ck in candidates],
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
        merged: dict[str, float] = {}
        for name in names:
            merged.update(table[best][name].get("values") or {})
        out["start_for_equivalent"] = merged
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
