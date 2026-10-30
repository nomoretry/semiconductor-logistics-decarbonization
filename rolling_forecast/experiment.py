"""Forecast calibration, paired control, independent ledgers, and full replay."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import tempfile
import time
import numpy as np
import scipy
from rolling_inventory.environment import Environment, generate
from rolling_inventory.experiment import ROOT, audit, close, digest, write
from rolling_inventory.planning import base_stock
from rolling_sensitivity.planning import samples, solve
from .forecasting import policy_observation, score_path, scores, select

DEFAULT = ROOT/'benchmark_results/rolling_forecast_development'
MODELS = ['original_ewma', 'fast_ewma', 'seasonal_window']
METRICS = ['total_cost', 'fill_rate', 'emissions', 'final_stock', 'final_backlog',
           'backlog_unit_periods', 'solver_calls']


def identity():
    paths = []
    for package in ['rolling_forecast', 'rolling_inventory', 'rolling_sensitivity']:
        paths += list((ROOT/package).glob('*.py'))
        paths.append(ROOT/package/'config.json')
    paths += [ROOT/'docs/rolling_forecast_protocol.md',
              ROOT/'benchmark_results/rolling_inventory_development/selection.json']
    return {str(p.relative_to(ROOT)):digest(p) for p in sorted(paths)}


def settings(smoke=False):
    cfg = json.loads((ROOT/'rolling_forecast/config.json').read_text())
    physical = json.loads((ROOT/'rolling_inventory/config.json').read_text())
    old = json.loads((ROOT/'rolling_sensitivity/config.json').read_text())
    old_seeds = set(physical['calibration_seeds']+physical['development_seeds']+old['demand_seeds'])
    a, b = set(cfg['calibration_seeds']), set(cfg['development_seeds'])
    if a & b or (a | b) & old_seeds or len(a) != len(cfg['calibration_seeds']) or len(b) != len(cfg['development_seeds']):
        raise ValueError('seed_overlap_or_duplicate')
    prior_z = json.loads((ROOT/'benchmark_results/rolling_inventory_development/selection.json').read_text())['z']
    if cfg['base_stock_z'] != prior_z or physical['forecast_alpha'] != 0.35:
        raise ValueError('prior_baseline_changed')
    if (cfg['horizon'],cfg['scenarios'],cfg['allocation'],cfg['terminal_fraction']) != (6,7,'uniform',0.):
        raise ValueError('fixed_controller_changed')
    if smoke:
        cfg.update(calibration_seeds=[880001], development_seeds=[880003], sampler_seeds=[901337], bootstrap_replicates=40)
        physical.update(periods=4, horizon=3, profiles=['stable'])
    return cfg, physical


def jsonl(path, rows):
    Path(path).write_text(''.join(json.dumps(r,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n' for r in rows))


def load(path):
    if path.suffix == '.jsonl':
        return [json.loads(line) for line in path.read_text().splitlines()]
    return json.loads(path.read_text())


def hashed(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def rollout(task, name, model, sampler, cfg):
    env = Environment(task); rows = []; times = []; plan = None; calls = 0
    if name == 'clairvoyant':
        start = time.perf_counter()
        plan, info = solve(env.observe(), [task['demand']], 'free', 0.)
        times.append(time.perf_counter()-start); calls = 1
    for t in range(task['public']['periods']):
        if plan is None:
            start = time.perf_counter()
            if name == 'base_stock':
                obs = env.observe(); action, info = base_stock(obs, cfg['base_stock_z'])
            else:
                obs = policy_observation(env.observe(), model)
                schedule, info = solve(obs, samples(obs,cfg['scenarios'],sampler), 'uniform', 0.)
                action = schedule[0]; info = dict(info,solver_calls=1)
            times.append(time.perf_counter()-start); calls += info['solver_calls']
        else:
            obs = env.observe(); action = plan[t]
        row = env.step(action)
        row['policy_observation_sha256'] = hashed(obs)
        row['forecast_used'] = obs['forecast'][:task['public']['horizon']]
        row['planning'] = deepcopy(info)
        rows.append(row)
    audit(task,rows)
    demand = sum(sum(r['demand']) for r in rows)
    outcome = {'id':task['id'], 'profile':task['profile'], 'method':name, 'sampler':sampler,
               'total_cost':float(sum(r['cost'] for r in rows)),
               'costs':{k:float(sum(r['costs'][k] for r in rows)) for k in rows[0]['costs']},
               'fill_rate':sum(sum(r['filled_new']) for r in rows)/demand if demand else 1.,
               'emissions':sum(r['emissions'] for r in rows), 'remaining_carbon':env.remaining,
               'final_stock':sum(rows[-1]['stock_end']), 'final_backlog':sum(rows[-1]['backlog_end']),
               'backlog_unit_periods':sum(sum(r['backlog_end']) for r in rows), 'solver_calls':calls}
    # Regeneration reconstructs full public observations; do not repeat static parameters in every row.
    for row in rows:
        row['observation'] = {k:row['observation'][k] for k in ['arrivals','served_old']}
        row.pop('forecast_error')
    audit(task,rows)
    return outcome, rows, {'id':task['id'], 'method':name, 'sampler':sampler, 'decision_seconds':times}


def mean_metrics(rows):
    return {k:float(np.mean([r[k] for r in rows])) for k in METRICS}


def paired_contrast(outcomes, forecasts, tasks, cfg, name):
    by = {(r['id'],r['method'],r['sampler']):r for r in outcomes}
    rows = []; seed_costs = {str(s):[] for s in cfg['sampler_seeds']}
    for task in tasks:
        per_seed = []
        for seed in cfg['sampler_seeds']:
            base = by[task['id'],'original_ewma',seed]; other = by[task['id'],name,seed]
            d = {k:other[k]-base[k] for k in METRICS}; per_seed.append(d)
            seed_costs[str(seed)].append(d['total_cost'])
        delta = {k:float(np.mean([d[k] for d in per_seed])) for k in METRICS}
        nll = {}
        for method in [name,'original_ewma']:
            nll[method] = scores([r for r in forecasts if r['id']==task['id'] and r['model']==method and r['lead']==1])['poisson_nll']
        rows.append({'id':task['id'], 'profile':task['profile'], 'delta':delta,
                     'one_step_nll_delta':nll[name]-nll['original_ewma']})
    groups = [[r for r in rows if r['profile']==p] for p in sorted({t['profile'] for t in tasks})]
    rng = np.random.default_rng(cfg['bootstrap_seed']); boot = []
    for _ in range(cfg['bootstrap_replicates']):
        sample = [g[int(i)]['delta']['total_cost'] for g in groups for i in rng.integers(0,len(g),len(g))]
        boot.append(float(np.mean(sample)))
    mean = {k:float(np.mean([r['delta'][k] for r in rows])) for k in METRICS}
    interval = np.percentile(boot,[2.5,97.5]).tolist()
    seed_means = {s:float(np.mean(v)) for s,v in seed_costs.items()}
    cross = {x:0 for x in ['both_improve','forecast_only','cost_only','neither_improves']}
    for r in rows:
        f = r['one_step_nll_delta'] < -1e-9; c = r['delta']['total_cost'] < -1e-6
        cross['both_improve' if f and c else 'forecast_only' if f else 'cost_only' if c else 'neither_improves'] += 1
    return {'mean_delta':mean, 'cost_descriptive_95_interval':interval,
            'sampling_seed_cost_deltas':seed_means,
            'profile_cost_deltas':{g[0]['profile']:float(np.mean([r['delta']['total_cost'] for r in g])) for g in groups},
            'better_paths':sum(r['delta']['total_cost'] < -1e-6 for r in rows),
            'worse_paths':sum(r['delta']['total_cost'] > 1e-6 for r in rows),
            'tied_paths':sum(abs(r['delta']['total_cost']) <= 1e-6 for r in rows),
            'forecast_cost_cross_tab':cross, 'paths':rows,
            'descriptive_teacher_stable':bool(mean['total_cost']<0 and interval[1]<0 and all(x<0 for x in seed_means.values()) and mean['fill_rate']>=-0.01)}


def summarize(outcomes, forecasts, timing, tasks, cfg, selection):
    methods = MODELS+['base_stock','clairvoyant']; profiles = sorted({t['profile'] for t in tasks})
    groups = {p:{m:mean_metrics([r for r in outcomes if r['method']==m and (p=='all' or r['profile']==p)])
                 for m in methods} for p in ['all']+profiles}
    predictive = {p:{m:{str(lead):scores([r for r in forecasts if r['model']==m and r['lead']==lead and (p=='all' or r['profile']==p)])
                       for lead in sorted({r['lead'] for r in forecasts})} for m in MODELS} for p in ['all']+profiles}
    measured = {}
    for m in methods:
        values = np.asarray([x for r in timing if r['method']==m for x in r['decision_seconds']])
        expected = len(tasks) * (1 if m=='clairvoyant' else tasks[0]['public']['periods']) * (len(cfg['sampler_seeds']) if m in MODELS else 1)
        if len(values)!=expected or not np.all(np.isfinite(values)) or np.any(values<0):
            raise ValueError('invalid_timing')
        measured[m] = {'calls_timed':len(values), 'mean_seconds':float(values.mean()),
                       'p95_seconds':float(np.percentile(values,95))}
    contrasts = {m:paired_contrast(outcomes,forecasts,tasks,cfg,m) for m in MODELS[1:]}
    return {'scope':cfg['scope'], 'calibration_paths':selection['calibration_paths'],
            'distinct_development_paths':len(tasks), 'trajectories':len(outcomes),
            'period_records':len(outcomes)*tasks[0]['public']['periods'],
            'selected_models':selection['models'], 'forecast_scores':predictive,
            'decision_metrics':groups, 'paired_contrasts':contrasts,
            'timing_measured_not_replay_equal':measured,
            'learning':{'rl_trained':False, 'formal_final_created':False,
                        'decision':'defer_rolling_BC_PPO',
                        'reason':'Development screening is not independent confirmation; no deployment deadline or acceptable quality loss is specified.'}}


def run(output, smoke=False):
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise ValueError('output_must_be_empty')
    out.mkdir(parents=True,exist_ok=True)
    cfg, physical = settings(smoke)
    calibration = generate(physical,'forecast-calibration',cfg['calibration_seeds'])
    selection, calibration_scores = select(calibration,cfg)
    write(out/'selection.json',selection)  # Fixed before generating development paths.
    tasks = generate(physical,'forecast-development',cfg['development_seeds'])
    variants = [(m,s) for m in MODELS for s in cfg['sampler_seeds']]+[('base_stock',0),('clairvoyant',0)]
    outcomes = []; timing = []; forecasts = []
    for index, task in enumerate(tasks):
        forecast_rows = []
        for name, model in selection['models'].items():
            forecast_rows += score_path(task,model,name)
        forecasts += forecast_rows
        jsonl(out/f'forecasts-{index:02}.jsonl',forecast_rows)
        records = []
        for i in np.random.default_rng(5581+index).permutation(len(variants)):
            name, seed = variants[int(i)]
            result, rows, seconds = rollout(task,name,selection['models'].get(name),seed,cfg)
            outcomes.append(result); timing.append(seconds)
            records.append({'id':task['id'], 'method':name, 'sampler':seed, 'rows':rows})
        subset = [r for r in outcomes if r['id']==task['id']]
        lower = next(r['total_cost'] for r in subset if r['method']=='clairvoyant')
        if any(r['total_cost'] < lower-1e-5 for r in subset):
            raise ValueError('clairvoyant_bound_violated')
        jsonl(out/f'traces-{index:02}.jsonl',sorted(records,key=lambda r:(r['method'],r['sampler'])))
        print(f'evaluated {index+1}/{len(tasks)}: {task["id"]}',flush=True)
    outcomes.sort(key=lambda r:(r['id'],r['method'],r['sampler']))
    timing.sort(key=lambda r:(r['id'],r['method'],r['sampler']))
    result = summarize(outcomes,forecasts,timing,tasks,cfg,selection)
    write(out/'config.json',cfg); write(out/'tasks.json',calibration+tasks)
    jsonl(out/'calibration.jsonl',calibration_scores); jsonl(out/'outcomes.jsonl',outcomes)
    jsonl(out/'timing.jsonl',timing); write(out/'summary.json',result)
    write(out/'runtime.json',{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__})
    write(out/'manifest.json',{'schema':cfg['schema'],'smoke':smoke,'sources':identity(),
                              'files':{p.name:digest(p) for p in sorted(out.iterdir())}})
    return result


def verify(output):
    out = Path(output); manifest = load(out/'manifest.json')
    if manifest['sources'] != identity():
        raise ValueError('source_identity')
    if type(manifest['smoke']) is not bool:
        raise ValueError('invalid_smoke_flag')
    cfg, physical = settings(manifest['smoke'])
    count = len(cfg['development_seeds'])*len(physical['profiles'])
    expected = {'config.json','tasks.json','selection.json','calibration.jsonl','outcomes.jsonl','timing.jsonl','summary.json','runtime.json'}
    expected |= {f'{prefix}-{i:02}.jsonl' for prefix in ['traces','forecasts'] for i in range(count)}
    if set(manifest['files'])!=expected or {p.name for p in out.iterdir()}!=expected|{'manifest.json'}:
        raise ValueError('artifact_coverage')
    for name, sha in manifest['files'].items():
        if (out/name).is_symlink() or digest(out/name)!=sha:
            raise ValueError('artifact_hash')
    tasks = [t for t in load(out/'tasks.json') if t['split']=='forecast-development']
    forecasts = [r for i in range(count) for r in load(out/f'forecasts-{i:02}.jsonl')]
    # Recompute the archived timing summary from its own measurements, not fresh wall time.
    close(load(out/'summary.json'),summarize(load(out/'outcomes.jsonl'),forecasts,load(out/'timing.jsonl'),tasks,cfg,load(out/'selection.json')))
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp); run(fresh,manifest['smoke'])
        for name in expected-{'timing.jsonl','runtime.json'}:
            a, b = load(out/name), load(fresh/name)
            if name=='summary.json':
                a.pop('timing_measured_not_replay_equal'); b.pop('timing_measured_not_replay_equal')
            close(a,b,name)
    return {'verified':True,'data_regenerated':True,'calibration_repeated':True,
            'all_policies_reexecuted':True,'physical_ledgers_audited':True,
            'forecast_scores_recomputed':True,'archived_timing_summary_recomputed':True}
