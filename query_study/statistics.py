"""Paired, crossed seed/context bootstrap with fixed SKU/route strata."""
from __future__ import annotations

import numpy as np
from .common import LEARNED,BASELINES


def paired_interval(difference,strata,replicates,seed):
    a=np.asarray(difference,dtype=float)
    if a.ndim!=2 or not a.shape[0] or not a.shape[1] or len(strata)!=a.shape[1] or not np.isfinite(a).all():
        raise ValueError("finite_paired_matrix_required")
    groups=[np.asarray([i for i,g in enumerate(strata) if g==key]) for key in sorted(set(strata))]
    rng=np.random.default_rng(seed);means=[]
    for _ in range(replicates):
        seeds=rng.integers(0,a.shape[0],size=a.shape[0])
        cases=np.concatenate([rng.choice(g,len(g),replace=True) for g in groups])
        means.append(float(a[np.ix_(seeds,cases)].mean()))
    lo,hi=np.quantile(means,[.025,.975])
    return {"mean":float(a.mean()),"ci95":[float(lo),float(hi)],
            "per_seed":a.mean(axis=1).tolist(),"replicates":replicates,
            "resampling":"paired_seed_by_context_within_sku_route_strata"}


def summarize(rows,tasks,cfg,scope):
    ids=[t["id"] for t in tasks];seeds=cfg["training_seeds"]
    if len(ids)!=len(set(ids)) or len(seeds)!=len(set(seeds)):
        raise ValueError("duplicate_task_or_seed")
    lookup={}
    for r in rows:
        key=(r["method"],r["seed"],r["id"])
        if key in lookup:raise ValueError("duplicate_outcome")
        lookup[key]=r
    expected={(m,s,i) for m in LEARNED for s in seeds for i in ids}
    expected|={(m,None,i) for m in BASELINES for i in ids}
    if set(lookup)!=expected:raise ValueError("exact_paired_coverage_required")
    arrays={m:np.asarray([[lookup[(m,s,i)]["regret"] for i in ids] for s in seeds]) for m in LEARNED}
    strata=[f"{len(t['public']['known_orders']):02d}-{t['public']['delay_bits']}" for t in tasks]
    methods={}
    for m in (*LEARNED,*BASELINES):
        group=[r for r in rows if r["method"]==m]
        methods[m]={"observations":len(group),"distinct_contexts":len(ids),
            "mean_regret":float(np.mean([r["regret"] for r in group])),
            "max_regret":max(r["regret"] for r in group),
            "mean_expected_loss":float(np.mean([r["expected_loss"] for r in group])),
            "mean_queries":float(np.mean([r["expected_queries"] for r in group])),
            "mean_milp_calls":float(np.mean([r["expected_milp_calls"] for r in group]))}
        if m in arrays:methods[m]["per_seed_mean_regret"]=arrays[m].mean(axis=1).tolist()
    contrasts={}
    for a,b in (("ppo","bc"),("ppo_no_entropy","ppo"),("ppo_lambda1","ppo"),("ppo_last","ppo")):
        contrasts[f"{a}_minus_{b}"]=paired_interval(arrays[a]-arrays[b],strata,cfg["bootstrap_replicates"],cfg["bootstrap_seed"])
    primary=contrasts["ppo_minus_bc"]
    stability=sum(v<0 for v in primary["per_seed"])>=cfg["development_stability"]["minimum_improved_seeds"] and primary["ci95"][1]<0
    return {"scope":scope,"distinct_contexts":len(ids),"training_seeds":seeds,"policy_evaluations":len(rows),
            "methods":methods,"contrasts":contrasts,
            "primary_interval_below_zero":primary["ci95"][1]<0,
            "descriptive_stability_condition":bool(stability),
            "full_project_complete":False,
            "limits":"Synthetic same-generator contexts; five training seeds; approximate crossed bootstrap; secondary contrasts exploratory; known priors and orders; no long-horizon or enterprise-generalization claim."}
