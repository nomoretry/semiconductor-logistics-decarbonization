"""Factorial development study with paired paths and complete solver replay."""
from copy import deepcopy
import gzip
import itertools
import json
from pathlib import Path
import platform
import tempfile
import time
import numpy as np
import scipy
from rolling_inventory.environment import Environment, generate
from rolling_inventory.experiment import ROOT, audit, close, digest, write, lines
from .planning import credit_rates, decide, solve

DEFAULT=ROOT/'benchmark_results/rolling_sensitivity_development'
METRICS=['net_cost','operating_cost','terminal_credit','fill_rate','emissions','final_stock',
         'final_backlog','backlog_unit_periods','remaining_carbon','solver_calls']


def identity():
    paths=list((ROOT/'rolling_sensitivity').glob('*.py'))+list((ROOT/'rolling_inventory').glob('*.py'))
    paths += [ROOT/p for p in ['rolling_sensitivity/config.json','rolling_inventory/config.json',
              'docs/rolling_sensitivity_protocol.md','benchmark_results/rolling_inventory_development/selection.json']]
    return {str(p.relative_to(ROOT)):digest(p) for p in sorted(paths)}


def variant(kind,allocation,fraction,count=0,sampler=0):
    return dict(kind=kind,allocation=allocation,fraction=fraction,count=count,sampler=sampler)


def key(v,with_sampler=True):
    fields=['kind','allocation','fraction','count']+(['sampler'] if with_sampler else [])
    return '|'.join(str(v[k]) for k in fields)


def variants(cfg):
    rows=[variant('scenario',a,v,s,k) for a,v,s,k in itertools.product(
        cfg['allocations'],cfg['terminal_fractions'],cfg['scenario_counts'],cfg['sampler_seeds'])]
    rows += [variant('mean',a,v) for a,v in itertools.product(cfg['allocations'],cfg['terminal_fractions'])]
    rows += [variant(m,'uniform' if m=='base_stock' else 'free',v)
             for m,v in itertools.product(['base_stock','oracle'],cfg['terminal_fractions'])]
    return rows


def rollout(task,v,z):
    env=Environment(task);rows=[];timing=[];calls=0;plan=None
    if v['kind']=='oracle':
        start=time.perf_counter();plan,info=solve(env.observe(),[task['demand']],'free',v['fraction'])
        timing.append(time.perf_counter()-start);calls=1
    for t in range(task['public']['periods']):
        if plan is None:
            start=time.perf_counter();action,info=decide(env.observe(),v,z)
            timing.append(time.perf_counter()-start);calls+=info['solver_calls']
        else:action=plan[t]
        row=env.step(action);row['planning']=deepcopy(info)
        # Original costs remain operating costs; credit is a separate final ledger.
        credit=float(np.asarray(row['stock_end'])@credit_rates(env.p,v['fraction'])) if t==env.p['periods']-1 else 0.
        row.update(terminal_credit=credit,net_cost=row['cost']-credit);rows.append(row)
    audit(task,rows)
    for t,row in enumerate(rows):
        expected=float(np.asarray(row['stock_end'])@credit_rates(env.p,v['fraction'])) if t==env.p['periods']-1 else 0.
        close(expected,row['terminal_credit']);close(row['cost']-expected,row['net_cost'])
    demand=sum(sum(r['demand']) for r in rows)
    result={'id':task['id'],'profile':task['profile'],'variant':v,
            'net_cost':sum(r['net_cost'] for r in rows),'operating_cost':sum(r['cost'] for r in rows),
            'terminal_credit':sum(r['terminal_credit'] for r in rows),
            'fill_rate':sum(sum(r['filled_new']) for r in rows)/demand if demand else 1.,
            'emissions':sum(r['emissions'] for r in rows),'remaining_carbon':env.remaining,
            'final_stock':sum(rows[-1]['stock_end']),'final_stock_by_sku':rows[-1]['stock_end'],
            'final_backlog':sum(rows[-1]['backlog_end']),
            'backlog_unit_periods':sum(sum(r['backlog_end']) for r in rows),'solver_calls':calls}
    return result,rows,timing


def mean_metrics(records):
    return {k:float(np.mean([r[k] for r in records])) for k in METRICS}


