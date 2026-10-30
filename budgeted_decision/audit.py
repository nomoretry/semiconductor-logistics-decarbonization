"""Evaluate full policy trees; compress repeated plans without sharing policy caches."""
from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path
import platform
import random
import time

from notice_benchmark.api_runner import canonical_bytes as canonical, sha256
from scripts.audit_decision_scale import Planner, generate
from .planning import Decision

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "budgeted_decision/config.json"


def configuration():
    return json.loads(CONFIG.read_text())


def tasks(smoke=False):
    cfg = configuration()
    grid = [(4, 2, 61)] if smoke else [(n, k, s) for n in cfg["sku_counts"] for k in cfg["delay_bits"] for s in cfg["seeds"]]
    result = []
    for n, k, seed in grid:
        public = generate(n, k, seed)
        rng = random.Random(seed+n*17+k*31)
        result.append({"id": f"budget-{n}-{k}-{seed}", "cohort": "old18" if seed in cfg["old_seeds"] else "new36",
                       "public": public, "private_evaluation_bits": [int(rng.random()<p) for p in public["prior"]]})
    return result


def evaluate(public, method, budget, backend_factory=None):
    nodes, timing = [], []
    def visit(h, inherited_cache, probability):
        index = len(nodes)
        start = time.perf_counter()
        backend = backend_factory(index) if backend_factory else None
        session = Decision(public, budget, inherited_cache, backend)
        row, after = session.choose(h, method)
        timing.append({"node": index, "probability": probability, "wall_seconds": time.perf_counter()-start})
        row.update(node=index, probability=probability, children=[])
        nodes.append(row)
        action = row["action"]
        if action == -1:
            return index, row["terminal_loss"], row["milp_calls"], row["milp_calls"], 0.
        if action not in row["legal_queries"]:
            raise ValueError("illegal_query")
        loss = public["query_fees"][action]
        calls, maximum, queries = float(row["milp_calls"]), row["milp_calls"], 1.
        child_maximum = 0
        for answer, weight in ((0, 1-public["prior"][action]), (1, public["prior"][action])):
            nxt = list(h); nxt[action] = answer
            child, cost, expected_calls, max_calls, q = visit(tuple(nxt), after, probability*weight)
            row["children"].append(child)
            loss += weight*cost; calls += weight*expected_calls; queries += weight*q
            child_maximum = max(child_maximum, max_calls)
        return index, loss, calls, maximum+child_maximum, queries
    _, loss, calls, maximum, queries = visit((-1,)*public["delay_bits"], {}, 1.)
    return {"method": method, "budget": budget, "expected_loss": loss,
            "expected_milp_calls": calls, "max_path_milp_calls": maximum,
            "expected_queries": queries, "nodes": nodes}, timing


def sampled_path(public, truth, nodes):
    model = Planner(public)
    index = fees = calls = 0
    path = []
    while True:
        node = nodes[index]; path.append(index); calls += node["milp_calls"]
        if node["action"] == -1:
            physical = model.shipping(node["commit_plan"], tuple(truth))
            return {"nodes": path, "milp_calls": calls, "query_fees": fees,
                    "physical": physical, "realized_loss": fees+physical["loss"]}
        fees += public["query_fees"][node["action"]]
        index = node["children"][truth[node["action"]]]


def compress(result, pool, pool_index):
    """Evidence-only deduplication; never consulted by the planning policy."""
    for node in result["nodes"]:
        ids = []
        for solve in node.pop("solves"):
            identity = canonical(solve)
            if identity not in pool_index:
                pool_index[identity] = len(pool)
                pool.append(solve)
            ids.append(pool_index[identity])
        node["solve_ids"] = ids


