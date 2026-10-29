"""Input-only adapter and read-only verification of frozen runner artifacts.

No function here resolves credentials or sends requests. The unmodified
notice_benchmark.api_runner remains the separately invoked execution boundary.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Any

from notice_benchmark import api_runner as runner

from .data import (ANNOTATION_STATUS, EVALUATION_SCOPE, canonical_bytes,
                   corpus_summary, digest, read_json, require, strict_json,
                   validate_dataset)
from .evaluation import score_predictions


def api_input_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    """Project reviewed source excerpts to the frozen runner's input contract."""
    validate_dataset(dataset)
    return {
        "schema_version": "real-notice-api-inputs-v1", "synthetic": False,
        "annotation_status": ANNOTATION_STATUS, "evaluation_scope": EVALUATION_SCOPE,
        "source_corpus_sha256": digest(canonical_bytes(dataset)),
        "source_provenance": "Recorded in the separately retained source corpus, not sent to the model.",
        "splits": {split: [{"id": case["id"], "model_input": case["model_input"]} for case in cases]
                   for split, cases in dataset["splits"].items()},
    }


def _provider_text(response: dict[str, Any]) -> str:
    texts = []
    outputs = response.get("output", [])
    if not isinstance(outputs, list):
        return ""
    for output in outputs:
        if not isinstance(output, dict) or output.get("type") != "message":
            continue
        content = output.get("content", [])
        if not isinstance(content, list):
            continue
        for item in content:
            if (isinstance(item, dict) and item.get("type") == "output_text"
                    and isinstance(item.get("text"), str)):
                texts.append(item["text"])
    return "".join(texts)


