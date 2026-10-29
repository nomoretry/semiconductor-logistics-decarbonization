"""Real-corpus contract tests; synthetic fixtures and injected transport only."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from notice_benchmark import api_runner as runner
from notice_benchmark.data import default_context
from real_notice_eval.api import api_input_dataset, score_api_run
from real_notice_eval.data import (ANNOTATION_STATUS, canonical_bytes, digest,
                                   load_dataset, normalized_output, strict_json,
                                   validate_dataset)
from real_notice_eval.evaluation import evaluate_offline, score_predictions


def fixture():
    """Test-only declared provenance; these are not real notice observations."""
    sources, cases = [], []
    for index in range(2):
        text = f"Test fixture {index}: vessels may experience delays."
        source = {"source_id": f"S{index}", "url": f"https://example.com/fixture-{index}",
                  "publisher": "Synthetic test fixture", "title": f"Fixture {index}",
                  "published_date": None, "accessed_date": "2026-10-29",
                  "source_type": "official_notice", "event_group_id": f"E{index}",
                  "correlation_group_id": f"G{index}", "text": text,
                  "sha256": digest(text.encode()), "text_kind": "verbatim_excerpt",
                  "full_notice_reviewed": True, "full_text_redistributed": False,
                  "review_method": "Unit-test declaration only", "body_lines_reviewed": "1-2",
                  "evidence_location": "Test fixture", "web_reference_ids": [f"fixture{index}"]}
        sources.append(source)
        cases.append({"id": f"C{index}", "source_id": source["source_id"],
                      "event_group_id": source["event_group_id"],
                      "correlation_group_id": source["correlation_group_id"],
                      "excerpt_sha256": source["sha256"],
                      "model_input": {"text": text, "context": default_context()},
                      "reference": {"status": "needs_clarification", "changes": []},
                      "annotation": {"status": ANNOTATION_STATUS, "rationale": "No mapped route or dispatch interval.",
                                     "missing_information": ["route", "dispatch interval"]}})
    return {"schema_version": "real-notice-eval-v1", "synthetic": False,
            "annotation_status": ANNOTATION_STATUS, "sources": sources,
            "splits": {"test": cases}, "excluded_sources": [
                {"url": "https://example.com/excluded", "reason": "Synthetic exclusion test."}]}


def response(text=None):
    return {"id": "resp_mock_real_eval", "model": runner.DEFAULT_MODEL,
            "status": "completed", "error": None,
            "usage": {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60},
            "output": [{"type": "message", "content": [{"type": "output_text", "text":
                json.dumps({"status": "needs_clarification", "changes": []}) if text is None else text}]}]}


class RealNoticeEvalTests(unittest.TestCase):
    def setUp(self):
        self.dataset = fixture()

    def test_single_exploratory_split_unknown_publication_and_exclusions_are_explicit(self):
        validate_dataset(self.dataset)
        self.dataset["splits"]["development"] = []
        report = evaluate_offline(self.dataset)
        self.assertEqual(report["api_calls"], 0)
        self.assertFalse(report["human_annotated_ground_truth"])
        self.assertFalse(report["corpus"]["held_out_evaluation"])
        self.assertEqual(report["corpus"]["excluded_source_count"], 1)
        self.assertEqual(report["methods"]["always_clarify"]["exact_reference_match_rate"], 1)
        self.assertEqual(report["methods"]["always_noop"]["exact_reference_match_rate"], 0)
        self.assertIsNone(report["methods"]["rules_frozen_v1"]["class_results"]
                          ["ready_update"]["exact_reference_match_rate"])

    def test_duplicate_keys_and_nonfinite_numbers_rejected(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                strict_json(text)

    def test_source_integrity_leakage_and_unestablished_human_review_rejected(self):
        mutations = [
            lambda data: data["sources"][0].update(text="Edited excerpt"),
            lambda data: data["sources"][1].update(url=data["sources"][0]["url"] + "#part"),
            lambda data: data["splits"]["test"][0]["model_input"].update(reference="leak"),
            lambda data: data["splits"]["test"][0]["model_input"]["context"].update(horizon=17),
            lambda data: data["splits"]["test"][0].update(correlation_group_id="wrong"),
            lambda data: data.update(human_reviewed=True),
            lambda data: data["sources"][0].update(full_notice_reviewed=False),
            lambda data: data["excluded_sources"][0].update(reason=""),
        ]
        for mutate in mutations:
            altered = deepcopy(self.dataset)
            mutate(altered)
            with self.subTest(mutation=mutate), self.assertRaises((ValueError, runner.RunnerError)):
                validate_dataset(altered)

    def test_event_and_correlation_groups_may_repeat_within_split_but_never_cross(self):
        for key in ("event_group_id", "correlation_group_id"):
            changed = deepcopy(self.dataset)
            changed["sources"][1][key] = changed["sources"][0][key]
            changed["splits"]["test"][1][key] = changed["sources"][0][key]
            validate_dataset(changed)
            changed["splits"]["development"] = [changed["splits"]["test"].pop()]
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "cross_split_"):
                validate_dataset(changed)

    def test_scoped_integer_week_schema_and_duplicate_changes_are_strict(self):
        model_input = self.dataset["splits"]["test"][0]["model_input"]
        change = {"op": "add_lead", "route": "NL_ocean", "start_week": 1, "end_week": 2, "value": 1}
        normalized_output({"status": "ready", "changes": [change]}, model_input)
        outputs = [
            {"status": "ready", "changes": [change, change]},
            {"status": "ready", "changes": [{**change, "value": 1.0}]},
            {"status": "ready", "changes": [{**change, "value": True}]},
            {"status": "ready", "changes": [{**change, "end_week": 17}]},
            {"status": "ready", "changes": [{**change, "route": "NL_air"}]},
            '{"status":"ready","status":"needs_clarification","changes":[]}',
        ]
        for output in outputs:
            with self.subTest(output=output), self.assertRaises(ValueError):
                normalized_output(output, model_input)

    def test_missing_invalid_and_unsupported_ready_calls_keep_denominator(self):
        cases = self.dataset["splits"]["test"]
        score = score_predictions(cases, {"C0": {"status": "ready", "changes": []}})
        self.assertEqual(score["number_calls"], 2)
        self.assertEqual(score["missing_cases"], 1)
        self.assertEqual(score["unsupported_ready_calls"], 1)
        self.assertEqual(score["exact_reference_match_rate"], 0)
        with self.assertRaises(ValueError):
            score_predictions(cases, {"unknown": {"status": "ready", "changes": []}})

    def test_large_json_integer_schema_does_not_overflow_float_conversion(self):
        output = {"status": "ready", "changes": [
            {"op": "add_lead", "route": "NL_ocean", "start_week": 1, "end_week": 2, "value": 10 ** 500}]}
        score = score_predictions(self.dataset["splits"]["test"], {"C0": output})
        self.assertEqual(score["number_calls"], 2)
        self.assertEqual(score["exact_reference_match_rate"], 0)
        self.assertTrue(score["per_case"][0]["calls"][0]["schema_valid"])

    def _files(self, directory):
        exported = Path(directory) / "input_dataset.json"
        exported.write_bytes(canonical_bytes(api_input_dataset(self.dataset)) + b"\n")
        return exported, Path(directory) / "run"

    def test_export_and_frozen_default_dry_run_never_resolve_key_or_transport(self):
        projected = api_input_dataset(self.dataset)
        self.assertIs(projected["synthetic"], False)
        self.assertEqual(set(projected["splits"]["test"][0]), {"id", "model_input"})
        with tempfile.TemporaryDirectory() as directory:
            exported, run = self._files(directory)
            with patch.object(runner, "_load_api_key", side_effect=AssertionError("credential read")):
                result = runner.run_benchmark(exported, run, transport=lambda *args: self.fail("transport called"))
                report = score_api_run(self.dataset, exported, run)
            self.assertEqual(result["executed_requests"], 0)
            self.assertEqual(report["status"], "no_run_artifacts")
            self.assertIsNone(report["reference_agreement_completed_outputs"])

    def test_partial_mock_ledger_uses_planned_denominator_and_rejects_tampering(self):
        count = 0
        def transport(*args):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError("test-only transport failure")
            return response()
        with tempfile.TemporaryDirectory() as directory:
            exported, run = self._files(directory)
            runner.run_benchmark(exported, run, execute=True, repeats=2, max_usd="1",
                                 api_key="sk-proj-" + "TEST_ONLY_" * 8, transport=transport)
            report = score_api_run(self.dataset, exported, run)
            self.assertEqual(report["status"], "partial_mock_evaluation")
            self.assertFalse(report["live_api_evidence"])
            self.assertEqual(report["counts"]["requested_calls"], 4)
            self.assertEqual(report["counts"]["unattempted_calls"], 2)
            self.assertEqual(report["reference_agreement_completed_outputs"]["exact_reference_match_rate"], 1)
            self.assertEqual(report["reference_agreement_all_planned_outputs"]["exact_reference_match_rate"], .25)
            ledger = run / "records.jsonl"
            ledger.write_bytes(ledger.read_bytes().splitlines()[0] + b"\n")
            with self.assertRaises((ValueError, runner.RunnerError)):
                score_api_run(self.dataset, exported, run)

    def test_raw_provider_duplicate_keys_fail_new_schema_even_when_frozen_parser_accepts(self):
        with tempfile.TemporaryDirectory() as directory:
            exported, run = self._files(directory)
            duplicate = '{"status":"ready","status":"needs_clarification","changes":[]}'
            runner.run_benchmark(exported, run, execute=True, max_usd="1", max_calls=1,
                                 api_key="sk-proj-" + "TEST_ONLY_" * 8,
                                 transport=lambda *args: response(duplicate))
            report = score_api_run(self.dataset, exported, run)
            score = report["reference_agreement_completed_outputs"]
            self.assertEqual(score["schema_validity_rate"], 0)
            self.assertEqual(score["exact_reference_match_rate"], 0)

    def test_archived_prompt_and_schema_must_match_frozen_request_contract(self):
        for name in ("prompt.txt", "schema.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                exported, run = self._files(directory)
                runner.run_benchmark(exported, run, execute=True, max_usd="1", max_calls=1,
                                     api_key="sk-proj-" + "TEST_ONLY_" * 8,
                                     transport=lambda *args: response())
                (run / name).write_text("tampered")
                with self.assertRaisesRegex(ValueError, "archived_"):
                    score_api_run(self.dataset, exported, run)

    def test_provider_message_with_null_content_is_skipped_as_in_frozen_parser(self):
        mock = response()
        mock["output"].insert(0, {"type": "message", "content": None})
        with tempfile.TemporaryDirectory() as directory:
            exported, run = self._files(directory)
            runner.run_benchmark(exported, run, execute=True, max_usd="1", max_calls=1,
                                 api_key="sk-proj-" + "TEST_ONLY_" * 8,
                                 transport=lambda *args: mock)
            report = score_api_run(self.dataset, exported, run)
            self.assertEqual(report["reference_agreement_completed_outputs"]["exact_reference_match_rate"], 1)

    def test_shipped_real_corpus_matches_loader_contract(self):
        path = Path(__file__).resolve().parents[1] / "benchmarks/real_notices_v1/dataset.json"
        data = load_dataset(path)
        self.assertFalse(data["synthetic"])
        self.assertTrue(data["splits"]["test"])


if __name__ == "__main__":
    unittest.main()
