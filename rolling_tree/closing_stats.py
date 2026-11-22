"""Path-paired estimates and first-dispatch diagnostics for the closing protocol."""
from collections import Counter

import numpy as np
from scipy.stats import t as student


METHODS = ('M1', 'M2', 'M2*', 'B1', 'B0', 'LB')
METRICS = ('total_cost', 'immediate_fill_rate', 'emissions')
CONTRASTS = (('M1', 'M2'), ('M1', 'M2*'), ('M1', 'B1'), ('M2', 'B1'), ('B1', 'B0'),
             *((method, 'LB') for method in METHODS[:-1]))


def paired(left, right, seed):
    """Rows are complete paths in protocol order. Resample whole rows for all metrics."""
    n = len(left)
    if not n:
        return {'pairs': 0, 'metrics': {}}
    comparator = np.asarray(right, dtype=float)
    diff = np.asarray(left, dtype=float) - comparator
    means = diff.mean(axis=0)
    reference = comparator.mean(axis=0)
    rng = np.random.default_rng(seed)
    draws = rng.integers(n, size=(10000, n))
    result = {}
    for j, metric in enumerate(METRICS):
        mean = float(means[j])
        interval = None
        if n >= 2:
            half = float(student.ppf(.975, n-1) * diff[:, j].std(ddof=1) / np.sqrt(n))
            interval = [mean-half, mean+half]
        bootstrap = np.percentile(diff[:, j][draws].mean(axis=1), [2.5, 97.5]).tolist()
        result[metric] = {'mean_difference': mean, 'comparator_mean': float(reference[j]),
                          'relative': float(mean/reference[j]) if reference[j] else None,
                          't95': interval, 'bootstrap95': bootstrap,
                          't_contains_zero': interval[0] <= 0 <= interval[1] if interval else None,
                          'bootstrap_contains_zero': bootstrap[0] <= 0 <= bootstrap[1]}
    return {'pairs': n, 'metrics': result}


def decision(interval, margin, fill_difference, emissions_difference, emissions_mean, thresholds):
    if interval is None:
        return 'uncertain'
    lower, upper = interval
    if (upper < -margin and fill_difference >= -thresholds['fill_rate_absolute_drop']
            and emissions_difference <= thresholds['emissions_relative_increase'] * emissions_mean):
        return 'practical_benefit'
    if lower > -margin and upper < margin:
        return 'equivalent'
    if lower > margin:
        return 'harm'
    return 'uncertain'


def first_divergence(left, right, cost_difference):
    for a, b in zip(left, right, strict=True):
        if a['action'] == b['action']:
            continue
        if a['observation'] != b['observation']:
            raise ValueError('first_divergence_observation')
        obs = a['observation']
        p = obs['public']
        actions = {method: row['action'] for method, row in [('M1', a), ('M2', b)]}
        resources = {}
        for method, row in [('M1', a), ('M2', b)]:
            load = np.asarray(p['mass']) @ np.asarray(row['action'])
            allowance = obs['carbon_remaining'] * min(p['horizon'], len(obs['forecast'])) / (p['periods']-obs['t'])
            resources[method] = {'route_mass': load.tolist(), 'load_fraction': (load/p['capacity']).tolist(),
                                 'window_allowance': allowance, 'dispatch_carbon': row['emissions'],
                                 'dispatch_allowance_fraction': row['emissions']/allowance if allowance else None,
                                 'max_leaf_carbon': row['planning']['max_leaf_carbon'],
                                 'carbon_binding': abs(row['planning']['max_leaf_carbon']-allowance) <= 1e-7}
        return {'t': obs['t'], 'actions': actions, 'unit_difference': (
            np.asarray(a['action'])-np.asarray(b['action'])).tolist(), 'resources': resources, 'D': cost_difference}
    if cost_difference != 0:
        raise ValueError('identical_actions_cost_difference')
    return {'t': None, 'D': cost_difference}


def distribution(values):
    return {'count': len(values), 'mean': float(np.mean(values)) if values else None,
            'p95': float(np.percentile(values, 95)) if values else None}


