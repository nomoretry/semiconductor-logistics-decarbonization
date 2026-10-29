"""Semantic and split-integrity checks for the synthetic notice benchmark."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from notice_benchmark.data import CATEGORIES, generate_dataset, validate_dataset, write_dataset


class NoticeDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = generate_dataset(20261030)

    def test_generation_is_deterministic_and_seed_changes_actual_inputs(self):
        same = generate_dataset(20261030)
        changed = generate_dataset(20261031)
        self.assertEqual(self.dataset, same)
        self.assertNotEqual(self.dataset["manifest"]["split_input_sha256"], changed["manifest"]["split_input_sha256"])

    def test_default_counts_and_full_semantic_coverage(self):
        manifest = self.dataset["manifest"]
        self.assertEqual(manifest["split_counts"], {"development": 120, "test": 400})
        self.assertEqual(manifest["event_counts"], manifest["split_counts"])
        self.assertEqual(manifest["real_notice_count"], 0)
        for split in ("development", "test"):
            self.assertEqual(set(manifest["category_counts"][split]), set(CATEGORIES))
            self.assertEqual(manifest["template_family_counts"][split], 2 * len(CATEGORIES))

    def test_events_families_and_payloads_are_disjoint(self):
        dev, test = self.dataset["splits"].values()
        for key in ("id", "event_id", "template_family_id"):
            self.assertFalse({r[key] for r in dev} & {r[key] for r in test})
        self.assertFalse({r["model_input"]["text"] for r in dev} & {r["model_input"]["text"] for r in test})
        for record in dev + test:
            self.assertEqual(set(record["model_input"]), {"text", "context"})
            self.assertFalse(set(record["model_input"]["context"]) & {"reference", "category", "annotation", "expected", "event_id"})

    def test_total_duration_and_unit_conversions_are_increments(self):
        for record in self.dataset["splits"]["test"]:
            category = record["category"]
            if category not in {"revised_total", "added_days", "added_fortnights"}:
                continue
            p = record["annotation"]["parameters"]
            increment = record["reference"]["changes"][0]["value"]
            if category == "revised_total":
                self.assertEqual(increment, p["total"] - p["baseline"])
                self.assertNotEqual(increment, p["total"])
            elif category == "added_days":
                self.assertEqual(7 * increment, p["days"])
            else:
                self.assertEqual(increment, 2 * p["fortnights"])

    def test_corrections_replace_and_superseded_windows_are_not_applied(self):
        for record in self.dataset["splits"]["test"]:
            p = record["annotation"]["parameters"]
            if record["category"] == "correction":
                change = record["reference"]["changes"][0]
                self.assertEqual(change["value"], p["delta"])
                self.assertNotEqual(change["value"], p["old_delta"])
                self.assertNotEqual(change["value"], p["old_delta"] + p["delta"])
            elif record["category"] == "superseded_window":
                change = record["reference"]["changes"][0]
                self.assertEqual((change["start_week"], change["end_week"]), (p["start"], p["end"]))
                self.assertGreater(change["start_week"], p["old_end"])

    def test_missing_conflicting_or_unsupported_data_never_guessed(self):
        categories = {"missing_route", "missing_window", "missing_increment", "nonintegral_days",
                      "uncertain_range", "arrival_window", "unknown_route", "conflicting_reports"}
        for record in self.dataset["splits"]["test"]:
            if record["category"] in categories:
                self.assertEqual(record["reference"], {"status": "needs_clarification", "changes": []})
                if record["category"] == "nonintegral_days":
                    self.assertNotEqual(record["annotation"]["parameters"]["nonintegral_days"] % 7, 0)

    def test_no_change_and_other_known_route_are_ready_noops(self):
        for record in self.dataset["splits"]["test"]:
            if record["category"] in {"no_change", "negated_alert", "unrelated_route"}:
                self.assertEqual(record["reference"], {"status": "ready", "changes": []})

    def test_multiple_windows_have_distinct_nonoverlapping_updates(self):
        for record in self.dataset["splits"]["test"]:
            if record["category"] == "multiple_windows":
                first, second = record["reference"]["changes"]
                self.assertLess(first["end_week"], second["start_week"])
                self.assertLessEqual(second["end_week"], record["model_input"]["context"]["horizon"])

    def test_manifest_tampering_label_mutation_and_leakage_are_rejected(self):
        cases = []
        modified = copy.deepcopy(self.dataset); modified["manifest"]["split_counts"]["test"] += 1; cases.append(modified)
        modified = copy.deepcopy(self.dataset); modified["splits"]["test"][0]["reference"]["status"] = "invented"; cases.append(modified)
        modified = copy.deepcopy(self.dataset); modified["splits"]["test"][0]["model_input"]["reference"] = {}; cases.append(modified)
        modified = copy.deepcopy(self.dataset); modified["splits"]["test"][0]["model_input"]["context"]["category"] = "leak"; cases.append(modified)
        modified = copy.deepcopy(self.dataset); modified["splits"]["test"][0]["event_id"] = modified["splits"]["development"][0]["event_id"]; cases.append(modified)
        for item in cases:
            with self.assertRaises(ValueError):
                validate_dataset(item)

    def test_writer_file_hashes_and_never_creates_fake_real_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = write_dataset(temporary, dev_count=36, test_count=36)
            manifest = json.loads(Path(paths["manifest"]).read_text())
            for filename, expected in manifest["file_sha256"].items():
                self.assertEqual(hashlib.sha256((Path(temporary) / filename).read_bytes()).hexdigest(), expected)
            self.assertEqual(len(Path(paths["test"]).read_text().splitlines()), 36)
            self.assertFalse(any("real" in p.name for p in Path(temporary).iterdir()))
            validate_dataset(json.loads(Path(paths["dataset"]).read_text()))

    def test_rejects_boolean_counts_and_bad_business_context(self):
        with self.assertRaises(ValueError):
            generate_dataset(test_count=True)
        with self.assertRaises(ValueError):
            generate_dataset(context={"scope_route": "NL_air", "period": "week"})


if __name__ == "__main__":
    unittest.main()
