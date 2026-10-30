"""Freeze tasks and model identities before any final evaluation outputs."""
from __future__ import annotations

from pathlib import Path
import re
import time

from scripts.audit_decision_scale import generate
from .common import (BC,PPO,ROOT,read,config,empty_output,seal,check_bundle,
                     canonical,sha256,close,write,write_lines,read_lines)
from .development import load_models,registry
from .evaluation import evaluate as evaluate_models,verify_evaluation
from .statistics import summarize


def generate_tasks(cfg):
    previous=read(BC/"tasks.json")+read(PPO/"tasks.json")+read(ROOT/"benchmark_results/query_budget_development/tasks.json")
    identities={sha256(canonical(t["public"])) for t in previous};streams=set();result=[]
    strata=[(n,k) for n in (4,8,12) for k in (2,4,6)]
    for index in range(cfg["final_contexts"]):
        n,k=strata[index%9]
        seed=cfg["final_generator_seed_start"]+index*cfg["final_generator_seed_stride"]
        stream=seed+n*100+k*10000
        if stream in streams:raise ValueError("duplicate_generator_stream")
        streams.add(stream);public=generate(n,k,seed);identity=sha256(canonical(public))
        if identity in identities:raise ValueError("duplicate_final_context")
        identities.add(identity)
        result.append({"id":f"final-{index:04d}","split":"final","generator_seed":seed,"public":public})
    return result


def freeze(development,output):
    development=Path(development);m=check_bundle(development,"query-study-development-v1")
    cfg=config(m["smoke"])
    if read(development/"config.json")!=cfg:raise ValueError("development_config")
    models=load_models(development,cfg)
    close(read(development/"models.json"),registry(models))
    path=empty_output(output);tasks=generate_tasks(cfg)
    write(path/"config.json",cfg);write_lines(path/"tasks.jsonl",tasks)
    write(path/"models.json",registry(models))
    write(path/"freeze.json",{"schema":"query-study-final-freeze-v1","distinct_contexts":len(tasks),
        "final_outputs_computed":False,"development_manifest_sha256":sha256((development/"manifest.json").read_bytes()),
        "task_list_sha256":sha256((path/"tasks.jsonl").read_bytes()),
        "model_registry_sha256":sha256((path/"models.json").read_bytes()),
        "primary_method":"ppo","primary_baseline":"bc"})
    seal(path,"query-study-freeze-v1",m["smoke"])
    return {"frozen":True,"distinct_contexts":len(tasks),"final_outputs_computed":False,
            "manifest_sha256":sha256((path/"manifest.json").read_bytes())}


def load_frozen(development,frozen):
    development,frozen=Path(development),Path(frozen)
    dm=check_bundle(development,"query-study-development-v1");fm=check_bundle(frozen,"query-study-freeze-v1")
    cfg=config(fm["smoke"]);f=read(frozen/"freeze.json")
    if dm["smoke"]!=fm["smoke"] or f["development_manifest_sha256"]!=sha256((development/"manifest.json").read_bytes()):
        raise ValueError("frozen_training_binding")
    if read(frozen/"config.json")!=cfg:raise ValueError("frozen_configuration")
    tasks=generate_tasks(cfg)
    if read_lines(frozen/"tasks.jsonl")!=tasks:raise ValueError("frozen_task_regeneration")
    if f["task_list_sha256"]!=sha256((frozen/"tasks.jsonl").read_bytes()) or f["distinct_contexts"]!=len(tasks):
        raise ValueError("frozen_task_binding")
    models=load_models(development,cfg)
    if read(frozen/"models.json")!=registry(models) or f["model_registry_sha256"]!=sha256((frozen/"models.json").read_bytes()):
        raise ValueError("frozen_model_binding")
    return cfg,tasks,models,fm["smoke"]


def run(development,frozen,output,freeze_commit):
    if not re.fullmatch(r"[0-9a-f]{40}",freeze_commit):raise ValueError("freeze_commit_sha_required")
    cfg,tasks,models,smoke=load_frozen(development,frozen)
    path=empty_output(output);start=time.perf_counter()
    rows,trees,_=evaluate_models(tasks,models,path,verbose=True)
    summary=summarize(rows,tasks,cfg,"frozen_synthetic_final" if not smoke else "smoke")
    summary.update(frozen_final_executed=not smoke,unique_action_trees=len(trees))
    write(path/"summary.json",summary);write(path/"runtime.json",{"evaluation_seconds":time.perf_counter()-start})
    seal(path,"query-study-final-v1",smoke,freeze_commit=freeze_commit,
         freeze_manifest_sha256=sha256((Path(frozen)/"manifest.json").read_bytes()))
    return summary


def verify(development,frozen,path):
    path=Path(path);m=check_bundle(path,"query-study-final-v1")
    cfg,tasks,models,smoke=load_frozen(development,frozen)
    if m["smoke"]!=smoke or m["freeze_manifest_sha256"]!=sha256((Path(frozen)/"manifest.json").read_bytes()):
        raise ValueError("final_freeze_binding")
    if not re.fullmatch(r"[0-9a-f]{40}",m["freeze_commit"]):raise ValueError("freeze_commit_identity")
    rows=verify_evaluation(path,tasks,models,verbose=True)
    summary=summarize(rows,tasks,cfg,"frozen_synthetic_final" if not smoke else "smoke")
    summary.update(frozen_final_executed=not smoke,unique_action_trees=len(read_lines(path/"trees.jsonl")))
    close(read(path/"summary.json"),summary)
    return {"verified":True,"distinct_contexts":len(tasks),"training_seeds":cfg["training_seeds"],
            "policy_evaluations":len(rows),"checkpoint_replayed":True,"statistics_recomputed":True}