def summarize(rows, smoke=False):
    cfg = configuration(); result = {}
    for cohort in ("all", "old18", "new36"):
        group = rows if cohort == "all" else [r for r in rows if r["cohort"] == cohort]
        if not group:
            continue
        cells = {}
        for budget in cfg["budgets"]:
            cells[str(budget)] = {}
            for method in cfg["methods"]:
                selected = [r for r in group if r["budget"] == budget and r["method"] == method]
                if not selected:
                    continue
                cells[str(budget)][method] = {
                    "tasks": len(selected), "mean_regret": sum(r["regret"] for r in selected)/len(selected),
                    "max_regret": max(r["regret"] for r in selected),
                    "fraction_at_least_2pct": sum(r["regret"] >= cfg["gate_case_regret"] for r in selected)/len(selected),
                    "expected_milp_calls": sum(r["expected_milp_calls"] for r in selected)/len(selected),
                    "max_path_milp_calls": max(r["max_path_milp_calls"] for r in selected),
                    "expected_queries": sum(r["expected_queries"] for r in selected)/len(selected)}
        result[cohort] = cells
    gates = {}
    if not smoke:
        for cohort in ("all", "new36"):
            primary = result[cohort][str(cfg["primary_budget"])]
            higher = result[cohort][str(cfg["comparison_budget"])]
            best = min(primary, key=lambda m: (primary[m]["mean_regret"], cfg["methods"].index(m)))
            best_high = min(higher, key=lambda m: (higher[m]["mean_regret"], cfg["methods"].index(m)))
            low_gap, high_gap = primary[best]["mean_regret"], higher[best_high]["mean_regret"]
            reduction = (low_gap-high_gap)/low_gap if low_gap > 1e-12 else 0.
            passed = (low_gap >= cfg["gate_mean_regret"] and primary[best]["fraction_at_least_2pct"] >= cfg["gate_case_fraction"]
                      and reduction >= cfg["gate_relative_gap_reduction"])
            gates[cohort] = {"best_primary": best, "best_high": best_high, "primary_mean_regret": low_gap,
                             "primary_fraction_at_least_2pct": primary[best]["fraction_at_least_2pct"],
                             "relative_gap_reduction": reduction, "passed": passed}
    return {"scope": cfg["scope"], "tasks": len({r["id"] for r in rows}), "runs": len(rows),
            "all_completed_paths_legal": True, "cohorts": result, "gate": gates,
            "bc_feasibility_gate_passed": bool(gates) and all(g["passed"] for g in gates.values()),
            "trained": False, "final_test_frozen": False,
            "budget_unit": "actual_uncached_MILP_calls_per_decision_not_wall_time"}


def source_identity():
    paths = ("budgeted_decision/planning.py", "budgeted_decision/audit.py", "budgeted_decision/config.json",
             "scripts/audit_decision_scale.py", "notice_benchmark/api_runner.py", "docs/query_budget_protocol.md")
    return {name: sha256((ROOT/name).read_bytes()) for name in paths}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value)+b"\n")


def run(output, smoke=False):
    import scipy
    output = Path(output)
    if (output/"manifest.json").exists():
        raise ValueError("existing_evidence_not_overwritten")
    cfg = configuration(); task_rows = tasks(smoke); rows = []; runtime = []; files = []; traces = []
    Planner(generate(2, 2, 1)).terminal((-1, -1))  # common startup only
    for task in task_rows:
        public = task["public"]
        reference = Planner(public).value((-1,)*public["delay_bits"], public["max_queries"])[0]
        pool, pool_index, runs = [], {}, []
        for budget in cfg["budgets"]:
            for method in cfg["methods"]:
                result, times = evaluate(public, method, budget)
                result["sample"] = sampled_path(public, task["private_evaluation_bits"], result["nodes"])
                regret = (result["expected_loss"]-reference)/max(1., reference)
                if regret < -1e-8 or not math.isfinite(regret):
                    raise ValueError("invalid_regret")
                result["regret"] = max(0., regret)
                rows.append({"id": task["id"], "cohort": task["cohort"], "reference_loss": reference,
                             **{k: v for k, v in result.items() if k not in ("nodes", "sample")}})
                runtime.append({"id": task["id"], "method": method, "budget": budget,
                                "root_wall_seconds": times[0]["wall_seconds"],
                                "expected_path_wall_seconds": sum(t["probability"]*t["wall_seconds"] for t in times)})
                compress(result, pool, pool_index); runs.append(result)
        traces.append({"id": task["id"], "reference_loss": reference, "solutions": pool, "runs": runs})
    summary = summarize(rows, smoke)
    for name, value in (("tasks.json", task_rows), ("outcomes.json", rows), ("summary.json", summary)):
        write(output/name, value); files.append(name)
    (output/"traces.jsonl.gz").write_bytes(gzip.compress(b"".join(canonical(t)+b"\n" for t in traces), mtime=0))
    files.append("traces.jsonl.gz")
    write(output/"runtime.json", {"python": platform.python_version(), "scipy": scipy.__version__, "runs": runtime,
                                 "note": "One machine/run; diagnostic only, not an equal-wall-time comparison or total audit duration."})
    write(output/"manifest.json", {"version": cfg["version"], "smoke": smoke, "sources": source_identity(),
                                   "files": {n: sha256((output/n).read_bytes()) for n in files},
                                   "runtime_excluded": "Machine-dependent diagnostics are not deterministic evidence."})
    return summary