def paired(outcomes,ids,cfg,change):
    by={(r['id'],key(r['variant'])):r for r in outcomes};seeds=cfg['sampler_seeds'];values=[]
    per_seed={str(s):[] for s in seeds}
    for task in ids:
        differences=[]
        for s in seeds:
            base=variant('scenario','uniform',0.,7,s)
            other=dict(base,**change)
            d=by[task,key(other)]['net_cost']-by[task,key(base)]['net_cost']
            differences.append(d);per_seed[str(s)].append(d)
        values.append(float(np.mean(differences)))
    return {'mean_paired_net_cost':float(np.mean(values)),
            'better_contexts':sum(x < -1e-6 for x in values),
            'worse_contexts':sum(x > 1e-6 for x in values),
            'ties':sum(abs(x)<=1e-6 for x in values),
            'sampling_seed_means':{s:float(np.mean(x)) for s,x in per_seed.items()},
            'distinct_contexts':len(ids)}


def summary(outcomes,timing,cfg):
    ids=sorted({r['id'] for r in outcomes});cells={};by_seed={};profiles={}
    for k in sorted({key(r['variant'],False) for r in outcomes}):
        subset=[r for r in outcomes if key(r['variant'],False)==k]
        cells[k]=dict(mean_metrics(subset),distinct_contexts=len({r['id'] for r in subset}),runs=len(subset))
    for k in sorted({key(r['variant']) for r in outcomes}):
        by_seed[k]=mean_metrics([r for r in outcomes if key(r['variant'])==k])
    for profile in sorted({r['profile'] for r in outcomes}):
        profiles[profile]={k:mean_metrics([r for r in outcomes if r['profile']==profile and key(r['variant'],False)==k]) for k in cells}
    contrasts={}
    for a in cfg['allocations']:
        if a!='uniform':contrasts['allocation_'+a]=paired(outcomes,ids,cfg,{'allocation':a})
    for c in cfg['scenario_counts']:
        if c!=7:contrasts['count_'+str(c)]=paired(outcomes,ids,cfg,{'count':c})
    for f in cfg['terminal_fractions']:
        if f:contrasts['credit_'+str(f)]=paired(outcomes,ids,cfg,{'fraction':f})
    decompositions={}
    for f in cfg['terminal_fractions']:
        if not f:continue
        subset=[r for r in outcomes if r['variant']['kind']=='scenario' and r['variant']['allocation']=='uniform'
                and r['variant']['count']==7 and r['variant']['fraction']==f]
        decompositions[str(f)]={k:float(np.mean([r[k] for r in subset])) for k in
            ['accounting_effect','behavior_effect','net_change_vs_zero_value','operating_change_vs_zero_value']}
    computational={}
    for count in cfg['scenario_counts']:
        times=[x for r in timing if r['variant']['kind']=='scenario' and r['variant']['allocation']=='uniform'
               and r['variant']['fraction']==0 and r['variant']['count']==count for x in r['decision_seconds']]
        computational[str(count)]={'decisions':len(times),'mean_seconds':float(np.mean(times)),
                                   'p95_seconds':float(np.percentile(times,95)),
                                   'max_integer_variables':max(r['max_integer_variables'] for r in timing if r['variant']['kind']=='scenario'),
                                   'max_continuous_variables':max(r['max_continuous_variables'] for r in timing if r['variant']['kind']=='scenario' and r['variant']['count']==count)}
    return {'scope':cfg['scope'],'distinct_demand_paths':len(ids),'trajectories':len(outcomes),
            'cells':cells,'sampling_seed_cells':by_seed,'profiles':profiles,'primary_contrasts':contrasts,
            'terminal_decomposition':decompositions,'timing_measured_not_replay_equal':computational,
            'learning':{'rl_trained':False,'formal_final_created':False,'decision':'not_yet_established',
                        'reason':'No deployment latency target or validated same-information teacher advantage is established by this sensitivity study.'}}


