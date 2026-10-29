"""Sanitized Actions scoring tests; all provider transport is mocked."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from notice_benchmark import api_runner as runner
from notice_benchmark.data import generate_dataset
from scripts.score_notice_api import score_run


FAKE_KEY = "sk-proj-" + ("TEST_ONLY_" * 8)


class ActionSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dataset = generate_dataset(seed=345, dev_count=3, test_count=3)
        self.dataset_path = self.root / "dataset.json"
        self.dataset_path.write_bytes(runner.canonical_bytes(self.dataset) + b"\n")
        self.run_dir = self.root / "run"
        self.answers = {runner.sha256(runner.canonical_bytes(row["model_input"])): row["reference"]
            for row in self.dataset["splits"]["development"]}

    def tearDown(self):
        self.temporary.cleanup()

    def response(self, body, *, provider_text="private-provider-text https://untrusted.invalid SECRET_SENTINEL"):
        payload = json.loads(body["input"][1]["content"][0]["text"])
        answer = self.answers[runner.sha256(runner.canonical_bytes(payload))]
        return {"id": provider_text, "model": provider_text, "status": "completed", "error": None,
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}]}

    def execute(self, transport=None):
        return runner.run_benchmark(self.dataset_path, self.run_dir, split="development",
            execute=True, max_usd="1", api_key=FAKE_KEY,
            transport=transport or (lambda body, key, timeout: self.response(body)))

    def test_missing_run_has_unavailable_accuracy_not_zero(self):
        report = score_run(self.dataset_path, self.run_dir)
        self.assertEqual(report["status"], "no_run_artifacts")
        self.assertIsNone(report["metrics"])
        self.assertIsNone(report["counts"]["requested_calls"])
        self.assertEqual(report["counts"]["completed_calls"], 0)
        self.assertIn("No live inference results", (self.run_dir / "evaluation.md").read_text())

    def test_completed_mocks_score_without_becoming_live_evidence(self):
        self.execute()
        summary = self.root / "github-summary.md"
        report = score_run(self.dataset_path, self.run_dir, summary)
        self.assertEqual(report["status"], "completed_mock_evaluation")
        self.assertFalse(report["live_api_evidence"])
        self.assertFalse(report["partial_run"])
        self.assertEqual(report["counts"]["completed_calls"], 3)
        self.assertEqual(report["metrics"]["whole_notice_accuracy"], 1)
        for path in [summary, self.run_dir / "evaluation.md", self.run_dir / "evaluation.json"]:
            content = path.read_text()
            for marker in ["private-provider-text", "untrusted.invalid", "SECRET_SENTINEL", FAKE_KEY]:
                self.assertNotIn(marker, content)

    def test_partial_api_failure_and_unattempted_calls_are_separate(self):
        calls = []
        def transport(body, key, timeout):
            calls.append(True)
            if len(calls) == 2:
                raise runner.TransportError(429, "quota_error", "insufficient_quota")
            return self.response(body)
        self.execute(transport)
        report = score_run(self.dataset_path, self.run_dir)
        self.assertTrue(report["partial_run"])
        counts = report["counts"]
        self.assertEqual((counts["requested_calls"], counts["attempted_calls"], counts["completed_calls"]), (3, 2, 1))
        self.assertEqual((counts["api_errors"], counts["unattempted_calls"]), (1, 1))
        self.assertEqual(report["metrics"]["whole_notice_accuracy"], 1)

    def test_no_completed_model_outputs_do_not_receive_accuracy(self):
        self.execute(lambda *args: (_ for _ in ()).throw(RuntimeError("secret-response-error")))
        report = score_run(self.dataset_path, self.run_dir)
        self.assertEqual(report["counts"]["transport_errors"], 1)
        self.assertEqual(report["counts"]["unattempted_calls"], 2)
        self.assertIsNone(report["metrics"])
        self.assertNotIn("secret-response-error", (self.run_dir / "evaluation.md").read_text())

    def test_valid_manifest_without_attempt_handles_missing_credentials(self):
        with self.assertRaises(runner.RunnerError):
            runner.run_benchmark(self.dataset_path, self.run_dir, split="development",
                execute=True, max_usd="1", api_key="invalid", transport=lambda *args: self.fail("must not call"))
        report = score_run(self.dataset_path, self.run_dir)
        self.assertEqual(report["counts"]["requested_calls"], 3)
        self.assertEqual(report["counts"]["attempted_calls"], 0)
        self.assertEqual(report["counts"]["unattempted_calls"], 3)
        self.assertIsNone(report["metrics"])

    def test_tampered_hash_chain_is_rejected(self):
        self.execute()
        path = self.run_dir / "records.jsonl"
        rows = path.read_text().splitlines()
        row = json.loads(rows[-1]); row["case_id"] = "unexpected-case"
        rows[-1] = json.dumps(row); path.write_text("\n".join(rows) + "\n")
        with self.assertRaises((ValueError, runner.RunnerError)):
            score_run(self.dataset_path, self.run_dir)

    def test_empty_truncated_log_with_anchor_is_rejected(self):
        self.execute()
        (self.run_dir / "records.jsonl").write_text("")
        with self.assertRaises((ValueError, runner.RunnerError)):
            score_run(self.dataset_path, self.run_dir)

    def test_duplicate_result_rejected_even_with_valid_rehashed_ledger(self):
        self.execute()
        path = self.run_dir / "records.jsonl"
        records, last = runner._read_log(path)
        duplicate = deepcopy(next(row for row in records if row["kind"] == "result"))
        duplicate.pop("record_sha256"); duplicate.pop("previous_sha256")
        runner._append_log(path, duplicate, last)
        with self.assertRaisesRegex(ValueError, "duplicate_or_unreserved_result"):
            score_run(self.dataset_path, self.run_dir)

    def test_wrong_dataset_identity_is_rejected(self):
        self.execute()
        alternate = generate_dataset(seed=789, dev_count=3, test_count=3)
        self.dataset_path.write_bytes(runner.canonical_bytes(alternate) + b"\n")
        with self.assertRaisesRegex(ValueError, "dataset_hash_mismatch"):
            score_run(self.dataset_path, self.run_dir)

    def test_recorded_usage_exceeding_reservation_is_not_reported_as_success(self):
        def excessive_usage(body, key, timeout):
            response = self.response(body)
            response["usage"] = {"input_tokens": 10000000, "output_tokens": 10000000}
            return response
        with self.assertRaises(runner.RunnerError):
            self.execute(excessive_usage)
        with self.assertRaisesRegex(ValueError, "usage_exceeded_reserved_bound"):
            score_run(self.dataset_path, self.run_dir)


if __name__ == "__main__":
    unittest.main()