def close(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, abs_tol=1e-6, rel_tol=1e-10)
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(close(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def verify(output):
    """Independently optimize each stored state, then replay the exact call ledger."""
    output = Path(output); manifest = json.loads((output/"manifest.json").read_text())
    if manifest["sources"] != source_identity() or type(manifest["smoke"]) is not bool:
        raise ValueError("source_or_scope_mismatch")
    expected_tasks = tasks(manifest["smoke"]); cfg = configuration()
    expected_files = {"tasks.json", "outcomes.json", "summary.json", "traces.jsonl.gz"}
    if manifest.get("version") != cfg["version"] or set(manifest["files"]) != expected_files:
        raise ValueError("manifest_coverage_mismatch")
    for name, digest in manifest["files"].items():
        if (output/name).is_symlink() or sha256((output/name).read_bytes()) != digest:
            raise ValueError("file_digest_mismatch")
    if json.loads((output/"tasks.json").read_text()) != expected_tasks:
        raise ValueError("task_regeneration_mismatch")
    archives = [json.loads(line) for line in gzip.decompress((output/"traces.jsonl.gz").read_bytes()).splitlines()]
    if len(archives) != len(expected_tasks):raise ValueError("trace_coverage_mismatch")
    rows = []
    for task, archive in zip(expected_tasks, archives):
        public = task["public"]; oracle = Planner(public)
        reference = oracle.value((-1,)*public["delay_bits"], public["max_queries"])[0]
        if archive["id"] != task["id"] or not close(reference, archive["reference_loss"]):
            raise ValueError("reference_mismatch")
        pool = archive["solutions"]
        for solution in pool:
            h = tuple(solution["history"])
            if (len(h) != oracle.k or any(type(x) is not int or x not in (-1, 0, 1) for x in h)
                    or sum(x != -1 for x in h) > public["max_queries"]
                    or sum(f for f, x in zip(public["query_fees"], h) if x != -1) > public["query_budget"]):
                raise ValueError("invalid_cached_history")
            if not close(oracle.shipping(solution["plan"], h)["loss"], solution["loss"]) or not close(oracle.terminal(h)[0], solution["loss"]):
                raise ValueError("nonoptimal_or_infeasible_cached_plan")
        combinations = [(b, m) for b in cfg["budgets"] for m in cfg["methods"]]
        if [(r["budget"], r["method"]) for r in archive["runs"]] != combinations:
            raise ValueError("run_coverage_mismatch")
        used = set()
        for saved in archive["runs"]:
            consumed = {}
            def factory(index):
                ids = saved["nodes"][index]["solve_ids"]
                consumed[index] = 0
                def replay(h):
                    position = consumed[index]
                    if position >= len(ids):raise ValueError("missing_solve_record")
                    ident = ids[position]
                    if type(ident) is not int or not 0 <= ident < len(pool):raise ValueError("invalid_solution_id")
                    solution = pool[ident]
                    if list(h) != solution["history"]:raise ValueError("solve_order_mismatch")
                    consumed[index] += 1; used.add(ident)
                    return solution["loss"], tuple(tuple(v for v in row) for row in solution["plan"])
                return replay
            result, _ = evaluate(public, saved["method"], saved["budget"], factory)
            result["sample"] = sampled_path(public, task["private_evaluation_bits"], result["nodes"])
            result["regret"] = max(0., (result["expected_loss"]-reference)/max(1., reference))
            if len(result["nodes"]) != len(saved["nodes"]):raise ValueError("node_coverage_mismatch")
            for node in result["nodes"]:
                index = node["node"]
                if consumed[index] != len(saved["nodes"][index]["solve_ids"]):raise ValueError("unused_solve_record")
                node.pop("solves");node["solve_ids"] = saved["nodes"][index]["solve_ids"]
            if not close(result, saved):raise ValueError("policy_replay_mismatch")
            rows.append({"id": task["id"], "cohort": task["cohort"], "reference_loss": reference,
                         **{k: v for k, v in result.items() if k not in ("nodes", "sample")}})
        if used != set(range(len(pool))):raise ValueError("unused_solution_pool_entry")
    if not close(rows, json.loads((output/"outcomes.json").read_text())):
        raise ValueError("outcome_mismatch")
    summary = summarize(rows, manifest["smoke"])
    if not close(summary, json.loads((output/"summary.json").read_text())):
        raise ValueError("summary_mismatch")
    return {"verified": True, "tasks": summary["tasks"], "runs": summary["runs"],
            "bc_feasibility_gate_passed": summary["bc_feasibility_gate_passed"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/query_budget"))
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = verify(args.output) if args.verify else run(args.output, args.smoke)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":main()
