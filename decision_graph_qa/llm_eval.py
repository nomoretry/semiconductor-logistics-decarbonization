"""CLI and offline cost projections for the preregistered model evaluation."""
from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .llm.data import (
    CURRENT,
    PROTOCOLS,
    LlmError,
    Task,
    load_config,
    plan,
    require_open,
    results_root,
    terminal_records,
)
from .llm.transport import Client, Prices

RATE_NAMES = ("input", "cached-input", "cache-write", "output")
PHASES = ("smoke", "pilot", "main", "p3")


def _dollars(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("expected a finite, nonnegative USD amount") from None
    if not result.is_finite() or result < 0:
        raise argparse.ArgumentTypeError("expected a finite, nonnegative USD amount")
    return result


def _positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return result


def _call_limit(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("expected a nonnegative call limit")
    return result


def _workers(value: str) -> int:
    result = _positive_int(value)
    if result > 32:
        raise argparse.ArgumentTypeError("expected at most 32 workers")
    return result


def _timeout(value: str) -> float:
    result = float(value)
    if not 0 < result < float("inf"):
        raise argparse.ArgumentTypeError("expected a finite positive timeout")
    return result


def _wait_seconds(value: str) -> float:
    result = float(value)
    if not 0 <= result < float("inf"):
        raise argparse.ArgumentTypeError("expected a finite nonnegative wait")
    return result


def _add_prices(parser: argparse.ArgumentParser, prefix: str = "", *, required: bool = False) -> None:
    for name in RATE_NAMES:
        parser.add_argument(f"--{prefix}{name}-usd-per-m", type=_dollars, required=required)


def _prices(args: argparse.Namespace, prefix: str = "", *, required: bool = True) -> Prices | None:
    values = [getattr(args, f"{prefix}{name}_usd_per_m".replace("-", "_")) for name in RATE_NAMES]
    if not required and all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise LlmError("all four USD-per-million-token rates are required")
    return Prices(*values)


def _add_scope(parser: argparse.ArgumentParser, phases: tuple[str, ...] | None) -> None:
    if phases:
        parser.add_argument("--phase", choices=phases, required=True)
    parser.add_argument("--arm", choices=("S", "A"), required=True)
    parser.add_argument("--size", choices=("full", "half"))


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--protocol", choices=sorted(PROTOCOLS), default=CURRENT,
                        help="protocol version of the questions, configuration and results root")
    parser.add_argument("--root", type=Path, help="results root, by default the one of the protocol version")


def register(subparsers: argparse._SubParsersAction) -> None:
    run = subparsers.add_parser("llm-run", help="check, preview or run a model evaluation phase")
    phase = run.add_mutually_exclusive_group(required=True)
    phase.add_argument("--phase", choices=PHASES)
    phase.add_argument("--check", action="store_true")
    _add_scope(run, None)
    _add_root(run)
    _add_prices(run)
    _add_prices(run, "batch-")
    run.add_argument("--max-usd", type=_dollars)
    run.add_argument("--max-calls", type=_call_limit)
    run.add_argument("--workers", type=_workers, default=8)
    run.add_argument("--timeout", type=_timeout, default=3600)
    run.add_argument("--dry-run", action="store_true")

    batch = subparsers.add_parser("llm-batch", help="export, submit, fetch or import Batch evaluation")
    commands = batch.add_subparsers(dest="batch_command", required=True)
    export = commands.add_parser("export")
    _add_root(export)
    _add_scope(export, ("main", "p3"))
    export.add_argument("--pilot-root", type=Path, required=True)
    export.add_argument("--chunk-size", type=_positive_int, default=250)
    _add_prices(export, required=True)

    submit = commands.add_parser("submit")
    _add_root(submit)
    submit.add_argument("--file", type=Path, required=True)
    submit.add_argument("--max-usd", type=_dollars, required=True)
    _add_prices(submit, required=True)

    fetch = commands.add_parser("fetch")
    _add_root(fetch)
    fetch.add_argument("--batch-id")
    fetch.add_argument("--wait-seconds", type=_wait_seconds, default=0)

    load = commands.add_parser("import")
    _add_root(load)
    load.add_argument("files", type=Path, nargs="+")
    _add_prices(load, required=True)

    score = subparsers.add_parser("llm-score", help="grade and summarize recorded model replies")
    _add_root(score)
    _add_scope(score, ("pilot", "main", "p3"))

    prompts = subparsers.add_parser("llm-prompts", help="export and check the self-contained v2 questions offline")
    statements = prompts.add_subparsers(dest="prompts_command", required=True)
    home = PROTOCOLS["v2"].root
    write = statements.add_parser("export")
    write.add_argument("--out", type=Path, default=home / "prompts")
    for name in ("check", "replay"):
        command = statements.add_parser(name)
        command.add_argument("--prompts", type=Path, default=home / "prompts")
        command.add_argument("--out" if name == "check" else "--check", type=Path, default=home / "statement_check")
    reading = statements.add_parser("independent", help="repeat the program written from the question texts alone")
    reading.add_argument("--prompts", type=Path, default=home / "prompts")
    reading.add_argument("--dir", type=Path, default=home / "independent_reading")
    reading.add_argument("--limit", type=_positive_int, help="repeat the first N graphs only")
    reading.add_argument("--write", action="store_true", help="write the evidence instead of comparing with it")


def _projection(tasks: list[Task], prices: Prices, output_scenarios: list[int]) -> dict:
    input_chars = sum(task.input_characters for task in tasks)
    system_chars = sum(task.system_characters for task in tasks)
    typical = sum(task.input_tokens(3.5) for task in tasks)
    conservative = sum(task.input_tokens(3) for task in tasks)
    n = len(tasks)
    def cost(inputs: int, outputs: int) -> Decimal:
        return (inputs * prices.input + outputs * prices.output) / 1_000_000

    return {
        "calls": n,
        "prompt_characters": input_chars,
        "system_characters": system_chars,
        "prompt_tokens_typical": sum((2 * task.input_characters + 6) // 7 for task in tasks),
        "system_tokens_typical": sum((2 * task.system_characters + 6) // 7 for task in tasks),
        "prompt_tokens_conservative": sum((task.input_characters + 2) // 3 for task in tasks),
        "system_tokens_conservative": sum((task.system_characters + 2) // 3 for task in tasks),
        "input_tokens_typical": typical,
        "input_tokens_conservative": conservative,
        "worst_usd": sum((prices.worst(task) for task in tasks), Decimal(0)),
        "output_scenarios_usd": {
            out: {"typical_input": cost(typical, n * out), "conservative_input": cost(conservative, n * out)}
            for out in output_scenarios
        },
        "prices_usd_per_m": prices.as_dict(),
    }


def preview(
    config: dict, root: Path, tasks: list[Task], prices: Prices, *,
    phase: str, arm: str, size: str, batch_prices: Prices | None = None,
) -> dict:
    completed = terminal_records(root, tasks)
    new_tasks = [task for task in tasks if task.custom_id not in completed]
    scenarios = config["dry_output_tokens"]
    result = {
        "phase": phase, "arm": arm, "size": size if phase == "main" else None,
        "configured_model": config["arms"][arm]["request"]["model"],
        "record_only": config["arms"][arm]["record_only"],
        "max_output_tokens": config["arms"][arm]["request"]["max_output_tokens"],
        "planned_calls": len(tasks),
        "completed_here": sum(row["phase"] == phase for row in completed.values()),
        "reused_pilot_calls": sum(row["phase"] != phase for row in completed.values()),
        "new_calls": len(new_tasks),
        "token_estimate": "round up combined prompt and system characters per request, at 3.5 or 3 chars/token",
        "worst_cost_formula": "(conservative input tokens * input rate + maximum output tokens * output rate) / 1e6",
        "actual_cost_formula": (
            "(uncached input * input rate + cache reads * cached input rate + "
            "cache writes * cache write rate + output including reasoning * output rate) / 1e6"
        ),
        "synchronous": _projection(new_tasks, prices, scenarios),
    }
    projections = {"synchronous": prices}
    if batch_prices is not None:
        projections["batch"] = batch_prices
        result["batch"] = _projection(new_tasks, batch_prices, scenarios)
    if phase == "main":
        pilot = {task.custom_id: task.request_hash for task in plan(config, "pilot", arm)}
        reused = [task for task in new_tasks if pilot.get(task.custom_id) == task.request_hash]
        additional = [task for task in new_tasks if pilot.get(task.custom_id) != task.request_hash]
        result["if_remaining_pilot_tasks_finish"] = {
            "extra_reused_pilot_calls": len(reused),
            "new_calls": len(additional),
            **{key: _projection(additional, rate, scenarios) for key, rate in projections.items()},
        }
    return result


def _size(args: argparse.Namespace) -> str:
    if args.size is not None and args.phase != "main":
        raise LlmError("--size applies to the main phase")
    return args.size or "full"


def _run(config: dict, args: argparse.Namespace) -> dict:
    if args.check:
        if args.dry_run or args.size is not None:
            raise LlmError("--check takes an arm and sends a model availability request")
        model = config["arms"][args.arm]["request"]["model"]
        client = Client.from_env(args.timeout)
        reply = client.json("GET", f"models/{model}")
        return {"arm": args.arm, "model": model, "returned_model": client.redact(reply.get("id")), "available": True}

    size = _size(args)
    prices = _prices(args)
    assert prices is not None
    if not args.dry_run:
        require_open(args.protocol)
    if not args.dry_run and args.max_usd is None:
        raise LlmError("--max-usd is required for live execution")
    batch_prices = _prices(args, "batch_", required=False)
    if not args.dry_run and batch_prices is not None:
        raise LlmError("--batch- price options apply to dry runs")
    tasks = plan(config, args.phase, args.arm, size)
    if args.dry_run:
        return preview(
            config, args.root, tasks, prices, phase=args.phase, arm=args.arm,
            size=size, batch_prices=batch_prices,
        )
    from .llm.live import run

    return run(
        args.root, tasks, prices, max_usd=args.max_usd,
        max_calls=args.max_calls, workers=args.workers, timeout=args.timeout, config=config,
    )


def _batch(config: dict, args: argparse.Namespace) -> dict:
    from .llm import batch

    if args.batch_command == "fetch":
        return batch.fetch_batches(args.root, batch_id=args.batch_id, wait_seconds=args.wait_seconds)
    prices = _prices(args)
    assert prices is not None
    if args.batch_command in ("export", "submit"):
        require_open(args.protocol)
    if args.batch_command == "export":
        return batch.export_batches(
            config, args.root, phase=args.phase, arm=args.arm, size=_size(args),
            pilot_root=args.pilot_root, chunk_size=args.chunk_size, prices=prices,
        )
    if args.batch_command == "submit":
        return batch.submit_batch(config, args.root, file=args.file, max_usd=args.max_usd, prices=prices)
    return batch.import_batches(config, args.root, files=args.files, prices=prices)


def _statements(args: argparse.Namespace) -> dict:
    from .llm import statement, statement_check

    if args.prompts_command == "check":
        return statement_check.check(args.prompts, args.out)
    if args.prompts_command == "replay":
        return statement_check.replay(args.prompts, args.check)
    if args.prompts_command == "independent":
        from .llm import independent_reading

        if args.write:
            return independent_reading.check(args.prompts, args.dir)
        return independent_reading.replay(args.prompts, args.dir, args.limit)
    sources = load_config("v1")["sources"]
    return statement.export(statement_check.load_graphs({"sources": sources}), args.out,
                            {"manifest": sources["dataset_manifest"], "sha256": sources["dataset_sha256"]})


def dispatch(args: argparse.Namespace) -> None:
    if args.command == "llm-prompts":
        result = _statements(args)
    else:
        config = load_config(args.protocol)
        args.root = results_root(args.protocol, args.root)
        if args.command == "llm-run":
            result = _run(config, args)
        elif args.command == "llm-batch":
            result = _batch(config, args)
        else:
            from .llm.score import score

            result = score(args.root, args.phase, args.arm, _size(args), config=config)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, default=str), flush=True)
