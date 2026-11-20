"""M1 first-action stability on the frozen v2 audit observations."""
from collections import Counter
from itertools import combinations, product
import json
from pathlib import Path
import time

import numpy as np

from rolling_inventory.environment import validate
from . import scenarios as sc
from .experiment import ROOT, array_digest, digest_bytes, forced_zero, read_lines, runtime, write_json
from .experiment_v2 import PILOT
from .planning import Model, solve


OUTPUT = ROOT/'benchmark_results/rolling_tree_stability'
PROTOCOL = ROOT/'docs/rolling_tree_stability_protocol.md'
SOURCE_FILES = ('config.json', 'summary.json', 'tasks.json', 'traces.jsonl', 'audit.jsonl')
EVIDENCE_FILES = ('config.json', 'timing.jsonl', 'states.jsonl', 'summary.json', 'runtime.json')


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _hashes(folder, files):
    return {name: digest_bytes((folder/name).read_bytes()) for name in files}


def _inputs(pilot):
    pilot = Path(pilot)
    hashes = _hashes(pilot, SOURCE_FILES)
    manifest = _json(pilot/'manifest.json')
    if any(manifest[name] != value for name, value in hashes.items()):
        raise ValueError('pilot_source_hash')
    saved = _json(pilot/'config.json')
    cfg = saved['rolling_tree_v2']
    selection = saved['selection']
    tasks = _json(pilot/'tasks.json')
    profiles = {task['id']: task['profile'] for task in tasks}
    states = {}
    for trace in read_lines(pilot/'traces.jsonl'):
        if trace['method'] != 'B1':
            continue
        for row in sorted(trace['rows'], key=lambda r: r['observation']['t']):
            obs = row['observation']
            sc.check_observation(obs)
            if not forced_zero(obs):
                key = (trace['id'], obs['t'])
                if key in states:
                    raise ValueError(f'duplicate_B1_observation:{key}')
                states[key] = (profiles[trace['id']], obs)
    seeds = cfg['sampler_seeds']
    audits = [(row['path'], row['t'], row['sampler_seed']) for row in read_lines(pilot/'audit.jsonl')
              if not row['forced_zero']]
    expected = {(path, t, seed) for (path, t), seed in product(states, seeds)}
    if not expected or len(audits) != len(expected) or set(audits) != expected:
        raise ValueError('audit_observation_alignment')
    config = {
        'schema': 'rolling-tree-first-action-stability',
        'split': cfg['pilot']['split'],
        'pilot_sha256': hashes,
        'protocol_sha256': digest_bytes(PROTOCOL.read_bytes()),
        'observations': len(states),
        'audit_states': len(audits),
        'sampler_seeds': seeds,
        'branching': selection['shape']['branching'],
        'prior_strength': selection['prior_strength'],
        'fitted_variance': _json(pilot/'summary.json')['fit']['fitted_variance'],
        'variance_cap': cfg['common_variance_cap'],
        'paced_carbon': cfg['paced_carbon'],
        'solver': cfg['solver'],
        'reference_tiers': [1, 3],
        'larger_tiers': [6, 9, 12],
        'online_p95_limit_seconds': 10.0,
        'max_formal_wall_seconds': 3600.0,
        'start_guard_seconds': 45.0,
        'max_failure_rate': 0.05,
        'max_action_change_rate': 0.10,
        'retries': 0,
    }
    return config, states


def _jobs(states, config, tiers, timing=False):
    first_periods = {}
    for path, t in states:
        first_periods.setdefault(path, t)
    observations = first_periods.items() if timing else states
    return [(path, t, seed, tier) for (path, t), seed, tier in product(observations, config['sampler_seeds'], tiers)]


def _model(obs, config, seed, tier):
    variance = sc.common_variance(obs, config['fitted_variance'], config['prior_strength'], config['variance_cap'])
    paths, _, depth = sc.joint_tree_v2(obs, variance, config['branching'], tier, seed)
    return Model(obs, paths, depth, config['paced_carbon']), paths, variance


