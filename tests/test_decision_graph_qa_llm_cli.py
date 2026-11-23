"""Check the public entry point and offline evaluation scope."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from decision_graph_qa.__main__ import main
from decision_graph_qa.llm import data

RATES = ["--input-usd-per-m", "2.00", "--cached-input-usd-per-m", "0.10",
         "--cache-write-usd-per-m", "2.50", "--output-usd-per-m", "10.00"]


class LlmCliTests(unittest.TestCase):
    def invoke(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        status = 0
        with patch("sys.argv", ["decision_graph_qa", *args]), redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                main()
            except SystemExit as error:
                status = error.code
        return status, stdout.getvalue(), stderr.getvalue()

    def test_dry_run_uses_protocol_and_shows_projected_pilot_reuse(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "decision_graph_qa.llm.transport.Client.from_env", side_effect=AssertionError("credential access"),
        ):
            root = Path(directory) / "untouched"
            code, stdout, stderr = self.invoke([
                "llm-run", "--phase", "main", "--size", "half", "--arm", "S", "--root", str(root),
                *RATES, "--dry-run",
            ])
            self.assertEqual((code, stderr), (0, ""))
            result = json.loads(stdout)
            self.assertEqual(result["new_calls"], 576)
            self.assertEqual(result["reused_pilot_calls"], 0)
            self.assertEqual(result["if_remaining_pilot_tasks_finish"]["extra_reused_pilot_calls"], 96)
            self.assertEqual(result["if_remaining_pilot_tasks_finish"]["new_calls"], 480)
            self.assertFalse(root.exists())

    def test_startup_checks_finish_before_api_client_creation(self):
        base = ["llm-run", "--phase", "smoke", "--arm", "S"]
        with patch("decision_graph_qa.llm.transport.Client.from_env", side_effect=AssertionError("request")):
            code, _, stderr = self.invoke([*base, *RATES[:-2], "--max-usd", "1"])
            self.assertEqual(code, 2)
            self.assertIn("all four", stderr)
            code, _, stderr = self.invoke([*base, *RATES])
            self.assertEqual(code, 2)
            self.assertIn("--max-usd", stderr)
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "protocol_config.json").write_bytes(b"{}\n")
                with patch.object(data, "DEFAULT_ROOT", root):
                    code, _, stderr = self.invoke([*base, *RATES, "--max-usd", "1"])
                self.assertEqual(code, 2)
                self.assertIn("Protocol config SHA256 mismatch", stderr)


if __name__ == "__main__":
    unittest.main()