def divergence_summary(records):
    changed = [r for r in records if r['t'] is not None]
    same = [r['D'] for r in records if r['t'] is None]
    cells = np.zeros((3, 2), dtype=int)
    skus = np.zeros(3, dtype=int)
    routes = np.zeros(2, dtype=int)
    for row in changed:
        changed_cells = np.asarray(row['unit_difference']) != 0
        cells += changed_cells
        skus += changed_cells.any(axis=1)
        routes += changed_cells.any(axis=0)
    shares = {}
    for method in ('M1', 'M2'):
        values = [r['resources'][method] for r in changed]
        shares[method] = {
            'slow_full_share': sum(v['load_fraction'][0] == 1 for v in values)/len(values) if values else None,
            'carbon_binding_share': sum(v['carbon_binding'] for v in values)/len(values) if values else None}
    return {'by_t': dict(Counter(str(r['t']) for r in changed)), 'by_sku_route': cells.tolist(),
            'by_sku': skus.tolist(), 'by_route': routes.tolist(), 'resources': shares,
            'divergent_D': distribution([r['D'] for r in changed]), 'identical_D': distribution(same)}


def is_timeout(record):
    # SciPy's status 1 also covers iteration limits. HiGHS supplies the specific reason.
    return 'Time limit reached' in record.get('message', '')


def summarize(results, traces, solves, paths, bootstrap_seed, thresholds):
    by = {(r['id'], r['method']): r for r in results}
    groups = {'overall': paths}
    for item in paths:
        groups.setdefault(item['profile'], []).append(item)
    comparisons = {}
    for group, items in groups.items():
        comparisons[group] = {}
        for a, b in CONTRASTS:
            left, right = [], []
            for item in items:
                x, y = by.get((item['id'], a)), by.get((item['id'], b))
                if x and y and x['status'] == y['status'] == 'complete':
                    left.append([x['metrics'][m] for m in METRICS])
                    right.append([y['metrics'][m] for m in METRICS])
            comparisons[group][f'{a}-{b}'] = paired(left, right, bootstrap_seed)
    primary = comparisons['overall']['M1-M2']['metrics']
    verdict, margin = 'uncertain', None
    if primary:
        cost, fill, emissions = (primary[m] for m in METRICS)
        margin = thresholds['practical_cost_reduction'] * cost['comparator_mean']
        verdict = decision(cost['t95'], margin, fill['mean_difference'], emissions['mean_difference'],
                           emissions['comparator_mean'], thresholds)
    traces_by = {(r['id'], r['method']): r['rows'] for r in traces}
    divergence, missing = [], []
    for item in paths:
        path = item['id']
        pair = [by.get((path, m)) for m in ('M1', 'M2')]
        status = {m: r['status'] if r else 'not_run' for m, r in zip(('M1', 'M2'), pair)}
        if any(s != 'complete' for s in status.values()):
            missing.append({'id': path, 'status': status})
            continue
        d = pair[0]['metrics']['total_cost']-pair[1]['metrics']['total_cost']
        divergence.append(dict(id=path, **first_divergence(traces_by[path, 'M1'], traces_by[path, 'M2'], d)))
    timing = {}
    for method in METHODS:
        logs = [s for s in solves if s.get('trajectory', s.get('method')) == method]
        attempts = [row.get('planning', row.get('failure', {})) for tr in traces if tr['method'] == method
                    for row in tr['rows']]
        seconds = ([s['wall_seconds'] for s in logs] if method == 'LB' else
                   [x['online_seconds'] for x in attempts if 'online_seconds' in x])
        timing[method] = {**distribution(seconds), 'solves': len(logs),
                          'nonoptimal': sum(s['status'] != 0 for s in logs),
                          'timeouts': sum(is_timeout(s) for s in logs),
                          'fallbacks': sum(bool(x.get('fallback')) for x in attempts),
                          'incomplete': sum(r['method'] == method and r['status'] != 'complete' for r in results)}
    return {'comparisons': comparisons, 'decision': verdict, 'margin': margin, 'primary_omissions': missing,
            'first_divergence': divergence_summary(divergence), 'computation': timing}, divergence
