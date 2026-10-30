"""Paired development evidence with regeneration, policy replay and cost audits."""
from copy import deepcopy
import hashlib
import gzip
import json
from pathlib import Path
import platform
import tempfile
import time
import numpy as np
import scipy
from .environment import Environment, generate
from .planning import decide, solve

ROOT=Path(__file__).resolve().parents[1]
DEFAULT=ROOT/'benchmark_results/rolling_inventory_development'


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')


def lines(path, records):
    Path(path).write_text(''.join(json.dumps(r,sort_keys=True,allow_nan=False)+'\n' for r in records))


def source_identity():
    paths=sorted((ROOT/'rolling_inventory').glob('*.py'))+[
        ROOT/'rolling_inventory/config.json',ROOT/'docs/rolling_inventory_protocol.md']
    return {str(p.relative_to(ROOT)):digest(p) for p in paths}


def audit(task, rows):
    """Independent ledger arithmetic: no environment transition or planner call."""
    p=task['public']; stock=np.array(p['initial_inventory']); backlog=np.zeros_like(stock)
    pipe=np.array(p['initial_pipeline']); remaining=p['carbon_budget']
    total_arrived=np.zeros_like(stock); total_demand=np.zeros_like(stock); total_sent=np.zeros_like(stock)
    initial_pipe=pipe.sum(axis=0)
    for t,row in enumerate(rows):
        a=np.array(row['action']); d=np.array(task['demand'][t]); arrival=pipe[t].copy()
        if a.dtype.kind not in 'iu' or np.any(a<0) or a.shape!=(len(stock),len(p['lead'])):
            raise ValueError('audit_dispatch')
        if np.any(np.array(p['mass'])@a>p['capacity']):raise ValueError('audit_capacity')
        emitted=int(sum(a[i,j]*p['mass'][i]*p['emissions'][j]
                        for i in range(len(stock)) for j in range(len(p['lead']))))
        if emitted>remaining:raise ValueError('audit_carbon')
        available=stock+arrival; old=np.minimum(available,backlog); available-=old; backlog-=old
        filled=np.minimum(available,d); stock=available-filled; backlog+=d-filled;pipe[t]=0
        for j,lead in enumerate(p['lead']):
            if t+lead>=p['periods']:
                if a[:,j].any():raise ValueError('audit_late_arrival')
            else:pipe[t+lead]+=a[:,j]
        total_arrived+=arrival;total_demand+=d;total_sent+=a.sum(axis=1);remaining-=emitted
        expected={'stock_end':stock.tolist(),'backlog_end':backlog.tolist(),
                  'pipeline_end':pipe.tolist(),'demand':d.tolist(),'filled_new':filled.tolist(),
                  'emissions':emitted}
        for key,value in expected.items():
            if row[key]!=value:raise ValueError('audit_'+key)
        if row['observation']['arrivals']!=arrival.tolist() or row['observation']['served_old']!=old.tolist():
            raise ValueError('audit_arrival_service')
        if not np.array_equal(stock-backlog,np.array(p['initial_inventory'])+total_arrived-total_demand):
            raise ValueError('net_inventory_conservation')
        if not np.array_equal(initial_pipe+total_sent,total_arrived+pipe.sum(axis=0)):
            raise ValueError('pipeline_conservation')
        costs={'freight':float(sum(a[i,j]*p['mass'][i]*p['freight'][j]
                                  for i in range(len(stock)) for j in range(len(p['lead'])))),
               'carbon':emitted*p['carbon_price'], 'holding':float(stock@p['holding']),
               'backlog':float(backlog@p['backlog']),
               'terminal_backlog':float(backlog@p['terminal_backlog']) if t==p['periods']-1 else 0.}
        close(costs,row['costs']);close(sum(costs.values()),row['cost'])
    if len(rows)!=p['periods']:raise ValueError('incomplete_episode')


