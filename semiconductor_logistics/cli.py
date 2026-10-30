"""Dispatch research commands without changing the archived implementations.

An editable install in the repository is the primary workflow. Wheels contain
Python modules, not research datasets, configurations or evidence. A wheel can
operate on a checkout selected with ``--workspace``; help is available anywhere.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import runpy
import sys
from typing import Iterator, Sequence

from . import __version__


COMMANDS = {
    "optimize": ("scripts.run_experiments", "Run the company-inspired MILP grids"),
    "generate": ("notice_benchmark.data", "Generate synthetic development and test notices"),
    "evaluate": ("notice_benchmark.run_offline", "Evaluate frozen offline notice rules"),
    "workflow-audit": ("notice_benchmark.run_workflow_audit", "Run or verify the development tool workflow audit"),
    "verify-run": ("notice_benchmark.verify_offline", "Read-only verification of the frozen offline run"),
    "api": ("notice_benchmark.api_runner", "Estimate API cost; live calls require --execute and a budget"),
    "score-api": ("scripts.score_notice_api", "Verify and score an existing API ledger offline"),
    "compare-api": ("scripts.compare_notice_api", "Compare a verified heldout API run with frozen rules"),
    "real-notices": ("real_notice_eval", "Review and evaluate official notice excerpts"),
    "decision-audit": ("decision_benchmark.audit", "Audit information costs and logistics decisions"),
    "coupled-audit": ("coupled_decision.audit", "Audit shared freight capacities and information budgets"),
    "scale-audit": ("scripts.audit_decision_scale", "Measure MILP and query planning at larger development sizes"),
    "query-budget": ("budgeted_decision.audit", "Audit planners under the same per-decision MILP call caps"),
    "notice-facts": ("notice_facts", "Evaluate source quantities without inferring internal routes"),
    "report": ("scripts.create_reports", "Generate Markdown research reports from saved results"),
    "sensitivity": ("scripts.run_sensitivity", "Run the separate assumption sensitivity study"),
    "download-data": ("scripts.download_source_data", "Download and hash-check the two public source datasets"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="semiconductor-logistics",
        description="Reproducible Python logistics optimization and notice benchmarks.",
        epilog=("Use COMMAND --help for experiment options. Workloads use a repository "
                "checkout; wheels do not bundle datasets or archived evidence. "
                "API estimation is offline unless --execute is explicitly supplied."),
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--workspace", type=Path, help="Research checkout (default: current checkout or editable install)")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for command, (_, description) in COMMANDS.items():
        # Delegated parsers own their --help and their original options.
        own_options = command in {"optimize", "sensitivity", "report"}
        subparser = subparsers.add_parser(
            command, help=description, description=description,
            add_help=own_options, allow_abbrev=False,
        )
        subparser.add_argument("--workspace", type=Path, default=argparse.SUPPRESS,
                               help="Research checkout (may also be supplied before COMMAND)")
        if command in {"optimize", "sensitivity"}:
            subparser.add_argument("--project", choices=("asml", "marvell", "both"), default="both")
        if command == "optimize":
            subparser.add_argument("--smoke", action="store_true",
                                   help="One synthetic seed per scenario; no external demand analogue")
    return parser


def _is_workspace(path: Path) -> bool:
    return all((path / relative).is_file() for relative in (
        "notice_benchmark/data.py", "shared/optimization.py", "scripts/run_experiments.py",
        "data_sources/source_manifest.json", "benchmarks/notices_v1/dataset.json",
    ))


def _find_workspace(explicit: Path | None) -> Path | None:
    if explicit is not None:
        resolved = explicit.expanduser().resolve()
        return resolved if _is_workspace(resolved) else None
    cwd = Path.cwd().resolve()
    candidates = (cwd, *cwd.parents, Path(__file__).resolve().parents[1])
    return next((path for path in candidates if _is_workspace(path)), None)


@contextmanager
def _execution_context(module: str, argv: Sequence[str], workspace: Path | None) -> Iterator[None]:
    """Give legacy argparse entry points explicit argv and restore process state."""
    saved_argv, saved_path, saved_cwd = sys.argv, sys.path[:], Path.cwd()
    try:
        sys.argv = [module, *argv]
        if workspace is not None:
            sys.path.insert(0, str(workspace))
            os.chdir(workspace)
        yield
    finally:
        sys.argv = saved_argv
        sys.path[:] = saved_path
        os.chdir(saved_cwd)


def _run_module(module: str, argv: Sequence[str], workspace: Path | None) -> int:
    with _execution_context(module, argv, workspace):
        try:
            runpy.run_module(module, run_name="__main__", alter_sys=True)
        except SystemExit as error:
            if error.code is None:
                return 0
            if isinstance(error.code, int):
                return error.code
            print(error.code, file=sys.stderr)
            return 1
    return 0


def _check_optimization_inputs(parser: argparse.ArgumentParser, workspace: Path, project: str) -> None:
    projects = ("asml", "marvell") if project == "both" else (project,)
    required = [workspace / name / "config.json" for name in projects]
    required.append(workspace / "llm/reference_labels.json")
    missing = [str(path.relative_to(workspace)) for path in required if not path.is_file()]
    if missing:
        parser.error("Missing workspace inputs: " + ", ".join(missing))
    # The frozen grid records both raw-source hashes even in synthetic smoke
    # mode. Preserve its provenance behavior instead of fabricating those hashes.
    source_paths = ("data_sources/raw/car_parts_dataset_with_missing_values.zip",
                    "data_sources/raw/ghg_factors_2026_flat_revised.xlsx")
    if any(not (workspace / relative).is_file() for relative in source_paths):
        parser.error("Optimization requires the recorded source files for its manifest. "
                     "Run semiconductor-logistics download-data in this workspace first. "
                     "The offline `make smoke` and `make test` do not need these downloads.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args, forwarded = parser.parse_known_args(argv)
    if args.command in {"optimize", "sensitivity", "report"} and forwarded:
        parser.error("unrecognized arguments: " + " ".join(forwarded))
    help_requested = any(option in {"--help", "-h"} for option in forwarded)
    workspace = _find_workspace(args.workspace)
    if args.workspace is not None and workspace is None:
        parser.error(f"Not a research checkout: {args.workspace}")
    if workspace is None and not help_requested:
        parser.error(f"`{args.command}` needs the research checkout. Run from the repository "
                     "or pass --workspace /path/to/checkout; datasets, configurations and "
                     "archived evidence are not bundled in the wheel.")
    if args.command == "optimize":
        _check_optimization_inputs(parser, workspace, args.project)
        forwarded = ["--project", args.project, *(["--smoke"] if args.smoke else [])]
    elif args.command == "sensitivity":
        forwarded = ["--project", args.project]
    return _run_module(COMMANDS[args.command][0], forwarded, workspace)
