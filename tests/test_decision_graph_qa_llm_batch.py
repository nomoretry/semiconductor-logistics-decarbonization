"""Offline checks for DQ-3 Batch evidence."""
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from decision_graph_qa.llm.batch import (
    ENDPOINT,
    active_batch_tasks,
    export_batches,
    import_batches,
)
from decision_graph_qa.llm.data import (
    LlmError,
    append_jsonl,
    canonical,
    digest,
    load_config,
    plan,
    read_jsonl,
    response_path,
    terminal_records,
)
from decision_graph_qa.llm.transport import Prices, decode_response


class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()
        cls.pilot = plan(cls.config, "pilot", "S")
        cls.main = plan(cls.config, "main", "S", "half")
        cls.prices = Prices("1.00", "0.05", "1.25", "5.00")

    def test_export_matches_response_body_and_reuses_terminal_pilot_record(self):
        first = self.pilot[0]
        body = {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "null"}]}],
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 10, "cache_write_tokens": 5},
                "output_tokens": 200,
                "output_tokens_details": {"reasoning_tokens": 100},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "main"
            pilot_root = Path(directory) / "pilot"
            pilot_row = decode_response(first, body, self.prices, transport="sync")
            append_jsonl(response_path(pilot_root, "pilot", "S"), pilot_row)
            kwargs = {"phase": "main", "arm": "S", "size": "half", "pilot_root": pilot_root,
                      "chunk_size": 250, "prices": self.prices}
            with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network call")):
                result = export_batches(self.config, root, **kwargs)
                self.assertEqual(result, export_batches(self.config, root, **kwargs))

            self.assertEqual(result["planned"], 576)
            self.assertEqual(result["reused"], 1)
            reused = terminal_records(root, self.main)
            self.assertEqual(set(reused), {first.custom_id})
            self.assertEqual(reused[first.custom_id]["phase"], "pilot")
            self.assertEqual(result["exported"], 575)
            self.assertEqual([chunk["requests"] for chunk in result["chunks"]], [250, 250, 75])
            self.assertEqual(result["pilot_output_observations"], 1)
            self.assertEqual(Decimal(result["pilot_mean_output_tokens"]), Decimal(200))

            exported = []
            by_id = {task.custom_id: task for task in self.main}
            for chunk in result["chunks"]:
                path = Path(chunk["file"])
                manifest = json.loads(Path(chunk["manifest"]).read_bytes())
                self.assertEqual(chunk["sha256"], digest(path))
                self.assertEqual(manifest["sha256"], chunk["sha256"])
                rows = list(read_jsonl(path))
                self.assertEqual(len(rows), chunk["requests"])
                for row, proof in zip(rows, manifest["requests"], strict=True):
                    task = by_id[row["custom_id"]]
                    self.assertEqual(row, {"custom_id": task.custom_id, "method": "POST", "url": ENDPOINT,
                                           "body": task.body})
                    self.assertEqual(proof, {"custom_id": task.custom_id, "request_hash": task.request_hash})
                    exported.append(row["custom_id"])
                expected = (chunk["input_tokens_estimate"] + chunk["requests"] * 200 * 5) / 1_000_000
                self.assertAlmostEqual(float(chunk["expected_usd"]), expected)
            self.assertEqual(exported, [task.custom_id for task in self.main if task.custom_id != first.custom_id])

    def test_export_rejects_changed_evidence_and_pilot_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = {"phase": "p3", "arm": "S", "size": "full", "pilot_root": root,
                      "chunk_size": 250, "prices": self.prices}
            with self.assertRaisesRegex(LlmError, "between 1 and 250"):
                export_batches(self.config, root, **{**kwargs, "chunk_size": 251})
            result = export_batches(self.config, root, **kwargs)
            self.assertIsNone(result["chunks"][0]["expected_usd"])
            Path(result["chunks"][0]["file"]).write_bytes(b"changed\n")
            with self.assertRaisesRegex(LlmError, "Batch evidence differs"):
                export_batches(self.config, root, **kwargs)

            task = self.pilot[0]
            truncated = decode_response(task, {"status": "incomplete", "incomplete_details": {
                "reason": "max_output_tokens"
            }}, self.prices, transport="sync")
            append_jsonl(response_path(root, "pilot", "S"), truncated)
            with self.assertRaisesRegex(LlmError, "protocol amendment"):
                export_batches(self.config, root, **{**kwargs, "phase": "main"})

    def test_import_matches_manual_files_and_keeps_ledger_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exported = export_batches(self.config, root, phase="p3", arm="S", size="full", pilot_root=root,
                                      chunk_size=250, prices=self.prices)
            # Choose the last chunk, so the fixture can present one omitted request
            # while retaining exact input-to-result matching for the others.
            path = Path(exported["chunks"][-1]["file"])
            requests = list(read_jsonl(path))
            results = root / "manual.jsonl"
            response = {
                "status_code": 200,
                "request_id": "req_batch_test",
                "body": {
                    "status": "completed",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "25"}]}],
                    "usage": {
                        "input_tokens": 100, "input_tokens_details": {"cached_tokens": 10, "cache_write_tokens": 5},
                        "output_tokens": 200, "output_tokens_details": {"reasoning_tokens": 100},
                    },
                },
            }
            for index, request in enumerate(requests[:-1]):
                append_jsonl(results, {"id": f"batch_req_test_{index}", "custom_id": request["custom_id"],
                                       "response": response, "error": None})
            with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network call")):
                summary = import_batches(self.config, root, files=[results], prices=self.prices)
                repeated = import_batches(self.config, root, files=[results], prices=self.prices)
            self.assertEqual(summary["missing"], [requests[-1]["custom_id"]])
            self.assertEqual(summary["imported"], len(requests))
            self.assertEqual(repeated["already_imported"], len(requests))
            self.assertEqual(Decimal(repeated["committed_usd"]), Decimal("0.00109175") * (len(requests) - 1))
            saved = list(read_jsonl(response_path(root, "p3", "S")))
            self.assertEqual(len(saved), len(requests))
            self.assertEqual((saved[0]["status"], saved[0]["transport"], saved[0]["parsed"]), ("ok", "batch", 25))
            self.assertEqual((saved[-1]["status"], saved[-1]["usage_status"]), ("error", "service_unreported"))

    def test_unresolved_batch_defers_only_matching_request_hashes(self):
        first, second = self.main[:2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "batches" / "state.json"
            state.parent.mkdir()
            records = {"submission_test": {"status": "in_progress", "requests": [
                {"custom_id": first.custom_id, "request_hash": first.request_hash},
                {"custom_id": second.custom_id, "request_hash": "0" * 64},
            ]}}
            state.write_bytes(canonical(records))
            self.assertIn((first.custom_id, first.request_hash), active_batch_tasks(root))
            self.assertNotIn((second.custom_id, second.request_hash), active_batch_tasks(root))
            result = export_batches(self.config, root, phase="main", arm="S", size="half", pilot_root=root,
                                    chunk_size=250, prices=self.prices)
            self.assertEqual(result["deferred_batch"], 1)
            self.assertEqual(result["exported"], 575)
            records["submission_test"]["status"] = "imported"
            state.write_bytes(canonical(records))
            self.assertEqual(active_batch_tasks(root), set())

    def test_unrelated_manual_results_do_not_mark_local_requests_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export_batches(self.config, root, phase="p3", arm="S", size="full", pilot_root=root,
                           chunk_size=600, prices=self.prices)
            path = root / "unrelated.jsonl"
            append_jsonl(path, {"id": "batch_req_unrelated", "custom_id": "outside_the_export",
                                "response": None, "error": {"code": "batch_expired", "message": "Expired"}})
            with self.assertRaisesRegex(LlmError, "outside_the_export"):
                import_batches(self.config, root, files=[path], prices=self.prices)
            self.assertFalse(response_path(root, "p3", "S").exists())
            self.assertFalse((root / "ledger.jsonl").exists())
