"""Strict, independent scoring for notice extraction experiments.

The scorer never imports the generator or an extractor.  It compares a model or
rule output with separately supplied references.  Calls are nested within cases
and cases within events: repeat calls do not increase the independent sample
count, and paired confidence intervals resample complete event clusters.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
import hashlib
import json
import math
import random
from statistics import NormalDist
from typing import Any


SCHEMA_VERSION = "notice-extraction-metrics-v1"
CHANGE_FIELDS = ("op", "route", "start_week", "end_week", "value")


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("non_finite_json_number")


def _decode_output(output: Any) -> tuple[Any, bool, str | None]:
    if isinstance(output, str):
        try:
            return json.loads(
                output, object_pairs_hook=_strict_pairs, parse_constant=_reject_constant
            ), True, None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None, False, "invalid_json"
    if isinstance(output, Mapping):
        try:
            # Reject non-JSON objects, NaN and Infinity even for in-memory inputs.
            json.dumps(output, allow_nan=False)
        except (TypeError, ValueError):
            return None, False, "invalid_json"
        return dict(output), True, None
    return None, False, "missing_output" if output is None else "invalid_json"


def normalize_output(output: Any) -> dict[str, Any]:
    """Return schema-validated output, with only change-list order normalized.

    Numeric ``2`` and ``2.0`` are semantically equal; bools are never numbers.
    Extra keys, unsupported operations, duplicate changes and schema violations
    are rejected rather than discarded.  The scope is announced lead additions.
    """
    value, json_valid, _ = _decode_output(output)
    if not json_valid:
        raise ValueError("invalid_json")
    if not isinstance(value, dict) or set(value) != {"status", "changes"}:
        raise ValueError("invalid_top_level_schema")
    if value["status"] not in ("ready", "needs_clarification"):
        raise ValueError("invalid_status")
    changes = value["changes"]
    if not isinstance(changes, list):
        raise ValueError("changes_must_be_list")
    if value["status"] == "needs_clarification" and changes:
        raise ValueError("clarification_must_not_apply_changes")
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != set(CHANGE_FIELDS):
            raise ValueError("invalid_change_schema")
        if change["op"] != "add_lead":
            raise ValueError("unsupported_operation")
        if not isinstance(change["route"], str) or not change["route"].strip():
            raise ValueError("invalid_route")
        start, end = change["start_week"], change["end_week"]
        if type(start) is not int or type(end) is not int or start < 1 or end < start:
            raise ValueError("invalid_week_window")
        amount = change["value"]
        if type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0:
            raise ValueError("invalid_lead_addition")
        key = (change["op"], change["route"], start, end, amount)
        if key in seen:
            raise ValueError("duplicate_change")
        seen.add(key)
        normalized.append({field: change[field] for field in CHANGE_FIELDS})
    normalized.sort(key=lambda change: tuple(change[field] for field in CHANGE_FIELDS))
    return {"status": value["status"], "changes": normalized}


def wilson_interval(
    successes: int, total: int, confidence: float = 0.95
) -> tuple[float, float] | None:
    """Wilson score interval for independent Bernoulli units; None for no units."""
    if type(successes) is not int or type(total) is not int:
        raise ValueError("Counts must be integers, not booleans")
    if total < 0 or successes < 0 or successes > total:
        raise ValueError("Require 0 <= successes <= total")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    if not total:
        return None
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    probability = successes / total
    denominator = 1 + z * z / total
    center = (probability + z * z / (2 * total)) / denominator
    half = z * math.sqrt(
        probability * (1 - probability) / total + z * z / (4 * total * total)
    ) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return numerator / denominator if denominator else None


def public_case_metadata(case: Mapping[str, Any]) -> dict[str, Any]:
    """Export only an allowlist, never raw text, context, credentials or URLs."""
    case_id = case.get("case_id", case.get("id"))
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("Each case requires a nonempty id or case_id")
    event_id = case.get("event_id", case_id)
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("event_id must be a nonempty string")
    result = {"case_id": case_id, "event_id": event_id}
    for key in ("template_family_id", "category", "source_id"):
        value = case.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string")
            result[key] = value
    if "synthetic" in case:
        if type(case["synthetic"]) is not bool:
            raise ValueError("synthetic must be a boolean")
        result["synthetic"] = case["synthetic"]
    return result


def _fingerprint(case: Mapping[str, Any], reference: dict[str, Any]) -> str:
    evidence = {
        "model_input": case.get("model_input"),
        "event_id": case.get("event_id", case.get("case_id", case.get("id"))),
        "reference": reference,
    }
    encoded = json.dumps(
        evidence, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _prediction_rows(predictions: Any) -> list[dict[str, Any]]:
    if isinstance(predictions, Mapping):
        return [
            {"case_id": key, "repeat_id": "0", "output": value}
            for key, value in predictions.items()
        ]
    if isinstance(predictions, Sequence) and not isinstance(predictions, (str, bytes)):
        rows = []
        for row in predictions:
            if not isinstance(row, Mapping):
                raise ValueError("Prediction rows must be mappings")
            if "case_id" not in row or "output" not in row:
                raise ValueError("Prediction rows require case_id and output")
            repeat = row.get("repeat_id", "0")
            if type(repeat) not in (str, int) or isinstance(repeat, bool):
                raise ValueError("repeat_id must be a string or integer")
            rows.append({
                "case_id": row["case_id"], "repeat_id": str(repeat),
                "output": row["output"],
            })
        return rows
    raise ValueError("Predictions must be an id mapping or a sequence of call rows")


def _field_results(
    reference: dict[str, Any], predicted: dict[str, Any] | None
) -> dict[str, bool]:
    fields = {
        "status": predicted is not None and predicted["status"] == reference["status"],
        "changes": predicted is not None and predicted["changes"] == reference["changes"],
        "change_count": predicted is not None
        and len(predicted["changes"]) == len(reference["changes"]),
    }
    if reference["changes"]:
        for field in CHANGE_FIELDS:
            fields[field] = predicted is not None and (
                [change[field] for change in predicted["changes"]]
                == [change[field] for change in reference["changes"]]
            )
    return fields


def score_predictions(
    cases: Sequence[Mapping[str, Any]], predictions: Any
) -> dict[str, Any]:
    """Score call outputs; return per-case evidence and explicitly nested counts.

    Cases use ``id``/``case_id``, ``event_id``, and ``reference`` (``expected`` or
    ``label`` are accepted aliases). Predictions may map id to one output, or be
    rows ``{case_id, repeat_id, output}``. Missing cases are failures, unknown ids
    and duplicate case/repeat pairs are errors. No successful-only filtering.
    """
    catalog: dict[str, tuple[Mapping[str, Any], dict[str, Any]]] = {}
    for case in cases:
        metadata = public_case_metadata(case)
        case_id = metadata["case_id"]
        if case_id in catalog:
            raise ValueError(f"Duplicate case id: {case_id}")
        reference = case.get("reference", case.get("expected", case.get("label")))
        try:
            normalized = normalize_output(reference)
        except ValueError as error:
            raise ValueError(f"Invalid reference for {case_id}: {error}") from error
        catalog[case_id] = (case, normalized)
    if not catalog:
        raise ValueError("At least one case is required")
    supplied = _prediction_rows(predictions)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    identities: set[tuple[str, str]] = set()
    for row in supplied:
        case_id = row["case_id"]
        if not isinstance(case_id, str) or case_id not in catalog:
            raise ValueError(f"Unknown prediction case id: {case_id}")
        identity = (case_id, row["repeat_id"])
        if identity in identities:
            raise ValueError(f"Duplicate prediction case/repeat: {identity}")
        identities.add(identity)
        grouped[case_id].append(row)
    missing_cases = sum(case_id not in grouped for case_id in catalog)
    for case_id in catalog:
        if case_id not in grouped:
            grouped[case_id] = [{"case_id": case_id, "repeat_id": "0", "output": None}]

    outcomes = []
    field_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    counts = defaultdict(int)
    for case_id in sorted(catalog):
        case, reference = catalog[case_id]
        metadata = public_case_metadata(case)
        calls = []
        canonical_values = []
        for row in sorted(grouped[case_id], key=lambda value: value["repeat_id"]):
            raw, json_valid, decode_error = _decode_output(row["output"])
            predicted = None
            error_code = decode_error
            if json_valid:
                try:
                    predicted = normalize_output(raw)
                except ValueError as error:
                    error_code = str(error)
            schema_valid = predicted is not None
            raw_status = raw.get("status") if isinstance(raw, dict) else None
            predicted_status = raw_status if raw_status in ("ready", "needs_clarification") else None
            exact = schema_valid and predicted == reference
            fields = _field_results(reference, predicted)
            for field, correct in fields.items():
                field_totals[field][0] += int(correct)
                field_totals[field][1] += 1
            gold_ready = reference["status"] == "ready"
            gold_clarify = not gold_ready
            pred_ready = predicted_status == "ready"
            pred_clarify = predicted_status == "needs_clarification"
            counts["calls"] += 1
            counts["exact"] += int(exact)
            counts["json_valid"] += int(json_valid)
            counts["schema_valid"] += int(schema_valid)
            counts["gold_ready"] += int(gold_ready)
            counts["gold_clarify"] += int(gold_clarify)
            counts["pred_ready"] += int(pred_ready)
            counts["pred_clarify"] += int(pred_clarify)
            counts["ready_true_positive"] += int(gold_ready and pred_ready)
            counts["clarify_true_positive"] += int(gold_clarify and pred_clarify)
            counts["correct_ready"] += int(gold_ready and exact)
            counts["unsupported_ready"] += int(gold_clarify and pred_ready)
            canonical_values.append(predicted)
            calls.append({
                "repeat_id": row["repeat_id"], "json_valid": json_valid,
                "schema_valid": schema_valid, "exact_match": bool(exact),
                "predicted_status": predicted_status,
                "reference_status": reference["status"],
                "field_exact": fields, "error_code": error_code,
            })
        successes = sum(call["exact_match"] for call in calls)
        consistent = all(value is not None for value in canonical_values) and all(
            value == canonical_values[0] for value in canonical_values
        )
        outcomes.append({
            **metadata, "case_sha256": _fingerprint(case, reference),
            "repeat_count": len(calls), "exact_matches": successes,
            "exact_match_rate": successes / len(calls),
            "all_repeats_correct": successes == len(calls),
            "consistent_valid_outputs": bool(consistent), "calls": calls,
        })

    events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for outcome in outcomes:
        events[outcome["event_id"]].append(outcome)
    event_successes = sum(
        all(case["all_repeats_correct"] for case in event_cases)
        for event_cases in events.values()
    )
    repeated = [case for case in outcomes if case["repeat_count"] > 1]
    consistent_repeated = sum(case["consistent_valid_outputs"] for case in repeated)
    summary = {
        "exact_matches": counts["exact"],
        "exact_match_rate": _ratio(counts["exact"], counts["calls"]),
        "mean_case_exact_match_rate": sum(case["exact_match_rate"] for case in outcomes) / len(outcomes),
        "json_validity_rate": _ratio(counts["json_valid"], counts["calls"]),
        "schema_validity_rate": _ratio(counts["schema_valid"], counts["calls"]),
        "ready_precision": _ratio(counts["ready_true_positive"], counts["pred_ready"]),
        "ready_recall": _ratio(counts["ready_true_positive"], counts["gold_ready"]),
        "clarification_precision": _ratio(counts["clarify_true_positive"], counts["pred_clarify"]),
        "clarification_recall": _ratio(counts["clarify_true_positive"], counts["gold_clarify"]),
        "ready_coverage": _ratio(counts["ready_true_positive"], counts["gold_ready"]),
        "correct_ready_coverage": _ratio(counts["correct_ready"], counts["gold_ready"]),
        "ready_semantic_precision": _ratio(counts["correct_ready"], counts["pred_ready"]),
        "unsupported_ready_on_missing_information_rate": _ratio(counts["unsupported_ready"], counts["gold_clarify"]),
        "field_accuracy": {
            key: {"correct": correct, "total": total, "rate": _ratio(correct, total)}
            for key, (correct, total) in sorted(field_totals.items())
        },
        "event_all_correct": {
            "successes": event_successes, "total": len(events),
            "rate": event_successes / len(events),
            "wilson95": wilson_interval(event_successes, len(events)),
            "definition": "Every case and every repeat in the event is exactly correct",
        },
        "repeat_consistency": {
            "repeated_cases": len(repeated),
            "consistent_valid_cases": consistent_repeated,
            "rate": _ratio(consistent_repeated, len(repeated)),
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "counts": {
            "number_cases": len(outcomes), "number_events": len(events),
            "number_calls": counts["calls"], "provided_calls": len(supplied),
            "missing_cases": missing_cases,
            "repeats_by_case": {case["case_id"]: case["repeat_count"] for case in outcomes},
            "gold_ready_calls": counts["gold_ready"],
            "gold_clarification_calls": counts["gold_clarify"],
        },
        "interval_scope": "Wilson is for event-all-correct Bernoulli outcomes; calls/repeats are not independent units",
        "summary": summary, "per_case": outcomes,
    }


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _paired_catalog(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if report.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported report schema")
    catalog = {}
    for case in report["per_case"]:
        case_id = case["case_id"]
        if case_id in catalog:
            raise ValueError("Duplicate report case id")
        repeat_ids = [call["repeat_id"] for call in case["calls"]]
        if len(repeat_ids) != len(set(repeat_ids)) or not repeat_ids:
            raise ValueError("Duplicate or absent report repeat ids")
        if any(type(call["exact_match"]) is not bool for call in case["calls"]):
            raise ValueError("Report outcomes must be booleans")
        catalog[case_id] = case
    if not catalog:
        raise ValueError("At least one paired case is required")
    return catalog


def paired_cluster_bootstrap(
    left_report: Mapping[str, Any], right_report: Mapping[str, Any], *,
    seed: int = 20261030, samples: int = 2000, confidence: float = 0.95,
) -> dict[str, Any]:
    """Percentile CI for left-minus-right mean case accuracy, by event cluster.

    Pairing requires identical cases, event identities, case fingerprints and
    repeat identities. Every call, including errors and abstentions, is kept.
    The same sampled event clusters are used for both systems.
    """
    if type(samples) is not int or samples < 1:
        raise ValueError("samples must be a positive integer")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    left, right = _paired_catalog(left_report), _paired_catalog(right_report)
    if set(left) != set(right):
        raise ValueError("Paired reports must have the identical case set")
    clusters: dict[str, list[float]] = defaultdict(list)
    total_calls = 0
    for case_id in sorted(left):
        a, b = left[case_id], right[case_id]
        if a["event_id"] != b["event_id"] or a["case_sha256"] != b["case_sha256"]:
            raise ValueError("Paired reports must describe identical event/input/reference identities")
        a_calls = {call["repeat_id"]: call for call in a["calls"]}
        b_calls = {call["repeat_id"]: call for call in b["calls"]}
        if set(a_calls) != set(b_calls):
            raise ValueError("Paired reports must have the identical repeat set for every case")
        delta = sum(
            int(a_calls[repeat]["exact_match"]) - int(b_calls[repeat]["exact_match"])
            for repeat in a_calls
        ) / len(a_calls)
        clusters[a["event_id"]].append(delta)
        total_calls += len(a_calls)
    cluster_values = [clusters[event] for event in sorted(clusters)]
    observed = sum(sum(values) for values in cluster_values) / len(left)
    generator = random.Random(seed)
    bootstrap = []
    for _ in range(samples):
        chosen = [cluster_values[generator.randrange(len(cluster_values))] for _ in cluster_values]
        bootstrap.append(sum(sum(values) for values in chosen) / sum(len(values) for values in chosen))
    alpha = (1 - confidence) / 2
    interval = [_quantile(bootstrap, alpha), _quantile(bootstrap, 1 - alpha)]
    return {
        "schema_version": "notice-paired-cluster-bootstrap-v1",
        "estimand": "left_minus_right_mean_case_exact_match_rate",
        "difference": observed, "confidence": confidence, "interval": interval,
        "number_cases": len(left), "number_event_clusters": len(clusters),
        "paired_calls": total_calls, "bootstrap_samples": samples, "seed": seed,
        "resampling_unit": "whole event, retaining all its cases and repeated calls",
        "interval_lower_positive": interval[0] > 0,
    }
