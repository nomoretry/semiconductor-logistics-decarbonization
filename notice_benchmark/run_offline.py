"""Freeze and evaluate offline notice baselines; no API calls or LLM results."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random

from .data import canonical_bytes, validate_dataset
from .effects import compare_effect
from .metrics import score_predictions
from .rules import extract_notice

ROOT = Path(__file__).resolve().parents[1]


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def freeze_rules(dataset_path: Path, freeze_path: Path) -> dict:
    """Create once, refusing to silently replace a previous frozen identity."""
    dataset = json.loads(dataset_path.read_text())
    validate_dataset(dataset)
    identity = {
        "schema_version": "notice-rules-freeze-v1",
        "dataset_sha256": dataset["manifest"]["dataset_sha256"],
        "rules_sha256": file_hash(ROOT / "notice_benchmark/rules.py"),
        "scope": "ASML-inspired NL_ocean announced delays; known committed orders",
        "development_only_rule_tuning": True,
        "test_used_for_rule_tuning": False,
        "primary_metric": "strict whole-notice exact match",
        "secondary_metric": "compiled weekly lead schedule equivalence",
    }
    if freeze_path.exists():
        if json.loads(freeze_path.read_text()) != identity:
            raise ValueError("Frozen identity differs; do not overwrite or reuse the holdout")
    else:
        write_json(freeze_path, identity)
    return identity


def family_interval(cases: list[dict], predictions: dict, seed: int = 20261030) -> dict:
    """Report template-cluster uncertainty separately from nominal event counts."""
    scores = score_predictions(cases, predictions)
    groups = defaultdict(list)
    for row in scores["per_case"]:
        groups[row["template_family_id"]].append(row["exact_match_rate"])
    rates = [sum(values) / len(values) for _, values in sorted(groups.items())]
    rng = random.Random(seed)
    draws = sorted(
        sum(rng.choice(rates) for _ in rates) / len(rates) for _ in range(2000)
    )
    return {
        "cluster": "template_family_id", "clusters": len(rates),
        "macro_accuracy": sum(rates) / len(rates),
        "bootstrap_95_percentile": [draws[49], draws[1949]],
        "bootstrap_samples": 2000, "bootstrap_seed": seed,
        "limitation": "Synthetic render families are not a random sample of real notices; this interval cannot establish real-world generalization.",
    }


def evaluate(dataset_path: Path, freeze_path: Path, output: Path) -> dict:
    dataset = json.loads(dataset_path.read_text())
    validate_dataset(dataset)
    if not freeze_path.is_file():
        raise ValueError("Freeze rules before evaluating the holdout")
    frozen = json.loads(freeze_path.read_text())
    if frozen["rules_sha256"] != file_hash(ROOT / "notice_benchmark/rules.py"):
        raise ValueError("Rules changed after freeze; heldout results cannot be reused")
    if frozen["dataset_sha256"] != dataset["manifest"]["dataset_sha256"]:
        raise ValueError("Dataset differs from frozen identity")
    cases = dataset["splits"]["test"]
    # Only text and public context enter the rule extractor.
    rules = {case["id"]: extract_notice(**case["model_input"]) for case in cases}
    methods = {
        "rules_frozen_v1": rules,
        "always_clarify": {c["id"]: {"status": "needs_clarification", "changes": []} for c in cases},
        "ignore_notice": {c["id"]: {"status": "ready", "changes": []} for c in cases},
        "reference_upper_bound": {c["id"]: c["reference"] for c in cases},
    }
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "notice-offline-comparison-v1", "frozen_identity": frozen,
        "synthetic": True, "independent_real_notices": 0,
        "test_records": len(cases),
        "interpretation": "Reference is an annotation upper bound, never a deployable policy. Always-clarify and ignore-notice are diagnostic controls, not the strong baseline.",
        "llm": {"executed": False, "reason": "No API inference executed; usable credential unavailable"},
        "methods": {},
    }
    for name, predictions in methods.items():
        scored = score_predictions(cases, predictions)
        effect = [compare_effect(c["reference"], predictions[c["id"]], c["model_input"]["context"]) for c in cases]
        categories = {}
        for category in sorted({c["category"] for c in cases}):
            subset = [c for c in cases if c["category"] == category]
            sub_predictions = {c["id"]: predictions[c["id"]] for c in subset}
            sub_score = score_predictions(subset, sub_predictions)
            categories[category] = {"records": len(subset), "exact_match_rate": sub_score["summary"]["exact_match_rate"]}
        report["methods"][name] = {
            "counts": scored["counts"], "summary": scored["summary"],
            "schedule_effect_match_rate": sum(bool(e["effect_match"]) for e in effect) / len(effect),
            "template_grouped": family_interval(cases, predictions), "by_category": categories,
        }
        write_json(output / f"{name}.metrics.json", scored)
        with (output / f"{name}.predictions.jsonl").open("wb") as stream:
            for c in cases:
                stream.write(canonical_bytes({"case_id": c["id"], "repeat_id": "0", "output": predictions[c["id"]]}) + b"\n")
    write_json(output / "summary.json", report)
    artifacts = {
        p.name: file_hash(p) for p in sorted(output.iterdir()) if p.is_file() and p.name != "manifest.json"
    }
    write_json(output / "manifest.json", {"schema_version": "notice-offline-artifacts-v1", "file_sha256": artifacts,
        "source_sha256": {str(p.relative_to(ROOT)): file_hash(p) for p in sorted((ROOT / "notice_benchmark").glob("*.py"))},
        "dataset_sha256": frozen["dataset_sha256"], "rules_sha256": frozen["rules_sha256"], "api_calls": 0})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "benchmarks/notices_v1/dataset.json")
    parser.add_argument("--freeze", type=Path, default=ROOT / "benchmarks/notices_v1/rules_freeze.json")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmark_results/notices_v1")
    parser.add_argument("--freeze-rules", action="store_true", help="Create/check a rule identity before first holdout evaluation")
    args = parser.parse_args()
    if args.freeze_rules:
        freeze_rules(args.dataset, args.freeze)
    report = evaluate(args.dataset, args.freeze, args.output)
    print(json.dumps({"test_records": report["test_records"], "api_calls": 0,
        "exact_match_rates": {k: v["summary"]["exact_match_rate"] for k, v in report["methods"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
