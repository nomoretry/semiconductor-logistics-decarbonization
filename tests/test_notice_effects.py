"""Independent semantic-effect fixtures; no benchmark/test labels imported."""

import copy
import unittest

from notice_benchmark.effects import compare_effect
from notice_benchmark.metrics import normalize_output


CONTEXT = {
    "horizon": 16,
    "routes": [{"name": "NL_ocean", "lead": 5}, {"name": "NL_air", "lead": 1}],
}


def change(start=3, end=6, value=2, route="NL_ocean"):
    return {"op": "add_lead", "route": route, "start_week": start,
            "end_week": end, "value": value}


def ready(*changes):
    return {"status": "ready", "changes": list(changes)}


def clarify():
    return {"status": "needs_clarification", "changes": []}


class NoticeEffectTests(unittest.TestCase):
    def assert_matches(self, reference, prediction):
        result = compare_effect(reference, prediction, CONTEXT)
        self.assertTrue(result["comparable"], result)
        self.assertTrue(result["effect_match"], result)
        return result

    def test_adjacent_same_increment_intervals_can_be_split_or_merged(self):
        merged = ready(change(3, 6, 2))
        split = ready(change(3, 4, 2), change(5, 6, 2))
        self.assertNotEqual(normalize_output(merged), normalize_output(split))
        self.assert_matches(merged, split)
        self.assert_matches(split, merged)

    def test_overlapping_changes_add_instead_of_replacing(self):
        overlapped = ready(change(3, 5, 2), change(5, 7, 3))
        expanded = ready(change(3, 4, 2), change(5, 5, 5), change(6, 7, 3))
        self.assert_matches(overlapped, expanded)
        wrong_replacement = ready(change(3, 4, 2), change(5, 7, 3))
        result = compare_effect(overlapped, wrong_replacement, CONTEXT)
        self.assertTrue(result["comparable"])
        self.assertFalse(result["effect_match"])

    def test_zero_additions_are_validated_then_treated_as_noops(self):
        self.assert_matches(ready(), ready(change(1, 16, 0)))
        self.assert_matches(ready(), ready(change(1, 16, 0.0, "NL_air")))
        for invalid_zero in (change(1, 16, 0, "unknown"), change(1, 17, 0)):
            result = compare_effect(ready(), ready(invalid_zero), CONTEXT)
            self.assertFalse(result["comparable"])
            self.assertFalse(result["effect_match"])

    def test_clarification_is_separate_from_actionable_ready_noop(self):
        result = self.assert_matches(clarify(), clarify())
        self.assertEqual(result["reason"], "both_require_clarification_no_action")
        self.assertEqual(result["reference_status"], "needs_clarification")
        for reference, prediction in ((clarify(), ready()), (ready(), clarify())):
            result = compare_effect(reference, prediction, CONTEXT)
            self.assertTrue(result["comparable"])
            self.assertFalse(result["effect_match"])
            self.assertEqual(result["reason"], "status_mismatch")

    def test_change_order_whole_week_float_and_json_string_are_equivalent(self):
        reference = ready(change(2, 3, 2), change(7, 9, 1))
        prediction = ready(change(7, 9, 1.0), change(2, 3, 2.0))
        self.assert_matches(reference, prediction)
        encoded = '{"status":"ready","changes":[{"op":"add_lead","route":"NL_ocean","start_week":3,"end_week":6,"value":2}]}'
        self.assert_matches(ready(change()), encoded)

    def test_wrong_units_are_not_converted_or_silently_rounded(self):
        result = compare_effect(ready(change(value=2)), ready(change(value=14)), CONTEXT)
        self.assertTrue(result["comparable"])
        self.assertFalse(result["effect_match"])
        result = compare_effect(ready(change()), ready(change(value=1.5)), CONTEXT)
        self.assertFalse(result["comparable"])
        self.assertIn("not_whole_weeks", result["reason"])

    def test_unknown_route_and_out_of_range_window_fail(self):
        for invalid in (change(route="ZX_ocean"), change(0, 3), change(3, 17)):
            result = compare_effect(ready(change()), ready(invalid), CONTEXT)
            self.assertFalse(result["comparable"])
            self.assertFalse(result["effect_match"])

    def test_known_other_route_is_valid_but_not_equal_to_scoped_change(self):
        result = compare_effect(ready(change()), ready(change(route="NL_air")), CONTEXT)
        self.assertTrue(result["comparable"])
        self.assertFalse(result["effect_match"])

    def test_bool_negative_nonfinite_duplicate_and_unsupported_changes_rejected(self):
        predictions = [ready(change(value=True)), ready(change(value=-1)),
                       ready(change(value=float("nan"))), ready(change(value=float("inf"))),
                       ready(change(), change())]
        bad_week = change(); bad_week["start_week"] = True; predictions.append(ready(bad_week))
        bad_op = change(); bad_op["op"] = "set_capacity"; predictions.append(ready(bad_op))
        for prediction in predictions:
            with self.subTest(prediction=prediction):
                result = compare_effect(ready(change()), prediction, CONTEXT)
                self.assertFalse(result["comparable"])
                self.assertFalse(result["effect_match"])
                self.assertTrue(result["reason"].startswith("prediction_schema_invalid:"))

    def test_invalid_reference_and_context_are_explicit_and_not_repaired(self):
        result = compare_effect(ready(change(route="unknown")), ready(change()), CONTEXT)
        self.assertFalse(result["comparable"])
        self.assertTrue(result["reason"].startswith("reference_business_invalid:"))
        for context in ({}, {"horizon": True, "routes": CONTEXT["routes"]},
                        {"horizon": 16, "routes": [{"name": "NL_ocean"}, {"name": "NL_ocean"}]}):
            result = compare_effect(ready(change()), ready(change()), context)
            self.assertFalse(result["comparable"])
            self.assertTrue(result["reason"].startswith("context_invalid:"))

    def test_inputs_are_not_modified_and_output_has_contract_fields(self):
        reference, prediction = ready(change()), ready(change())
        snapshot = copy.deepcopy((reference, prediction, CONTEXT))
        result = compare_effect(reference, prediction, CONTEXT)
        self.assertEqual((reference, prediction, CONTEXT), snapshot)
        self.assertEqual(set(result), {"reference_status", "predicted_status", "comparable", "effect_match", "reason"})


if __name__ == "__main__":
    unittest.main()