def run(output,smoke=False):
    out=Path(output)
    if out.exists() and any(out.iterdir()):raise ValueError('output_must_be_empty')
    out.mkdir(parents=True,exist_ok=True)
    cfg=json.loads((ROOT/'rolling_sensitivity/config.json').read_text())
    original=json.loads((ROOT/'rolling_inventory/config.json').read_text())
    selected=json.loads((ROOT/'benchmark_results/rolling_inventory_development/selection.json').read_text())
    if cfg['base_stock_z']!=selected['z']:raise ValueError('prior_calibration_changed')
    if set(cfg['demand_seeds']) & set(original['calibration_seeds']+original['development_seeds']):raise ValueError('overlapping_seeds')
    if smoke:
        cfg.update(demand_seeds=[2003],sampler_seeds=[901337],scenario_counts=[1,7],terminal_fractions=[0.,.9])
        original.update(periods=4,horizon=3,profiles=['stable'])
    tasks=generate(original,'sensitivity',cfg['demand_seeds']);vs=variants(cfg)
    outcomes=[];times=[];bundles={}
    for task_index,task in enumerate(tasks):
        # Shuffle execution order deterministically to reduce systematic timing-order bias.
        order=np.random.default_rng(331+task_index).permutation(len(vs))
        records=[]
        for i in order:
            v=vs[int(i)];result,rows,seconds=rollout(task,v,cfg['base_stock_z'])
            outcomes.append(result);times.append({'id':task['id'],'variant':v,'decision_seconds':seconds,
                'max_integer_variables':max(r['planning'].get('dispatch_variables',0) for r in rows),
                'max_continuous_variables':max(r['planning'].get('continuous_variables',0) for r in rows)})
            records.append({'id':task['id'],'variant':v,'rows':rows})
        index={(key(r['variant'])):r for r in outcomes if r['id']==task['id']}
        for record in records:
            v=record['variant'];r=index[key(v)];oracle=index[key(variant('oracle','free',v['fraction']))]
            if r['net_cost']<oracle['net_cost']-1e-5:raise ValueError('clairvoyant_bound_violated')
            if v['fraction']:
                zero=index[key(dict(v,fraction=0.))]
                fixed_credit=float(np.asarray(zero['final_stock_by_sku'])@credit_rates(task['public'],v['fraction']))
                r.update(accounting_effect=-fixed_credit,
                         behavior_effect=r['net_cost']-(zero['net_cost']-fixed_credit),
                         net_change_vs_zero_value=r['net_cost']-zero['net_cost'],
                         operating_change_vs_zero_value=r['operating_cost']-zero['operating_cost'])
                close(r['net_change_vs_zero_value'],r['accounting_effect']+r['behavior_effect'])
        records.sort(key=lambda r:key(r['variant']))
        shard=task_index//3;bundles.setdefault(shard,[]).extend(records)
        print(f'evaluated {task_index+1}/{len(tasks)}: {task["id"]}',flush=True)
    outcomes.sort(key=lambda r:(r['id'],key(r['variant'])));times.sort(key=lambda r:(r['id'],key(r['variant'])))
    result=summary(outcomes,times,cfg)
    write(out/'config.json',cfg);write(out/'tasks.json',tasks);write(out/'variants.json',vs)
    for name,records in [('outcomes',outcomes),('timing',times)]:
        raw=''.join(json.dumps(r,sort_keys=True,allow_nan=False)+'\n' for r in records).encode()
        (out/f'{name}.jsonl.gz').write_bytes(gzip.compress(raw,mtime=0))
    write(out/'summary.json',result)
    for shard,records in sorted(bundles.items()):
        raw=''.join(json.dumps(r,sort_keys=True,allow_nan=False)+'\n' for r in records).encode()
        (out/f'traces-{shard:02}.jsonl.gz').write_bytes(gzip.compress(raw,mtime=0))
    write(out/'runtime.json',{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__})
    write(out/'manifest.json',{'schema':cfg['schema'],'smoke':smoke,'sources':identity(),
                              'files':{p.name:digest(p) for p in sorted(out.iterdir())}})
    return result


def verify(output):
    out=Path(output);m=json.loads((out/'manifest.json').read_text())
    if m['sources']!=identity():raise ValueError('source_identity')
    fixed={'config.json','tasks.json','variants.json','outcomes.jsonl.gz','timing.jsonl.gz','summary.json','runtime.json'}
    expected=fixed|{f'traces-{i:02}.jsonl.gz' for i in range(1 if m['smoke'] else 8)}
    if set(m['files'])!=expected or {p.name for p in out.iterdir()}!=expected|{'manifest.json'}:raise ValueError('artifact_coverage')
    for name,sha in m['files'].items():
        if (out/name).is_symlink() or digest(out/name)!=sha:raise ValueError('artifact_hash')
    with tempfile.TemporaryDirectory() as tmp:
        fresh=Path(tmp);run(fresh,m['smoke'])
        for name in expected-{'timing.jsonl.gz','runtime.json'}:
            if name.endswith('.gz'):
                a=[json.loads(x) for x in gzip.decompress((out/name).read_bytes()).splitlines()]
                b=[json.loads(x) for x in gzip.decompress((fresh/name).read_bytes()).splitlines()]
            elif name.endswith('.jsonl'):
                a=[json.loads(x) for x in (out/name).read_text().splitlines()]
                b=[json.loads(x) for x in (fresh/name).read_text().splitlines()]
            else:
                a=json.loads((out/name).read_text());b=json.loads((fresh/name).read_text())
                if name=='summary.json':
                    a.pop('timing_measured_not_replay_equal');b.pop('timing_measured_not_replay_equal')
            close(a,b,name)
    return {'verified':True,'data_regenerated':True,'all_factorial_policies_reexecuted':True,
            'terminal_decomposition_recomputed':True,'all_value_specific_lower_bounds_resolved':True}
