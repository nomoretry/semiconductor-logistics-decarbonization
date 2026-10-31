"""Separated fitting, tuning and confirmation with policy-bound replay."""
import gzip
import json
from pathlib import Path
import platform
import tempfile
import time
import numpy as np
import scipy
from rolling_inventory.environment import Environment, generate
from rolling_inventory.experiment import ROOT, audit, close, digest, write
from rolling_inventory.planning import base_stock, path_cost
from rolling_sensitivity.planning import solve
from rolling_forecast.experiment import hashed
from .forecasting import fit, observation, sample, couple, nll, ensemble_scores, select

DEFAULT = ROOT/'benchmark_results/rolling_distribution_confirmation'
METHODS = ['poisson', 'residual_nb']
METRICS = ['total_cost', 'fill_rate', 'emissions', 'final_stock', 'final_backlog',
           'backlog_unit_periods', 'solver_calls']


def identity():
    paths = []
    for package in ['rolling_distribution', 'rolling_inventory', 'rolling_sensitivity', 'rolling_forecast']:
        paths += list((ROOT/package).glob('*.py'))+[ROOT/package/'config.json']
    paths += [ROOT/'docs/rolling_distribution_protocol.md',
              ROOT/'benchmark_results/rolling_inventory_development/selection.json']
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}


def settings(smoke=False):
    cfg = json.loads((ROOT/'rolling_distribution/config.json').read_text())
    physical = json.loads((ROOT/'rolling_inventory/config.json').read_text())
    old = set(physical['calibration_seeds']+physical['development_seeds'])
    for package, keys in [('rolling_sensitivity', ['demand_seeds']),
                          ('rolling_forecast', ['calibration_seeds', 'development_seeds'])]:
        prior = json.loads((ROOT/package/'config.json').read_text())
        for key in keys:
            old.update(prior[key])
    seeds = [s for k in ['fit_seeds', 'tune_seeds', 'confirmation_seeds'] for s in cfg[k]]
    if len(seeds) != len(set(seeds)) or old & set(seeds):
        raise ValueError('split_seed_overlap')
    if (cfg['horizon'], cfg['scenarios'], cfg['allocation'], cfg['terminal_fraction'],
        physical['forecast_alpha']) != (6, 7, 'uniform', 0., .35):
        raise ValueError('fixed_controller_changed')
    prior_z = json.loads((ROOT/'benchmark_results/rolling_inventory_development/selection.json').read_text())['z']
    if cfg['base_stock_z'] != prior_z:
        raise ValueError('base_stock_changed')
    if smoke:
        cfg.update(fit_seeds=[990001], tune_seeds=[990007], confirmation_seeds=[990013],
                   sampler_seeds=[901337], score_members=16, bootstrap_replicates=40)
        physical.update(periods=4, horizon=3, profiles=['stable'])
    return cfg, physical


