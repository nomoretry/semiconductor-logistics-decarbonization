"""Aggregate graph-level evidence and resample complete demand paths."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .ablation import ABLATIONS
from .planner import Record

BOOTSTRAP_SEED = 984301
BOOTSTRAP_REPLICATES = 10_000
STAGES = ("P1", "P2", "P3", "B", "M")
OUTCOME_METRICS = ("plan_excess", "relative_plan_excess", "cost_delta", "fill_rate_delta", "emissions_delta")
ABLATION_METRICS = ("changed", *OUTCOME_METRICS)


def _ratio(numerator: float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def bootstrap_clusters(rows: list[Record], metrics: tuple[str, ...]) -> Record:
    """Bootstrap graph-weighted means by whole paths within the given group."""
    paths: dict[tuple[str, str, int], list[Record]] = defaultdict(list)
    for row in rows:
        paths[row["split"], row["profile"], row["seed"]].append(row)
    clusters = [paths[key] for key in sorted(paths)]
    n_paths = len(clusters)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.integers(n_paths, size=(BOOTSTRAP_REPLICATES, n_paths)) if n_paths else None
    estimates: Record = {}
    for metric in metrics:
        observed = [[float(row[metric]) for row in cluster if row.get(metric) is not None]
                    for cluster in clusters]
        counts = np.array([len(values) for values in observed], dtype=int)
        sums = np.array([sum(values) for values in observed], dtype=float)
        n = int(counts.sum())
        lower = upper = None
        if n and draws is not None:
            sample_counts = counts[draws].sum(axis=1)
            sample_sums = sums[draws].sum(axis=1)
            valid = sample_counts > 0
            percentiles = np.percentile(sample_sums[valid] / sample_counts[valid], [2.5, 97.5], method="linear")
            lower, upper = (float(value) for value in percentiles)
        estimates[metric] = {"n": n, "mean": _ratio(float(sums.sum()), n), "lower": lower, "upper": upper}
    return {"graphs": len(rows), "paths": n_paths, "metrics": estimates}


def _summarize_ablation_group(rows: list[Record]) -> Record:
    output: Record = {}
    for item in ABLATIONS:
        evidence = [dict(row["ablations"].get(item, {}), split=row["split"], profile=row["profile"],
                         seed=row["seed"]) for row in rows]
        violations = [row["violation"] for row in evidence if row.get("violation") is not None]
        summary = bootstrap_clusters(evidence, ABLATION_METRICS)
        summary.update(violation_n=len(violations), violations=sum(violations),
                       violation_rate=_ratio(sum(violations), len(violations)))
        output[item] = summary
    return output


def summarize_ablations(rows: list[Record]) -> Record:
    """Summarize splits and their demand-profile by history-policy subgroups."""
    by_split: dict[str, list[Record]] = defaultdict(list)
    by_group: dict[tuple[str, str, str], list[Record]] = defaultdict(list)
    for row in rows:
        by_split[row["split"]].append(row)
        by_group[row["split"], row["profile"], row["policy"]].append(row)
    summary: Record = {split: {"all": _summarize_ablation_group(group), "by_profile_policy": {}}
                       for split, group in sorted(by_split.items())}
    for (split, profile, policy), group in sorted(by_group.items()):
        by_profile = summary[split]["by_profile_policy"].setdefault(profile, {})
        by_profile[policy] = _summarize_ablation_group(group)
    return summary


def _summarize_baseline_group(records: list[tuple[Record, float]]) -> Record:
    stages = {stage: {"expected": 0, "provided": 0, "correct": 0, "violations": 0} for stage in STAGES}
    values: dict[str, list[float]] = {metric: [] for metric in OUTCOME_METRICS}
    scored_graphs = action_count = violation_n = violations = 0
    for entry, objective in records:
        nodes = entry["nodes"]
        dispatch = None
        if nodes is not None:
            scored_graphs += 1
            for node in nodes:
                stage = stages[node["stage"]]
                stage["expected"] += 1
                stage["provided"] += int(node["provided"])
                stage["correct"] += int(node["correct"])
                stage["violations"] += int(node["violation"])
                if node["id"] == "B":
                    dispatch = node
        consequence = entry["consequence"]
        if dispatch is not None and dispatch["provided"]:
            action_count += 1
            violation_n += 1
            violations += int(dispatch["violation"])
            if dispatch["excess"] is not None:
                excess = float(dispatch["excess"])
                values["plan_excess"].append(excess)
                if objective:
                    values["relative_plan_excess"].append(excess / objective)
        elif dispatch is None and (entry["action"] is not None or consequence is not None):
            action_count += 1
            if consequence is not None and consequence["status"] in ("ok", "violation"):
                violation_n += 1
                violations += int(consequence["status"] == "violation")
        if consequence is not None and consequence["delta"] is not None:
            delta = consequence["delta"]
            values["cost_delta"].append(float(delta["cost"]))
            values["fill_rate_delta"].append(float(delta["fill_rate"]))
            values["emissions_delta"].append(float(delta["emissions"]))
    summaries = {name: dict(stage, accuracy=_ratio(stage["correct"], stage["expected"]))
                 for name, stage in stages.items()}
    violation_denominator = sum(stages[stage]["provided"] for stage in ("P3", "B", "M"))
    total_violations = sum(stage["violations"] for stage in stages.values())
    return {"graphs": len(records), "scored_graphs": scored_graphs, "stages": summaries,
            "violations": total_violations, "violation_denominator": violation_denominator,
            "violation_rate": _ratio(total_violations, violation_denominator),
            "B": {"provided": action_count, "violation_n": violation_n, "violations": violations,
                  "violation_rate": _ratio(violations, violation_n),
                  "metrics": {metric: {"n": len(items), "mean": _ratio(sum(items), len(items))}
                              for metric, items in values.items()}}}


def summarize_baselines(rows: list[Record]) -> Record:
    """Summarize each answerer, context mode and upstream answer source."""
    groups: dict[tuple[str, str, str], list[tuple[Record, float]]] = defaultdict(list)
    for row in rows:
        for answerer, modes in row["baselines"].items():
            for mode, sources in modes.items():
                for source, result in sources.items():
                    groups[answerer, mode, source].append((result, float(row["objective"])))
    output: Record = {}
    for (answerer, mode, source), records in sorted(groups.items()):
        output.setdefault(answerer, {}).setdefault(mode, {})[source] = _summarize_baseline_group(records)
    return output