def _tree_summary(model, paths, variance):
    return dict(model.summary(), paths_sha256=array_digest(paths), common_variance=variance)


def _attempt(index, job, states, config):
    path, t, seed, tier = job
    profile, obs = states[path, t]
    start = time.perf_counter()
    model, paths, variance = _model(obs, config, seed, tier)
    solution, record = solve(model, config['solver']['time_limit_seconds'])
    online_seconds = time.perf_counter()-start
    solver_fields = ('status', 'message', 'mip_gap', 'nodes', 'feasible_solution', 'wall_seconds', 'cpu_seconds')
    return {
        'attempt': index, 'path': path, 't': t, 'profile': profile, 'sampler_seed': seed, 'continuation': tier,
        'tree': _tree_summary(model, paths, variance),
        'solver': {field: record[field] for field in solver_fields},
        'online_seconds': online_seconds,
        'action': None if solution is None else solution['action'],
    }


def _run_phase(path, jobs, states, config, progress, formal=False):
    rows = []
    failures = 0
    next_report = 900
    start = time.perf_counter()
    with path.open('x', encoding='utf-8') as ledger:
        for index, job in enumerate(jobs, 1):
            if formal and time.perf_counter()-start > config['max_formal_wall_seconds']-config['start_guard_seconds']:
                break
            row = _attempt(index, job, states, config)
            ledger.write(json.dumps(row, sort_keys=True, allow_nan=False)+'\n')
            ledger.flush()
            rows.append(row)
            failures += row['action'] is None
            if formal:
                wall = time.perf_counter()-start
                if progress is not None and wall >= next_report:
                    progress('formal_progress', {'attempts': index, 'failures': failures, 'wall_seconds': wall})
                    next_report += 900
                if failures/index > config['max_failure_rate']:
                    break
    return rows, time.perf_counter()-start


def _duration(values):
    if not values:
        return None
    return {'mean': float(np.mean(values)), 'p95': float(np.quantile(values, .95)), 'max': max(values)}


def _tier_summary(rows, tiers):
    summary = {}
    for tier in tiers:
        group = [r for r in rows if r['continuation'] == tier]
        gaps = [r['solver']['mip_gap'] for r in group if r['solver']['mip_gap'] is not None]
        summary[str(tier)] = {
            'attempts': len(group),
            'failures': sum(r['action'] is None for r in group),
            'status_counts': dict(Counter(str(r['solver']['status']) for r in group)),
            'max_reported_mip_gap': max(gaps, default=None),
            'online_seconds': _duration([r['online_seconds'] for r in group]),
            'solver_wall_seconds': _duration([r['solver']['wall_seconds'] for r in group]),
        }
    return summary


def _select(config, timing):
    p95 = {int(tier): metrics['online_seconds']['p95'] for tier, metrics in timing.items()}
    accepted = [tier for tier in config['larger_tiers'] if p95[tier] <= config['online_p95_limit_seconds']]
    if not accepted:
        return {'tier': None, 'estimated_formal_wall_seconds': None, 'stop_reason': 'no_tier_within_online_p95'}
    tier = max(accepted)
    estimate = (config['audit_states'] * sum(p95[t] for t in [*config['reference_tiers'], tier])
                + config['start_guard_seconds'])
    reason = 'estimated_formal_wall_above_budget' if estimate > config['max_formal_wall_seconds'] else None
    return {'tier': tier, 'estimated_formal_wall_seconds': estimate, 'stop_reason': reason}


def _counts(differences):
    comparable = [d for d in differences if d is not None]
    changed = sum(bool(np.any(d)) for d in comparable)
    return {'planned': len(differences), 'comparable': len(comparable),
            'missing': len(differences)-len(comparable), 'changed': changed,
            'change_rate': changed/len(comparable) if comparable else None}


