"""The project CLI preserves legacy argv, offline defaults and workspace identity."""

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from semiconductor_logistics import __version__
from semiconductor_logistics import cli


ROOT = Path(__file__).resolve().parents[1]


class CommandLineTests(unittest.TestCase):
    def call(self, *arguments):
        with patch.object(cli, "_run_module", return_value=0) as delegate:
            status = cli.main(list(arguments))
        self.assertEqual(status, 0)
        return delegate.call_args.args

    def test_api_estimation_does_not_add_execute_or_budget(self):
        module, arguments, workspace = self.call("api", "--split", "development", "--max-calls", "3")
        self.assertEqual(module, "notice_benchmark.api_runner")
        self.assertEqual(arguments, ["--split", "development", "--max-calls", "3"])
        self.assertEqual(workspace, ROOT)
        self.assertNotIn("--execute", arguments)

    def test_only_explicit_live_options_are_forwarded_unchanged(self):
        arguments = ["--execute", "--max-usd", "0.05", "--max-calls", "2"]
        self.assertEqual(self.call("api", *arguments)[1], arguments)

    def test_all_offline_commands_delegate_to_the_archived_paths(self):
        expected = {
            "generate": "notice_benchmark.data",
            "evaluate": "notice_benchmark.run_offline",
            "verify-run": "notice_benchmark.verify_offline",
            "workflow-audit": "notice_benchmark.run_workflow_audit",
            "score-api": "scripts.score_notice_api",
            "report": "scripts.create_reports",
            "download-data": "scripts.download_source_data",
        }
        for command, module in expected.items():
            with self.subTest(command=command):
                self.assertEqual(self.call(command)[0], module)
        self.assertEqual(self.call("workflow-audit", "--verify")[1], ["--verify"])

    def test_project_and_smoke_are_explicit(self):
        with patch.object(cli, "_check_optimization_inputs"):
            module, arguments, _ = self.call("optimize", "--project", "asml", "--smoke")
        self.assertEqual(module, "scripts.run_experiments")
        self.assertEqual(arguments, ["--project", "asml", "--smoke"])
        self.assertEqual(self.call("sensitivity", "--project", "marvell")[1], ["--project", "marvell"])

    def test_workspace_can_precede_or_follow_command(self):
        for arguments in (("--workspace", str(ROOT), "api"), ("api", "--workspace", str(ROOT))):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.call(*arguments)[2], ROOT)

    def test_missing_workspace_reports_the_checkout_requirement(self):
        error = io.StringIO()
        with patch.object(cli, "_find_workspace", return_value=None), \
                contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            cli.main(["api"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--workspace", error.getvalue())
        self.assertIn("not bundled", error.getvalue())

    def test_help_and_version_do_not_run_experiments(self):
        for arguments in (["--help"], ["--version"], ["report", "--help"], ["optimize", "--help"]):
            output = io.StringIO()
            with patch.object(cli, "_run_module") as delegate, contextlib.redirect_stdout(output), \
                    self.assertRaises(SystemExit) as raised:
                cli.main(arguments)
            self.assertEqual(raised.exception.code, 0)
            delegate.assert_not_called()
            self.assertTrue(output.getvalue().strip())
            if arguments == ["--version"]:
                self.assertIn(__version__, output.getvalue())

    def test_delegated_help_works_without_a_workspace(self):
        with patch.object(cli, "_find_workspace", return_value=None):
            self.assertEqual(self.call("api", "--help"), ("notice_benchmark.api_runner", ["--help"], None))

    def test_code_modules_alone_are_not_a_complete_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("notice_benchmark/data.py", "shared/optimization.py", "scripts/run_experiments.py"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("")
            self.assertFalse(cli._is_workspace(root))

    def test_execution_context_restores_state_after_failure(self):
        original_argv, original_path, original_cwd = sys.argv, sys.path[:], Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                with cli._execution_context("notice_benchmark.api_runner", ["--max-calls", "1"], workspace):
                    self.assertEqual(sys.argv, ["notice_benchmark.api_runner", "--max-calls", "1"])
                    self.assertEqual(Path.cwd(), workspace)
                    self.assertEqual(sys.path[0], str(workspace))
                    raise RuntimeError("interrupted")
        self.assertIs(sys.argv, original_argv)
        self.assertEqual(sys.path, original_path)
        self.assertEqual(Path.cwd(), original_cwd)

    def test_missing_raw_optimization_inputs_fail_before_any_solves(self):
        error = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            for relative in ("asml/config.json", "llm/reference_labels.json"):
                path = workspace / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}")
            with contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
                cli._check_optimization_inputs(cli.build_parser(), workspace, "asml")
        self.assertIn("download-data", error.getvalue())
        self.assertIn("make smoke", error.getvalue())


if __name__ == "__main__":
    unittest.main()
