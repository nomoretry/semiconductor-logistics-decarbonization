"""Post-hoc exact performance-difference decomposition; no policy tuning."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from notice_benchmark.api_runner import canonical_bytes,sha256
from query_policy.experiment import read_lines,close


def diagnose(bundle):
    bundle=Path(bundle)
    teachers={t["id"]:t for t in read_lines(bundle/"teachers.jsonl")}
    by_case={t["id"]:t for t in json.loads((bundle/"outcomes.json").read_text()) if t["method"]=="bc"}
    kinds={key:0. for key in ("premature_commit","unnecessary_query","query_choice")}
    cases=[]
    for trace in read_lines(bundle/"traces.jsonl"):
        if trace["method"]!="bc":continue
        states={tuple(s["history"]):s for s in teachers[trace["id"]]["states"]}; mistakes=[]
        for node in trace["nodes"]:
            state=states[tuple(node["history"])];q=state["q_values"]
            gap=q[node["action"]+1]-min(v for v in q if v is not None)
            if gap<=1e-7:continue
            kind=("premature_commit" if node["action"]==-1 else
                  "unnecessary_query" if state["positives"][0] else "query_choice")
            contribution=node["probability"]*gap
            kinds[kind]+=contribution
            mistakes.append({"history":node["history"],"action":node["action"],"kind":kind,
                "probability":node["probability"],"local_cost_gap":gap,"weighted_cost_gap":contribution,
                "optimal_actions":[i-1 for i,positive in enumerate(state["positives"]) if positive]})
        row=by_case[trace["id"]]
        excess=row["expected_loss"]-row["optimal_expected_loss"]
        close(sum(m["weighted_cost_gap"] for m in mistakes),excess)
        cases.append({"id":trace["id"],"regret":row["regret"],"expected_excess_cost":excess,"mistakes":mistakes})
    return {"scope":"posthoc_development_error_decomposition_not_new_training",
        "parent_manifest_sha256":sha256((bundle/"manifest.json").read_bytes()),
        "script_sha256":sha256(Path(__file__).read_bytes()),"cases":cases,
        "total_excess_cost_by_kind":kinds,"worst_regret_case":max(cases,key=lambda r:r["regret"])["id"],
        "identity":"sum visitation_probability * (Q_star(action)-V_star) = policy_cost - V_star(root)"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle",type=Path,default=Path("benchmark_results/query_bc_development"))
    p.add_argument("--output",type=Path,default=Path("benchmark_results/query_bc_diagnostic/errors.json"))
    p.add_argument("--verify",action="store_true");a=p.parse_args();result=diagnose(a.bundle)
    if a.verify:close(json.loads(a.output.read_text()),result)
    else:
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(canonical_bytes(result)+b"\n")
    print(json.dumps({"verified":a.verify,"contexts":len(result["cases"]),"total_excess_cost_by_kind":result["total_excess_cost_by_kind"]}))


if __name__=="__main__":main()
