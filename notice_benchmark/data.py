"""Deterministic, synthetic-only ASML-inspired logistics notice benchmark.

This module does not call an LLM.  ``model_input`` is the entire inference
payload; reference answers and generator metadata must never be sent to it.
The split is by generated event AND rendering family, not random paraphrases.
"""

from __future__ import annotations

import argparse
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
from typing import Any


SCHEMA_VERSION = "notice-benchmark-v1.0"
SCOPE_ROUTE = "NL_ocean"
CATEGORIES = (
    "added_weeks", "added_days", "added_fortnights", "revised_total",
    "no_change", "negated_alert", "correction", "superseded_window",
    "unrelated_route", "missing_route", "missing_window", "missing_increment",
    "nonintegral_days", "uncertain_range", "arrival_window", "multiple_windows",
    "unknown_route", "conflicting_reports",
)

# Development and test have separate rendering families.  They share the
# declared task semantics, as an in-domain holdout should, but not templates.
# No learned model or rule parser is used to construct these reference labels.
_TEMPLATES: dict[str, dict[str, tuple[str, str]]] = {
    "development": {
        "added_weeks": (
            "For {route} dispatches in weeks {start} through {end} inclusive, add {delta} weeks to normal transit time.",
            "Dispatches on {route} in weeks {start}–{end} take {delta} additional weeks. Both endpoint weeks are included.",
        ),
        "added_days": (
            "For {route}, dispatch weeks {start} to {end} inclusive require {days} extra days in transit.",
            "Add {days} days to {route}'s usual transit time for departures in weeks {start}–{end}, inclusive.",
        ),
        "added_fortnights": (
            "For {route} departures during weeks {start}–{end} inclusive, the extra transit time is {fortnights} fortnight(s).",
            "Add {fortnights} fortnight(s) to normal {route} transit for dispatch weeks {start} through {end}, inclusive.",
        ),
        "revised_total": (
            "The total transit time for {route} dispatches in weeks {start}–{end} inclusive is now {total} weeks, replacing the normal duration.",
            "For departures on {route} in weeks {start} through {end} inclusive, use {total} weeks as the entire transit duration, not an increment.",
        ),
        "no_change": (
            "For {route} dispatches in weeks {start}–{end} inclusive, there is no delay. Normal transit time remains unchanged.",
            "No increase applies to {route} departures in weeks {start} through {end}, inclusive; retain the usual transit duration.",
        ),
        "negated_alert": (
            "The proposed {old_delta}-week increase for {route} dispatches in weeks {start}–{end} inclusive has been withdrawn. Normal transit applies; no delay is in force.",
            "Cancel the earlier {old_delta}-week delay alert for {route} departure weeks {start} through {end}, inclusive. The baseline transit duration is unchanged.",
        ),
        "correction": (
            "Correction for {route}, dispatch weeks {start}–{end} inclusive: the earlier notice said add {old_delta} weeks. Replace that figure with an extra {delta} weeks; do not add the two figures.",
            "For {route} departures in weeks {start} through {end}, inclusive, disregard the earlier {old_delta}-week increase. The final approved increase is {delta} weeks.",
        ),
        "superseded_window": (
            "Superseding notice for {route}: disregard the previous dispatch window weeks {old_start}–{old_end}. Add {delta} weeks only for dispatches in weeks {start}–{end}, inclusive. All other dispatch weeks retain baseline transit.",
            "Replace the old {route} alert for weeks {old_start} through {old_end}. The updated delay is {delta} extra weeks, covering departure weeks {start} through {end} inclusive only.",
        ),
        "unrelated_route": (
            "{other_route} dispatches in weeks {start}–{end} inclusive need {delta} extra weeks. {route} transit is unchanged.",
            "The {delta}-week increase for departure weeks {start} through {end}, inclusive, applies only to {other_route}. No change applies to {route}.",
        ),
        "missing_route": (
            "An unspecified shipping service needs {delta} extra weeks for dispatches in weeks {start}–{end} inclusive. The affected route has not been identified.",
            "Dispatch weeks {start} through {end}, inclusive, will incur an additional {delta} weeks, but operations has not provided the route identity.",
        ),
        "missing_window": (
            "Issued in planning week {issued}: {route} needs {delta} additional weeks in transit. The affected dispatch weeks have not been announced.",
            "Report received in week {issued}: transit on {route} will be {delta} weeks longer; start and end dispatch weeks remain unconfirmed.",
        ),
        "missing_increment": (
            "{route} dispatches in weeks {start}–{end} inclusive will take longer. Neither the increase nor the revised total transit time is available.",
            "There is a delay on {route} for departure weeks {start} through {end}, inclusive. The transit duration has not yet been quantified.",
        ),
        "nonintegral_days": (
            "Add {nonintegral_days} days to {route} transit for dispatch weeks {start}–{end} inclusive. No rounding rule has been agreed for the weekly model.",
            "{route} departures in weeks {start} through {end}, inclusive, need {nonintegral_days} additional days. The plan uses whole weeks and no conversion rounding policy is provided.",
        ),
        "uncertain_range": (
            "For {route} dispatches in weeks {start}–{end} inclusive, the increase may be between {delta} and {upper_delta} weeks. No single value has been confirmed.",
            "The delay range for {route} departure weeks {start} through {end}, inclusive, is {delta}–{upper_delta} extra weeks; an exact increase is unavailable.",
        ),
        "arrival_window": (
            "{route} arrivals expected in weeks {start}–{end} inclusive will be {delta} weeks late. The affected dispatch weeks have not been identified.",
            "For {route}, weeks {start} through {end} identify the expected arrival window, not dispatches. Those arrivals incur {delta} extra weeks; no departure-week mapping is available.",
        ),
        "multiple_windows": (
            "For {route}, add {delta} weeks to dispatches in weeks {start}–{end} inclusive; separately add {second_delta} weeks for dispatch weeks {second_start}–{second_end} inclusive. Other weeks are unchanged.",
            "{route} has two separate dispatch windows: weeks {start} through {end} inclusive need {delta} extra weeks, while weeks {second_start} through {second_end} inclusive need {second_delta} extra weeks.",
        ),
        "unknown_route": (
            "For dispatch weeks {start}–{end} inclusive, add {delta} weeks to service ZX_ocean. This is an unresolved alias for a Netherlands route; its mapping to the route catalog is unavailable.",
            "A Netherlands service labelled ZX_ocean needs {delta} extra weeks for departure weeks {start} through {end}, inclusive. The service alias is absent from the catalog and its actual route is unconfirmed.",
        ),
        "conflicting_reports": (
            "Two equally current reports cover {route} dispatch weeks {start}–{end} inclusive: one says add {old_delta} weeks and the other says add {delta} weeks. Neither report supersedes the other; precedence is unresolved.",
            "For {route} departures in weeks {start} through {end}, inclusive, carrier reports conflict: an extra {old_delta} weeks versus an extra {delta} weeks. No authoritative update is identified.",
        ),
    },
    "test": {
        "added_weeks": (
            "Service bulletin: the transit-time uplift for {route} departures between week {start} and week {end}, both included, is {delta} weeks.",
            "Planning instruction: keep baseline timings outside the window. Departure weeks {start} to {end} inclusive on {route} require an extra {delta}-week allowance.",
        ),
        "added_days": (
            "Schedule amendment for {route}: the increment is {days} days beyond standard transit, restricted to departures from week {start} through week {end} inclusive.",
            "Affected departures: {route}, weeks {start}–{end} including both boundaries. Transit extension over the usual duration: {days} days.",
        ),
        "added_fortnights": (
            "Transit supplement of {fortnights} fortnight(s) is required on {route}; eligible departures are those in weeks {start} to {end}, inclusive.",
            "For sailings dispatched on {route} between weeks {start} and {end}, inclusive, allow {fortnights} further fortnight(s) beyond baseline transit.",
        ),
        "revised_total": (
            "{route} scheduling replacement: departures falling within weeks {start} to {end} inclusive now have an end-to-end transit duration of {total} weeks in total.",
            "Use a replacement transit duration of {total} weeks for {route} shipments dispatched between week {start} and week {end}, inclusive. This number is the total, not an amount to add.",
        ),
        "no_change": (
            "Operational confirmation for {route}: departures spanning weeks {start}–{end}, inclusive, continue on the baseline schedule with zero extension.",
            "Keep the standard {route} transit duration for every departure in weeks {start} through {end}, including both endpoints. No extra transit weeks apply.",
        ),
        "negated_alert": (
            "Withdrawal bulletin: the suggested extension of {old_delta} weeks on {route}, covering departures in weeks {start}–{end} inclusive, will not take effect. Retain baseline timings.",
            "The {old_delta}-week extension previously mentioned for {route} departures between weeks {start} and {end}, inclusive, is cancelled rather than implemented; normal transit is retained.",
        ),
        "correction": (
            "Final amendment for departures in weeks {start}–{end} inclusive on {route}: substitute a {delta}-week extension for the earlier {old_delta}-week extension. The two extensions are alternatives, not cumulative.",
            "{route}, departure-week interval [{start}, {end}] with inclusive endpoints: the obsolete increase was {old_delta} weeks; the replacement increase is {delta} weeks only.",
        ),
        "superseded_window": (
            "{route} window replacement: the prior notice covering departure weeks {old_start}–{old_end} is void. The active notice adds {delta} transit weeks for departures in weeks {start} through {end} inclusive, and no others.",
            "Only the replacement sailing window is effective on {route}: departures from week {start} to week {end}, inclusive, take {delta} extra weeks. Discard the previous weeks {old_start}–{old_end} notice in full.",
        ),
        "unrelated_route": (
            "Transport advisory for {other_route} alone: departures within weeks {start}–{end} inclusive have a {delta}-week extension. The scoped {route} service retains its baseline timing.",
            "Apply a {delta}-week transit supplement to {other_route} departures from week {start} through week {end}, inclusive. This advisory explicitly excludes {route}.",
        ),
        "missing_route": (
            "Departure-window advisory, weeks {start}–{end} inclusive: a {delta}-week transit extension is confirmed, but the identity of the affected service is still missing.",
            "An additional {delta} transit weeks applies to departures between weeks {start} and {end}, inclusive. The carrier has not named which route is affected.",
        ),
        "missing_window": (
            "Message timestamp: planning week {issued}. A {delta}-week extension on {route} is confirmed, but this timestamp is not an effective dispatch date; the affected departure interval is unknown.",
            "At the week-{issued} planning meeting, operations reported {delta} extra transit weeks on {route}. No effective first or last departure week was supplied.",
        ),
        "missing_increment": (
            "Advisory applies to {route} departures between weeks {start} and {end}, inclusive. Transit is disrupted, but no numerical extension or replacement duration has been released.",
            "Affected departure interval on {route}: [{start}, {end}], inclusive. A longer journey is expected; neither an additional duration nor a revised end-to-end duration is specified.",
        ),
        "nonintegral_days": (
            "For {route} departures in weeks {start}–{end} inclusive, extend transit by {nonintegral_days} days. This does not equal a whole number of weeks, and no weekly rounding convention is authorized.",
            "The extra duration is {nonintegral_days} days on {route}, applying to departures from week {start} to week {end} inclusive. Conversion to the integer-week planning grid remains unresolved.",
        ),
        "uncertain_range": (
            "Unresolved estimate for {route}, departures from week {start} through week {end} inclusive: transit extension lies somewhere from {delta} to {upper_delta} weeks; no point estimate is approved.",
            "For departure weeks {start}–{end} inclusive, {route} may require {delta} extra weeks or as many as {upper_delta}. The current report does not select an exact value.",
        ),
        "arrival_window": (
            "Arrival-based advisory for {route}: the expected-arrival weeks {start} through {end}, inclusive, identify shipments taking {delta} extra weeks. Their dispatch-week interval is unavailable.",
            "Shipments on {route} due to arrive between weeks {start} and {end}, inclusive, need {delta} further weeks in transit. These dates describe arrivals, and the affected departures cannot be mapped from the provided information.",
        ),
        "multiple_windows": (
            "Two non-overlapping departure cohorts on {route} require separate uplifts: weeks {start}–{end} inclusive, plus {delta} weeks; weeks {second_start}–{second_end} inclusive, plus {second_delta} weeks. Baseline applies elsewhere.",
            "Schedule exception table for {route} departures: inclusive interval [{start}, {end}] has an extra {delta} weeks; inclusive interval [{second_start}, {second_end}] has an extra {second_delta} weeks. These increments are not a combined uplift.",
        ),
        "unknown_route": (
            "Route-alias notice: Netherlands service ZX_ocean has a {delta}-week extension for departures in weeks {start}–{end}, inclusive. Its actual catalog route cannot be resolved from the available alias information.",
            "For departures from week {start} through week {end} inclusive, a {delta}-week supplement applies to ZX_ocean. This unlisted Netherlands service alias has no confirmed mapping to a known route.",
        ),
        "conflicting_reports": (
            "Unreconciled notices for {route}, inclusive departure interval [{start}, {end}]: one current source gives a {old_delta}-week increment; another gives {delta} weeks. Authority and supersession are unspecified.",
            "{route} departures spanning weeks {start} to {end}, inclusive, have incompatible active updates of {old_delta} and {delta} additional weeks. Neither update has been designated the final one.",
        ),
    },
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def default_context() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "asml" / "config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    return {
        "routes": [{"name": r["name"], "lead": r["lead"]} for r in config["routes"]],
        "horizon": config["horizon"], "scope_route": SCOPE_ROUTE, "period": "week",
        "window_semantics": "dispatch_weeks_one_based_inclusive",
        "scope_policy": "Update NL_ocean only; explicit other known routes are no-ops. Unresolved route aliases require clarification.",
        "conversion_policy": "One fortnight is two weeks. Convert days only when divisible by seven; do not round. Missing, conflicting, or interval-valued critical parameters require clarification.",
    }


