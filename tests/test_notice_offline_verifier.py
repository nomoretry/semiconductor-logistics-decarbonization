"""Tamper checks for offline evidence replay, not additional heldout tuning."""

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from notice_benchmark.data import canonical_bytes, write_dataset
from notice_benchmark.run_offline import evaluate, freeze_rules
from notice_benchmark.verify_offline import verify


def load(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_bytes(canonical_bytes(value) + b"\n")


def refresh_artifact_hash(output, filename):
    path = output / "manifest.json"
    manifest = load(path)
    manifest["file_sha256"][filename] = hashlib.sha256((output / filename).read_bytes()).hexdigest()
    save(path, manifest)


class OfflineVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.template.cleanup)
        root = Path(cls.template.name)
        write_dataset(root / "data", seed=4481, dev_count=36, test_count=36)
        cls.dataset_name = Path("data/dataset.json")
        cls.freeze_name = Path("data/rules_freeze.json")
        freeze_rules(root / cls.dataset_name, root / cls.freeze_name)
        with contextlib.redirect_stdout(io.StringIO()):
            evaluate(root / cls.dataset_name, root / cls.freeze_name, root / "results")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "moved_bundle"
        shutil.copytree(self.template.name, self.root)
        self.dataset = self.root / self.dataset_name
        self.freeze = self.root / self.freeze_name
        self.output = self.root / "results"

    def test_valid_moved_bundle_replays_without_writing(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = verify(self.dataset, self.freeze, self.output)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(result["verified"])
        self.assertEqual(result["rules_replayed"], 36)
        self.assertEqual(result["prediction_records"], 144)
        self.assertEqual(result["api_calls"], 0)
        self.assertIn("not an independent", result["verification_scope"])

    def test_metric_and_manifest_replacement_is_detected_by_recomputation(self):
        filename = "rules_frozen_v1.metrics.json"
        metrics = load(self.output / filename)
        metrics["summary"]["exact_match_rate"] = 0.999
        save(self.output / filename, metrics)
        refresh_artifact_hash(self.output, filename)
        with self.assertRaisesRegex(ValueError, "metrics differs"):
            verify(self.dataset, self.freeze, self.output)

    def test_coherent_predictions_metrics_summary_and_manifest_still_fail_rule_replay(self):
        # Rebuild a wholly self-consistent forged result using a different
        # in-memory policy; the frozen source file itself remains unchanged.
        with patch("notice_benchmark.run_offline.extract_notice", return_value={"status": "needs_clarification", "changes": []}):
            evaluate(self.dataset, self.freeze, self.output)
        with self.assertRaisesRegex(ValueError, "algorithm replay"):
            verify(self.dataset, self.freeze, self.output)

    def test_duplicate_case_repeat_is_rejected_even_with_updated_hash(self):
        filename = "rules_frozen_v1.predictions.jsonl"
        path = self.output / filename
        lines = path.read_text().splitlines()
        path.write_text("\n".join(lines + [lines[0]]) + "\n")
        refresh_artifact_hash(self.output, filename)
        with self.assertRaisesRegex(ValueError, "Duplicate prediction"):
            verify(self.dataset, self.freeze, self.output)

    def test_undeclared_repeat_and_missing_case_are_rejected(self):
        filename = "ignore_notice.predictions.jsonl"
        path = self.output / filename
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["repeat_id"] = "1"
        path.write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in rows))
        refresh_artifact_hash(self.output, filename)
        with self.assertRaisesRegex(ValueError, "repeat_id 0"):
            verify(self.dataset, self.freeze, self.output)
        rows = rows[1:]
        path.write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in rows))
        refresh_artifact_hash(self.output, filename)
        with self.assertRaisesRegex(ValueError, "Missing prediction"):
            verify(self.dataset, self.freeze, self.output)

    def test_artifact_path_escape_is_rejected_before_reading_target(self):
        path = self.output / "manifest.json"
        manifest = load(path)
        manifest["file_sha256"]["../../outside.json"] = "0" * 64
        save(path, manifest)
        with self.assertRaisesRegex(ValueError, "Unsafe relative manifest path"):
            verify(self.dataset, self.freeze, self.output)

    def test_source_path_escape_and_source_identity_change_are_rejected(self):
        path = self.output / "manifest.json"
        original = load(path)
        manifest = copy.deepcopy(original)
        manifest["source_sha256"]["../outside.py"] = "0" * 64
        save(path, manifest)
        with self.assertRaisesRegex(ValueError, "Unsafe relative manifest path"):
            verify(self.dataset, self.freeze, self.output)
        original["source_sha256"]["notice_benchmark/metrics.py"] = "0" * 64
        save(path, original)
        with self.assertRaisesRegex(ValueError, "Source SHA-256 mismatch"):
            verify(self.dataset, self.freeze, self.output)

    def test_summary_effect_and_family_interval_recomputed(self):
        path = self.output / "summary.json"
        original = load(path)
        for field in ("schedule_effect_match_rate", "template_grouped", "by_category"):
            summary = copy.deepcopy(original)
            if field == "schedule_effect_match_rate":
                summary["methods"]["ignore_notice"][field] = 0.999
            elif field == "template_grouped":
                summary["methods"]["ignore_notice"][field]["bootstrap_95_percentile"] = [0.999, 1]
            else:
                first = next(iter(summary["methods"]["ignore_notice"][field]))
                summary["methods"]["ignore_notice"][field][first]["exact_match_rate"] = 0.999
            save(path, summary)
            refresh_artifact_hash(self.output, "summary.json")
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "summary/effects/categories/family interval"):
                verify(self.dataset, self.freeze, self.output)

    def test_freeze_and_dataset_reference_tampering_fail(self):
        frozen = load(self.freeze)
        frozen["rules_sha256"] = "0" * 64
        save(self.freeze, frozen)
        with self.assertRaisesRegex(ValueError, "Frozen dataset/rules identity"):
            verify(self.dataset, self.freeze, self.output)
        shutil.copyfile(Path(self.template.name) / self.freeze_name, self.freeze)
        dataset = load(self.dataset)
        dataset["splits"]["test"][0]["reference"]["status"] = "invented"
        save(self.dataset, dataset)
        with self.assertRaises(ValueError):
            verify(self.dataset, self.freeze, self.output)

    def test_symlink_artifact_is_rejected_even_when_its_bytes_match(self):
        filename = "ignore_notice.predictions.jsonl"
        path = self.output / filename
        outside = self.root / "copy.jsonl"
        shutil.copyfile(path, outside)
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "Symlink in manifest path"):
            verify(self.dataset, self.freeze, self.output)

    def test_unmanifested_artifact_and_false_llm_execution_claim_fail(self):
        extra = self.output / "unlisted.json"
        extra.write_text("{}")
        with self.assertRaisesRegex(ValueError, "Unmanifested"):
            verify(self.dataset, self.freeze, self.output)
        extra.unlink()
        summary_path = self.output / "summary.json"
        summary = load(summary_path)
        summary["llm"]["executed"] = True
        save(summary_path, summary)
        refresh_artifact_hash(self.output, "summary.json")
        with self.assertRaisesRegex(ValueError, "cannot claim LLM"):
            verify(self.dataset, self.freeze, self.output)

    def test_nested_manifest_filename_cannot_hide_an_unlisted_file(self):
        hidden = self.output / "nested" / "manifest.json"
        hidden.parent.mkdir()
        hidden.write_text("{}")
        with self.assertRaisesRegex(ValueError, "Unmanifested"):
            verify(self.dataset, self.freeze, self.output)


if __name__ == "__main__":
    unittest.main()
