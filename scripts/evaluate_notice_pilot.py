"""Replay saved in-session LLM extractions; never labels regex output as LLM.

The extraction generation itself occurred once in the ChatGPT agent session.
This script replays its saved outputs and benchmarks information handling on
synthetic notices. It does not call an API or regenerate an LLM response.
"""
from pathlib import Path
import argparse
import json
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shared.experiments import (ROOT, SEEDS, compile_notice, config, case_config,
    planning_inputs, solve_policy, synthetic_orders, write_json, sha256)


def replay_feasibility(c, demand, plan, cap):
    args,_ = planning_inputs(c,demand)
    q=plan["orders"]
    T,J,K=q.shape
    capacity_violations=int(np.sum(q.sum(axis=2)>args["route_capacity"]+1e-6))
    origins=list(dict.fromkeys(args["route_origin"]))
    for index,origin in enumerate(origins):
        js=[j for j,x in enumerate(args["route_origin"]) if x==origin]
        capacity_violations+=int(np.sum(q[:,js].sum(axis=(1,2))>args["origin_capacity"][:,index]+1e-6))
    receipts=args["pipeline_arrivals"].copy()
    stranded=0
    for t in range(T):
        for j in range(J):
            arrival=t+args["lead_times"][t,j]
            if arrival<T:receipts[arrival]+=q[t,j]
            else:stranded+=int(q[t,j].sum())
    net=args["initial_inventory"]+np.cumsum(receipts-demand,axis=0)
    inv,back=np.maximum(net,0),np.maximum(-net,0)
    emitted=float((q*args["unit_emissions"]).sum()+(inv*args["warehouse_emissions"]).sum())
    stock_shortfall=float(np.maximum(args["terminal_inventory"]-inv[-1],0).sum())
    executable=capacity_violations==0
    fill=1-float(np.minimum(demand,back).sum()/demand.sum()) if demand.sum() else 1.
    return dict(dispatch_executable=executable,capacity_violations=capacity_violations,
        terminal_stock_shortfall=stock_shortfall,stranded_units=stranded,
        backlog_unit_periods=float(back.sum()) if executable else None,
        on_time_fill_rate=fill if executable else None,
        actual_emissions=emitted if executable else None,
        carbon_cap_violated=bool(emitted>cap+1e-4) if executable else None,
        all_constraints_satisfied=bool(executable and np.all(back<1e-5) and stock_shortfall<1e-5 and stranded==0 and emitted<=cap+1e-4))


def main(projects=("asml","marvell")):
    refs=json.loads((ROOT/"llm/reference_labels.json").read_text())
    extracted=json.loads((ROOT/"llm/extracted_notices.json").read_text())
    checks=[]
    selected_keys=[key for key in refs if ("asml" if key.startswith("A") else "marvell") in projects]
    for key in selected_keys:
        expected,actual=refs[key],extracted.get(key)
        def canonical(value):
            if value is None:return None
            return {"status":value["status"],"changes":sorted(value["changes"],key=lambda x:json.dumps(x,sort_keys=True))}
        match=canonical(actual)==canonical(expected)
        checks.append(dict(id=key,exact_structure_match=match,expected_status=expected["status"]))
    if not all(x["exact_structure_match"] for x in checks):
        raise RuntimeError("Saved extraction does not match reference; inspect before optimization")
    rows=[]
    ids={"asml":{"ocean_delay":"A01","capacity_restriction":"A02"},
         "marvell":{"ocean_delay":"M01","capacity_restriction":"M02"}}
    for project in projects:
        for case,key in ids[project].items():
            actual=case_config(project,case,refs)
            inferred=compile_notice(config(project),extracted[key])
            assert actual==inferred
            for seed in SEEDS:
                demand=synthetic_orders(actual,seed)
                cost_reference,_=solve_policy(actual,demand,"cost_only")
                if not cost_reference["success"]:continue
                cap=.75*cost_reference["total_emissions"]
                oracle,_=solve_policy(actual,demand,"carbon_minus25",carbon_cap=cap)
                language,_=solve_policy(inferred,demand,"carbon_minus25",carbon_cap=cap)
                stale,_=solve_policy(config(project),demand,"carbon_minus25",carbon_cap=cap)
                for method,plan in (("correct_structured_input",oracle),("saved_LLM_extraction",language),("ignore_notice",stale)):
                    row=dict(project=project,case=case,seed=seed,method=method,planning_feasible=plan["success"])
                    if plan["success"]:
                        row.update(planned_cost=plan["total_cost"],**replay_feasibility(actual,demand,plan,cap))
                    rows.append(row)
    result=dict(
        provenance="One-off in-session ChatGPT-agent extraction, saved JSON; not external API inference",
        synthetic_notices=True, prompt_sha256=sha256(ROOT/"llm/extraction_prompt.txt"),
        notices_sha256=sha256(ROOT/"llm/notices.json"),output_sha256=sha256(ROOT/"llm/extracted_notices.json"),
        generation_batches=1, notices=len(checks), exact_matches=sum(x["exact_structure_match"] for x in checks),
        ambiguity_abstentions=sum(extracted[k]["status"]=="needs_clarification" for k in selected_keys),
        checks=checks, model_api="not_run",model_name="not independently selected or measured",
        limitations="Tiny templated synthetic pilot; no held-out prompt/model comparison, token/latency/cost benchmark or generalization claim. Numerical replays are reproducible; regeneration requires a new LLM session.",
        numerical_replays=rows)
    write_json(ROOT/"reports/notice_pilot.json",result)
    for project in projects:
        for method in ("correct_structured_input","saved_LLM_extraction","ignore_notice"):
            group=[r for r in rows if r["project"]==project and r["method"]==method]
            print(project,method,sum(r.get("all_constraints_satisfied",False) for r in group),"/",len(group),"all constraints satisfied")
    print("Extraction pilot:",result["exact_matches"],"/",len(checks),"; clarification:",result["ambiguity_abstentions"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",choices=["asml","marvell","both","auto"],default="auto")
    args=parser.parse_args()
    available=tuple(x for x in ("asml","marvell") if (ROOT/x/"config.json").exists())
    selected=("asml","marvell") if args.project=="both" else available if args.project=="auto" else (args.project,)
    main(selected)