def _check_context(context: dict[str, Any]) -> None:
    if context.get("scope_route") != SCOPE_ROUTE or context.get("period") != "week":
        raise ValueError("This benchmark is scoped to NL_ocean on a weekly grid")
    if type(context.get("horizon")) is not int or context["horizon"] < 10:
        raise ValueError("Horizon must be an integer of at least ten weeks")
    routes = context.get("routes")
    if not isinstance(routes, list) or len(routes) < 2:
        raise ValueError("Provide the scoped route and at least one other known route")
    names = [r.get("name") for r in routes if isinstance(r, dict)]
    if len(names) != len(routes) or len(set(names)) != len(names) or SCOPE_ROUTE not in names:
        raise ValueError("Route names must be unique and include NL_ocean")
    if any(type(r.get("lead")) is not int or r["lead"] < 0 for r in routes):
        raise ValueError("Normal transit durations must be nonnegative integer weeks")


def _parameters(rng: random.Random, context: dict[str, Any], category: str) -> dict[str, Any]:
    horizon = context["horizon"]
    # The first interval leaves enough space for a second disjoint interval.
    start = rng.randint(1, horizon - 6)
    end = start + rng.randint(1, 2)
    second_start = rng.randint(end + 1, horizon - 1)
    second_end = rng.randint(second_start, horizon)
    if category == "superseded_window":
        start = rng.randint(5, horizon - 2)
        end = rng.randint(start, min(start + 2, horizon))
    delta = rng.choice((2, 4)) if category == "added_fortnights" else rng.randint(1, 4)
    old_delta = rng.choice([x for x in range(1, 6) if x != delta])
    baseline = next(r["lead"] for r in context["routes"] if r["name"] == SCOPE_ROUTE)
    return {
        "route": SCOPE_ROUTE,
        "other_route": next(r["name"] for r in context["routes"] if r["name"] != SCOPE_ROUTE),
        "baseline": baseline, "start": start, "end": end, "delta": delta,
        "days": 7 * delta, "fortnights": delta // 2, "total": baseline + delta,
        "old_delta": old_delta, "old_start": 1, "old_end": 2,
        "issued": rng.randint(1, horizon), "nonintegral_days": rng.choice((8, 10, 15, 17, 22, 24)),
        "upper_delta": delta + rng.randint(1, 3), "second_start": second_start,
        "second_end": second_end, "second_delta": rng.randint(1, 4),
    }


