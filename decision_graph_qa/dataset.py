"""Sequential generation, raw evidence, manifest and release statistics."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from collections import Counter
from collections.abc import Iterator
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np

from rolling_inventory.environment import Environment, generate
from rolling_inventory.planning import base_stock

from .graph import compact, make_graph
from .planner import (
    PRESOLVE,
    RETRY_OUTCOMES,
    AuditFailure,
    PlannerMismatch,
    Record,
    SolveFailure,
    solve_counts,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "rolling_inventory" / "config.json"
SCHEMA = Path(__file__).parent / "schema" / "graph.json"
SEEDS = {"train": [5101, 5209, 5119, 5147], "dev": [5153, 5167], "test": [5171, 5179, 5189, 5227]}
POLICIES = ("mpc_scenarios", "base_stock")
RATE_LIMIT = 0.01
PUBLIC_FILES = {"config.json", "graph.schema.json", "environment.json", "summary.json", "attempts.jsonl",
                *(f"{split}.jsonl" for split in SEEDS)}


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
                    + "\n", encoding="utf-8", newline="\n")


def records(path: Path) -> Iterator[Record]:
    with path.open(encoding="utf-8") as file:
        for line in file:
            item = json.loads(line)
            if not isinstance(item, dict):
                raise TypeError(f"{path.name}: expected an object per line")
            yield item


def append(path: Path, item: Record) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(compact(item) + "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_manifest(directory: Path) -> None:
    files = read(directory / "manifest.json")["files"]
    if set(files) != PUBLIC_FILES or {p.name for p in directory.iterdir()} != PUBLIC_FILES | {"manifest.json"}:
        raise ValueError("manifest file set")
    for name in sorted(PUBLIC_FILES):
        if digest(directory / name) != files[name]:
            raise ValueError(f"SHA256 mismatch: {name}")


def graphs(directory: Path) -> Iterator[Record]:
    for split in SEEDS:
        yield from records(directory / f"{split}.jsonl")


def trajectories(pilot: bool) -> Iterator[tuple[Record, str]]:
    cfg = read(CONFIG)
    for split, seeds in SEEDS.items():
        for task in generate(cfg, split, seeds[:1] if pilot else seeds):
            for policy in POLICIES:
                yield task, policy


def stats(directory: Path) -> Record:
    splits: Counter[str] = Counter()
    profiles: Counter[str] = Counter()
    policies: Counter[str] = Counter()
    stages: Counter[str] = Counter()
    layers: Counter[str] = Counter()
    target_stages: Counter[str] = Counter()
    ties: Counter[str] = Counter()
    paths: set[tuple[str, int, str]] = set()
    traces: set[tuple[str, int, str, str]] = set()
    max_delta = 0.0
    max_relative = 0.0
    for g in graphs(directory):
        splits[g["split"]] += 1
        profiles[g["profile"]] += 1
        policies[g["policy"]] += 1
        path = (g["split"], g["seed"], g["profile"])
        paths.add(path)
        traces.add((*path, g["policy"]))
        stages.update(n["stage"] for n in g["nodes"])
        layers.update(e["layer"] for e in g["edges"])
        target_stages.update(e["to"].split(".")[0] for e in g["edges"])
        audit = g["ties"]
        for i, flag in enumerate(audit["opposite_flags"]):
            ties[f"P3.ship.{i}"] += int(flag)
        for j, (lo, hi) in enumerate(audit["load_ranges"]):
            ties[f"P3.load.{j}"] += int(lo != hi)
        lo, hi = audit["emission_range"]
        ties["P3.emission"] += int(lo != hi)
        ties["B"] += int(audit["other_action"])
        action = next(n["answer"] for n in g["nodes"] if n["id"] == "B")
        ties["known_action_differs"] += int(action != g["hindsight"]["first_action_with_known_demand"])
        delta = abs(audit["new_objective"] - g["objective"])
        max_delta = max(max_delta, delta)
        if g["objective"]:
            max_relative = max(max_relative, delta / abs(g["objective"]))
    attempts = list(records(directory / "attempts.jsonl"))
    counters: dict[str, Counter[str]] = {name: Counter() for name in ("solves", *RETRY_OUTCOMES)}
    for row in attempts:
        for name, counts in counters.items():
            counts.update(row.get(name, {}))
    p95 = float(np.percentile([r["seconds"] for r in attempts], 95)) if attempts else None
    return {"graphs": sum(splits.values()), "paths": len(paths), "trajectories": len(traces),
            "by_split": splits, "by_profile": profiles, "by_policy": policies, "nodes": stages,
            "edge_layers": layers, "edges_by_target_stage": target_stages, "tie_counts": ties,
            "max_abs_difference": max_delta, "max_relative_difference": max_relative,
            "attempted": len(attempts), "failures": sum(r["status"] != "ok" for r in attempts),
            **counters, "p95_seconds": p95,
            "estimated_formal_seconds": None if p95 is None else p95 * 880 + 60}


def environment() -> Record:
    packages: dict[str, str | None] = {}
    for package in ("numpy", "scipy", "jsonschema"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return {"python": sys.version, "platform": platform.platform(), "processor": platform.processor(),
            "extended_planner_presolve": PRESOLVE, "reference_planner_presolve": True,
            "packages": packages, "sha256_config": digest(CONFIG),
            "sha256_protocol": digest(ROOT / "docs" / "decision_graph_qa_protocol.md"),
            "sha256_amendment": digest(ROOT / "docs" / "decision_graph_qa_protocol_amendment.md"),
            "source_sha256": {p.relative_to(ROOT).as_posix(): digest(p) for p in
                              [*sorted(Path(__file__).parent.glob("*.py")), SCHEMA,
                               ROOT / "rolling_inventory" / "environment.py",
                               ROOT / "rolling_inventory" / "planning.py"]}}


def pilot_gate(directory: Path) -> None:
    check_manifest(directory)
    summary = read(directory / "summary.json")
    actual = stats(directory)
    expected_ids = {f"{t['id']}/{policy}/{u}" for t, policy in trajectories(True) for u in range(11)}
    if (summary["phase"] != "pilot" or summary["status"] != "complete"
            or any(summary[k] != v for k, v in actual.items())
            or {g["id"] for g in graphs(directory)} != expected_ids
            or actual["graphs"] != 264 or actual["attempted"] != 264 or actual["failures"]
            or actual["estimated_formal_seconds"] > 3600):
        raise ValueError("pilot did not clear the 264-graph / 3600-second gate")
    if read(directory / "environment.json") != environment():
        raise ValueError("pilot provenance differs from current build")


def build(directory: Path, *, pilot: bool, pilot_evidence: Path | None = None) -> Record:
    if not pilot:
        if pilot_evidence is None:
            raise ValueError("formal generation requires pilot evidence")
        pilot_gate(pilot_evidence)
    directory.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    for name in PUBLIC_FILES:
        if name.endswith(".jsonl"):
            (directory / name).touch()
    write(directory / "config.json", {"phase": "pilot" if pilot else "formal",
                                      "seeds": {s: v[:1] if pilot else v for s, v in SEEDS.items()},
                                      "policies": POLICIES, "environment": read(CONFIG)})
    (directory / "graph.schema.json").write_bytes(SCHEMA.read_bytes())
    write(directory / "environment.json", environment())
    attempted = failures = 0
    stop = ""
    for task, policy in trajectories(pilot):
        env = Environment(task)
        for _ in range(task["public"]["periods"] - 1):
            t0 = time.perf_counter()
            obs = env.observe()
            gid = f"{task['id']}/{policy}/{obs['t']}"
            counts: Counter[str] = Counter()
            row: Record = {"id": gid, "status": "ok"}
            try:
                g = make_graph(task, policy, obs, counts)
                gold = next(n["answer"] for n in g["nodes"] if n["id"] == "B")
                act = gold if policy == "mpc_scenarios" else base_stock(obs, 0.0)[0]
                env.step(act)
                append(directory / f"{task['split']}.jsonl", g)
            except (SolveFailure, PlannerMismatch) as exc:
                failures += 1
                row.update(status=type(exc).__name__, detail=str(exc), observation=obs,
                           unvisited_offsets=list(range(obs["t"] + 1, task["public"]["periods"] - 1)))
                if isinstance(exc, AuditFailure) and exc.diagnostics is not None:
                    row["diagnostics"] = exc.diagnostics
                if pilot or isinstance(exc, (PlannerMismatch, AuditFailure)) or failures / (attempted + 1) > RATE_LIMIT:
                    stop = f"{gid}: {exc}"
            row.update(seconds=time.perf_counter() - t0, **solve_counts(counts))
            append(directory / "attempts.jsonl", row)
            attempted += 1
            if row["status"] != "ok" or attempted % 11 == 0:
                print(compact({"attempted": attempted, "failures": failures, "id": gid,
                               "elapsed_seconds": time.perf_counter() - start}), flush=True)
            if row["status"] != "ok":
                break
        if stop:
            break
    summary = stats(directory)
    status = "complete"
    if stop:
        status = "failed"
    elif pilot and summary["estimated_formal_seconds"] > 3600:
        status = "over_budget"
        stop = "estimated formal wall time exceeds 3600 seconds"
    summary.update(phase="pilot" if pilot else "formal", status=status, stop_reason=stop,
                   extended_planner_presolve=PRESOLVE, reference_planner_presolve=True,
                   wall_seconds=time.perf_counter() - start)
    write(directory / "summary.json", summary)
    write(directory / "manifest.json", {"algorithm": "SHA256", "files": {
        name: digest(directory / name) for name in sorted(PUBLIC_FILES)}})
    return summary