def _comparison(pairs):
    """Each pair supplies a process, period and two optional first-action matrices."""
    rows = [(profile, t, np.abs(np.asarray(left)-right) if left is not None and right is not None else None)
            for profile, t, left, right in pairs]
    by_period = {str(t): _counts([d for _, period, d in rows if period == t])
                 for t in sorted({t for _, t, _ in rows})}
    by_profile = {p: _counts([d for profile, _, d in rows if profile == p])
                  for p in sorted({profile for profile, _, _ in rows})}
    cells = []
    for sku, (route, name) in product(range(3), enumerate(('slow', 'fast'))):
        units = [int(d[sku, route]) for _, _, d in rows if d is not None]
        cells.append({'sku': sku+1, 'route': name, 'changed_pairs': sum(n > 0 for n in units),
                      'absolute_units': sum(units)})
    return dict(_counts([d for _, _, d in rows]), by_period=by_period, by_profile=by_profile, by_sku_route=cells)


def _row_key(row):
    return row['path'], row['t'], row['sampler_seed'], row['continuation']


def _contrasts(states, seeds, tiers, rows):
    actions = {_row_key(r): r['action'] for r in rows}
    across_tiers = {}
    for left, right in combinations(tiers, 2):
        across_tiers[f'{left}_to_{right}'] = _comparison([
            (profile, t, actions.get((path, t, seed, left)), actions.get((path, t, seed, right)))
            for ((path, t), (profile, _)), seed in product(states.items(), seeds)
        ])
    across_seeds = {}
    for tier in tiers:
        across_seeds[str(tier)] = _comparison([
            (profile, t, actions.get((path, t, left, tier)), actions.get((path, t, right, tier)))
            for ((path, t), (profile, _)), (left, right) in product(states.items(), combinations(seeds, 2))
        ])
    return across_tiers, across_seeds


def _summary(config, states, trial, formal, timings):
    timing_tiers = config['reference_tiers'] + config['larger_tiers']
    timing = _tier_summary(trial, timing_tiers)
    selection = _select(config, timing)
    tier = selection['tier']
    stop = selection['stop_reason']
    levels = [] if tier is None else [*config['reference_tiers'], tier]
    failures = sum(r['action'] is None for r in formal)
    failure_rate = failures/len(formal) if formal else None
    wall = timings['formal_wall_seconds']
    planned = config['audit_states']*len(levels)
    if stop is None:
        if failure_rate is not None and failure_rate > config['max_failure_rate']:
            stop = 'formal_failure_rate_above_limit'
        elif len(formal) != planned or wall > config['max_formal_wall_seconds']:
            stop = 'formal_wall_budget'
    across_tiers, across_seeds = _contrasts(states, config['sampler_seeds'], levels, formal)
    gates = None
    conclusion = 'unassessed'
    if stop is None:
        limit = config['max_action_change_rate']
        gates = {'continuation': across_tiers[f'3_to_{tier}']['change_rate'] <= limit,
                 'sampling': across_seeds[str(tier)]['change_rate'] <= limit}
        conclusion = 'stable' if all(gates.values()) else 'unstable'
    return {
        'observations': config['observations'], 'audit_states': config['audit_states'],
        'timing': {'attempts': len(trial), 'wall_seconds': timings['timing_wall_seconds'], 'tiers': timing},
        'selection': selection, 'stop_reason': stop, 'conclusion': conclusion, 'gates': gates,
        'formal': {'planned': planned, 'attempts': len(formal), 'failures': failures, 'failure_rate': failure_rate,
                   'wall_seconds': wall, 'tiers': _tier_summary(formal, levels)},
        'across_tiers': across_tiers, 'across_seeds': across_seeds,
    }


