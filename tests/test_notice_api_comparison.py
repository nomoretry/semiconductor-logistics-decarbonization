"""Offline paired-coverage and archival-integrity checks; no live requests."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from notice_benchmark import api_runner as runner
from notice_benchmark.data import write_dataset
from notice_benchmark.metrics import score_predictions
from notice_benchmark.run_offline import freeze_rules
from notice_benchmark.rules import extract_notice
from scripts.compare_notice_api import compare_runs, EVIDENCE_FILES, _paired_intervals
from scripts.score_notice_api import score_run


FAKE_KEY = "sk-proj-" + "TEST_ONLY_" * 8


def load(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_bytes(runner.canonical_bytes(value) + b"\n")


class ApiComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.template.cleanup)
        root = Path(cls.template.name)
        write_dataset(root / "data", seed=4481, dev_count=36, test_count=36)
        dataset = root / "data/dataset.json"
        freeze_rules(dataset, root / "data/rules_freeze.json")
        references = {case["model_input"]["text"]: case["reference"]
            for case in load(dataset)["splits"]["test"]}

        def transport(body, key, timeout):
            model_input = json.loads(body["input"][1]["content"][0]["text"])
            return {"id": "resp_offline_comparison", "model": "gpt-6-luna",
                "status": "completed", "error": None,
                "usage": {"input_tokens": 150, "output_tokens": 40, "total_tokens": 190},
                "output": [{"type": "message", "content": [{"type": "output_text",
                    "text": json.dumps(references[model_input["text"]])}]}]}
        for name, calls in (("primary", 36), ("repeat", 36), ("subset", 35)):
            directory = root / name
            runner.run_benchmark(dataset, directory, split="test", max_calls=calls, max_usd="1")
            runner.run_benchmark(dataset, directory, split="test", execute=True,
                max_calls=calls, max_usd="1", api_key=FAKE_KEY, transport=transport)
            score_run(dataset, directory)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "bundle"
        shutil.copytree(self.template.name, self.root)
        self.dataset = self.root / "data/dataset.json"
        self.freeze = self.root / "data/rules_freeze.json"
        self.primary = self.root / "primary"
        self.repeat = self.root / "repeat"

    def compare(self, **kwargs):
        options = {"samples": 80, "seed": 4481}
        options.update(kwargs)
        with patch.object(runner, "_load_api_key", side_effect=AssertionError("credential read")), \
                patch.object(runner, "_default_transport", side_effect=AssertionError("network called")):
            return compare_runs(self.dataset, self.freeze, self.primary, **options)

    def test_complete_pairing_replays_rules_on_identical_inputs_without_changing_evidence(self):
        before = {name: (self.primary / name).read_bytes() for name in EVIDENCE_FILES}
        report = self.compare()
        cases = load(self.dataset)["splits"]["test"]
        rule_exact = sum(extract_notice(**case["model_input"]) == case["reference"] for case in cases)
        self.assertEqual(report["distinct_cases"], 36)
        self.assertEqual(report["primary"]["scoring_summary"]["exact_matches"], 36)
        self.assertEqual(report["rules"]["summary"]["exact_matches"], rule_exact)
        self.assertEqual(report["paired"]["api_only_correct"], 36 - rule_exact)
        self.assertEqual(report["paired"]["rules_only_correct"], 0)
        self.assertEqual(sum(row["cases"] for row in report["paired"]["by_category"].values()), 36)
        intervals = report["paired"]["confidence_intervals"]
        self.assertEqual(intervals["event"]["number_cases"], 36)
        self.assertEqual(intervals["event"]["paired_calls"], 36)
        self.assertEqual(intervals["render_family"]["number_render_family_clusters"], 36)
        self.assertEqual(before, {name: (self.primary / name).read_bytes() for name in EVIDENCE_FILES})
        self.assertEqual(report["api_calls_made_by_comparison"], 0)

    def test_repeat_does_not_pool_or_increase_case_or_cluster_counts(self):
        report = self.compare(repeat_run=self.repeat)
        self.assertEqual(report["total_recorded_calls"], 72)
        self.assertEqual(report["distinct_cases"], 36)
        self.assertEqual(report["event_clusters"], 36)
        self.assertEqual(report["repeat"]["distinct_additional_cases"], 0)
        self.assertEqual(report["repeat"]["identical_parsed_outputs"], 36)
        self.assertEqual(report["paired"]["confidence_intervals"]["event"]["paired_calls"], 36)

    def test_family_resampling_keeps_unequal_clusters_and_the_case_weighted_estimand(self):
        ready = {"status": "ready", "changes": []}
        clarify = {"status": "needs_clarification", "changes": []}
        cases = [{"id": str(index), "event_id": "event-" + str(index),
            "template_family_id": "family-a" if index < 3 else "family-b", "reference": ready}
            for index in range(4)]
        left = score_predictions(cases, {case["id"]: ready for case in cases})
        right = score_predictions(cases, {str(index): clarify if index < 3 else ready for index in range(4)})
        intervals = _paired_intervals(left, right, samples=2000, seed=4481)
        self.assertEqual(intervals["event"]["number_event_clusters"], 4)
        self.assertEqual(intervals["render_family"]["number_render_family_clusters"], 2)
        self.assertEqual(intervals["render_family"]["difference"], 0.75)
        self.assertEqual(intervals["render_family"]["interval"], [0.0, 1.0])
        self.assertGreater(intervals["event"]["interval"][0], 0.0)

    def test_same_directory_or_copied_ledger_is_not_an_independent_repeat(self):
        with self.assertRaisesRegex(ValueError, "repeat_must_be_a_separate_run"):
            self.compare(repeat_run=self.primary)
        duplicate = self.root / "duplicate"
        shutil.copytree(self.primary, duplicate)
        with self.assertRaisesRegex(ValueError, "same_ledger_is_not_a_repeat"):
            self.compare(repeat_run=duplicate)

    def test_complete_selected_subset_cannot_be_presented_as_full_test(self):
        self.primary = self.root / "subset"
        with self.assertRaisesRegex(ValueError, "complete_test_run_required"):
            self.compare()

    def test_missing_evidence_is_rejected_without_success_only_filtering(self):
        (self.primary / "inputs.jsonl").unlink()
        with self.assertRaisesRegex(ValueError, "missing_or_symlink_evidence"):
            self.compare()

    def test_duplicate_completed_result_is_rejected_with_a_valid_new_hash_chain(self):
        path = self.primary / "records.jsonl"
        records, last_hash = runner._read_log(path)
        duplicate = deepcopy(next(row for row in records if row["kind"] == "result"))
        for key in ("record_sha256", "previous_sha256"):
            duplicate.pop(key)
        runner._append_log(path, duplicate, last_hash)
        with self.assertRaisesRegex(ValueError, "duplicate_or_unreserved_result"):
            self.compare()

    def test_raw_response_tampering_is_rejected(self):
        path = self.primary / "records.jsonl"
        path.write_text(path.read_text().replace("resp_offline_comparison", "resp_tampered"))
        with self.assertRaises(runner.RunnerError):
            self.compare()

    def test_missing_result_is_rejected_even_if_the_prefix_chain_is_valid(self):
        path = self.primary / "records.jsonl"
        lines = path.read_text().splitlines()
        path.write_text("\n".join(lines[:-2]) + "\n")
        with self.assertRaises(runner.RunnerError):
            self.compare()

    def test_static_prompt_and_frozen_source_identity_are_verified(self):
        path = self.primary / "prompt.txt"
        original = path.read_bytes()
        path.write_bytes(original + b"changed")
        with self.assertRaisesRegex(ValueError, "prompt_file_mismatch"):
            self.compare()
        path.write_bytes(original)
        freeze = load(self.freeze)
        freeze["rules_sha256"] = "0" * 64
        save(self.freeze, freeze)
        with self.assertRaisesRegex(ValueError, "frozen_dataset_or_rules_changed"):
            self.compare()

    def test_recorded_evaluation_and_archival_file_hashes_are_checked(self):
        path = self.primary / "evaluation.json"
        original = path.read_bytes()
        evaluation = load(path)
        evaluation["metrics"]["whole_notice_accuracy"] = 0.1
        save(path, evaluation)
        with self.assertRaisesRegex(ValueError, "recorded_evaluation_mismatch"):
            self.compare()
        path.write_bytes(original)
        save(self.primary / "provenance.json", {"files_sha256": {name: "0" * 64 for name in EVIDENCE_FILES}})
        with self.assertRaisesRegex(ValueError, "provenance_file_hash_mismatch"):
            self.compare()


if __name__ == "__main__":
    unittest.main()
