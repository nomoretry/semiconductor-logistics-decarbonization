"""Retrain each BC seed, share its start across PPO variants, archive all runs."""
from __future__ import annotations

from pathlib import Path
import time

from .common import (BC,PPO,ROOT,read,config,source_identity,empty_output,seal,check_bundle,
                     canonical,sha256,close,write,write_lines,read_lines,pack_episodes,expand_episodes)
from .evaluation import evaluate,verify_evaluation
from .statistics import summarize


def datasets(smoke=False):
    original=read(BC/"tasks.json")
    training=[t for t in original if t["split"] in ("train","dev")]
    audit=[t for t in read(PPO/"tasks.json") if t["split"]=="pilot"]
    if smoke:
        training=[next(t for t in training if t["split"]==s) for s in ("train","dev")]
        audit=audit[:2]
    return training,audit


def prepare_teachers(training):
    from query_policy.experiment import teacher
    saved={t["id"]:t for t in read_lines(BC/"teachers.jsonl")}
    rows=[]
    for t in training:
        new=teacher(t,1e-7);close(new,saved[t["id"]]);rows.append(new)
    return rows


def train_seed(seed,training,teachers,cfg,smoke=False):
    from query_policy.experiment import batch
    from query_policy.model import train as train_bc,serialize
    from query_ppo.training import train as train_ppo
    from query_ppo.experiment import config as ppo_config
    bc_cfg=read(ROOT/"query_policy/config.json");bc_cfg["training_seed"]=seed
    if smoke:bc_cfg["epochs"]=2
    initial,bc,log=train_bc(batch(training,teachers,"train"),batch(training,teachers,"dev"),bc_cfg)
    bc_payload={"seed":seed,"config":bc_cfg,"initial":serialize(initial),"selected":serialize(bc),"training":log}
    runs=[]
    for variant,overrides in cfg["variants"].items():
        pcfg=ppo_config(smoke);pcfg.update(training_seed=seed,**overrides)
        initial,selected,last,log,episodes=train_ppo(training,bc,pcfg)
        if initial["actor"]!=serialize(bc):raise ValueError("shared_bc_initialization")
        if log["total_updates"]<=0 or log["last_actor_l2_from_bc"]<=0:raise ValueError("missing_real_ppo_updates")
        payload={"seed":seed,"variant":variant,"config":pcfg,"initial":initial,
                 "selected":selected,"last":last,"training":log,
                 "bc_start_sha256":sha256(canonical(serialize(bc)))}
        runs.append((variant,payload,episodes))
    return bc_payload,runs


def load_models(path,cfg):
    from query_policy.model import deserialize
    models=[]
    def add(method,seed,payload):
        models.append({"method":method,"seed":seed,"parameters":deserialize(payload,32),"sha256":sha256(canonical(payload))})
    for seed in cfg["training_seeds"]:
        bc=read(path/f"models/{seed}-bc.json")["selected"];add("bc",seed,bc)
        for variant in cfg["variants"]:
            p=read(path/f"models/{seed}-{variant}.json")
            if p["initial"]["actor"]!=bc or p["bc_start_sha256"]!=sha256(canonical(bc)):
                raise ValueError("shared_start_binding")
            add(variant,seed,p["selected"]["actor"])
            if variant=="ppo":add("ppo_last",seed,p["last"]["actor"])
    return models


def registry(models):
    return [{k:m[k] for k in ("method","seed","sha256")} for m in models]


def run(output,smoke=False):
    path=empty_output(output);cfg=config(smoke);training,audit=datasets(smoke)
    (path/"models").mkdir();(path/"episodes").mkdir()
    write(path/"config.json",cfg);write(path/"training_tasks.json",training);write(path/"audit_tasks.json",audit)
    start=time.perf_counter();teachers=prepare_teachers(training)
    for seed in cfg["training_seeds"]:
        bc,runs=train_seed(seed,training,teachers,cfg,smoke)
        write(path/f"models/{seed}-bc.json",bc)
        for variant,payload,episodes in runs:
            write(path/f"models/{seed}-{variant}.json",payload)
            write_lines(path/f"episodes/{seed}-{variant}.jsonl",pack_episodes(episodes))
        print(f"completed training seed {seed}",flush=True)
    training_seconds=time.perf_counter()-start;start=time.perf_counter()
    models=load_models(path,cfg);write(path/"models.json",registry(models))
    rows,_,_=evaluate(audit,models,path)
    summary=summarize(rows,audit,cfg,"multi_seed_development" if not smoke else "smoke")
    write(path/"summary.json",summary)
    write(path/"runtime.json",{"training_seconds":training_seconds,"evaluation_seconds":time.perf_counter()-start})
    seal(path,"query-study-development-v1",smoke)
    return summary


def verify(path,verbose=True):
    path=Path(path);m=check_bundle(path,"query-study-development-v1");cfg=config(m["smoke"])
    training,audit=datasets(m["smoke"])
    if read(path/"config.json")!=cfg or read(path/"training_tasks.json")!=training or read(path/"audit_tasks.json")!=audit:
        raise ValueError("development_configuration_or_data")
    teachers=prepare_teachers(training)
    for seed in cfg["training_seeds"]:
        bc,runs=train_seed(seed,training,teachers,cfg,m["smoke"])
        close(read(path/f"models/{seed}-bc.json"),bc)
        for variant,payload,episodes in runs:
            close(read(path/f"models/{seed}-{variant}.json"),payload)
            expanded=expand_episodes(read_lines(path/f"episodes/{seed}-{variant}.jsonl"),training,payload["config"])
            close(expanded,episodes)
        if verbose:print(f"verified BC and three PPO runs for seed {seed}",flush=True)
    models=load_models(path,cfg);close(read(path/"models.json"),registry(models))
    rows=verify_evaluation(path,audit,models)
    close(read(path/"summary.json"),summarize(rows,audit,cfg,"multi_seed_development" if not m["smoke"] else "smoke"))
    return {"verified":True,"bc_runs":len(cfg["training_seeds"]),"ppo_runs":len(cfg["training_seeds"])*len(cfg["variants"]),
            "policy_evaluations":len(rows),"training_reexecuted":True}
