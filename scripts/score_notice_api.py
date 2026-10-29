"""Verify an API-run ledger and write a sanitized, numeric-only assessment.

This command never calls a model, reads a credential, or copies provider text to
the GitHub step summary. Missing credentials/runs do not become zero accuracy.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from notice_benchmark import api_runner as runner
from notice_benchmark.data import validate_dataset
from notice_benchmark.effects import compare_effect
from notice_benchmark.metrics import score_predictions


def _pairs(values):
    out = {}
    for key, value in values:
        if key in out:
            raise ValueError("duplicate_json_key")
        out[key] = value
    return out


def _read_json(path):
    return json.loads(path.read_text(), object_pairs_hook=_pairs)


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _empty(status="no_run_artifacts"):
    return {"schema_version": "notice-api-assessment-v1", "status": status,
        "transport": "unavailable", "live_api_evidence": False,
        "partial_run": True, "score_scope": "completed_outputs_only",
        "counts": {"requested_calls": None, "attempted_calls": 0,
            "completed_calls": 0, "api_errors": 0, "transport_errors": 0,
            "other_model_failures": 0, "unknown_outcome_attempts": 0,
            "unattempted_calls": None, "completed_cases": 0},
        "metrics": None}


def _markdown(report):
    counts = report["counts"]
    titles = {"completed_live_evaluation": "Completed API evaluation",
        "partial_live_evaluation": "Partial API evaluation",
        "completed_mock_evaluation": "Mock transport evaluation only",
        "partial_mock_evaluation": "Partial mock transport evaluation only",
        "no_completed_outputs": "No live inference results",
        "no_run_artifacts": "No live inference results",
        "integrity_failure": "Integrity verification failed; no scores reported"}
    lines = ["## Notice API assessment", "", titles[report["status"]], "",
        "| Count | Value |", "|---|---:|"]
    for key in ["requested_calls", "attempted_calls", "completed_calls", "api_errors",
                "transport_errors", "other_model_failures", "unknown_outcome_attempts",
                "unattempted_calls", "completed_cases"]:
        value = counts[key]
        lines.append(f"| {key} | {'unavailable' if value is None else int(value)} |")
    lines += ["", "Accuracy is conditional on completed outputs. Errors and unattempted requests remain separate."]
    if report["transport"] == "injected_test_transport":
        lines += ["", "Mocked outputs are not evidence of real model performance."]
    if report["metrics"] is None:
        lines += ["", "Accuracy: unavailable. No completed outputs were scored."]
    else:
        lines += ["", "| Metric | Value |", "|---|---:|"]
        for key, value in report["metrics"].items():
            lines.append(f"| {key} | {'unavailable' if value is None else format(float(value), '.6f')} |")
    return "\n".join(lines) + "\n"


def _write(report, run_dir, github_summary=None):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evaluation.json").write_bytes(runner.canonical_bytes(report) + b"\n")
    markdown = _markdown(report)
    (run_dir / "evaluation.md").write_text(markdown)
    if github_summary:
        with Path(github_summary).open("a", encoding="utf-8") as stream:
            stream.write(markdown)
    return report


def score_run(dataset_path, run_dir, github_summary=None):
    """Verify declared requests and ledger; score only completed model outputs."""
    run_dir = Path(run_dir)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        _require(not (run_dir / "records.jsonl").exists()
            and not (run_dir / "ledger-anchor.json").exists(), "orphaned_run_ledger")
        return _write(_empty(), run_dir, github_summary)
    _require(not manifest_path.is_symlink(), "symlink_manifest")
    manifest = _read_json(manifest_path)
    core = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    _require(manifest.get("manifest_sha256") == runner.sha256(runner.canonical_bytes(core)), "manifest_hash_mismatch")
    _require(manifest.get("schema_version") == "notice-api-run-v1", "unsupported_manifest")
    raw = Path(dataset_path).read_bytes()
    dataset = json.loads(raw, object_pairs_hook=_pairs)
    validate_dataset(dataset)
    identity = manifest["identity"]
    config = identity["configuration"]
    _require(identity["dataset_sha256"] == runner.sha256(raw), "dataset_hash_mismatch")
    _require(identity["configuration_sha256"] == runner.sha256(runner.canonical_bytes(config)), "configuration_hash_mismatch")
    _require(identity["prompt_sha256"] == runner.sha256(runner.PROMPT.encode()), "prompt_hash_mismatch")
    _require(identity["schema_sha256"] == runner.sha256(runner.canonical_bytes(runner.SCHEMA)), "schema_hash_mismatch")
    _require(identity["runner_sha256"] == runner.sha256(Path(runner.__file__).read_bytes()), "runner_hash_mismatch")
    _require(identity["split"] in {"development", "test"}, "unknown_split")
    transport = config.get("transport_mode")
    _require(transport in {"openai_https", "injected_test_transport"}, "unknown_transport")
    _require(config.get("endpoint") == runner.ENDPOINT, "unknown_endpoint")
    input_rate = Decimal(config["input_usd_per_million"])
    output_rate = Decimal(config["output_usd_per_million"])
    _require(input_rate.is_finite() and output_rate.is_finite()
        and input_rate >= 0 and output_rate >= 0, "invalid_recorded_prices")
    rows = dataset["splits"][identity["split"]]
    repeats, limit = config["repeats"], config["max_calls"]
    _require(type(repeats) is int and 1 <= repeats <= 5 and type(limit) is int
        and 1 <= limit <= len(rows) * repeats, "invalid_request_count")
    requested, inputs, planned_cases = [], [], {}
    for case in rows:
        for repeat in range(repeats):
            if len(requested) == limit:
                break
            model_input = case["model_input"]
            input_hash = runner.sha256(runner.canonical_bytes(model_input))
            body = runner.build_request(model_input, config["model"], config["max_output_tokens"])
            body_bytes = runner.canonical_bytes(body)
            bound = len(body_bytes) + runner.INPUT_OVERHEAD_TOKENS
            price = ((bound * input_rate
                + config["max_output_tokens"] * output_rate)
                / 1_000_000).quantize(Decimal(".00000001"), rounding=ROUND_CEILING)
            cache = {key: identity[key] for key in ["dataset_sha256", "prompt_sha256", "schema_sha256", "configuration_sha256"]}
            cache.update(input_sha256=input_hash, repeat_index=repeat)
            item = {"case_id": case["id"], "request_key": runner.sha256(runner.canonical_bytes(cache)),
                "request_sha256": runner.sha256(body_bytes), "input_sha256": input_hash,
                "repeat_index": repeat, "input_token_upper_bound": bound,
                "reservation_usd": format(price, "f")}
            requested.append(item)
            inputs.append({"case_id": case["id"], "repeat_index": repeat, "model_input": model_input})
            planned_cases[item["request_key"]] = case
        if len(requested) == limit:
            break
    _require(requested == manifest["requests"], "request_identity_mismatch")
    input_bytes = b"".join(runner.canonical_bytes(row) + b"\n" for row in inputs)
    _require(runner.sha256(input_bytes) == identity["inputs_sha256"], "inputs_hash_mismatch")
    input_path = run_dir / "inputs.jsonl"
    _require(not input_path.is_symlink() and input_path.read_bytes() == input_bytes, "inputs_file_mismatch")
    records, _ = runner._read_log(run_dir / "records.jsonl")
    _require(records or not (run_dir / "ledger-anchor.json").exists(), "empty_truncated_ledger")
    plan = {row["request_key"]: row for row in requested}
    reservations, results = {}, {}
    expected_model = config.get("expected_returned_model") or (
        config["model"] if identity["model_pinning"] == "dated_snapshot_requested" else None)
    for record in records:
        key = record.get("request_key")
        _require(key in plan, "unknown_request")
        item = plan[key]
        if record.get("kind") == "reservation":
            _require(key not in reservations and all(record.get(field) == item[field]
                for field in ["request_sha256", "input_sha256", "repeat_index", "reservation_usd"]), "reservation_identity_mismatch")
            reservations[key] = record
        elif record.get("kind") == "result":
            _require(key in reservations and key not in results, "duplicate_or_unreserved_result")
            _require(all(record.get(field) == item[field] for field in ["case_id", "input_sha256", "repeat_index"]), "result_identity_mismatch")
            if "raw_response" in record:
                response = record["raw_response"]
                _require(isinstance(response, dict) and record.get("raw_response_sha256") == runner.sha256(runner.canonical_bytes(response)), "response_hash_mismatch")
                parsed = runner._response_result(response, planned_cases[key]["model_input"], expected_model,
                    input_rate, output_rate)
                _require(all(record.get(field) == value for field, value in parsed.items()), "response_parse_mismatch")
            else:
                _require(record.get("status") in {"api_error", "transport_error"}
                    and all(record.get(field) is None for field in ["parsed_output", "usage", "usage_cost_usd"]), "result_without_response")
            if record.get("usage_cost_usd") is not None:
                observed_cost = Decimal(record["usage_cost_usd"])
                _require(observed_cost.is_finite() and observed_cost >= 0
                    and observed_cost <= Decimal(item["reservation_usd"]), "usage_exceeded_reserved_bound")
            results[key] = record
        else:
            raise ValueError("unknown_record_kind")
    counts = Counter(record["status"] for record in results.values())
    completed = [(plan[key], record) for key, record in results.items() if record["status"] == "completed"]
    report = _empty("no_completed_outputs")
    report["transport"] = transport
    report["counts"] = {"requested_calls": len(plan), "attempted_calls": len(reservations),
        "completed_calls": len(completed), "api_errors": counts["api_error"],
        "transport_errors": counts["transport_error"],
        "other_model_failures": len(results) - len(completed) - counts["api_error"] - counts["transport_error"],
        "unknown_outcome_attempts": len(reservations) - len(results),
        "unattempted_calls": len(plan) - len(reservations),
        "completed_cases": len({item["case_id"] for item, _ in completed})}
    report["partial_run"] = len(completed) != len(plan)
    if completed:
        report["status"] = ("partial_" if report["partial_run"] else "completed_") + (
            "mock_evaluation" if transport == "injected_test_transport" else "live_evaluation")
        report["live_api_evidence"] = transport == "openai_https"
        completed_ids = {item["case_id"] for item, _ in completed}
        cases = [row for row in rows if row["id"] in completed_ids]
        predictions = [{"case_id": item["case_id"], "repeat_id": str(item["repeat_index"]),
            "output": record["parsed_output"]} for item, record in completed]
        scored = score_predictions(cases, predictions)["summary"]
        numeric = {"whole_notice_accuracy": scored["exact_match_rate"],
            "json_validity": scored["json_validity_rate"], "schema_validity": scored["schema_validity_rate"],
            "correct_ready_coverage": scored["correct_ready_coverage"],
            "ready_semantic_precision": scored["ready_semantic_precision"],
            "clarification_precision": scored["clarification_precision"],
            "clarification_recall": scored["clarification_recall"]}
        effects = [compare_effect(planned_cases[item["request_key"]]["reference"],
            record["parsed_output"], planned_cases[item["request_key"]]["model_input"]["context"])
            for item, record in completed]
        numeric["schedule_effect_accuracy"] = sum(bool(effect["effect_match"]) for effect in effects) / len(effects)
        report["metrics"] = numeric
    return _write(report, run_dir, github_summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "benchmarks/notices_v1/dataset.json")
    parser.add_argument("--run", type=Path, default=ROOT / "artifacts/notice_api")
    parser.add_argument("--github-summary", type=Path)
    args = parser.parse_args()
    try:
        result = score_run(args.dataset, args.run, args.github_summary)
    except (ValueError, KeyError, TypeError, OSError, ArithmeticError, runner.RunnerError):
        result = _write(_empty("integrity_failure"), args.run, args.github_summary)
        print(json.dumps({"status": result["status"], "accuracy": None}))
        return 2
    print(json.dumps({"status": result["status"], "counts": result["counts"], "metrics": result["metrics"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