def close(a,b,path='root'):
    if isinstance(a,dict):
        if not isinstance(b,dict) or set(a)!=set(b):raise ValueError('keys:'+path)
        for k in a:close(a[k],b[k],path+'/'+k)
    elif isinstance(a,list):
        if not isinstance(b,list) or len(a)!=len(b):raise ValueError('length:'+path)
        for i,(x,y) in enumerate(zip(a,b)):close(x,y,path+f'/{i}')
    elif isinstance(a,float):
        if not isinstance(b,(float,int)) or not np.isfinite(b) or abs(a-b)>1e-7+1e-9*abs(a):
            raise ValueError('numeric:'+path)
    elif type(a)!=type(b) or a!=b:raise ValueError('value:'+path)


def rollout(task, method, z=0.):
    env=Environment(task);rows=[];seconds=0.;calls=0
    schedule=None
    if method=='perfect_information':
        start=time.perf_counter();schedule,info=solve(env.observe(),[task['demand']],paced=False)
        seconds+=time.perf_counter()-start;calls=1
    for t in range(task['public']['periods']):
        if schedule is None:
            start=time.perf_counter();a,info=decide(env.observe(),method,z)
            seconds+=time.perf_counter()-start;calls+=info['solver_calls']
        else:a=schedule[t]
        row=env.step(a);row['planning']=deepcopy(info);rows.append(row)
    audit(task,rows)
    costs={k:float(sum(x['costs'][k] for x in rows)) for k in rows[0]['costs']}
    demand=sum(sum(x['demand']) for x in rows)
    result={'id':task['id'],'profile':task['profile'],'method':method,
            'total_cost':sum(costs.values()),'costs':costs,
            'immediate_fill_rate':sum(sum(x['filled_new']) for x in rows)/demand if demand else 1.,
            'backlog_unit_periods':sum(sum(x['backlog_end']) for x in rows),
            'emissions':sum(x['emissions'] for x in rows),'final_stock':sum(rows[-1]['stock_end']),
            'final_backlog':sum(rows[-1]['backlog_end']),
            'forecast_mae':float(np.mean(np.abs([x['forecast_error'] for x in rows]))),
            'forecast_bias':float(np.mean([x['forecast_error'] for x in rows])),
            'solver_calls':calls}
    return result,rows,seconds


def summarize(outcomes, timing):
    methods=sorted({x['method'] for x in outcomes}); groups={}
    for profile in ['all']+sorted({x['profile'] for x in outcomes}):
        groups[profile]={}
        for method in methods:
            selected=[x for x in outcomes if x['method']==method and (profile=='all' or x['profile']==profile)]
            keys=['total_cost','immediate_fill_rate','backlog_unit_periods','emissions',
                  'final_stock','final_backlog','forecast_mae','forecast_bias','solver_calls','gap_to_perfect_information_pct']
            groups[profile][method]={k:float(np.mean([x[k] for x in selected])) for k in keys}
            groups[profile][method]['contexts']=len(selected)
    by={(x['id'],x['method']):x for x in outcomes};ids=sorted({x['id'] for x in outcomes})
    paired={}
    for method in methods:
        if method in ('base_stock','perfect_information'):continue
        differences=[by[i,method]['total_cost']-by[i,'base_stock']['total_cost'] for i in ids]
        paired[method]={'mean_cost_minus_base_stock':float(np.mean(differences)),
                        'better':sum(d < -1e-6 for d in differences),
                        'worse':sum(d > 1e-6 for d in differences),
                        'ties':sum(abs(d)<=1e-6 for d in differences)}
    return {'scope':'synthetic_development_descriptive_only','distinct_development_contexts':len(ids),
            'outcomes_including_offline_bound':len(outcomes),'groups':groups,'paired':paired,
            'rl_trained':False,'final_test_created':False}


