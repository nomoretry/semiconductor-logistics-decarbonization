"""Offline corpus validation; recorded provenance is not external attestation."""

from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from notice_benchmark.api_runner import _validate_input, validate_output
from notice_benchmark.data import default_context

SCHEMA_VERSION = "real-notice-eval-v1"
ANNOTATION_STATUS = "assistant_reference_pending_human_review"
EVALUATION_SCOPE = "exploratory_short_excerpt_abstention_audit"
CLASSES = ("ready_update", "ready_noop", "needs_clarification")


def require(condition: Any, code: str) -> None:
    if not condition:
        raise ValueError(code)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(_: str) -> None:
    raise ValueError("nonfinite_json_number")


def strict_json(raw: str | bytes) -> Any:
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)


def read_json(path: str | Path) -> Any:
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), "regular_json_file_required")
    return strict_json(path.read_bytes())


def output_class(output: dict[str, Any]) -> str:
    if output["status"] == "needs_clarification":
        return "needs_clarification"
    return "ready_update" if output["changes"] else "ready_noop"


def normalized_output(value: Any, model_input: dict[str, Any]) -> dict[str, Any]:
    """Combine strict schema, integer-week scope, and duplicate-change checks."""
    if isinstance(value, str):
        value = strict_json(value)
    require(validate_output(value, model_input), "invalid_scoped_integer_week_output")
    # All numeric fields are already exact ints under the frozen validator.
    # Do not coerce them through float/isfinite: valid large JSON integers can
    # overflow a float conversion even though the integer schema has no cap.
    fields = ("op", "route", "start_week", "end_week", "value")
    changes = [{key: change[key] for key in fields} for change in value["changes"]]
    identities = [tuple(change[key] for key in fields) for change in changes]
    require(len(set(identities)) == len(identities), "duplicate_change")
    canonical_bytes(value)  # Reject non-JSON in-memory objects and detach below.
    changes.sort(key=lambda change: tuple(change[key] for key in fields))
    return {"status": value["status"], "changes": changes}


def _text(value: Any, code: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), code)
    return value


def _date(value: Any, code: str) -> date:
    require(isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), code)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(code) from None


def _url(value: Any) -> str:
    _text(value, "invalid_source_url")
    parsed = urlsplit(value)
    require(parsed.scheme == "https" and bool(parsed.netloc)
            and parsed.username is None and parsed.password is None, "invalid_source_url")
    # Fragments do not create a second source document.
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path,
                       parsed.query, ""))


