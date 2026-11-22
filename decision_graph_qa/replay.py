"""Dataset replay including independent scalar forecast balances and tie audits."""
from __future__ import annotations

import math
import random
from collections import Counter
from pathlib import Path

from rolling_inventory.environment import Environment
from rolling_inventory.planning import base_stock

from .dataset import (
    CONFIG,
    POLICIES,
    SCHEMA,
    SEEDS,
    check_manifest,
    digest,
    graphs,
    read,
    records,
    stats,
    trajectories,
)
from .graph import state_text, structure
from .planner import (
    Model,
    PlannerMismatch,
    Record,
    allowance,
    feasible_plan,
    original,
    physical_cost,
    scenarios,
    solve_counts,
    tolerance,
    window,
)
from .scoring import grade_graph, matches


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_forecasts(obs: Record, demand: list[list[float]], answers: Record) -> None:
    h = window(obs)
    mass_needed = 0.0
    p = obs["public"]
    for i, mass in enumerate(p["mass"]):
        balance = obs["stock"][i] - obs["backlog"][i]
        worst = 0.0
        first = None
        received = used = 0.0
        for offset in range(h):
            received += obs["pipeline"][obs["t"] + offset][i]
            used += demand[offset][i]
            net = balance + (received - used)
            # Match the grouping of period flows when testing the strict first-shortage boundary.
            if abs(net) < 1e-12:
                net = balance + sum(obs["pipeline"][obs["t"] + v][i] - demand[v][i]
                                    for v in range(offset + 1))
            if net < 0 and first is None:
                first = offset
            worst = max(worst, -net)
        total = float(sum(row[i] for row in demand[:min(3, h)]))
        require(matches(total, answers[f"P2.sum.{i}"]) and matches(first, answers[f"P2.first.{i}"])
                and matches(worst, answers[f"P2.peak.{i}"]), f"forecast SKU {i}")
        mass_needed += mass * worst
    require(matches(mass_needed > p["capacity"][0] * max(0, h - p["lead"][0]), answers["P2.capacity"])
            and matches(mass_needed * p["emissions"][0] > allowance(obs), answers["P2.carbon"]),
            "global pressure mismatch")


def verify(directory: Path) -> Record:
    check_manifest(directory)
    config, summary = read(directory / "config.json"), read(directory / "summary.json")
    pilot = config["phase"] == "pilot"
    require(config == {"phase": "pilot" if pilot else "formal", "environment": read(CONFIG),
                       "policies": list(POLICIES), "seeds": {s: v[:1] if pilot else v for s, v in SEEDS.items()}},
            "config mismatch")
    require(digest(directory / "graph.schema.json") == digest(SCHEMA), "schema source mismatch")
    try:
        from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
    except ImportError:
        validator = None
    else:
        schema = read(SCHEMA)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
    attempts = list(records(directory / "attempts.jsonl"))
    logs = {r["id"]: r for r in attempts}
    require(len(logs) == len(attempts), "duplicate attempt")
    streams = {s: records(directory / f"{s}.jsonl") for s in SEEDS}
    verified = 0
    seen: set[str] = set()
    for task, policy in trajectories(pilot):
        env = Environment(task)
        for t in range(task["public"]["periods"] - 1):
            gid = f"{task['id']}/{policy}/{t}"
            require(gid in logs, f"missing attempt: {gid}")
            seen.add(gid)
            if logs[gid]["status"] != "ok":
                require(logs[gid]["unvisited_offsets"] == list(range(t + 1, 11)), "failure accounting")
                break
            g = next(streams[task["split"]], None)
            require(g is not None, f"missing graph: {gid}")
            assert g is not None
            if validator is not None:
                validator.validate(g)
            obs = env.observe()
            require((g["id"], g["split"], g["profile"], g["seed"], g["policy"]) ==
                    (gid, task["split"], task["profile"], task["seed"], policy), "graph identity")
            require(g["observation"] == obs and g["state_text"] == state_text(obs), "observation replay")
            require(g["modes"] == ["None", "Chain", "Graph"], "context modes")
            answers = {n["id"]: n["answer"] for n in g["nodes"]}
            plan = answers["M"]
            require(feasible_plan(obs, plan) and feasible_plan(obs, [answers["B"]], first=True)
                    and plan[0] == answers["B"], "action or plan feasibility")
            nodes, edges = structure(obs, plan)
            require(len(nodes) == len(g["nodes"]) and g["edges"] == edges, "topology/template mismatch")
            for n, actual in zip(nodes, g["nodes"]):
                require(all(n[k] == actual[k] for k in ("id", "stage", "question"))
                        and matches(n["answer"], actual["answer"]), "node mismatch")
            verify_forecasts(obs, obs["forecast"], answers)
            verify_forecasts(obs, task["demand"][t:], g["hindsight"]["prediction"])
            require(feasible_plan(obs, [g["hindsight"]["first_action_with_known_demand"]], first=True),
                    "known-demand action infeasible")
            cost = physical_cost(obs, plan, scenarios(obs))
            require(matches(cost, g["objective"]) and matches(cost, g["ties"]["new_objective"]),
                    "objective replay")
            for j, (lo, hi) in enumerate(g["ties"]["load_ranges"]):
                require(0 <= lo <= answers[f"P3.load.{j}"] <= hi <= obs["public"]["capacity"][j],
                        "route range")
            lo, hi = g["ties"]["emission_range"]
            require(0 <= lo <= answers["P3.emission"] <= hi <= allowance(obs), "emission range")
            action = plan[0] if policy == "mpc_scenarios" else base_stock(obs, 0.0)[0]
            env.step(action)
            verified += 1
    require(seen == set(logs) and all(next(stream, None) is None for stream in streams.values()),
            "unexpected graph or attempt")
    require(all(summary[k] == v for k, v in stats(directory).items()), "summary statistics")
    return {"verified": verified, "solver_calls": 0, "sha256_files": len(read(directory / "manifest.json")["files"]),
            "schema": "2020-12" if validator is not None else "basic"}