def _change(start: int, end: int, value: int) -> dict[str, Any]:
    return {"op": "add_lead", "route": SCOPE_ROUTE, "start_week": start,
            "end_week": end, "value": value}


def _reference(category: str, p: dict[str, Any]) -> dict[str, Any]:
    if category in {"no_change", "negated_alert", "unrelated_route"}:
        return {"status": "ready", "changes": []}
    if category in {"added_weeks", "added_days", "added_fortnights", "revised_total",
                    "correction", "superseded_window", "multiple_windows"}:
        changes = [_change(p["start"], p["end"], p["delta"])]
        if category == "multiple_windows":
            changes.append(_change(p["second_start"], p["second_end"], p["second_delta"]))
        return {"status": "ready", "changes": changes}
    return {"status": "needs_clarification", "changes": []}


def _split_records(seed: int, split: str, count: int, context: dict[str, Any],
                   seen_inputs: set[str]) -> list[dict[str, Any]]:
    split_seed = int.from_bytes(hashlib.sha256(f"{seed}:{split}".encode()).digest()[:8], "big")
    rng = random.Random(split_seed)
    schedule = [CATEGORIES[i % len(CATEGORIES)] for i in range(count)]
    rng.shuffle(schedule)
    counters: Counter[str] = Counter()
    records = []
    for index, category in enumerate(schedule):
        variant = counters[category] % 2
        counters[category] += 1
        for _ in range(10000):
            parameters = _parameters(rng, context, category)
            text = _TEMPLATES[split][category][variant].format(**parameters)
            model_input = {"text": text, "context": copy.deepcopy(context)}
            input_digest = sha256(model_input)
            if input_digest not in seen_inputs:
                seen_inputs.add(input_digest)
                break
        else:
            raise ValueError("Requested size exceeds distinct inputs available from the template families")
        opaque = hashlib.sha256(f"{seed}:{split}:{index}:event".encode()).hexdigest()[:20]
        records.append({
            "id": f"notice_{opaque}", "event_id": f"event_{opaque}",
            "template_family_id": f"{split}.{category}.rendering{variant + 1}",
            "category": category, "synthetic": True,
            "model_input": model_input, "reference": _reference(category, parameters),
            "annotation": {"reason": category, "parameters": parameters,
                           "rendering_variant": variant, "origin": "programmatically_constructed_synthetic_event"},
        })
    return records


