"""Fixed study identities, lossless training records and bundle integrity."""
from __future__ import annotations

import json
from pathlib import Path

from notice_benchmark.api_runner import canonical_bytes as canonical,sha256
from query_policy.experiment import close,read_lines,write,write_lines

ROOT=Path(__file__).resolve().parents[1]
BC=ROOT/"benchmark_results/query_bc_development"
PPO=ROOT/"benchmark_results/query_ppo_development"
LEARNED=("bc","ppo","ppo_no_entropy","ppo_lambda1","ppo_last")
BASELINES=("lookahead_two_13","iterative_dp_65")


def read(path):
    return json.loads(Path(path).read_text())


def config(smoke=False):
    c=read(ROOT/"query_study/config.json")
    if smoke:
        c.update(training_seeds=[17],final_contexts=3,bootstrap_replicates=40,
                 final_generator_seed_start=900000000)
    return c


def source_identity():
    from query_ppo.experiment import source_identity as previous
    result=previous()
    paths=[p.relative_to(ROOT).as_posix() for p in (ROOT/"query_study").glob("*.py")]
    paths += ["query_study/config.json","docs/query_study_protocol.md",
              "benchmark_results/query_bc_development/teachers.jsonl",
              "benchmark_results/query_ppo_development/tasks.json"]
    result.update({p:sha256((ROOT/p).read_bytes()) for p in paths})
    return result


def empty_output(path):
    p=Path(path)
    if p.exists() and any(p.iterdir()):
        raise ValueError("output_not_empty_use_new_directory")
    p.mkdir(parents=True,exist_ok=True)
    return p


def seal(path,schema,smoke,**metadata):
    p=Path(path)
    files={f.relative_to(p).as_posix():sha256(f.read_bytes()) for f in sorted(p.rglob("*")) if f.is_file() and f.name!="manifest.json"}
    write(p/"manifest.json",{"schema":schema,"smoke":smoke,"source":source_identity(),"files":files,**metadata})


def check_bundle(path,schema):
    p=Path(path);m=read(p/"manifest.json")
    if m["schema"]!=schema or type(m["smoke"]) is not bool or m["source"]!=source_identity():
        raise ValueError("bundle_identity_mismatch")
    actual={f.relative_to(p).as_posix() for f in p.rglob("*") if f.is_file() and f.name!="manifest.json"}
    if actual!=set(m["files"]):
        raise ValueError("bundle_file_coverage")
    for name,identity in m["files"].items():
        relative=Path(name)
        if relative.is_absolute() or ".." in relative.parts or (p/relative).is_symlink():
            raise ValueError("unsafe_bundle_path")
        if sha256((p/name).read_bytes())!=identity:
            raise ValueError("bundle_file_hash")
    return m


def pack_episodes(episodes):
    """[iteration, task ID, repeat, [[action, answer, reward, old logp, old V]]]."""
    return [[e["iteration"],e["id"],e["repeat"],
             [[s[k] for k in ("action","answer","reward","old_logp","old_value")] for s in e["steps"]]] for e in episodes]


def expand_episodes(rows,tasks,cfg):
    import numpy as np
    from query_ppo.algorithm import gae
    from query_policy.features import encode
    public={t["id"]:t["public"] for t in tasks}
    result=[]
    for iteration,identity,repeat,records in rows:
        c=public[identity];h=[-1]*c["delay_bits"];steps=[]
        for j,(action,answer,reward,logp,v) in enumerate(records):
            if type(action) is not int or action<0 or action>len(h) or not encode(c,tuple(h))[1][action]:
                raise ValueError("illegal_compact_action")
            if (action==0)!=(j==len(records)-1) or (action==0 and answer is not None):
                raise ValueError("compact_terminal_boundary")
            if action and (type(answer) is not int or answer not in (0,1)):
                raise ValueError("compact_answer")
            steps.append({"history":h.copy(),"action":action,"answer":answer,"reward":reward,
                          "done":action==0,"old_logp":logp,"old_value":v})
            if action:h[action-1]=answer
        adv,ret=gae([s["reward"] for s in steps],[s["old_value"] for s in steps],
                    np.asarray([s["done"] for s in steps]),cfg["gamma"],cfg["gae_lambda"])
        for s,a,r in zip(steps,adv,ret):s.update(advantage=float(a),value_target=float(r))
        result.append({"iteration":iteration,"id":identity,"repeat":repeat,"steps":steps})
    return result
