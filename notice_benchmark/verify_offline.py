"""Read-only replay verification of the frozen offline notice experiment.

This verifies data/source identities, stored predictions, declared algorithms,
and deterministic metric recomputation.  It deliberately reuses the project's
scoring functions: it is an execution/integrity check, not a second independent
implementation of the metrics or an external attestation of the freeze date.
No API client is imported and no model call or output-file write is performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .data import canonical_bytes, validate_dataset
from .effects import compare_effect
from .metrics import score_predictions
from .rules import extract_notice
from .run_offline import family_interval


ROOT = Path(__file__).resolve().parents[1]
METHODS = ("rules_frozen_v1", "always_clarify", "ignore_notice", "reference_upper_bound")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON object key")
        value[key] = item
    return value


def _reject_constant(_: str) -> None:
    raise ValueError("Non-finite JSON number")


def _decode(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)


def _json_file(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Required regular file missing or symlinked: {path.name}")
    return _decode(path.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_file(base: Path, relative: Any) -> Path:
    """Resolve manifest-owned paths without accepting traversal or symlinks."""
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or "\x00" in relative or ":" in relative
            or any(part in ("", ".", "..") for part in relative.split("/"))):
        raise ValueError("Unsafe relative manifest path")
    pure = PurePosixPath(relative)
    if pure.is_absolute():
        raise ValueError("Unsafe absolute manifest path")
    base = base.absolute()
    if base.is_symlink() or not base.is_dir():
        raise ValueError("Manifest root must be a regular directory")
    candidate = base
    for part in pure.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("Symlink in manifest path")
    try:
        candidate.resolve(strict=True).relative_to(base.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ValueError("Missing or escaping manifest path") from exc
    if not candidate.is_file():
        raise ValueError("Manifest target must be a regular file")
    return candidate


def _check_hashes(base: Path, identities: Any, description: str) -> int:
    if not isinstance(identities, dict) or not identities:
        raise ValueError(f"Missing {description} SHA-256 map")
    for relative, expected in identities.items():
        path = _safe_file(base, relative)
        if not isinstance(expected, str) or _DIGEST.fullmatch(expected) is None:
            raise ValueError(f"Invalid {description} SHA-256")
        if _digest(path) != expected:
            raise ValueError(f"{description} SHA-256 mismatch: {relative}")
    return len(identities)


def _prediction_rows(path: Path, case_ids: set[str]) -> dict[str, Any]:
    predictions: dict[str, Any] = {}
    pairs: set[tuple[str, str]] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"Blank prediction record at line {line_number}")
        row = _decode(line)
        if not isinstance(row, dict) or set(row) != {"case_id", "repeat_id", "output"}:
            raise ValueError("Unexpected offline prediction record schema")
        case_id, repeat_id = row["case_id"], row["repeat_id"]
        if not isinstance(case_id, str) or not isinstance(repeat_id, str):
            raise ValueError("Prediction identifiers must be strings")
        if (case_id, repeat_id) in pairs or case_id in predictions:
            raise ValueError("Duplicate prediction case/repeat")
        pairs.add((case_id, repeat_id))
        if repeat_id != "0":
            raise ValueError("Offline v1 requires exactly repeat_id 0 per case")
        if case_id not in case_ids:
            raise ValueError("Unknown prediction case")
        predictions[case_id] = row["output"]
    if set(predictions) != case_ids:
        raise ValueError("Missing prediction case coverage")
    return predictions


def _require_equal(actual: Any, expected: Any, description: str) -> None:
    if canonical_bytes(actual) != canonical_bytes(expected):
        raise ValueError(f"{description} differs from deterministic recomputation")


def _check_dataset_exports(dataset: dict[str, Any], dataset_path: Path) -> int:
    """Validate the writer's byte manifests as well as its semantic identity."""
    manifest_path = dataset_path.parent / "manifest.json"
    manifest = _json_file(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != dataset["schema_version"]:
        raise ValueError("Unexpected dataset export manifest")
    for key, value in dataset["manifest"].items():
        _require_equal(manifest.get(key), value, f"Dataset manifest {key}")
    if manifest.get("synthetic") is not True or manifest.get("seed") != dataset["seed"]:
        raise ValueError("Dataset export metadata mismatch")
    hashes = manifest.get("file_sha256")
    count = _check_hashes(dataset_path.parent, hashes, "Dataset export")
    expected_names = {dataset_path.name, "development.jsonl", "test.jsonl"}
    if set(hashes) != expected_names:
        raise ValueError("Unexpected dataset export files")
    for split, records in dataset["splits"].items():
        path = _safe_file(dataset_path.parent, f"{split}.jsonl")
        rows = [_decode(line) for line in path.read_text(encoding="utf-8").splitlines()]
        _require_equal(rows, records, f"Dataset {split} export")
    return count


def _method_summary(cases: list[dict], predictions: dict[str, Any], scored: dict) -> dict:
    effects = [compare_effect(case["reference"], predictions[case["id"]],
                              case["model_input"]["context"]) for case in cases]
    if any(str(effect["reason"]).startswith("reference_") for effect in effects):
        raise ValueError("Invalid reference in semantic-effect scoring")
    categories = {}
    for category in sorted({case["category"] for case in cases}):
        subset = [case for case in cases if case["category"] == category]
        subset_predictions = {case["id"]: predictions[case["id"]] for case in subset}
        sub_score = score_predictions(subset, subset_predictions)
        categories[category] = {
            "records": len(subset),
            "exact_match_rate": sub_score["summary"]["exact_match_rate"],
        }
    return {
        "counts": scored["counts"], "summary": scored["summary"],
        "schedule_effect_match_rate": sum(bool(e["effect_match"]) for e in effects) / len(effects),
        "template_grouped": family_interval(cases, predictions),
        "by_category": categories,
    }


def verify(dataset_path: str | Path, freeze_path: str | Path,
           output: str | Path) -> dict[str, Any]:
    """Reexecute and verify an existing offline result directory without writes."""
    dataset_path, freeze_path, output = Path(dataset_path), Path(freeze_path), Path(output)
    dataset = _json_file(dataset_path)
    validate_dataset(dataset)
    dataset_files = _check_dataset_exports(dataset, dataset_path)
    frozen = _json_file(freeze_path)
    expected_freeze = {
        "schema_version": "notice-rules-freeze-v1",
        "dataset_sha256": dataset["manifest"]["dataset_sha256"],
        "rules_sha256": _digest(ROOT / "notice_benchmark/rules.py"),
        "scope": "ASML-inspired NL_ocean announced delays; known committed orders",
        "development_only_rule_tuning": True,
        "test_used_for_rule_tuning": False,
        "primary_metric": "strict whole-notice exact match",
        "secondary_metric": "compiled weekly lead schedule equivalence",
    }
    _require_equal(frozen, expected_freeze, "Frozen dataset/rules identity")

    manifest = _json_file(output / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "notice-offline-artifacts-v1":
        raise ValueError("Unexpected offline artifact manifest")
    if type(manifest.get("api_calls")) is not int or manifest["api_calls"] != 0:
        raise ValueError("Offline result must declare zero API calls")
    for key in ("dataset_sha256", "rules_sha256"):
        if manifest.get(key) != frozen[key]:
            raise ValueError(f"Offline manifest {key} mismatch")
    artifact_count = _check_hashes(output, manifest.get("file_sha256"), "Artifact")
    expected_artifacts = {"summary.json"} | {
        f"{method}.{suffix}" for method in METHODS
        for suffix in ("predictions.jsonl", "metrics.json")
    }
    if set(manifest["file_sha256"]) != expected_artifacts:
        raise ValueError("Unexpected offline artifact inventory")
    actual_artifacts = {
        path.relative_to(output).as_posix() for path in output.rglob("*")
        if (path.is_file() or path.is_symlink())
        and path.relative_to(output).as_posix() != "manifest.json"
    }
    if actual_artifacts != expected_artifacts:
        raise ValueError("Unmanifested or missing offline artifact")

    sources = manifest.get("source_sha256")
    source_count = _check_hashes(ROOT, sources, "Source")
    expected_sources = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "notice_benchmark").glob("*.py") if path.is_file()
    }
    if set(sources) != expected_sources:
        raise ValueError("Source manifest does not cover the current notice-benchmark implementation")

    cases = dataset["splits"]["test"]
    case_ids = {case["id"] for case in cases}
    summary = _json_file(output / "summary.json")
    if (not isinstance(summary, dict) or summary.get("schema_version") != "notice-offline-comparison-v1"
            or summary.get("synthetic") is not True
            or type(summary.get("independent_real_notices")) is not int
            or summary["independent_real_notices"] != 0
            or type(summary.get("test_records")) is not int or summary["test_records"] != len(cases)):
        raise ValueError("Offline summary metadata mismatch")
    _require_equal(summary.get("frozen_identity"), frozen, "Summary frozen identity")
    if not isinstance(summary.get("llm"), dict) or summary["llm"].get("executed") is not False:
        raise ValueError("Offline result cannot claim LLM execution")
    if not isinstance(summary.get("methods"), dict) or set(summary["methods"]) != set(METHODS):
        raise ValueError("Unexpected summary method coverage")

    for method in METHODS:
        predictions = _prediction_rows(output / f"{method}.predictions.jsonl", case_ids)
        for case in cases:
            if method == "rules_frozen_v1":
                # Replay consumes only the exact text/context inference payload.
                expected = extract_notice(**case["model_input"])
            elif method == "always_clarify":
                expected = {"status": "needs_clarification", "changes": []}
            elif method == "ignore_notice":
                expected = {"status": "ready", "changes": []}
            else:
                expected = case["reference"]
            _require_equal(predictions[case["id"]], expected, f"{method} algorithm replay")
        scored = score_predictions(cases, predictions)
        stored_score = _json_file(output / f"{method}.metrics.json")
        _require_equal(stored_score, scored, f"{method} metrics")
        _require_equal(summary["methods"][method], _method_summary(cases, predictions, scored),
                       f"{method} summary/effects/categories/family interval")

    return {
        "verified": True, "schema_version": "notice-offline-verification-v1",
        "dataset_sha256": frozen["dataset_sha256"], "rules_sha256": frozen["rules_sha256"],
        "test_records": len(cases), "methods": len(METHODS),
        "prediction_records": len(cases) * len(METHODS), "rules_replayed": len(cases),
        "artifact_files": artifact_count, "dataset_export_files": dataset_files,
        "source_files": source_count, "api_calls": 0,
        "verification_scope": "Frozen algorithm replay and deterministic consistency recomputation using the shared metric/effect helpers; not an independent scoring implementation or external freeze-date attestation.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "benchmarks/notices_v1/dataset.json")
    parser.add_argument("--freeze", type=Path, default=ROOT / "benchmarks/notices_v1/rules_freeze.json")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmark_results/notices_v1",
                        help="Existing result directory to verify; no files are written")
    args = parser.parse_args()
    try:
        result = verify(args.dataset, args.freeze, args.output)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        parser.exit(2, f"Verification failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