def run(output, smoke=False):
    out=Path(output)
    if out.exists() and any(out.iterdir()):raise ValueError('output_must_be_empty')
    out.mkdir(parents=True,exist_ok=True)
    cfg=json.loads((ROOT/'rolling_inventory/config.json').read_text())
    if smoke:
        cfg.update(periods=4,horizon=3,profiles=['stable','upshift'],calibration_seeds=[101],development_seeds=[1009])
    tasks=generate(cfg,'calibration',cfg['calibration_seeds'])+generate(cfg,'development',cfg['development_seeds'])
    calibration=[];traces=[];times=[]
    for z in cfg['base_stock_z_candidates']:
        for task in tasks:
            if task['split']!='calibration':continue
            result,rows,seconds=rollout(task,'base_stock',z)
            calibration.append(dict(result,z=z));traces.append({'id':task['id'],'method':'base_stock','z':z,'rows':rows})
            times.append({'id':task['id'],'method':'base_stock','split':'calibration','z':z,'seconds':seconds})
    scores={str(z):float(np.mean([x['total_cost'] for x in calibration if x['z']==z])) for z in cfg['base_stock_z_candidates']}
    selected=min(cfg['base_stock_z_candidates'],key=lambda z:(scores[str(z)],z))
    selection={'z':selected,'mean_calibration_cost':scores,'calibration_contexts':sum(t['split']=='calibration' for t in tasks)}
    # Selection is fixed before touching any development outcomes.
    outcomes=[]
    for task in tasks:
        if task['split']!='development':continue
        ref,rows,seconds=rollout(task,'perfect_information'); lower=ref['total_cost']
        for method in ['perfect_information']+cfg['methods']:
            if method!='perfect_information':result,rows,seconds=rollout(task,method,selected)
            else:result=ref
            if result['total_cost']+1e-5<lower:raise ValueError('offline_lower_bound_violated')
            result['gap_to_perfect_information_pct']=100*(result['total_cost']-lower)/max(lower,1e-9)
            outcomes.append(result);traces.append({'id':task['id'],'method':method,'z':selected,'rows':rows})
            times.append({'id':task['id'],'method':method,'split':'development','seconds':seconds})
        print('evaluated',task['id'],flush=True)
    summary=summarize(outcomes,times)
    write(out/'config.json',cfg);write(out/'tasks.json',tasks);write(out/'selection.json',selection)
    lines(out/'calibration.jsonl',calibration);lines(out/'outcomes.jsonl',outcomes)
    raw=''.join(json.dumps(r,sort_keys=True,allow_nan=False)+'\n' for r in traces).encode()
    (out/'traces.jsonl.gz').write_bytes(gzip.compress(raw,mtime=0))
    lines(out/'timing.jsonl',times);write(out/'summary.json',summary)
    write(out/'runtime.json',{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__})
    write(out/'manifest.json',{'schema':cfg['schema'],'smoke':smoke,'sources':source_identity(),
                              'files':{p.name:digest(p) for p in sorted(out.iterdir())}})
    return summary


def verify(output):
    out=Path(output);manifest=json.loads((out/'manifest.json').read_text())
    if manifest['sources']!=source_identity():raise ValueError('source_identity')
    expected={'config.json','tasks.json','selection.json','calibration.jsonl','outcomes.jsonl',
              'traces.jsonl.gz','timing.jsonl','summary.json','runtime.json'}
    if set(manifest['files'])!=expected or {p.name for p in out.iterdir()}!=expected|{'manifest.json'}:
        raise ValueError('artifact_coverage')
    for name,sha in manifest['files'].items():
        if (out/name).is_symlink() or digest(out/name)!=sha:raise ValueError('artifact_hash')
    with tempfile.TemporaryDirectory() as tmp:
        fresh=Path(tmp);run(fresh,manifest['smoke'])
        for name in expected-{'timing.jsonl','runtime.json'}:
            if name.endswith('.gz'):
                a=[json.loads(x) for x in gzip.decompress((out/name).read_bytes()).splitlines()]
                b=[json.loads(x) for x in gzip.decompress((fresh/name).read_bytes()).splitlines()]
            elif name.endswith('.jsonl'):
                a=[json.loads(x) for x in (out/name).read_text().splitlines()]
                b=[json.loads(x) for x in (fresh/name).read_text().splitlines()]
            else:a=json.loads((out/name).read_text());b=json.loads((fresh/name).read_text())
            close(a,b,name)
    return {'verified':True,'data_regenerated':True,'calibration_repeated':True,
            'all_policies_reexecuted':True,'offline_bounds_resolved':True}
