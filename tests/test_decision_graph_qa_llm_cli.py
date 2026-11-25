"""Check the public entry point and offline evaluation scope."""
from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from decision_graph_qa.__main__ import main
from decision_graph_qa.llm import data
from decision_graph_qa.llm_eval import register

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

    def test_run_waits_one_hour_by_default(self):
        parser = argparse.ArgumentParser()
        register(parser.add_subparsers(dest="command"))
        self.assertEqual(parser.parse_args(["llm-run", "--check", "--arm", "S"]).timeout, 3600)

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
                moved = replace(data.PROTOCOLS[data.CURRENT], root=root)
                with patch.dict(data.PROTOCOLS, {data.CURRENT: moved}):
                    code, _, stderr = self.invoke([*base, *RATES, "--max-usd", "1"])
                self.assertEqual(code, 2)
                self.assertIn("Protocol config SHA256 mismatch", stderr)

    def test_closed_protocol_and_foreign_root_stop_before_credentials(self):
        live = ["--phase", "pilot", "--arm", "S", *RATES, "--max-usd", "1"]
        closed = str(data.PROTOCOLS["v1"].root)
        with patch("decision_graph_qa.llm.transport.Client.from_env", side_effect=AssertionError("request")):
            for args, message in (
                (["llm-run", "--protocol", "v1", *live], "closed to new requests"),
                (["llm-batch", "export", "--protocol", "v1", "--phase", "main", "--arm", "S",
                  "--pilot-root", closed, *RATES], "closed to new requests"),
                (["llm-run", "--root", closed, *live], "another protocol version"),
            ):
                code, _, stderr = self.invoke(args)
                self.assertEqual(code, 2)
                self.assertIn(message, stderr)
            code, stdout, _ = self.invoke(["llm-run", "--protocol", "v1", "--phase", "pilot", "--arm", "S", *RATES,
                                           "--dry-run"])
        self.assertEqual((code, json.loads(stdout)["completed_here"], json.loads(stdout)["new_calls"]), (0, 12, 84))


if __name__ == "__main__":
    unittest.main()
