"""Evaluate independently, deduplicate action trees only after execution."""
from __future__ import annotations

from query_policy.experiment import rollout
from query_policy.solver import Planner
from .common import canonical,sha256,close,read_lines,write_lines,BASELINES


def compact_tree(public,result):
    return {"public_sha256":sha256(canonical(public)),
            "nodes":[[n[k] for k in ("history","probability","action","milp_calls","commit_plan","terminal_loss")] for n in result["nodes"]]}


def evaluate(tasks,models,output=None,verbose=False):
    outcomes=[];trees={};references=[]
    for index,t in enumerate(tasks):
        model=Planner(t["public"]);reference=model.value((-1,)*model.k,model.k)[0]
        references.append({"id":t["id"],"optimal_expected_loss":reference,"reference_milp_calls":model.calls})
        methods=[*models,*[{"method":m,"seed":None,"sha256":None,"parameters":None} for m in BASELINES]]
        for entry in methods:
            result=rollout(t["public"],entry["method"],entry["parameters"])
            tree=compact_tree(t["public"],result);identity=sha256(canonical(tree))
            trees[identity]=tree
            row={k:result[k] for k in ("expected_loss","expected_queries","expected_milp_calls")}
            row.update(id=t["id"],method=entry["method"],seed=entry["seed"],model_sha256=entry["sha256"],
                       tree_sha256=identity,optimal_expected_loss=reference,
                       regret=(result["expected_loss"]-reference)/max(1.,reference))
            if row["regret"] < -1e-7:raise ValueError("better_than_exact_reference")
            outcomes.append(row)
        if verbose and (index+1)%50==0:
            print(f"evaluated contexts {index+1}/{len(tasks)}",flush=True)
    tree_rows=[{"sha256":k,**v} for k,v in sorted(trees.items())]
    if output is not None:
        write_lines(output/"outcomes.jsonl",outcomes);write_lines(output/"trees.jsonl",tree_rows)
        write_lines(output/"references.jsonl",references)
    return outcomes,tree_rows,references


def check_tree(public,saved,fresh):
    if saved["public_sha256"]!=fresh["public_sha256"] or len(saved["nodes"])!=len(fresh["nodes"]):
        raise ValueError("tree_context_or_coverage")
    model=Planner(public)
    for old,new in zip(saved["nodes"],fresh["nodes"]):
        a,b=list(old),list(new);old_plan,new_plan=a.pop(4),b.pop(4)
        if old[2]==-1:
            close(model.shipping(old_plan,tuple(old[0]))["loss"],new[5])
        elif old_plan is not None:raise ValueError("plan_before_commit")
        close(a,b)


def verify_evaluation(path,tasks,models,verbose=False):
    saved=read_lines(path/"outcomes.jsonl");saved_trees=read_lines(path/"trees.jsonl")
    by_hash={}
    for tree in saved_trees:
        payload={k:v for k,v in tree.items() if k!="sha256"};key=tree["sha256"]
        if key in by_hash or sha256(canonical(payload))!=key:raise ValueError("tree_hash_or_duplicate")
        by_hash[key]=payload
    fresh,trees,references=evaluate(tasks,models,verbose=verbose)
    if len(saved)!=len(fresh):raise ValueError("outcome_coverage")
    fresh_trees={t["sha256"]:{k:v for k,v in t.items() if k!="sha256"} for t in trees}
    contexts={t["id"]:t["public"] for t in tasks};used=set()
    for old,new in zip(saved,fresh):
        a,b=dict(old),dict(new);key=a.pop("tree_sha256");fresh_key=b.pop("tree_sha256")
        close(a,b)
        check_tree(contexts[new["id"]],by_hash[key],fresh_trees[fresh_key]);used.add(key)
    if used!=set(by_hash):raise ValueError("unused_tree")
    close(read_lines(path/"references.jsonl"),references)
    return fresh
