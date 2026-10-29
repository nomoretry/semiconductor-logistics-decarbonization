import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from notice_benchmark.run_workflow_audit import ROOT, run_audit, verify_audit


class WorkflowAuditEvidenceTests(unittest.TestCase):
    def test_audit_reexecutes_traces_and_distinguishes_development_units(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = run_audit(ROOT / "benchmarks/notices_v1/dataset.json", output, tasks=3)
            self.assertTrue(result["development_only"])
            self.assertFalse(result["canonical_final_executed"])
            self.assertEqual(result["method_runs"], 6)
            self.assertFalse(result["rl_gate"]["passed"])
            self.assertTrue(verify_audit(ROOT / "benchmarks/notices_v1/dataset.json", output)["verified"])

    def test_rehashed_forged_trace_is_detected_by_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            run_audit(ROOT / "benchmarks/notices_v1/dataset.json", output, tasks=2)
            trace_path = output / "traces.jsonl"
            rows = trace_path.read_text().splitlines()
            first = json.loads(rows[0])
            first["trace"] = []
            rows[0] = json.dumps(first)
            trace_path.write_text("\n".join(rows) + "\n")
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["file_sha256"]["traces.jsonl"] = hashlib.sha256(trace_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "replay mismatch"):
                verify_audit(ROOT / "benchmarks/notices_v1/dataset.json", output)


if __name__ == "__main__":
    unittest.main()
