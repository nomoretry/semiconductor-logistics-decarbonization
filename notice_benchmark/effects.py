"""Secondary semantic scoring of announced lead-time updates.

Strict structured exact-match remains a separate metric.  This comparator
instead expands valid ``add_lead`` changes into the route/week increments used
by the planner: adjacent intervals may be merged, and overlapping intervals
add.  It never imports a generator, extractor, or reference-label registry.

Matching clarification decisions are reported explicitly as *no action*, not
as successful executable plans.  Invalid/uncomparable predictions remain
failures when computing any unconditional match rate; filtering them out would
inflate that rate.  Report ready-update matches and clarification matches
separately.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from notice_benchmark.metrics import normalize_output


def _business_context(context: Any) -> tuple[int, set[str]]:
    if not isinstance(context, Mapping):
        raise ValueError("context_must_be_mapping")
    horizon = context.get("horizon")
    if type(horizon) is not int or horizon <= 0:
        raise ValueError("invalid_horizon")
    routes = context.get("routes")
    if not isinstance(routes, list) or not routes:
        raise ValueError("missing_route_catalog")
    names: set[str] = set()
    for route in routes:
        if not isinstance(route, Mapping):
            raise ValueError("invalid_route_catalog_entry")
        name = route.get("name")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("invalid_or_duplicate_route_name")
        names.add(name)
    return horizon, names


def _increments(output: dict[str, Any], horizon: int,
                route_names: set[str]) -> dict[tuple[str, int], int]:
    increments: dict[tuple[str, int], int] = {}
    for change in output["changes"]:
        route = change["route"]
        if route not in route_names:
            raise ValueError("unknown_route")
        start, end = change["start_week"], change["end_week"]
        if not 1 <= start <= end <= horizon:
            raise ValueError("out_of_horizon_window")
        value = change["value"]
        # normalize_output already rejects booleans, negative/nonfinite values,
        # and unsupported operations.  The compiler additionally requires an
        # integral number of planning weeks (2.0 is valid; 1.5 is not).
        if int(value) != value:
            raise ValueError("lead_increment_not_whole_weeks")
        amount = int(value)
        if amount == 0:
            # Validation above still applies to zero-valued updates.  An
            # unknown route or out-of-range zero change must not be hidden.
            continue
        for week in range(start, end + 1):
            key = (route, week)
            increments[key] = increments.get(key, 0) + amount
    return increments


def compare_effect(reference: Any, prediction: Any,
                   context: Mapping[str, Any]) -> dict[str, Any]:
    """Compare schema-valid outputs by their compiled route/week effects.

    ``comparable`` means that both schemas and both business updates can be
    validated in the supplied context.  A valid status mismatch is comparable
    but never matches, including ``ready:[]`` versus ``needs_clarification:[]``.
    Bad references are explicit errors in the returned reason, not repaired or
    inferred; callers should stop an evaluation if reference validation fails.
    """
    result: dict[str, Any] = {
        "reference_status": None,
        "predicted_status": None,
        "comparable": False,
        "effect_match": False,
        "reason": None,
    }
    try:
        expected = normalize_output(reference)
        result["reference_status"] = expected["status"]
    except (TypeError, ValueError) as exc:
        result["reason"] = f"reference_schema_invalid:{exc}"
        return result
    try:
        observed = normalize_output(prediction)
        result["predicted_status"] = observed["status"]
    except (TypeError, ValueError) as exc:
        result["reason"] = f"prediction_schema_invalid:{exc}"
        return result
    try:
        horizon, route_names = _business_context(context)
    except (TypeError, ValueError) as exc:
        result["reason"] = f"context_invalid:{exc}"
        return result
    try:
        expected_effect = _increments(expected, horizon, route_names)
    except (TypeError, ValueError, OverflowError) as exc:
        result["reason"] = f"reference_business_invalid:{exc}"
        return result
    try:
        observed_effect = _increments(observed, horizon, route_names)
    except (TypeError, ValueError, OverflowError) as exc:
        result["reason"] = f"prediction_business_invalid:{exc}"
        return result

    result["comparable"] = True
    if expected["status"] != observed["status"]:
        result["reason"] = "status_mismatch"
        return result
    if expected["status"] == "needs_clarification":
        result["effect_match"] = True
        result["reason"] = "both_require_clarification_no_action"
        return result
    result["effect_match"] = expected_effect == observed_effect
    result["reason"] = (
        "identical_route_week_lead_increments" if result["effect_match"]
        else "different_route_week_lead_increments"
    )
    return result