def validate_dataset(dataset: Any) -> None:
    """Validate declarations and excerpt integrity without fetching source pages.

    The tiny corpus is exploratory. A single test split is allowed and is not a
    held-out test set. If development cases exist, recorded source/event and
    correlation groups must be disjoint. Human review is never inferred.
    """
    require(isinstance(dataset, dict), "dataset_object_required")
    require(dataset.get("schema_version") == SCHEMA_VERSION
            and dataset.get("synthetic") is False, "real_dataset_declaration_required")
    require(dataset.get("annotation_status") == ANNOTATION_STATUS,
            "assistant_pending_annotation_declaration_required")
    require(dataset.get("human_reviewed", False) is False, "human_review_not_established")
    require(dataset.get("human_review_pending", True) is True
            and dataset.get("usable_as_frozen_gold", False) is False
            and dataset.get("exploratory", True) is True, "exploratory_pending_review_required")
    sources = dataset.get("sources")
    require(isinstance(sources, list) and bool(sources), "sources_required")
    catalog: dict[str, dict[str, Any]] = {}
    urls: set[str] = set()
    for source in sources:
        require(isinstance(source, dict), "source_object_required")
        source_id = _text(source.get("source_id"), "source_id_required")
        require(source_id not in catalog, "duplicate_source_id")
        url = _url(source.get("url"))
        require(url not in urls, "duplicate_source_document_url")
        urls.add(url)
        for key in ("publisher", "title", "event_group_id", "correlation_group_id",
                    "evidence_location", "review_method"):
            _text(source.get(key), "source_" + key + "_required")
        require(source.get("source_type") == "official_notice", "official_notice_declaration_required")
        # A missing or ambiguous publication date stays unknown; URL paths and
        # access dates are not publication-date evidence.
        require("published_date" in source, "publication_date_or_explicit_null_required")
        published = (_date(source["published_date"], "invalid_publication_date")
                     if source["published_date"] is not None else None)
        accessed = _date(source.get("accessed_date"), "invalid_access_date")
        require(published is None or published <= accessed, "publication_after_access")
        excerpt = _text(source.get("text"), "source_excerpt_required")
        require(len(excerpt.split()) <= 25, "source_excerpt_word_limit")
        require(source.get("text_kind") == "verbatim_excerpt", "verbatim_excerpt_declaration_required")
        require(source.get("sha256") == digest(excerpt.encode("utf-8")), "source_excerpt_hash_mismatch")
        require(source.get("text_sha256", source["sha256"]) == source["sha256"],
                "conflicting_source_excerpt_hashes")
        require(source.get("full_notice_reviewed") is True
                and source.get("full_text_redistributed") is False, "source_review_declaration_required")
        require(bool(source.get("body_lines_reviewed")), "source_review_locator_required")
        require(isinstance(source.get("web_reference_ids"), list)
                and all(isinstance(value, str) and value for value in source["web_reference_ids"])
                and bool(source["web_reference_ids"]), "source_web_references_required")
        require(source.get("human_reviewed", False) is False, "human_review_not_established")
        require(source.get("human_review_pending", True) is True
                and source.get("annotation_status", ANNOTATION_STATUS) == ANNOTATION_STATUS,
                "source_assistant_review_declaration_required")
        catalog[source_id] = source

    splits = dataset.get("splits")
    require(isinstance(splits, dict) and "test" in splits
            and set(splits) <= {"development", "test"}, "unsupported_splits")
    require(isinstance(splits["test"], list) and bool(splits["test"]), "test_cases_required")
    ids: set[str] = set()
    payloads: set[str] = set()
    used: set[str] = set()
    groups: dict[str, dict[str, set[str]]] = {}
    for split, cases in splits.items():
        require(isinstance(cases, list), "split_array_required")
        split_groups = {key: set() for key in
                        ("source_id", "event_group_id", "correlation_group_id", "excerpt_sha256")}
        for case in cases:
            require(isinstance(case, dict), "case_object_required")
            case_id = _text(case.get("id"), "case_id_required")
            require(case_id not in ids, "duplicate_case_id")
            require(case.get("synthetic", False) is False, "synthetic_case_in_real_corpus")
            ids.add(case_id)
            source_id = case.get("source_id")
            require(isinstance(source_id, str) and source_id in catalog, "unknown_case_source")
            source = catalog[source_id]
            used.add(source_id)
            for key in ("event_group_id", "correlation_group_id"):
                require(case.get(key) == source[key], "case_source_group_mismatch")
            require(case.get("excerpt_sha256") == source["sha256"], "case_excerpt_hash_mismatch")
            model_input = _validate_input(case.get("model_input"))
            require(model_input["text"] == source["text"], "case_excerpt_differs_from_source")
            require(model_input["context"] == default_context(), "published_business_context_required")
            payload_hash = digest(canonical_bytes(model_input))
            require(payload_hash not in payloads, "duplicate_model_input")
            payloads.add(payload_hash)
            normalized_output(case.get("reference"), model_input)
            annotation = case.get("annotation")
            require(isinstance(annotation, dict) and annotation.get("status") == ANNOTATION_STATUS,
                    "assistant_case_annotation_required")
            _text(annotation.get("rationale"), "case_rationale_required")
            missing = annotation.get("missing_information")
            require(isinstance(missing, list) and all(isinstance(value, str) and value.strip()
                                                    for value in missing), "missing_information_array_required")
            require(case["reference"]["status"] != "needs_clarification" or bool(missing),
                    "clarification_reasons_required")
            require(annotation.get("human_reviewed", False) is False, "human_review_not_established")
            require(annotation.get("human_review_pending", True) is True
                    and annotation.get("annotator_type", "assistant") == "assistant",
                    "case_assistant_review_declaration_required")
            if "broad_reference" in annotation:
                broad = annotation["broad_reference"]
                require(isinstance(broad, dict)
                        and broad.get("schema_version") == "real-notice-facts-v1"
                        and broad.get("evidence_scope") == "model_input.text_only",
                        "unsupported_broad_reference_contract")
                _text(broad.get("event_kind"), "broad_event_kind_required")
                for key in ("named_services", "locations", "temporal_qualifiers",
                            "quantities", "unsupported_inferences"):
                    require(isinstance(broad.get(key), list), "broad_" + key + "_array_required")
            for key in split_groups:
                split_groups[key].add(case[key])
        groups[split] = split_groups
    require(used == set(catalog), "unreferenced_sources_must_be_excluded_explicitly")
    all_cases = [case for cases in splits.values() for case in cases]
    for key, actual in (("source_count", len(catalog)),
                        ("event_group_count", len({case["event_group_id"] for case in all_cases})),
                        ("correlation_group_count", len({case["correlation_group_id"] for case in all_cases}))):
        require(key not in dataset or (type(dataset[key]) is int and dataset[key] == actual),
                "declared_" + key + "_mismatch")
    if "development" in groups:
        for key in groups["test"]:
            require(not groups["test"][key] & groups["development"][key], "cross_split_" + key)
    exclusions = dataset.get("excluded_sources", [])
    require(isinstance(exclusions, list), "exclusions_array_required")
    for item in exclusions:
        require(isinstance(item, dict), "exclusion_object_required")
        _text(item.get("reason"), "exclusion_reason_required")
        require(bool(item.get("source_id") or item.get("url")), "excluded_source_identity_required")
        if item.get("source_id"):
            require(isinstance(item["source_id"], str) and item["source_id"] not in catalog,
                    "excluded_source_is_evaluated")
        if item.get("url"):
            require(_url(item["url"]) not in urls, "excluded_source_document_is_evaluated")


def load_dataset(path: str | Path) -> dict[str, Any]:
    dataset = read_json(path)
    validate_dataset(dataset)
    return dataset


def corpus_summary(dataset: dict[str, Any], split: str = "test") -> dict[str, Any]:
    validate_dataset(dataset)
    require(split in dataset["splits"], "unknown_split")
    cases = dataset["splits"][split]
    balance = Counter(output_class(case["reference"]) for case in cases)
    return {
        "number_cases": len(cases),
        "number_source_documents": len({case["source_id"] for case in cases}),
        "number_event_groups": len({case["event_group_id"] for case in cases}),
        "number_correlation_groups": len({case["correlation_group_id"] for case in cases}),
        "reference_class_balance": {key: balance[key] for key in CLASSES},
        "excluded_source_count": len(dataset.get("excluded_sources", [])),
        "excluded_sources": dataset.get("excluded_sources", []),
        "ready_update_coverage_established": balance["ready_update"] > 0,
        "development_count": len(dataset["splits"].get("development", [])),
        "held_out_evaluation": False,
    }