def generate_dataset(seed: int = 20261030, dev_count: int = 120, test_count: int = 400,
                     context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate grouped synthetic development/test records and integrity metadata."""
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if any(type(n) is not int or n <= 0 for n in (dev_count, test_count)):
        raise ValueError("Split counts must be positive integers")
    context = copy.deepcopy(default_context() if context is None else context)
    _check_context(context)
    seen_inputs: set[str] = set()
    splits = {
        "development": _split_records(seed, "development", dev_count, context, seen_inputs),
        "test": _split_records(seed, "test", test_count, context, seen_inputs),
    }
    dataset = {
        "schema_version": SCHEMA_VERSION, "scope": "ASML-inspired NL_ocean announced-delay extraction",
        "synthetic": True, "seed": seed, "route_catalog": copy.deepcopy(context["routes"]),
        "splits": splits,
    }
    dataset["manifest"] = _manifest(dataset)
    validate_dataset(dataset)
    return dataset


def _manifest(dataset: dict[str, Any]) -> dict[str, Any]:
    splits = dataset["splits"]
    payload = {key: value for key, value in dataset.items() if key != "manifest"}
    return {
        "dataset_sha256": sha256(payload),
        "split_record_sha256": {name: sha256(rows) for name, rows in splits.items()},
        "split_input_sha256": {name: sha256([r["model_input"] for r in rows]) for name, rows in splits.items()},
        "split_counts": {name: len(rows) for name, rows in splits.items()},
        "event_counts": {name: len({r["event_id"] for r in rows}) for name, rows in splits.items()},
        "template_family_counts": {name: len({r["template_family_id"] for r in rows}) for name, rows in splits.items()},
        "category_counts": {name: dict(sorted(Counter(r["category"] for r in rows).items())) for name, rows in splits.items()},
        "status_counts": {name: dict(sorted(Counter(r["reference"]["status"] for r in rows).items())) for name, rows in splits.items()},
        "model_payload_fields": ["text", "context"],
        "grouping": "Generated event IDs and rendering-family IDs are disjoint across development/test; same-event paraphrases are not split across sets.",
        "independence_limit": "All notices are synthetic template-generated events. Shared templates within a split induce related cases; record counts are not independent real-world event counts. Report event- and family-grouped results.",
        "real_notice_count": 0,
    }


def validate_dataset(dataset: dict[str, Any]) -> None:
    """Reject label leakage, overlapping groups, malformed updates, or tampering."""
    if dataset.get("schema_version") != SCHEMA_VERSION or dataset.get("synthetic") is not True:
        raise ValueError("Unexpected schema or missing synthetic declaration")
    if set(dataset.get("splits", {})) != {"development", "test"}:
        raise ValueError("Expected development and test splits")
    id_sets: dict[str, set[str]] = {}; event_sets: dict[str, set[str]] = {}
    family_sets: dict[str, set[str]] = {}; input_sets: dict[str, set[str]] = {}
    for split, records in dataset["splits"].items():
        if not isinstance(records, list) or not records:
            raise ValueError("Each split must be a nonempty record list")
        ids: set[str] = set(); events: set[str] = set(); families: set[str] = set(); inputs: set[str] = set()
        for record in records:
            if record.get("synthetic") is not True or record.get("category") not in CATEGORIES:
                raise ValueError("Unmarked or unsupported synthetic record")
            model_input = record.get("model_input", {})
            if set(model_input) != {"text", "context"} or not isinstance(model_input["text"], str):
                raise ValueError("Inference payload must contain only text and context")
            context = model_input["context"]; _check_context(context)
            if any(key in context for key in ("reference", "label", "expected", "category", "annotation", "event_id", "template_family_id")):
                raise ValueError("Reference/generator metadata leaked into model context")
            for field, values in (("id", ids), ("event_id", events)):
                value = record.get(field)
                if not isinstance(value, str) or not value or value in values:
                    raise ValueError("Duplicate or invalid record/event identifier")
                values.add(value)
            family = record.get("template_family_id")
            if not isinstance(family, str) or not family.startswith(split + "."):
                raise ValueError("Rendering family assigned to wrong split")
            families.add(family)
            digest = sha256(model_input)
            if digest in inputs:
                raise ValueError("Duplicate inference payload within split")
            inputs.add(digest)
            reference = record.get("reference", {})
            if set(reference) != {"status", "changes"} or reference["status"] not in {"ready", "needs_clarification"} or not isinstance(reference["changes"], list):
                raise ValueError("Malformed reference extraction")
            if reference["status"] == "needs_clarification" and reference["changes"]:
                raise ValueError("Clarification references cannot apply changes")
            for change in reference["changes"]:
                if set(change) != {"op", "route", "start_week", "end_week", "value"} or change["op"] != "add_lead" or change["route"] != SCOPE_ROUTE:
                    raise ValueError("Invalid scoped operation")
                start, end, value = change["start_week"], change["end_week"], change["value"]
                if any(type(x) is not int for x in (start, end, value)) or not 1 <= start <= end <= context["horizon"] or value <= 0:
                    raise ValueError("Invalid integer-week operation")
            annotation = record.get("annotation", {})
            variant = annotation.get("rendering_variant")
            if type(variant) is not int or variant not in (0, 1):
                raise ValueError("Invalid rendering variant")
            parameters = annotation["parameters"]
            expected_text = _TEMPLATES[split][record["category"]][variant].format(**parameters)
            if expected_text != model_input["text"] or reference != _reference(record["category"], parameters):
                raise ValueError("Text/reference differs from declared synthetic event")
        id_sets[split], event_sets[split], family_sets[split], input_sets[split] = ids, events, families, inputs
    for groups in (id_sets, event_sets, family_sets, input_sets):
        if groups["development"] & groups["test"]:
            raise ValueError("Development/test overlap")
    if dataset.get("manifest") != _manifest(dataset):
        raise ValueError("Dataset manifest or SHA-256 mismatch")


def write_dataset(output_dir: str | Path, seed: int = 20261030, dev_count: int = 120,
                  test_count: int = 400, context: dict[str, Any] | None = None) -> dict[str, str]:
    """Write complete records and a manifest; do not create a fake real-data set."""
    dataset = generate_dataset(seed, dev_count, test_count, context)
    output = Path(output_dir); output.mkdir(parents=True, exist_ok=True)
    dataset_path = output / "dataset.json"
    dataset_path.write_bytes(canonical_bytes(dataset) + b"\n")
    paths = {"dataset": str(dataset_path)}
    file_hashes = {"dataset.json": hashlib.sha256(dataset_path.read_bytes()).hexdigest()}
    for split, rows in dataset["splits"].items():
        path = output / f"{split}.jsonl"
        path.write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in rows))
        paths[split] = str(path)
        file_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path = output / "manifest.json"
    write_manifest = {**dataset["manifest"], "schema_version": SCHEMA_VERSION,
                      "synthetic": True, "seed": seed, "file_sha256": file_hashes}
    manifest_path.write_bytes(canonical_bytes(write_manifest) + b"\n")
    paths["manifest"] = str(manifest_path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--development", type=int, default=120)
    parser.add_argument("--test", type=int, default=400)
    args = parser.parse_args()
    paths = write_dataset(args.output, args.seed, args.development, args.test)
    print(json.dumps({"synthetic": True, "paths": paths}, ensure_ascii=False))


if __name__ == "__main__":
    main()
