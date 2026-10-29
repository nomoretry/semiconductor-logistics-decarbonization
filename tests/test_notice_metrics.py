"""Tests of scoring semantics and independent sampling units."""

import copy
import unittest

from notice_benchmark.metrics import (
    normalize_output, paired_cluster_bootstrap, public_case_metadata,
    score_predictions, wilson_interval,
)


def ready(route="NL_ocean", start=5, end=9, value=2):
    return {"status": "ready", "changes": [{
        "op": "add_lead", "route": route, "start_week": start,
        "end_week": end, "value": value,
    }]}


def clarify():
    return {"status": "needs_clarification", "changes": []}


def case(identity="a", event=None, reference=None):
    return {
        "id": identity, "event_id": event or identity, "synthetic": True,
        "model_input": {"text": "A synthetic notice", "context": {}},
        "reference": ready() if reference is None else reference,
    }


class NoticeSchemaTests(unittest.TestCase):
    def test_change_order_is_semantic_but_extra_keys_are_not_discarded(self):
        first = ready()
        second = ready(start=11, end=12, value=1)["changes"][0]
        first["changes"].append(second)
        reverse = copy.deepcopy(first)
        reverse["changes"].reverse()
        self.assertEqual(normalize_output(first), normalize_output(reverse))
        extra = copy.deepcopy(first)
        extra["made_up"] = 1
        with self.assertRaises(ValueError):
            normalize_output(extra)
        extra = ready()
        extra["changes"][0]["units"] = "weeks"
        with self.assertRaises(ValueError):
            normalize_output(extra)

    def test_booleans_and_nonfinite_values_are_not_numbers(self):
        for field in ("start_week", "end_week", "value"):
            output = ready()
            output["changes"][0][field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                normalize_output(output)
        for value in (float("nan"), float("inf"), -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_output(ready(value=value))

    def test_duplicate_json_keys_and_changes_fail_closed(self):
        with self.assertRaises(ValueError):
            normalize_output('{"status":"ready","status":"needs_clarification","changes":[]}')
        output = ready()
        output["changes"].append(copy.deepcopy(output["changes"][0]))
        with self.assertRaises(ValueError):
            normalize_output(output)

    def test_clarification_cannot_mutate_and_unknown_operation_rejected(self):
        output = ready()
        output["status"] = "needs_clarification"
        with self.assertRaises(ValueError):
            normalize_output(output)
        output = ready()
        output["changes"][0]["op"] = "set_capacity"
        with self.assertRaises(ValueError):
            normalize_output(output)


class NoticeScoreTests(unittest.TestCase):
    def test_all_refusal_does_not_hide_failure_to_process_complete_notices(self):
        cases = [case("ready"), case("missing", reference=clarify())]
        report = score_predictions(cases, {"ready": clarify(), "missing": clarify()})
        summary = report["summary"]
        self.assertEqual(summary["exact_match_rate"], 0.5)
        self.assertEqual(summary["correct_ready_coverage"], 0)
        self.assertEqual(summary["ready_coverage"], 0)
        self.assertEqual(summary["clarification_recall"], 1)
        self.assertIsNone(summary["ready_precision"])

    def test_route_window_and_unit_errors_remain_visible(self):
        for field, replacement in (("route", "NL_air"), ("start_week", 6), ("value", 14)):
            predicted = ready()
            predicted["changes"][0][field] = replacement
            report = score_predictions([case()], {"a": predicted})
            with self.subTest(field=field):
                self.assertEqual(report["summary"]["exact_match_rate"], 0)
                self.assertEqual(report["summary"]["field_accuracy"][field]["rate"], 0)
                self.assertEqual(report["summary"]["schema_validity_rate"], 1)

    def test_invalid_json_is_not_an_abstention(self):
        report = score_predictions([case(reference=clarify())], {"a": "not json"})
        summary = report["summary"]
        self.assertEqual(summary["json_validity_rate"], 0)
        self.assertEqual(summary["clarification_recall"], 0)
        self.assertEqual(summary["exact_match_rate"], 0)

    def test_missing_case_is_failure_and_unknown_or_duplicate_predictions_error(self):
        report = score_predictions([case("a"), case("b")], {"a": ready()})
        self.assertEqual(report["counts"]["missing_cases"], 1)
        self.assertEqual(report["summary"]["exact_match_rate"], 0.5)
        with self.assertRaises(ValueError):
            score_predictions([case()], {"unknown": ready()})
        with self.assertRaises(ValueError):
            score_predictions([case()], [
                {"case_id": "a", "repeat_id": 0, "output": ready()},
                {"case_id": "a", "repeat_id": "0", "output": ready()},
            ])

    def test_repeated_calls_do_not_inflate_independent_event_count(self):
        cases = [case("a", "event"), case("b", "event")]
        calls = [
            {"case_id": identity, "repeat_id": repeat, "output": ready()}
            for identity in ("a", "b") for repeat in range(3)
        ]
        report = score_predictions(cases, calls)
        self.assertEqual(report["counts"]["number_calls"], 6)
        self.assertEqual(report["counts"]["number_cases"], 2)
        self.assertEqual(report["counts"]["number_events"], 1)
        self.assertEqual(report["summary"]["event_all_correct"]["total"], 1)
        self.assertEqual(report["summary"]["event_all_correct"]["wilson95"], wilson_interval(1, 1))
        self.assertEqual(report["summary"]["repeat_consistency"]["rate"], 1)

    def test_unsupported_ready_is_counted_even_when_it_is_schema_invalid(self):
        output = ready()
        output["unexpected"] = True
        report = score_predictions([case(reference=clarify())], {"a": output})
        self.assertEqual(report["summary"]["schema_validity_rate"], 0)
        self.assertEqual(report["summary"]["unsupported_ready_on_missing_information_rate"], 1)

    def test_metadata_export_never_copies_raw_input_or_auth_fields(self):
        original = case()
        original.update({"source_id": "source-1", "api_key": "secret", "source_url": "https://example.com/?token=secret"})
        metadata = public_case_metadata(original)
        self.assertEqual(metadata["source_id"], "source-1")
        self.assertNotIn("model_input", metadata)
        self.assertNotIn("reference", metadata)
        self.assertNotIn("api_key", metadata)
        self.assertNotIn("source_url", metadata)


class NoticeStatisticsTests(unittest.TestCase):
    def test_wilson_interval_does_not_treat_small_perfect_sample_as_certainty(self):
        low, high = wilson_interval(40, 40)
        self.assertAlmostEqual(low, 0.9123783988)
        self.assertAlmostEqual(high, 1)
        self.assertIsNone(wilson_interval(0, 0))
        for args in [(True, 1), (2, 1), (-1, 2), (1, -1)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                wilson_interval(*args)

    def test_paired_bootstrap_is_deterministic_and_retains_all_failures(self):
        cases = [case("a", "event1"), case("b", "event1"), case("c", "event2")]
        left = score_predictions(cases, {"a": ready(), "b": ready(), "c": clarify()})
        right = score_predictions(cases, {"a": clarify(), "b": clarify(), "c": clarify()})
        result = paired_cluster_bootstrap(left, right, seed=17, samples=300)
        self.assertEqual(result, paired_cluster_bootstrap(left, right, seed=17, samples=300))
        self.assertAlmostEqual(result["difference"], 2 / 3)
        self.assertEqual(result["number_event_clusters"], 2)
        self.assertEqual(result["paired_calls"], 3)
        self.assertEqual(result["interval"], [0, 1])

    def test_identical_systems_have_zero_paired_difference(self):
        cases = [case("a"), case("b")]
        report = score_predictions(cases, {"a": ready(), "b": clarify()})
        result = paired_cluster_bootstrap(report, report, samples=30)
        self.assertEqual(result["difference"], 0)
        self.assertEqual(result["interval"], [0, 0])

    def test_pairing_requires_identical_cases_inputs_and_repeat_ids(self):
        cases = [case("a"), case("b")]
        left = score_predictions(cases, {"a": ready(), "b": ready()})
        short = score_predictions(cases[:1], {"a": ready()})
        with self.assertRaises(ValueError):
            paired_cluster_bootstrap(left, short)
        edited_cases = copy.deepcopy(cases)
        edited_cases[0]["model_input"]["text"] = "Changed task"
        edited = score_predictions(edited_cases, {"a": ready(), "b": ready()})
        with self.assertRaises(ValueError):
            paired_cluster_bootstrap(left, edited)
        repeated = score_predictions(cases, [
            {"case_id": "a", "repeat_id": 1, "output": ready()},
            {"case_id": "b", "repeat_id": 1, "output": ready()},
        ])
        with self.assertRaises(ValueError):
            paired_cluster_bootstrap(left, repeated)


if __name__ == "__main__":
    unittest.main()
