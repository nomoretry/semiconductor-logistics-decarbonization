"""Development-only tool-workflow difficulty audit, never a final RL benchmark."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
import tempfile

import numpy as np

from shared.experiments import config, planning_inputs, synthetic_orders
from .data import canonical_bytes, validate_dataset
from .rules import extract_notice
from .tool_env import ToolWorkflowEnv, run_fixed_workflow

ROOT = Path(__file__).resolve().parents[1]


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def run_audit(dataset_path: Path, output: Path, tasks: int = 200,
              seed: int = 20261030) -> dict:
    if type(tasks) is not int or tasks < 1:
        raise ValueError("tasks must be positive")
    dataset_path = dataset_path.resolve()
    output = output.resolve()
    if not dataset_path.is_relative_to(ROOT):
        raise ValueError("Audit dataset must be inside this project for portable input identity")
    dataset = json.loads(dataset_path.read_text())
    validate_dataset(dataset)
    cases = dataset["splits"]["development"]
    rng = random.Random(seed)
    base = config("asml")
    output.mkdir(parents=True, exist_ok=True)
    task_rows, results, runtime_rows = [], [], []
    method_names = ["fixed_workflow_rules", "fixed_workflow_reference_upper_bound"]
    aggregates = {name: {"task_success": 0, "successful_shipping": 0,
        "correct_handoff": 0, "unnecessary_handoff": 0, "steps": 0,
        "solver_calls": 0, "ready_cases": 0} for name in method_names}
    trace_path = output / "traces.jsonl"
    with trace_path.open("wb") as trace_stream:
        for index in range(tasks):
            case = cases[rng.randrange(len(cases))]
            order_seed = seed + 100000 + index
            orders = synthetic_orders(base, order_seed)
            args, _ = planning_inputs(base, orders)
            initial = np.asarray(args["initial_inventory"]).copy()
            task_id = f"workflow-development-{index:05d}"
            task_rows.append({"task_id": task_id, "source_notice_id": case["id"],
                "event_id": case["event_id"], "template_family_id": case["template_family_id"],
                "order_seed": order_seed, "orders_sha256": digest(orders.tolist()),
                "initial_inventory": initial.tolist(), "synthetic": True})
            reference = copy.deepcopy(case["reference"])
            extractors = {
                "fixed_workflow_rules": extract_notice,
                "fixed_workflow_reference_upper_bound": lambda text, context=None, value=reference: copy.deepcopy(value),
            }
            for method, extractor in extractors.items():
                env = ToolWorkflowEnv(case, base, orders, extractor,
                    extractor_name=method, initial_inventory=initial)
                run = run_fixed_workflow(env)
                evaluation = run["evaluation"]
                trace_row = {"task_id": task_id, "method": method, "trace": run["trace"]}
                trace_stream.write(canonical_bytes(trace_row) + b"\n")
                results.append({"task_id": task_id, "method": method,
                    "evaluation": evaluation, "trace_sha256": digest(trace_row)})
                runtime_rows.append({"task_id": task_id, "method": method, **run["runtime"]})
                row = aggregates[method]
                for key in ["task_success", "successful_shipping", "correct_handoff", "unnecessary_handoff", "steps", "solver_calls"]:
                    row[key] += int(evaluation[key])
                row["ready_cases"] += int(evaluation["reference_status"] == "ready")
    for row in aggregates.values():
        row["runs"] = tasks
        row["task_success_rate"] = row["task_success"] / tasks
        row["shipping_success_among_ready"] = row["successful_shipping"] / row["ready_cases"] if row["ready_cases"] else None
        row["mean_steps"] = row["steps"] / tasks
    summary = {"schema_version": "tool-workflow-development-audit-v1",
        "scope": "known committed orders and announced synthetic NL_ocean delays",
        "development_only": True, "canonical_final_executed": False,
        "numerical_task_configurations": tasks, "method_runs": tasks * len(method_names),
        "distinct_development_notice_events": len({row["event_id"] for row in task_rows}),
        "distinct_render_families": len({row["template_family_id"] for row in task_rows}),
        "seed": seed, "dataset_sha256": dataset["manifest"]["dataset_sha256"],
        "methods": aggregates, "api_calls": 0, "trained_policies": 0,
        "rl_gate": {"passed": False,
            "reason": "This environment has a strong fixed tool sequence and no demonstrated substantive information or tool-budget trade-off. Extraction errors do not by themselves establish a PPO problem.",
            "next_requirement": "Evaluate a fixed LLM; then design and audit genuine information/tool-cost choices before BC/PPO."},
        "interpretation": "Reference input is an annotation upper bound, not an agent. Correct handoff is not successful shipping. Shared notice groups prevent treating every numerical configuration as a new independent text."}
    write_json(output / "tasks.json", task_rows)
    write_json(output / "outcomes.json", results)
    write_json(output / "runtime.json", runtime_rows)
    write_json(output / "summary.json", summary)
    manifest = {"schema_version": "workflow-audit-artifacts-v1", "api_calls": 0,
        "replay_command": f"python -m notice_benchmark.run_workflow_audit --tasks {tasks} --seed {seed} --output <new-directory>",
        "runtime_excluded_from_deterministic_comparison": True,
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [ROOT / "notice_benchmark/tool_env.py", ROOT / "notice_benchmark/rules.py",
                ROOT / "notice_benchmark/run_workflow_audit.py", ROOT / "shared/experiments.py",
                ROOT / "shared/optimization.py"]},
        "input_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [dataset_path, ROOT / "asml/config.json", ROOT / "data_sources/selected_emission_factors.json"]},
        "file_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.iterdir()) if p.is_file() and p.name != "manifest.json"}}
    write_json(output / "manifest.json", manifest)
    return summary


def verify_audit(dataset_path: Path, output: Path) -> dict:
    dataset_path = dataset_path.resolve()
    output = output.resolve()
    manifest = json.loads((output / "manifest.json").read_text())
    for field, parent in [("file_sha256", output), ("source_sha256", ROOT), ("input_sha256", ROOT)]:
        for relative, expected in manifest[field].items():
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe audit artifact path")
            target = parent / path
            if target.is_symlink() or not target.resolve().is_relative_to(parent.resolve()):
                raise ValueError("Audit path escapes its root")
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Audit identity mismatch: {relative}")
    summary = json.loads((output / "summary.json").read_text())
    with tempfile.TemporaryDirectory(prefix="notice-workflow-replay-") as temporary:
        replay = Path(temporary)
        run_audit(dataset_path, replay, summary["numerical_task_configurations"], summary["seed"])
        for name in ["tasks.json", "outcomes.json", "summary.json", "traces.jsonl"]:
            if (replay / name).read_bytes() != (output / name).read_bytes():
                raise ValueError(f"Deterministic tool replay mismatch: {name}")
    return {"verified": True, "development_tasks": summary["numerical_task_configurations"],
        "method_runs": summary["method_runs"], "walltime_compared": False, "api_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "benchmarks/notices_v1/dataset.json")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmark_results/workflow_development_v1")
    parser.add_argument("--tasks", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--verify", action="store_true", help="Hash-check and reexecute the existing development audit")
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_audit(args.dataset, args.output)))
        return
    result = run_audit(args.dataset, args.output, args.tasks, args.seed)
    print(json.dumps({key: result[key] for key in ["numerical_task_configurations", "method_runs", "distinct_development_notice_events", "methods", "rl_gate"]}))


if __name__ == "__main__":
    main()
