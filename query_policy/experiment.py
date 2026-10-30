"""Generate teacher states, train BC, evaluate and replay a development bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import tempfile
import time

from notice_benchmark.api_runner import canonical_bytes as canonical, sha256
from scripts.audit_decision_scale import generate
from .solver import Planner
from budgeted_decision.audit import close as numerically_close, evaluate as search_evaluate

ROOT = Path(__file__).resolve().parents[1]
METHODS = ("no_query", "prior_priority", "untrained", "bc", "lookahead_two_13", "iterative_dp_65")
FILES = ("config.json", "tasks.json", "teachers.jsonl", "initial.json", "checkpoint.json",
         "training.json", "traces.jsonl", "outcomes.json", "summary.json", "runtime.json")


def close(actual, expected):
    if not numerically_close(actual, expected):
        raise ValueError("evidence_reexecution_mismatch")


def config(smoke=False):
    cfg = json.loads((ROOT/"query_policy/config.json").read_text())
    if smoke:
        cfg.update(sku_counts=[4], delay_bits=[2], splits={"train":[1001],"dev":[2001],"pilot":[3001]}, epochs=2)
    return cfg


def tasks(cfg):
    result, identities = [], set()
    previous = json.loads((ROOT/"benchmark_results/query_budget_development/tasks.json").read_text())
    old = {sha256(canonical(t["public"])) for t in previous}
    for split, seeds in cfg["splits"].items():
        for n in cfg["sku_counts"]:
            for k in cfg["delay_bits"]:
                for seed in seeds:
                    public = generate(n,k,seed)
                    identity = sha256(canonical(public))
                    if identity in identities or identity in old:
                        raise ValueError("duplicate_context")
                    identities.add(identity)
                    result.append({"id":f"bc-{split}-{n}-{k}-{seed}","split":split,"public":public})
    return result


def teacher(task, tolerance):
    """Enumerate all legal public histories; no realized hidden truth is drawn."""
    model = Planner(task["public"])
    seen = set()
    def visit(h):
        if h in seen:
            return
        seen.add(h)
        for i in model.legal(h):
            for _, nxt in model.branch(h,i):
                visit(nxt)
    root = (-1,)*model.k
    visit(root)
    records = []
    for h in sorted(seen):
        q = [model.terminal(h)[0]] + [None]*model.k
        for i in model.legal(h):
            q[i+1] = task["public"]["query_fees"][i] + sum(p*model.value(nxt,model.k)[0] for p,nxt in model.branch(h,i))
        best = min(v for v in q if v is not None)
        records.append({"history":list(h),"q_values":q,
                        "positives":[v is not None and v <= best+tolerance for v in q]})
    return {"id":task["id"],"split":task["split"],"states":records,
            "optimal_expected_loss":model.value(root,model.k)[0],"teacher_milp_calls":model.calls}


def batch(task_list, teachers, split):
    import numpy as np
    from .features import encode
    by_id = {t["id"]:t for t in teachers}
    rows = []
    for task in task_list:
        if task["split"] != split:
            continue
        states = [s for s in by_id[task["id"]]["states"] if sum(v is not None for v in s["q_values"]) > 1]
        for s in states:
            x, mask = encode(task["public"],s["history"])
            rows.append((x,mask,s["positives"],1/len(states)))
    size, width = len(rows), max(len(r[1]) for r in rows)
    x, masks, positive = np.zeros((size,width,37)), np.zeros((size,width),bool), np.zeros((size,width),bool)
    weights = np.asarray([r[3] for r in rows])
    weights /= weights.mean()
    for i,(features,mask,pos,_) in enumerate(rows):
        x[i,:len(mask)] = features; masks[i,:len(mask)] = mask; positive[i,:len(mask)] = pos
    return x,masks,positive,weights


def learned_tree(public, method, parameters=None):
    """One final MILP on each executed path; enumeration is evaluator work."""
    from .features import encode
    from .model import probabilities
    model = Planner(public)
    nodes = []
    def visit(h, weight):
        x, mask = encode(public,h)
        legal = list(model.legal(h))
        if list(mask) != [True,*[i in legal for i in range(model.k)]]:
            raise ValueError("independent_mask_mismatch")
        probs = None
        if not legal or method == "no_query":
            action = -1
        elif method == "prior_priority":
            action = max(legal,key=lambda i:(public["prior"][i]*(1-public["prior"][i])/public["query_fees"][i],-i))
        else:
            probs, _, _ = probabilities(parameters,x,mask)
            action = int(probs.argmax())-1
        if action != -1 and action not in legal:
            raise ValueError("illegal_policy_action")
        node = {"history":list(h),"probability":weight,"action":action,"legal_queries":legal,
                "input_sha256":sha256(canonical({"features":x.tolist(),"mask":mask.tolist()})),
                "probabilities":None if probs is None else probs.tolist(),"milp_calls":int(action == -1),
                "commit_plan":None,"terminal_loss":None}
        nodes.append(node)
        if action == -1:
            loss, plan = model._terminal(h)
            node.update(terminal_loss=loss,commit_plan=plan)
            return loss,0.
        values = [visit(nxt,weight*p) for p,nxt in model.branch(h,action)]
        p = public["prior"][action]
        return (public["query_fees"][action]+(1-p)*values[0][0]+p*values[1][0],
                1+(1-p)*values[0][1]+p*values[1][1])
    loss, queries = visit((-1,)*model.k,1.)
    return {"method":method,"expected_loss":loss,"expected_milp_calls":1.,
            "expected_queries":queries,"nodes":nodes}


def rollout(public, method, parameters):
    if method in ("lookahead_two_13","iterative_dp_65"):
        name,budget = method.rsplit("_",1)
        backend = Planner(public)
        result,_ = search_evaluate(public,name,int(budget),backend_factory=lambda _:backend._terminal)
        # Search is rerun during verification; the old budget package owns its full ledger.
        return {"method":method,"expected_loss":result["expected_loss"],
                "expected_milp_calls":result["expected_milp_calls"],"expected_queries":result["expected_queries"],
                "nodes":[{k:n[k] for k in ("history","probability","action","legal_queries","milp_calls","commit_plan","terminal_loss")}
                         for n in result["nodes"]]}
    return learned_tree(public,method,parameters)


def summarize(rows, teachers, training, cfg, smoke):
    groups = {m:[r for r in rows if r["method"] == m] for m in METHODS}
    return {"scope":"smoke" if smoke else "synthetic_query_bc_development",
            "canonical":False,"ppo_trained":False,"training_seeds":[cfg["training_seed"]],
            "contexts":{s:sum(t["split"] == s for t in teachers) for s in cfg["splits"]},
            "teacher_states":{s:sum(len(t["states"]) for t in teachers if t["split"] == s) for s in cfg["splits"]},
            "teacher_milp_calls":{s:sum(t["teacher_milp_calls"] for t in teachers if t["split"] == s) for s in cfg["splits"]},
            "selected_epoch":training["selected_epoch"],"training_updates":training["updates"],
            "parameter_l2_delta":training["selected_parameter_l2_delta"],
            "methods":{m:{"contexts":len(rs),"mean_regret":sum(r["regret"] for r in rs)/len(rs),
                    "max_regret":max(r["regret"] for r in rs),
                    "mean_expected_loss":sum(r["expected_loss"] for r in rs)/len(rs),
                    "mean_milp_calls":sum(r["expected_milp_calls"] for r in rs)/len(rs),
                    "mean_queries":sum(r["expected_queries"] for r in rs)/len(rs)} for m,rs in groups.items()},
            "limits":"Single-seed development; fixed generator; exact priors; terminal MILP retained; calls are not wall-clock speedup."}


def write(path,value):
    path.write_bytes(canonical(value)+b"\n")


def write_lines(path,rows):
    path.write_bytes(b"".join(canonical(row)+b"\n" for row in rows))


def read_lines(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def source_identity():
    paths = ["query_policy/"+s for s in ("config.json","features.py","model.py","experiment.py","solver.py")]
    paths += ["scripts/audit_decision_scale.py","budgeted_decision/planning.py","budgeted_decision/audit.py",
              "notice_benchmark/api_runner.py","docs/query_policy_protocol.md",
              "benchmark_results/query_budget_development/tasks.json"]
    return {p:sha256((ROOT/p).read_bytes()) for p in paths}


def run(output, smoke=False):
    from .model import train, serialize
    import numpy as np
    import scipy
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("output_not_empty_use_new_directory")
    output.mkdir(parents=True,exist_ok=True)
    cfg = config(smoke); task_list = tasks(cfg)
    start = time.perf_counter(); teachers = []
    for i,t in enumerate(task_list):
        teachers.append(teacher(t,cfg["positive_tolerance"]))
        if (i+1)%18 == 0:
            print(f"teacher contexts {i+1}/{len(task_list)}",flush=True)
    teacher_seconds = time.perf_counter()-start
    start = time.perf_counter()
    initial, selected, training = train(batch(task_list,teachers,"train"),batch(task_list,teachers,"dev"),cfg)
    train_seconds = time.perf_counter()-start
    by_id = {t["id"]:t for t in teachers}; traces, rows = [],[]
    start = time.perf_counter()
    for t in task_list:
        if t["split"] != "pilot":
            continue
        reference = by_id[t["id"]]["optimal_expected_loss"]
        for method in METHODS:
            result = rollout(t["public"],method,initial if method == "untrained" else selected)
            result["id"] = t["id"]; traces.append(result)
            row = {k:result[k] for k in ("id","method","expected_loss","expected_milp_calls","expected_queries")}
            row.update(optimal_expected_loss=reference,regret=(result["expected_loss"]-reference)/max(1.,reference))
            if row["regret"] < -1e-7:
                raise ValueError("better_than_exact_teacher")
            rows.append(row)
    summary = summarize(rows,teachers,training,cfg,smoke)
    runtime = {"python":platform.python_version(),"numpy":np.__version__,"scipy":scipy.__version__,
               "teacher_seconds":teacher_seconds,"training_seconds":train_seconds,"evaluation_seconds":time.perf_counter()-start}
    for name,value in (("config.json",cfg),("tasks.json",task_list),("initial.json",serialize(initial)),
                       ("checkpoint.json",serialize(selected)),("training.json",training),("outcomes.json",rows),
                       ("summary.json",summary),("runtime.json",runtime)):
        write(output/name,value)
    write_lines(output/"teachers.jsonl",teachers); write_lines(output/"traces.jsonl",traces)
    write(output/"manifest.json",{"schema":"query-bc-bundle-v1","smoke":smoke,"source":source_identity(),
          "files":{name:sha256((output/name).read_bytes()) for name in FILES}})
    return summary


def verify_trace(public, saved, fresh):
    """Accept tied MILP plans only after checking feasibility and optimal loss."""
    model = Planner(public)
    if len(saved["nodes"]) != len(fresh["nodes"]):
        raise ValueError("node_coverage")
    for old,new in zip(saved["nodes"],fresh["nodes"]):
        a,b = dict(old),dict(new)
        plan, _ = a.pop("commit_plan"),b.pop("commit_plan")
        if old["action"] == -1:
            physical = model.shipping(plan,tuple(old["history"]))["loss"]
            if abs(physical-new["terminal_loss"]) > 1e-6:
                raise ValueError("nonoptimal_commit_plan")
        elif plan is not None:
            raise ValueError("plan_before_commit")
        close(a,b)
    close({k:v for k,v in saved.items() if k != "nodes"}, {k:v for k,v in fresh.items() if k != "nodes"})


def verify(output):
    from .model import deserialize,serialize,train
    output = Path(output)
    read = lambda name:json.loads((output/name).read_text())
    manifest = read("manifest.json")
    if manifest["schema"] != "query-bc-bundle-v1" or type(manifest["smoke"]) is not bool:
        raise ValueError("manifest_schema")
    if manifest["source"] != source_identity() or set(manifest["files"]) != set(FILES):
        raise ValueError("source_or_file_coverage")
    for name in FILES:
        if (output/name).is_symlink() or sha256((output/name).read_bytes()) != manifest["files"][name]:
            raise ValueError("file_hash_mismatch")
    cfg = config(manifest["smoke"])
    if read("config.json") != cfg:
        raise ValueError("configuration_mismatch")
    task_list = tasks(cfg)
    if read("tasks.json") != task_list:
        raise ValueError("task_regeneration_mismatch")
    teachers = read_lines(output/"teachers.jsonl")
    if len(teachers) != len(task_list):
        raise ValueError("teacher_coverage")
    for t,old in zip(task_list,teachers):
        close(old,teacher(t,cfg["positive_tolerance"]))
    initial, selected, training = train(batch(task_list,teachers,"train"),batch(task_list,teachers,"dev"),cfg)
    close(read("initial.json"),serialize(initial)); close(read("checkpoint.json"),serialize(selected))
    close(read("training.json"),training)
    checkpoints = {"bc":deserialize(read("checkpoint.json"),cfg["hidden"]),
                   "untrained":deserialize(read("initial.json"),cfg["hidden"])}
    traces = read_lines(output/"traces.jsonl"); rows = []; index = 0
    by_id = {t["id"]:t for t in teachers}
    for t in task_list:
        if t["split"] != "pilot":
            continue
        reference = by_id[t["id"]]["optimal_expected_loss"]
        for method in METHODS:
            result = rollout(t["public"],method,checkpoints.get(method));result["id"] = t["id"]
            if index >= len(traces):
                raise ValueError("trace_missing")
            verify_trace(t["public"],traces[index],result);index += 1
            row = {k:result[k] for k in ("id","method","expected_loss","expected_milp_calls","expected_queries")}
            row.update(optimal_expected_loss=reference,regret=(result["expected_loss"]-reference)/max(1.,reference))
            rows.append(row)
    if index != len(traces):
        raise ValueError("extra_traces")
    close(read("outcomes.json"),rows)
    summary = summarize(rows,teachers,training,cfg,manifest["smoke"])
    close(read("summary.json"),summary)
    return {"verified":True,"contexts":len(task_list),"policy_runs":len(rows),
            "teacher_recomputed":True,"training_reexecuted":True,"checkpoint_replayed":True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path("artifacts/query_bc"))
    parser.add_argument("--smoke",action="store_true")
    parser.add_argument("--verify",action="store_true")
    parser.add_argument("--smoke-check",action="store_true",help="Run and verify an isolated temporary smoke bundle")
    args = parser.parse_args()
    if args.smoke_check:
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp,True); result = verify(tmp)
    else:
        result = verify(args.output) if args.verify else run(args.output,args.smoke)
    print(json.dumps(result,sort_keys=True))


if __name__ == "__main__":
    main()