def score_api_run(dataset: dict[str, Any], input_dataset_path: str | Path,
                  run_dir: str | Path) -> dict[str, Any]:
    """Verify identities/ledger, then report completed and planned denominators.

    Verification reuses frozen runner hash/response helpers; it is not an
    independent implementation or external attestation of a live transaction.
    Injected test transports are always labeled as mock evidence.
    """
    validate_dataset(dataset)
    input_dataset_path, run_dir = Path(input_dataset_path), Path(run_dir)
    require(read_json(input_dataset_path) == api_input_dataset(dataset), "exported_input_corpus_mismatch")
    raw_inputs_dataset = input_dataset_path.read_bytes()
    base = {
        "schema_version": "real-notice-api-assessment-v1", "synthetic": False,
        "annotation_status": ANNOTATION_STATUS, "evaluation_scope": EVALUATION_SCOPE,
        "human_annotated_ground_truth": False, "held_out_evaluation": False,
        "live_api_evidence": False, "transport": "unavailable",
        "source_corpus_sha256": digest(canonical_bytes(dataset)),
        "input_dataset_sha256": digest(raw_inputs_dataset),
        "reference_agreement_completed_outputs": None,
        "reference_agreement_all_planned_outputs": None,
        "partial_run": True,
        "verification_note": "Read-only replay using frozen runner helpers; not independent transaction attestation.",
        "claim_limit": "Short-excerpt abstention audit against assistant references pending human review; no update skill or generalization claim.",
    }
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        require(not (run_dir / "records.jsonl").exists()
                and not (run_dir / "ledger-anchor.json").exists(), "orphaned_run_ledger")
        return {**base, "status": "no_run_artifacts", "counts": {
            "requested_calls": None, "attempted_calls": 0, "completed_calls": 0,
            "unknown_outcome_attempts": 0, "unattempted_calls": None,
            "api_errors": 0, "transport_errors": 0, "other_model_failures": 0}}
    manifest = read_json(manifest_path)
    require(isinstance(manifest, dict), "invalid_api_manifest")
    core = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    require(manifest.get("manifest_sha256") == digest(canonical_bytes(core)), "manifest_hash_mismatch")
    require(manifest.get("schema_version") == "notice-api-run-v1", "unsupported_api_manifest")
    identity = manifest["identity"]
    config = identity["configuration"]
    require(identity["dataset_sha256"] == digest(raw_inputs_dataset), "api_dataset_hash_mismatch")
    require(identity["configuration_sha256"] == digest(canonical_bytes(config)), "configuration_hash_mismatch")
    require(identity["prompt_sha256"] == digest(runner.PROMPT.encode()), "prompt_hash_mismatch")
    require(identity["schema_sha256"] == digest(canonical_bytes(runner.SCHEMA)), "schema_hash_mismatch")
    require(identity["runner_sha256"] == digest(Path(runner.__file__).read_bytes()), "frozen_runner_hash_mismatch")
    for name, expected in (("prompt.txt", runner.PROMPT.encode("utf-8")),
                           ("schema.json", canonical_bytes(runner.SCHEMA) + b"\n")):
        retained = run_dir / name
        require(not retained.is_symlink() and retained.is_file()
                and retained.read_bytes() == expected, "archived_" + name.replace(".", "_") + "_mismatch")
    split = identity["split"]
    require(split in dataset["splits"] and bool(dataset["splits"][split]), "unknown_or_empty_api_split")
    transport = config.get("transport_mode")
    require(transport in {"openai_https", "injected_test_transport"}, "unknown_api_transport")
    require(config.get("endpoint") == runner.ENDPOINT and config.get("automatic_retries") == 0,
            "unexpected_api_execution_contract")
    prices = [Decimal(config[key]) for key in ("input_usd_per_million", "output_usd_per_million")]
    require(all(value.is_finite() and value >= 0 for value in prices), "invalid_recorded_prices")
    rows = dataset["splits"][split]
    repeats, limit = config["repeats"], config["max_calls"]
    require(type(repeats) is int and 1 <= repeats <= 5 and type(limit) is int
            and 1 <= limit <= len(rows) * repeats, "invalid_api_request_count")
    require(config["max_output_tokens"] in {512, 768}, "invalid_api_output_bound")
    requested, inputs, planned_cases = [], [], {}
    for case in rows:
        for repeat in range(repeats):
            if len(requested) == limit:
                break
            model_input = case["model_input"]
            input_hash = digest(canonical_bytes(model_input))
            body = runner.build_request(model_input, config["model"], config["max_output_tokens"])
            body_bytes = canonical_bytes(body)
            bound = len(body_bytes) + runner.INPUT_OVERHEAD_TOKENS
            price = ((bound * prices[0] + config["max_output_tokens"] * prices[1])
                     / 1_000_000).quantize(Decimal(".00000001"), rounding=ROUND_CEILING)
            cache = {key: identity[key] for key in
                     ("dataset_sha256", "prompt_sha256", "schema_sha256", "configuration_sha256")}
            cache.update(input_sha256=input_hash, repeat_index=repeat)
            item = {"case_id": case["id"], "request_key": digest(canonical_bytes(cache)),
                    "request_sha256": digest(body_bytes), "input_sha256": input_hash,
                    "repeat_index": repeat, "input_token_upper_bound": bound,
                    "reservation_usd": format(price, "f")}
            requested.append(item)
            inputs.append({"case_id": case["id"], "repeat_index": repeat, "model_input": model_input})
            planned_cases[item["request_key"]] = case
        if len(requested) == limit:
            break
    require(requested == manifest["requests"], "api_request_identity_mismatch")
    input_bytes = b"".join(canonical_bytes(row) + b"\n" for row in inputs)
    require(digest(input_bytes) == identity["inputs_sha256"], "api_inputs_hash_mismatch")
    input_path = run_dir / "inputs.jsonl"
    require(not input_path.is_symlink() and input_path.read_bytes() == input_bytes, "api_inputs_file_mismatch")
    log_path = run_dir / "records.jsonl"
    if log_path.exists():
        require(not log_path.is_symlink(), "symlink_api_ledger")
        for line in log_path.read_bytes().splitlines():
            strict_json(line)  # The frozen reader's hash checks follow this strict JSON check.
    anchor_path = run_dir / "ledger-anchor.json"
    if anchor_path.exists():
        read_json(anchor_path)
    records, _ = runner._read_log(log_path)
    require(bool(records) or not anchor_path.exists(), "empty_truncated_api_ledger")
    plan = {row["request_key"]: row for row in requested}
    reservations, results = {}, {}
    expected_model = config.get("expected_returned_model") or (
        config["model"] if identity["model_pinning"] == "dated_snapshot_requested" else None)
    for record in records:
        key = record.get("request_key")
        require(key in plan, "unknown_api_request")
        item = plan[key]
        if record.get("kind") == "reservation":
            require(key not in reservations and all(record.get(field) == item[field]
                    for field in ("request_sha256", "input_sha256", "repeat_index", "reservation_usd")),
                    "api_reservation_identity_mismatch")
            reservations[key] = record
        elif record.get("kind") == "result":
            require(key in reservations and key not in results, "duplicate_or_unreserved_api_result")
            require(all(record.get(field) == item[field]
                    for field in ("case_id", "input_sha256", "repeat_index")), "api_result_identity_mismatch")
            if "raw_response" in record:
                response = record["raw_response"]
                require(isinstance(response, dict)
                        and record.get("raw_response_sha256") == digest(canonical_bytes(response)),
                        "api_response_hash_mismatch")
                parsed = runner._response_result(response, planned_cases[key]["model_input"],
                                                 expected_model, *prices)
                require(all(record.get(field) == value for field, value in parsed.items()),
                        "api_response_parse_mismatch")
            else:
                require(record.get("status") in {"api_error", "transport_error"}
                        and all(record.get(field) is None for field in
                                ("parsed_output", "usage", "usage_cost_usd")), "api_result_without_response")
            if record.get("usage_cost_usd") is not None:
                cost = Decimal(record["usage_cost_usd"])
                require(cost.is_finite() and 0 <= cost <= Decimal(item["reservation_usd"]),
                        "api_usage_exceeds_reservation")
            results[key] = record
        else:
            raise ValueError("unknown_api_record_kind")
    status_counts = Counter(record["status"] for record in results.values())
    completed = {key: record for key, record in results.items() if record["status"] == "completed"}
    report = {**base, "split": split, "corpus": corpus_summary(dataset, split),
              "transport": transport, "counts": {
                  "requested_calls": len(plan), "attempted_calls": len(reservations),
                  "completed_calls": len(completed), "api_errors": status_counts["api_error"],
                  "transport_errors": status_counts["transport_error"],
                  "other_model_failures": len(results) - len(completed)
                      - status_counts["api_error"] - status_counts["transport_error"],
                  "unknown_outcome_attempts": len(reservations) - len(results),
                  "unattempted_calls": len(plan) - len(reservations)},
              "partial_run": len(completed) != len(plan)}
    report["status"] = "no_completed_outputs"
    if completed:
        report["status"] = ("partial_" if report["partial_run"] else "completed_") + (
            "mock_evaluation" if transport == "injected_test_transport" else "live_evaluation")
        report["live_api_evidence"] = transport == "openai_https"
        predictions = [{"case_id": plan[key]["case_id"], "repeat_id": str(plan[key]["repeat_index"]),
                        "output": _provider_text(record["raw_response"])} for key, record in completed.items()]
        completed_ids = {row["case_id"] for row in predictions}
        report["reference_agreement_completed_outputs"] = score_predictions(
            [case for case in rows if case["id"] in completed_ids], predictions)
        all_predictions = [{"case_id": item["case_id"], "repeat_id": str(item["repeat_index"]),
                            "output": (_provider_text(completed[key]["raw_response"])
                                       if key in completed else None)} for key, item in plan.items()]
        planned_ids = {item["case_id"] for item in plan.values()}
        report["reference_agreement_all_planned_outputs"] = score_predictions(
            [case for case in rows if case["id"] in planned_ids], all_predictions)
    return report