def run(output=OUTPUT, pilot=PILOT, progress=None):
    """Run the timing trial and, if its time gates pass, the formal M1 comparison."""
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f'output_not_empty:{out}')
    config, states = _inputs(pilot)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out/'config.json', config)
    tiers = config['reference_tiers'] + config['larger_tiers']
    timing_jobs = _jobs(states, config, tiers, timing=True)
    trial, timing_wall = _run_phase(out/'timing.jsonl', timing_jobs, states, config, progress)
    timing = _tier_summary(trial, tiers)
    selection = _select(config, timing)
    if progress is not None:
        progress('timing_complete', dict(selection, attempts=len(trial), wall_seconds=timing_wall,
                                         p95_seconds={k: v['online_seconds']['p95'] for k, v in timing.items()}))
    formal_wall = None
    formal = []
    if selection['stop_reason'] is None:
        jobs = _jobs(states, config, [*config['reference_tiers'], selection['tier']])
        if progress is not None:
            progress('formal_start', {'tier': selection['tier'], 'planned': len(jobs)})
        formal, formal_wall = _run_phase(out/'states.jsonl', jobs, states, config, progress, formal=True)
    else:
        (out/'states.jsonl').touch()
    timings = {'timing_wall_seconds': timing_wall, 'formal_wall_seconds': formal_wall}
    summary = _summary(config, states, trial, formal, timings)
    write_json(out/'runtime.json', dict(runtime(), **timings))
    write_json(out/'summary.json', summary)
    write_json(out/'manifest.json', _hashes(out, EVIDENCE_FILES))
    if progress is not None and formal_wall is not None:
        progress('formal_complete', dict(summary['formal'], stop_reason=summary['stop_reason']))
    return summary


def _verify_rows(rows, jobs, states, config, formal=False):
    failures = 0
    for index, (row, job) in enumerate(zip(rows, jobs), 1):
        path, t, seed, tier = job
        profile, obs = states[path, t]
        if row['attempt'] != index or _row_key(row) != job or row['profile'] != profile:
            raise ValueError(f'attempt_alignment:{index}')
        model, paths, variance = _model(obs, config, seed, tier)
        if row['tree'] != _tree_summary(model, paths, variance):
            raise ValueError(f'tree_changed:{job}')
        solver = row['solver']
        optimal = solver['status'] == 0 and solver['feasible_solution']
        action = row['action']
        if optimal != (action is not None):
            raise ValueError(f'action_status:{job}')
        if action is not None:
            validate(action, obs)
        failures += action is None
        if formal and failures/index > config['max_failure_rate'] and index != len(rows):
            raise ValueError('formal_run_continued_after_failure_gate')


def verify(output=OUTPUT, pilot=PILOT):
    """Check hashes, rebuild models and recompute the complete result without running a solver."""
    out = Path(output)
    if _json(out/'manifest.json') != _hashes(out, EVIDENCE_FILES):
        raise ValueError('stability_evidence_hash')
    config, states = _inputs(pilot)
    if config != _json(out/'config.json'):
        raise ValueError('stability_configuration_changed')
    trial = read_lines(out/'timing.jsonl')
    formal = read_lines(out/'states.jsonl')
    timings = _json(out/'runtime.json')
    tiers = config['reference_tiers'] + config['larger_tiers']
    trial_jobs = _jobs(states, config, tiers, timing=True)
    if len(trial) != len(trial_jobs):
        raise ValueError('timing_attempt_count')
    _verify_rows(trial, trial_jobs, states, config)
    selection = _select(config, _tier_summary(trial, tiers))
    if selection['stop_reason'] is None:
        jobs = _jobs(states, config, [*config['reference_tiers'], selection['tier']])
        if len(formal) > len(jobs) or timings['formal_wall_seconds'] is None:
            raise ValueError('formal_attempt_count')
        _verify_rows(formal, jobs, states, config, formal=True)
    elif formal or timings['formal_wall_seconds'] is not None:
        raise ValueError('formal_run_after_timing_stop')
    if _summary(config, states, trial, formal, timings) != _json(out/'summary.json'):
        raise ValueError('stability_summary_changed')
    return {'files': len(EVIDENCE_FILES), 'timing_attempts': len(trial), 'formal_attempts': len(formal),
            'trees_regenerated': len(trial)+len(formal), 'solves_run': 0}
