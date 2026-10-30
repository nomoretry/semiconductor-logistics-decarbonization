"""Train, evaluate and independently reexecute a shared-initialization PPO pilot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import tempfile
import time

from notice_benchmark.api_runner import canonical_bytes as canonical, sha256
from query_policy.experiment import (close, read_lines, rollout, source_identity as bc_sources,
                                     verify_trace, write, write_lines)
from query_policy.solver import Planner
from scripts.audit_decision_scale import generate

ROOT = Path(__file__).resolve().parents[1]
BC_ROOT = ROOT/"benchmark_results/query_bc_development"
BC_SHA = "ca83ee84ba78c95282be0a7da878dc4b18bec1a08a4e8459f379527befbef7f4"
METHODS = ("bc","ppo_selected","ppo_last","lookahead_two_13","iterative_dp_65")
FILES = ("config.json","tasks.json","initial.json","selected.json","last.json","training.json",
         "episodes.jsonl","references.json","traces.jsonl","outcomes.json","summary.json","runtime.json")


def config(smoke=False):
    cfg = json.loads((ROOT/"query_ppo/config.json").read_text())
    if smoke:
        cfg.update(iterations=2,episodes_per_context=1,update_epochs=2,evaluate_every=1)
    return cfg


def initial_actor():
    from query_policy.model import deserialize
    path = BC_ROOT/"checkpoint.json"
    if sha256(path.read_bytes()) != BC_SHA:
        raise ValueError("frozen_bc_checkpoint_mismatch")
    return deserialize(json.loads(path.read_text()),32)


def tasks(cfg, smoke=False):
    old_bc = json.loads((BC_ROOT/"tasks.json").read_text())
    old_budget = json.loads((ROOT/"benchmark_results/query_budget_development/tasks.json").read_text())
    identities = {sha256(canonical(t["public"])) for t in [*old_bc,*old_budget]}
    result = [t for t in old_bc if t["split"] in ("train","dev")]
    if smoke:
        result = [next(t for t in result if t["split"]==split) for split in ("train","dev")]
    for n in ([4] if smoke else [4,8,12]):
        for k in ([2] if smoke else [2,4,6]):
            for seed in (cfg["pilot_seeds"][:1] if smoke else cfg["pilot_seeds"]):
                public = generate(n,k,seed);identity = sha256(canonical(public))
                if identity in identities:
                    raise ValueError("duplicate_context")
                identities.add(identity)
                result.append({"id":f"ppo-pilot-{n}-{k}-{seed}","split":"pilot","public":public})
    return result


def evaluate(task_list, bc, selected, last):
    parameters = {"bc":bc,"ppo_selected":selected,"ppo_last":last}
    references, traces, outcomes = [],[],[]
    for task in task_list:
        if task["split"] != "pilot":
            continue
        model = Planner(task["public"])
        reference = model.value((-1,)*model.k,model.k)[0]
        references.append({"id":task["id"],"optimal_expected_loss":reference,"milp_calls":model.calls})
        for method in METHODS:
            result = rollout(task["public"],method,parameters.get(method));result["id"]=task["id"]
            traces.append(result)
            row = {k:result[k] for k in ("id","method","expected_loss","expected_milp_calls","expected_queries")}
            row.update(optimal_expected_loss=reference,regret=(result["expected_loss"]-reference)/max(1.,reference))
            if row["regret"] < -1e-7:
                raise ValueError("better_than_exact_reference")
            outcomes.append(row)
    return references,traces,outcomes


def summarize(task_list, outcomes, training, cfg, smoke):
    groups = {m:[r for r in outcomes if r["method"]==m] for m in METHODS}
    base = {r["id"]:r for r in groups["bc"]}
    paired = []
    for row in groups["ppo_selected"]:
        b = base[row["id"]]
        paired.append({"id":row["id"],"expected_cost_difference_ppo_minus_bc":row["expected_loss"]-b["expected_loss"],
                       "regret_difference_ppo_minus_bc":row["regret"]-b["regret"]})
    return {"scope":"smoke" if smoke else "synthetic_query_ppo_development","canonical":False,
            "ppo_trained":True,"training_seeds":[cfg["training_seed"]],"bc_checkpoint_sha256":BC_SHA,
            "contexts":{s:sum(t["split"]==s for t in task_list) for s in ("train","dev","pilot")},
            "selected_iteration":training["selected_iteration"],"training_updates":training["total_updates"],
            "sampled_episodes":training["episodes"],"sampled_steps":training["sampled_steps"],
            "selected_actor_l2_from_bc":training["selected_actor_l2_from_bc"],
            "last_actor_l2_from_bc":training["last_actor_l2_from_bc"],
            "methods":{m:{"contexts":len(rows),"mean_regret":sum(r["regret"] for r in rows)/len(rows),
                "max_regret":max(r["regret"] for r in rows),
                "mean_expected_loss":sum(r["expected_loss"] for r in rows)/len(rows),
                "mean_milp_calls":sum(r["expected_milp_calls"] for r in rows)/len(rows),
                "mean_queries":sum(r["expected_queries"] for r in rows)/len(rows)} for m,rows in groups.items()},
            "paired_selected_vs_bc":{
                "improved":sum(r["expected_cost_difference_ppo_minus_bc"] < -1e-7 for r in paired),
                "tied":sum(abs(r["expected_cost_difference_ppo_minus_bc"]) <= 1e-7 for r in paired),
                "worse":sum(r["expected_cost_difference_ppo_minus_bc"] > 1e-7 for r in paired),
                "contexts":paired},
            "limits":"One training seed; reused validation; new development contexts from same generator; known priors and orders; no final test or significance claim."}


def source_identity():
    result = bc_sources()
    paths = ["query_ppo/"+p for p in ("config.json","algorithm.py","training.py","experiment.py")]
    paths += ["docs/query_ppo_protocol.md"]
    paths += ["benchmark_results/query_bc_development/"+p for p in ("checkpoint.json","tasks.json","manifest.json")]
    result.update({p:sha256((ROOT/p).read_bytes()) for p in paths})
    return result


def run(output, smoke=False):
    from .training import train
    from query_policy.model import deserialize
    import numpy as np
    import scipy
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("output_not_empty_use_new_directory")
    output.mkdir(parents=True,exist_ok=True)
    cfg=config(smoke);task_list=tasks(cfg,smoke);bc=initial_actor()
    start=time.perf_counter()
    initial,selected,last,training,episodes=train([t for t in task_list if t["split"]!="pilot"],bc,cfg,verbose=True)
    training_seconds=time.perf_counter()-start
    start=time.perf_counter()
    references,traces,outcomes=evaluate(task_list,bc,deserialize(selected["actor"],32),deserialize(last["actor"],32))
    summary=summarize(task_list,outcomes,training,cfg,smoke)
    runtime={"python":platform.python_version(),"numpy":np.__version__,"scipy":scipy.__version__,
             "training_seconds":training_seconds,"evaluation_seconds":time.perf_counter()-start,
             "offline_terminal_milp_calls":training["offline_terminal_milp_calls"],
             "reference_milp_calls":sum(r["milp_calls"] for r in references)}
    for name,payload in (("config.json",cfg),("tasks.json",task_list),("initial.json",initial),
                         ("selected.json",selected),("last.json",last),("training.json",training),
                         ("references.json",references),("outcomes.json",outcomes),("summary.json",summary),("runtime.json",runtime)):
        write(output/name,payload)
    write_lines(output/"episodes.jsonl",episodes);write_lines(output/"traces.jsonl",traces)
    write(output/"manifest.json",{"schema":"query-ppo-bundle-v1","smoke":smoke,"source":source_identity(),
          "files":{name:sha256((output/name).read_bytes()) for name in FILES}})
    return summary


def verify(output):
    from .training import train
    from .algorithm import decode_critic
    from query_policy.model import deserialize,serialize
    output=Path(output);read=lambda name:json.loads((output/name).read_text())
    manifest=read("manifest.json")
    if manifest["schema"]!="query-ppo-bundle-v1" or type(manifest["smoke"]) is not bool:
        raise ValueError("manifest_schema")
    if manifest["source"]!=source_identity() or set(manifest["files"])!=set(FILES):
        raise ValueError("source_or_file_coverage")
    for name in FILES:
        if (output/name).is_symlink() or sha256((output/name).read_bytes())!=manifest["files"][name]:
            raise ValueError("file_hash_mismatch")
    cfg=config(manifest["smoke"]);task_list=tasks(cfg,manifest["smoke"])
    if read("config.json")!=cfg or read("tasks.json")!=task_list:
        raise ValueError("configuration_or_task_regeneration")
    bc=initial_actor()
    # Enforce equality to the frozen actor before any approximate checks.
    if read("initial.json")["actor"]!=serialize(bc):
        raise ValueError("shared_bc_start_mismatch")
    initial,selected,last,training,episodes=train([t for t in task_list if t["split"]!="pilot"],bc,cfg)
    for name,fresh in (("initial.json",initial),("selected.json",selected),("last.json",last),("training.json",training)):
        close(read(name),fresh)
    close(read_lines(output/"episodes.jsonl"),episodes)
    for name in ("initial.json","selected.json","last.json"):
        decode_critic(read(name)["critic"])
    references,traces,outcomes=evaluate(task_list,bc,deserialize(read("selected.json")["actor"],32),deserialize(read("last.json")["actor"],32))
    saved_traces=read_lines(output/"traces.jsonl")
    if len(saved_traces)!=len(traces):
        raise ValueError("trace_coverage")
    lookup={t["id"]:t["public"] for t in task_list}
    for saved,fresh in zip(saved_traces,traces):
        verify_trace(lookup[fresh["id"]],saved,fresh)
    close(read("references.json"),references);close(read("outcomes.json"),outcomes)
    close(read("summary.json"),summarize(task_list,outcomes,training,cfg,manifest["smoke"]))
    close(read("runtime.json")["offline_terminal_milp_calls"],training["offline_terminal_milp_calls"])
    close(read("runtime.json")["reference_milp_calls"],sum(r["milp_calls"] for r in references))
    return {"verified":True,"training_reexecuted":True,"sampled_episodes":len(episodes),
            "policy_runs":len(outcomes),"checkpoint_replayed":True,"shared_bc_start":True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path("artifacts/query_ppo"))
    parser.add_argument("--smoke",action="store_true")
    parser.add_argument("--verify",action="store_true")
    parser.add_argument("--smoke-check",action="store_true")
    args=parser.parse_args()
    if args.smoke_check:
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp,True);result=verify(tmp)
    else:
        result=verify(args.output) if args.verify else run(args.output,args.smoke)
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