def save_rows(path, rows):
    raw = ''.join(json.dumps(r, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n' for r in rows).encode()
    Path(path).write_bytes(gzip.compress(raw, mtime=0) if str(path).endswith('.gz') else raw)


def read(path):
    path = Path(path)
    raw = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
    return [json.loads(x) for x in raw.splitlines()] if '.jsonl' in path.name else json.loads(raw)


def dependence_audit(obs, scenarios, plan, info, prior, strength, seed):
    rearranged = couple(scenarios, obs, prior, strength, seed)
    other, second = solve(obs, rearranged, 'uniform', 0.)
    values = [[float(np.mean([path_cost(obs, schedule, d) for d in ensemble]))
               for ensemble in [scenarios, rearranged]] for schedule in [plan, other]]
    error = max(abs(values[0][0]-values[0][1]), abs(values[1][0]-values[1][1]),
                abs(info['objective']-second['objective']))
    if error > 1e-5:
        raise ValueError('cross_sku_pairing_invariance_failed')
    return {'origin': obs['t'], 'original': scenarios.tolist(), 'rearranged': rearranged.tolist(),
            'original_schedule': plan, 'rearranged_schedule': other,
            'cross_objectives': values, 'max_error': error,
            'first_action_differs': plan[0] != other[0],
            'schedule_differs': plan != other}


def rollout(task, method, seed, prior, strength, cfg):
    env = Environment(task); rows = []; times = []; audits = []; plan = None; calls = 0
    if method == 'clairvoyant':
        start = time.perf_counter()
        plan, info = solve(env.observe(), [task['demand']], 'free', 0.)
        times.append(time.perf_counter()-start); calls = 1
    for t in range(task['public']['periods']):
        scenarios = None; kappa = None
        if plan is None:
            start = time.perf_counter()
            obs = observation(env.observe())
            if method == 'base_stock':
                action, info = base_stock(obs, cfg['base_stock_z'])
            else:
                scenarios, kappa = sample(obs, prior, strength, method, cfg['scenarios'], seed, cfg['dispersion_cap'])
                schedule, info = solve(obs, scenarios, 'uniform', 0.)
                action = schedule[0]; info = dict(info, solver_calls=1)
            times.append(time.perf_counter()-start); calls += info['solver_calls']
            if method == 'residual_nb' and seed == cfg['sampler_seeds'][0]:
                audits.append(dependence_audit(obs, scenarios, schedule, info, prior, strength, seed))
        else:
            obs = observation(env.observe()); action = plan[t]
        row = env.step(action)
        row.update(policy_observation_sha256=hashed(obs), planning=info,
                   scenarios=None if scenarios is None else scenarios.tolist(),
                   kappa=None if kappa is None else kappa.tolist())
        rows.append(row)
    audit(task, rows)
    demand = sum(sum(r['demand']) for r in rows)
    outcome = {'id': task['id'], 'profile': task['profile'], 'method': method, 'sampler': seed,
               'total_cost': float(sum(r['cost'] for r in rows)),
               'costs': {k: float(sum(r['costs'][k] for r in rows)) for k in rows[0]['costs']},
               'fill_rate': sum(sum(r['filled_new']) for r in rows)/demand if demand else 1.,
               'emissions': sum(r['emissions'] for r in rows), 'remaining_carbon': env.remaining,
               'final_stock': sum(rows[-1]['stock_end']), 'final_backlog': sum(rows[-1]['backlog_end']),
               'backlog_unit_periods': sum(sum(r['backlog_end']) for r in rows), 'solver_calls': calls}
    for row in rows:
        row['observation'] = {k: row['observation'][k] for k in ['arrivals', 'served_old']}
        row.pop('forecast_error')
    audit(task, rows)
    return outcome, rows, {'id': task['id'], 'method': method, 'sampler': seed,
                           'decision_seconds': times}, audits


def score_forecasts(task, prior, strength, cfg):
    env = Environment(task); rows = []
    for t in range(task['public']['periods']):
        obs = observation(env.observe())
        ensembles = {}; dispersion = {}
        for method in METHODS:
            ensembles[method], dispersion[method] = sample(obs, prior, strength, method, cfg['score_members'],
                                                          cfg['score_seed'], cfg['dispersion_cap'])
        ensembles['joint_diagnostic'] = couple(ensembles['residual_nb'], obs, prior, strength, cfg['score_seed'])
        # Truth is accessed only after all predictive ensembles have been constructed.
        for method, values in ensembles.items():
            h = values.shape[1]; truth = np.asarray(task['demand'][t:t+h])
            kappa = dispersion['residual_nb' if method == 'joint_diagnostic' else method]
            rows.append({'id': task['id'], 'profile': task['profile'], 'origin': t, 'method': method,
                         'members': values.tolist(), 'mean': obs['forecast'][:h],
                         'kappa': kappa.tolist(), 'truth': truth.tolist(),
                         'one_step_nll': float(nll(truth[0], obs['forecast'][0], kappa).mean()),
                         'one_step': ensemble_scores(values[:, 0, :], truth[0]),
                         'horizon_total': ensemble_scores(values.sum(axis=1), truth.sum(axis=0))})
        env.step(np.zeros((3, 2), dtype=int))
    return rows


def summarize(outcomes, forecasts, audits, timing, tasks, selection, cfg):
    profiles = sorted({t['profile'] for t in tasks})
    all_methods = METHODS+['base_stock', 'clairvoyant']
    metrics = {p: {m: {k: float(np.mean([r[k] for r in outcomes if r['method'] == m
                                       and (p == 'all' or r['profile'] == p)])) for k in METRICS}
                   for m in all_methods} for p in ['all']+profiles}
    predictive = {m: {'one_step_nll': float(np.mean([r['one_step_nll'] for r in forecasts if r['method'] == m])),
                     **{h: {k: float(np.mean([r[h][k] for r in forecasts if r['method'] == m]))
                            for k in forecasts[0][h]} for h in ['one_step', 'horizon_total']}}
                  for m in METHODS+['joint_diagnostic']}
    by = {(r['id'], r['method'], r['sampler']): r for r in outcomes}
    differences = []; per_seed = {str(s): [] for s in cfg['sampler_seeds']}
    for task in tasks:
        ds = []
        for seed in cfg['sampler_seeds']:
            d = {k: by[task['id'], 'residual_nb', seed][k]-by[task['id'], 'poisson', seed][k] for k in METRICS}
            ds.append(d); per_seed[str(seed)].append(d['total_cost'])
        differences.append({'id': task['id'], 'profile': task['profile'],
                            'delta': {k: float(np.mean([d[k] for d in ds])) for k in METRICS}})
    groups = [[r['delta']['total_cost'] for r in differences if r['profile'] == p] for p in profiles]
    rng = np.random.default_rng(cfg['bootstrap_seed'])
    boot = [float(np.mean([g[int(i)] for g in groups for i in rng.integers(len(g), size=len(g))]))
            for _ in range(cfg['bootstrap_replicates'])]
    interval = np.percentile(boot, [2.5, 97.5]).tolist()
    delta = {k: metrics['all']['residual_nb'][k]-metrics['all']['poisson'][k] for k in METRICS}
    seeds = {k: float(np.mean(v)) for k, v in per_seed.items()}
    relative = delta['total_cost']/metrics['all']['poisson']['total_cost']
    checks = {'cost_reduction_at_least_2pct': relative <= -cfg['teacher_min_relative_improvement'],
              'primary_interval_upper_negative': interval[1] < 0,
              'each_sampler_improves': all(v < 0 for v in seeds.values()),
              'fill_loss_at_most_0_005': delta['fill_rate'] >= -cfg['teacher_fill_tolerance'],
              'emissions_increase_at_most_2pct': delta['emissions'] <=
                   cfg['teacher_emissions_relative_tolerance']*metrics['all']['poisson']['emissions']}
    measured = {}
    for method in all_methods:
        values = np.asarray([x for r in timing if r['method'] == method for x in r['decision_seconds']])
        expected = len(tasks)*(1 if method == 'clairvoyant' else tasks[0]['public']['periods'])*(len(cfg['sampler_seeds']) if method in METHODS else 1)
        if len(values) != expected or not np.all(np.isfinite(values)) or np.any(values < 0):
            raise ValueError('invalid_timing')
        measured[method] = {'count': len(values), 'mean_seconds': float(values.mean()),
                            'p95_seconds': float(np.percentile(values, 95))}
    audit_rows = [x for r in audits for x in r['rows']]
    if len(audit_rows) != len(tasks)*tasks[0]['public']['periods']:
        raise ValueError('audit_coverage')
    return {'scope': cfg['scope'], 'fit_paths': 4*len(cfg['fit_seeds']) if len(profiles)==4 else len(cfg['fit_seeds']),
            'tune_paths': selection['tuning_paths'], 'confirmation_paths': len(tasks),
            'trajectories': len(outcomes), 'period_records': len(outcomes)*tasks[0]['public']['periods'],
            'selected_strength': selection['strength'], 'decision_metrics': metrics, 'forecast_scores': predictive,
            'primary_contrast': {'mean_delta': delta, 'relative_cost_delta': relative,
                                 'paired_path_95_interval': interval, 'sampler_cost_deltas': seeds,
                                 'profile_cost_deltas': dict(zip(profiles, [float(np.mean(g)) for g in groups])),
                                 'better_paths': sum(r['delta']['total_cost'] < -1e-6 for r in differences),
                                 'worse_paths': sum(r['delta']['total_cost'] > 1e-6 for r in differences),
                                 'paths': differences},
            'dependence_audit': {'origins': len(audit_rows),
                                 'max_objective_error': max(r['max_error'] for r in audit_rows),
                                 'different_first_actions': sum(r['first_action_differs'] for r in audit_rows),
                                 'different_schedules': sum(r['schedule_differs'] for r in audit_rows),
                                 'decision_value_identifiable': False},
            'timing_measured_not_replay_equal': measured,
            'learning': {'quality_teacher_checks': checks, 'quality_teacher_passed': all(checks.values()),
                         'compute_target_specified': cfg['deployment_p95_deadline_seconds'] is not None
                              and cfg['acceptable_policy_cost_increase'] is not None,
                         'rolling_bc_trained': False, 'rolling_ppo_trained': False,
                         'decision': 'separate_policy_study_required_if_teacher_passes_otherwise_defer'}}


def run(output, smoke=False):
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise ValueError('output_must_be_empty')
    out.mkdir(parents=True, exist_ok=True)
    cfg, physical = settings(smoke)
    fitting = generate(physical, 'distribution-fit', cfg['fit_seeds'])
    tuning = generate(physical, 'distribution-tune', cfg['tune_seeds'])
    prior, residuals = fit(fitting)
    selection, tuning_rows = select(tuning, prior, cfg)
    write(out/'fit.json', prior); write(out/'selection.json', selection)
    tasks = generate(physical, 'distribution-confirmation', cfg['confirmation_seeds'])
    variants = [(m, s) for m in METHODS for s in cfg['sampler_seeds']]+[('base_stock', 0), ('clairvoyant', 0)]
    outcomes = []; timing = []; forecasts = []; audits = []; records = []
    for index, task in enumerate(tasks):
        forecasts += score_forecasts(task, prior, selection['strength'], cfg)
        for j in np.random.default_rng(77101+index).permutation(len(variants)):
            method, seed = variants[int(j)]
            result, rows, seconds, checks = rollout(task, method, seed, prior, selection['strength'], cfg)
            outcomes.append(result); timing.append(seconds)
            records.append({'id': task['id'], 'method': method, 'sampler': seed, 'rows': rows})
            if checks:
                audits.append({'id': task['id'], 'rows': checks})
        current = [r for r in outcomes if r['id'] == task['id']]
        lower = next(r['total_cost'] for r in current if r['method'] == 'clairvoyant')
        if any(r['total_cost'] < lower-1e-5 for r in current):
            raise ValueError('clairvoyant_bound_violated')
        print(f'evaluated {index+1}/{len(tasks)}: {task["id"]}', flush=True)
    for values in [outcomes, timing, records]:
        values.sort(key=lambda r: (r['id'], r['method'], r['sampler']))
    summary = summarize(outcomes, forecasts, audits, timing, tasks, selection, cfg)
    write(out/'config.json', cfg); write(out/'tasks.json', fitting+tuning+tasks)
    save_rows(out/'fit_residuals.jsonl.gz', residuals); save_rows(out/'tuning.jsonl.gz', tuning_rows)
    save_rows(out/'outcomes.jsonl', outcomes); save_rows(out/'timing.jsonl.gz', timing)
    # Small deterministic chunks fit GitHub's ordinary blob API; no hidden omitted evidence.
    for chunk, start in enumerate(range(0, len(tasks), 8)):
        ids = {t['id'] for t in tasks[start:start+8]}
        for prefix, values in [('traces', records), ('forecasts', forecasts), ('dependence', audits)]:
            save_rows(out/f'{prefix}-{chunk:02}.jsonl.gz', [r for r in values if r['id'] in ids])
    write(out/'summary.json', summary)
    write(out/'runtime.json', {'python': platform.python_version(), 'numpy': np.__version__, 'scipy': scipy.__version__})
    write(out/'manifest.json', {'schema': cfg['schema'], 'smoke': smoke, 'sources': identity(),
                               'files': {p.name: digest(p) for p in sorted(out.iterdir())}})
    return summary


def verify(output):
    out = Path(output); manifest = read(out/'manifest.json')
    if manifest['sources'] != identity():
        raise ValueError('source_identity')
    if type(manifest['smoke']) is not bool:
        raise ValueError('invalid_smoke_flag')
    cfg, physical = settings(manifest['smoke'])
    count = len(cfg['confirmation_seeds'])*len(physical['profiles'])
    expected = {'config.json', 'tasks.json', 'fit.json', 'selection.json', 'fit_residuals.jsonl.gz',
                'tuning.jsonl.gz', 'outcomes.jsonl', 'timing.jsonl.gz', 'summary.json', 'runtime.json'}
    expected |= {f'{prefix}-{i:02}.jsonl.gz' for prefix in ['traces', 'forecasts', 'dependence']
                 for i in range((count+7)//8)}
    if set(manifest['files']) != expected or {p.name for p in out.iterdir()} != expected|{'manifest.json'}:
        raise ValueError('artifact_coverage')
    for name, sha in manifest['files'].items():
        if (out/name).is_symlink() or digest(out/name) != sha:
            raise ValueError('artifact_hash')
    tasks = [t for t in read(out/'tasks.json') if t['split'] == 'distribution-confirmation']
    forecasts = [r for i in range((count+7)//8) for r in read(out/f'forecasts-{i:02}.jsonl.gz')]
    audits = [r for i in range((count+7)//8) for r in read(out/f'dependence-{i:02}.jsonl.gz')]
    close(read(out/'summary.json'), summarize(read(out/'outcomes.jsonl'), forecasts, audits,
          read(out/'timing.jsonl.gz'), tasks, read(out/'selection.json'), cfg))
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp); run(fresh, manifest['smoke'])
        for name in sorted(expected-{'runtime.json', 'timing.jsonl.gz'}):
            a, b = read(out/name), read(fresh/name)
            if name == 'summary.json':
                a.pop('timing_measured_not_replay_equal'); b.pop('timing_measured_not_replay_equal')
            close(a, b, name)
    return {'verified': True, 'splits_regenerated': True, 'selection_repeated': True,
            'policies_reexecuted': True, 'independent_physical_audit': True,
            'dependence_invariance_rechecked': True, 'forecast_scores_recomputed': True,
            'archived_timing_summary_recomputed': True}