def recheck(directory: Path, sample: float) -> Record:
    require(0 < sample <= 1, "sample must lie in (0,1]")
    check_manifest(directory)
    items = list(graphs(directory))
    selected = random.Random(901337).sample(items, math.ceil(len(items) * sample))
    counts: Counter[str] = Counter()
    for g in selected:
        obs = g["observation"]
        demands = scenarios(obs)
        _, value = original(obs, demands, counts, "reference")
        if abs(value - g["objective"]) > tolerance(value):
            raise PlannerMismatch(f"{g['id']}: reference objective mismatch")
        plan = next(n["answer"] for n in g["nodes"] if n["id"] == "M")
        actual = Model(obs, demands, counts).audit(plan, value)
        expected = g["ties"]
        require(matches(value, actual["new_objective"]) and all(actual[k] == expected[k] for k in
                ("opposite_flags", "load_ranges", "emission_range", "other_action")),
                f"{g['id']}: tie discrepancy")
        answers = {n["id"]: n["answer"] for n in g["nodes"] if n["stage"] in ("P3", "B")}
        rows = grade_graph(g, answers, counts)
        require(all(r["correct"] for r in rows if r["provided"]), f"{g['id']}: P3/B score")
    return {"verified": len(selected), "sample": sample, "sample_seed": 901337,
            "graph_ids": [g["id"] for g in selected], **solve_counts(counts)}


def score(directory: Path, responses: Path, details: Path | None = None) -> Record:
    check_manifest(directory)
    submitted: dict[str, Record] = {}
    for item in records(responses):
        key = item["id"]
        require(key not in submitted and isinstance(item["answers"], dict), "duplicate or invalid response")
        submitted[key] = item["answers"]
    counts: Counter[str] = Counter()
    totals: dict[str, Counter[str]] = {}
    l1_sum = feasible_plans = 0
    output = details.open("x", encoding="utf-8", newline="\n") if details is not None else None
    try:
        from .graph import compact
        for g in graphs(directory):
            rows = grade_graph(g, submitted.pop(g["id"], {}), counts)
            for row in rows:
                c = totals.setdefault(row["stage"], Counter())
                c.update({"expected": 1, "correct": int(row["correct"]), "provided": int(row["provided"]),
                          "violations": int(row["violation"])})
                if row["l1"] is not None:
                    l1_sum += row["l1"]
                    feasible_plans += 1
            if output is not None:
                output.write(compact({"id": g["id"], "nodes": rows}) + "\n")
    finally:
        if output is not None:
            output.close()
    require(not submitted, "unknown graph ID")
    all_counts = sum(totals.values(), Counter())
    denom = sum(totals.get(stage, Counter())["provided"] for stage in ("P3", "B", "M"))
    return {"stages": totals, "stage_accuracy": {s: c["correct"] / c["expected"] for s, c in totals.items()},
            "feasible_plans": feasible_plans, "mean_plan_l1": l1_sum / feasible_plans if feasible_plans else None,
            "expected": all_counts["expected"], "correct": all_counts["correct"],
            "accuracy": all_counts["correct"] / all_counts["expected"] if all_counts["expected"] else None,
            "violations": all_counts["violations"], "violation_denominator": denom,
            "violation_rate": all_counts["violations"] / denom if denom else None, **solve_counts(counts)}

