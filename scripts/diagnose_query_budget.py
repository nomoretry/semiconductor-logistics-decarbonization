"""Post-hoc worst-case inspection; never changes policies, thresholds or references."""
import argparse
import gzip
import json
from pathlib import Path

from notice_benchmark.api_runner import canonical_bytes, sha256
from scripts.audit_decision_scale import Planner
from budgeted_decision.audit import close


def diagnose(source, output=None):
    source = Path(source)
    summary = json.loads((source/"summary.json").read_text())
    primary_method = summary["gate"]["all"]["best_primary"]
    high_method = summary["gate"]["all"]["best_high"]
    rows = json.loads((source/"outcomes.json").read_text())
    worst = max((r for r in rows if r["budget"] == 13 and r["method"] == primary_method),
                key=lambda r: (r["regret"], r["id"]))
    task = next(t for t in json.loads((source/"tasks.json").read_text()) if t["id"] == worst["id"])
    archives = [json.loads(line) for line in gzip.decompress((source/"traces.jsonl.gz").read_bytes()).splitlines()]
    trace = next(t for t in archives if t["id"] == worst["id"])
    low = next(r for r in trace["runs"] if r["budget"] == 13 and r["method"] == primary_method)
    high = next(r for r in trace["runs"] if r["budget"] == 65 and r["method"] == high_method)
    high_nodes = {tuple(n["history"]): n for n in high["nodes"]}
    differences = [(n, high_nodes[tuple(n["history"])]) for n in low["nodes"]
                   if tuple(n["history"]) in high_nodes and n["action"] != high_nodes[tuple(n["history"])]["action"]]
    differences.sort(key=lambda pair: (-pair[0]["probability"], pair[0]["node"]))
    conditional = None
    if differences:
        left, right = differences[0]; h = tuple(left["history"]); public = task["public"]; oracle = Planner(public)
        spent = sum(f for f, x in zip(public["query_fees"], h) if x != -1)
        remaining = public["max_queries"]-sum(x != -1 for x in h)
        candidates = []
        for i in oracle.legal(h):
            candidates.append({"query": i, "fee": public["query_fees"][i],
                "money_left_after_query": public["query_budget"]-spent-public["query_fees"][i],
                "one_step_cost": public["query_fees"][i]+sum(w*oracle.terminal(n)[0] for w, n in oracle.branch(h, i)),
                "full_continuation_cost": public["query_fees"][i]+sum(w*oracle.value(n, remaining-1)[0] for w, n in oracle.branch(h, i))})
        conditional = {"history": list(h), "probability": left["probability"],
                       "low_budget_action": left["action"], "high_budget_action": right["action"],
                       "money_before_query": public["query_budget"]-spent, "candidates": candidates}
    result = {"scope": "post_hoc_development_diagnostic_not_new_test",
              "selection": "Largest primary-budget regret of the predeclared strongest-mean public method",
              "benchmark_manifest_sha256": sha256((source/"manifest.json").read_bytes()),
              "script_sha256": sha256(Path(__file__).read_bytes()), "id": worst["id"],
              "low_budget": {k: low[k] for k in ("method", "budget", "expected_loss", "expected_milp_calls", "expected_queries", "regret", "sample")},
              "high_budget": {k: high[k] for k in ("method", "budget", "expected_loss", "expected_milp_calls", "expected_queries", "regret", "sample")},
              "exact_reference_loss": trace["reference_loss"], "first_shared_history_disagreement": conditional}
    if output is not None:
        output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(canonical_bytes(result)+b"\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=Path("benchmark_results/query_budget_development"))
    p.add_argument("--output", type=Path, default=Path("benchmark_results/query_budget_diagnostic/worst_case.json"))
    p.add_argument("--verify", action="store_true")
    a = p.parse_args(); r = diagnose(a.source, None if a.verify else a.output)
    if a.verify and not close(r, json.loads(a.output.read_text())):
        raise ValueError("diagnostic_replay_mismatch")
    print(json.dumps({"id": r["id"], "scope": r["scope"], "verified": a.verify}))


if __name__ == "__main__":main()
