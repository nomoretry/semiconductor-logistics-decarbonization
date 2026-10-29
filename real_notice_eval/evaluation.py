"""Reference agreement for the narrow original task, with trivial baselines."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from notice_benchmark.rules import extract_notice

from .data import (ANNOTATION_STATUS, CLASSES, EVALUATION_SCOPE, canonical_bytes,
                   corpus_summary, digest, normalized_output, output_class,
                   require, strict_json, validate_dataset)


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score_predictions(cases: list[dict[str, Any]], predictions: Any) -> dict[str, Any]:
    """Score every supplied call; absent cases fail and never disappear.

    This reports agreement with assistant reference decisions, not accuracy
    against independently human-annotated ground truth. Calls remain nested
    within cases and recorded event/correlation groups.
    """
    require(bool(cases), "cases_required_for_scoring")
    catalog = {case["id"]: case for case in cases}
    require(len(catalog) == len(cases), "duplicate_scoring_case")
    if isinstance(predictions, dict):
        rows = [{"case_id": key, "repeat_id": "0", "output": value}
                for key, value in predictions.items()]
    else:
        require(isinstance(predictions, list), "prediction_rows_required")
        rows = predictions
    supplied = len(rows)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        require(isinstance(row, dict) and set(row) == {"case_id", "repeat_id", "output"},
                "invalid_prediction_row")
        case_id, repeat = row["case_id"], row["repeat_id"]
        require(isinstance(case_id, str) and case_id in catalog, "unknown_prediction_case")
        require(isinstance(repeat, str) and bool(repeat), "invalid_prediction_repeat")
        require((case_id, repeat) not in seen, "duplicate_prediction_case_repeat")
        seen.add((case_id, repeat))
        grouped[case_id].append(row)
    missing = sum(case_id not in grouped for case_id in catalog)
    for case_id in catalog:
        if case_id not in grouped:
            grouped[case_id] = [{"case_id": case_id, "repeat_id": "0", "output": None}]
    counts: Counter[str] = Counter()
    class_totals: Counter[str] = Counter()
    class_correct: Counter[str] = Counter()
    predicted_classes: Counter[str] = Counter()
    confusion = {key: {other: 0 for other in (*CLASSES, "invalid_or_missing")}
                 for key in CLASSES}
    per_case = []
    for case_id, case in catalog.items():
        reference = normalized_output(case["reference"], case["model_input"])
        reference_class = output_class(reference)
        calls = []
        for row in sorted(grouped[case_id], key=lambda item: item["repeat_id"]):
            raw = row["output"]
            normalized = None
            error_code = None
            try:
                if isinstance(raw, str):
                    raw = strict_json(raw)
                normalized = normalized_output(raw, case["model_input"])
            except (ValueError, TypeError, KeyError):
                error_code = "invalid_or_missing_output"
            exact = normalized == reference
            predicted_class = output_class(normalized) if normalized is not None else "invalid_or_missing"
            unsupported_ready = (reference_class == "needs_clarification"
                                 and isinstance(raw, dict) and raw.get("status") == "ready")
            counts["calls"] += 1
            counts["schema_valid"] += normalized is not None
            counts["exact"] += exact
            counts["unsupported_ready"] += unsupported_ready
            class_totals[reference_class] += 1
            class_correct[reference_class] += exact
            predicted_classes[predicted_class] += 1
            confusion[reference_class][predicted_class] += 1
            calls.append({"repeat_id": row["repeat_id"], "schema_valid": normalized is not None,
                          "reference_class": reference_class, "predicted_class": predicted_class,
                          "exact_reference_match": exact, "unsupported_ready": unsupported_ready,
                          "error_code": error_code, "output": normalized})
        per_case.append({"case_id": case_id, "source_id": case["source_id"],
                         "event_group_id": case["event_group_id"],
                         "correlation_group_id": case["correlation_group_id"],
                         "reference_class": reference_class,
                         "all_calls_match_reference": all(call["exact_reference_match"] for call in calls),
                         "calls": calls})
    group_results = {}
    for key in ("event_group_id", "correlation_group_id"):
        groups: dict[str, list[bool]] = defaultdict(list)
        for case in per_case:
            groups[case[key]].append(case["all_calls_match_reference"])
        successes = sum(all(values) for values in groups.values())
        group_results[key] = {"all_cases_match_reference": successes, "total": len(groups),
                              "rate": _rate(successes, len(groups))}
    return {
        "score_scope": "assistant_reference_agreement_all_planned_outputs",
        "number_cases": len(cases), "number_calls": counts["calls"],
        "provided_calls": supplied, "missing_cases": missing,
        "exact_reference_matches": counts["exact"],
        "exact_reference_match_rate": _rate(counts["exact"], counts["calls"]),
        "schema_validity_rate": _rate(counts["schema_valid"], counts["calls"]),
        "unsupported_ready_calls": counts["unsupported_ready"],
        "unsupported_ready_rate_on_clarification_references": _rate(
            counts["unsupported_ready"], class_totals["needs_clarification"]),
        "class_results": {key: {"reference_calls": class_totals[key],
                                "predicted_calls": predicted_classes[key],
                                "exact_reference_matches": class_correct[key],
                                "exact_reference_match_rate": _rate(class_correct[key], class_totals[key])}
                          for key in CLASSES},
        "confusion_matrix": confusion, "recorded_group_results": group_results,
        "per_case": per_case,
    }


def evaluate_offline(dataset: dict[str, Any], split: str = "test") -> dict[str, Any]:
    validate_dataset(dataset)
    require(split in dataset["splits"] and bool(dataset["splits"][split]), "nonempty_split_required")
    cases = dataset["splits"][split]
    methods = {
        "rules_frozen_v1": {case["id"]: extract_notice(**case["model_input"]) for case in cases},
        "always_clarify": {case["id"]: {"status": "needs_clarification", "changes": []} for case in cases},
        "always_noop": {case["id"]: {"status": "ready", "changes": []} for case in cases},
    }
    scores = {name: score_predictions(cases, outputs) for name, outputs in methods.items()}
    balance = corpus_summary(dataset, split)
    return {
        "schema_version": "real-notice-offline-report-v1", "synthetic": False,
        "annotation_status": ANNOTATION_STATUS, "evaluation_scope": EVALUATION_SCOPE,
        "dataset_sha256": digest(canonical_bytes(dataset)), "split": split,
        "api_calls": 0, "live_api_evidence": False, "human_annotated_ground_truth": False,
        "corpus": balance,
        "always_clarify_reference_match_rate": scores["always_clarify"]["exact_reference_match_rate"],
        "methods": scores,
        "limitations": [
            "References were reviewed by an assistant and remain pending independent human review.",
            "Cases are short verbatim excerpts; full source pages were inspected but are not archived here.",
            "Recorded hashes verify excerpt integrity, not source authenticity or independent annotation.",
            "This exploratory corpus is not a held-out sample; source selection was not random.",
            "Absent reference classes have null rates; no update-extraction skill is established without ready_update cases.",
            "Source dates and route names do not supply an undeclared mapping to the original 16-week NL_ocean model.",
        ],
    }
