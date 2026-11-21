"""Rebuild closing paths, information sets, scenario trees, ledgers and paired estimates without solves."""
from collections import Counter
from pathlib import Path

import numpy as np

from rolling_inventory.environment import Environment, carbon
from rolling_inventory.planning import base_stock
from . import closing, experiment_v2 as v2, scenarios
from .closing_stats import METHODS, is_timeout, summarize
from .experiment import array_digest, check_ledger, forced_zero, metrics, read_lines


def require(condition, label):
    if not condition:
        raise ValueError(label)


def check_timing(gate, cfg, limit):
    pilot = cfg['v2']['pilot']
    development = v2.pilot_tasks(cfg['v2'], cfg['environment'])
    times = gate['development']
    require([r['id'] for r in times] == [task['id'] for task in development], 'timing_paths')
    require(pilot['profiles'] == [x['profile'] for x in development], 'timing_profiles')
    require(gate['sampler_seed'] == cfg['v2']['sampler_seeds'][0], 'timing_sampler')
    require(all(r['wall_seconds'] > 0 for r in times), 'timing_wall')
    estimate = 160*max(r['wall_seconds'] for r in times)+60
    require(gate['estimated_seconds'] == estimate and gate['passed'] is True
            and gate['limit_seconds'] == cfg['formal_limit'] and estimate <= limit, 'timing_gate')


def leaf_carbon_certificate(obs, tree, depth, nodes, action):
    keys = scenarios.node_keys(tree, depth)
    totals = np.zeros(len(tree), dtype=int)
    require(len(nodes) == tree.shape[1], 'carbon_stages')
    require(nodes[0] == [carbon(action, obs['public'])], 'carbon_root')
    for stage, histories in zip(nodes, zip(*keys), strict=True):
        order = {key: i for i, key in enumerate(dict.fromkeys(histories))}
        require(len(stage) == len(order) and all(type(x) is int and x >= 0 for x in stage), 'carbon_nodes')
        totals += [stage[order[key]] for key in histories]
    allowance = obs['carbon_remaining']*tree.shape[1]/(obs['public']['periods']-obs['t'])
    require(totals.max() <= allowance+1e-7, 'carbon_leaf_budget')
    return int(totals.max())


def check_decision(obs, method, info, action, logs, planner):
    require(info['method'] == method and len(logs) == len(info['solves']), 'decision_metadata')
    require(info['online_seconds'] >= 0, 'decision_time')
    if method == 'B0':
        expected, _ = base_stock(obs, planner.cfg['pilot']['base_stock_z'])
        require(not logs and np.array_equal(expected, action), 'base_stock_action')
        return 0
    if method == 'B1':
        require(len(logs) == 1 and logs[0]['purpose'] == 'B1', 'B1_solve')
        require((logs[0]['status'] == 0) == (action is not None), 'B1_status')
        require(info['scenarios_sha256'] == array_digest(v2.anchor_paths(obs)), 'B1_scenarios')
        if action is not None:
            require(action == logs[0]['first_action'], 'B1_action')
        return 1
    if forced_zero(obs):
        require(info['forced_zero'] and not logs and action is not None and not np.any(action), 'forced_action')
        return 0
    v = planner.variance(obs)
    require(info['common_variance'] == v and not info['forced_zero'], 'common_variance')
    tree, labels, depth = planner.joint(obs, v)
    require(info['joint_sha256'] == array_digest(tree), 'joint_tree')
    count = 1
    if method != 'M1':
        mixed = planner.shuffled(obs, tree, labels, depth)
        require(info['shuffled_sha256'] == array_digest(mixed), 'shuffled_tree')
        for i in range(tree.shape[2]):
            require(sorted(map(tuple, tree[:, :, i])) == sorted(map(tuple, mixed[:, :, i])), 'sku_marginal')
        tree = mixed
        count += 1
    purpose = 'M1' if method == 'M1' else method+':own'
    require(logs and logs[0]['purpose'] == purpose, 'first_solve')
    own = logs[0]
    if own['status'] != 0:
        require(action is None and len(logs) == 1 and not info.get('fallback'), 'own_failure')
        return count
    if method in ('M1', 'M2'):
        require(len(logs) == 1 and action == own['first_action'], 'own_action')
        value = leaf_carbon_certificate(obs, tree, depth, own['node_carbon'], action)
        require(value == info['max_leaf_carbon'], 'max_leaf_carbon')
    else:
        require(len(logs) == 2 and logs[1]['purpose'] == 'M2*:tie', 'tie_solve')
        tie = logs[1]
        fallback = tie['status'] == 1 and is_timeout(tie)
        require(fallback == bool(info.get('fallback')), 'fallback_status')
        if fallback:
            require(action == own['first_action'], 'fallback_action')
        elif tie['status'] == 0:
            require(action == tie['first_action'], 'tie_action')
        else:
            require(action is None, 'tie_failure')
    return count


def verify(output=closing.OUTPUT, *, expected_config=None):
    out = Path(output)
    require(closing.read(out/'manifest.json') == {n: closing.file_hash(out/n) for n in closing.FILES}, 'manifest')
    cfg = closing.settings() if expected_config is None else expected_config
    require(cfg == closing.read(out/'config.json'), 'configuration')
    require(v2.fitted_variance(cfg['v2'], cfg['environment']) == cfg['fit'], 'fitted_variance')
    execution = closing.read(out/'execution.json')
    check_timing(closing.read(out/'timing.json'), cfg, execution['max_wall_seconds'])
    tasks = closing.ordered_tasks(cfg)
    paths = closing.path_index(tasks, cfg)
    require(paths == closing.read(out/'tasks.json'), 'task_digest')
    results = read_lines(out/'results.jsonl')
    traces = read_lines(out/'traces.jsonl')
    solves = read_lines(out/'solves.jsonl')
    plan = [(p['id'], m) for p in paths for m in METHODS]
    pairs = [(r['id'], r['method']) for r in results]
    require(pairs == plan[:len(pairs)] and pairs == [(tr['id'], tr['method']) for tr in traces], 'coverage')
    require(len(results) == execution['recorded_trajectories'] and len(paths) == execution['scheduled_paths'],
            'execution_counts')
    require([s['solve'] for s in solves] == list(range(1, len(solves)+1)) and len(solves) == execution['solves'],
            'solve_sequence')
    used, regenerated, ledger_rows = [], 0, 0
    failures = Counter()
    for pos, (result, trace) in enumerate(zip(results, traces, strict=True)):
        task, item = tasks[pos//len(METHODS)], paths[pos//len(METHODS)]
        method, rows, status = result['method'], trace['rows'], result['status']
        require(trace['sampler_seed'] == item['sampler_seed'] and result['profile'] == task['profile'], 'path_seed')
        planner = v2.PlannerV2(cfg['v2'], cfg['fit']['fitted_variance'], None, cfg['selection']['shape'],
                               cfg['selection']['prior_strength'], item['sampler_seed'])
        env, rebuilt = Environment(task), []
        if method == 'LB' and not status.startswith('budget_exhausted'):
            index = len(used)+1
            log = solves[index-1]
            require(log['method'] == 'LB' and log['purpose'] == 'LB' and log['path'] == task['id'], 'LB_solve')
            require((log['status'] == 0) == (status == 'complete'), 'LB_status')
            used.append(index)
        for t, row in enumerate(rows):
            obs = env.observe()
            if row.get('interrupted') == 'budget':
                require(row['observation'] == obs and status == f'budget_exhausted_at_{t}' and t+1 == len(rows),
                        'budget_observation')
                # The own solve may have completed just before the budget guard refused the tie.
                for log in solves[len(used):]:
                    require(method == 'M2*' and log['purpose'] == 'M2*:own' and log['path'] == task['id']
                            and log['t'] == t, 'interrupted_solve')
                    used.append(log['solve'])
                break
            info = row.get('planning', row.get('failure'))
            if method == 'LB':
                require(info == {'solves': [index] if t == 0 else []}, 'LB_reference')
            else:
                logs = [solves[i-1] for i in info['solves']]
                for log in logs:
                    require(log['path'] == task['id'] and log['trajectory'] == method and log['t'] == t
                            and log['sampler_seed'] == item['sampler_seed'], 'solve_context')
                    used.append(log['solve'])
                regenerated += check_decision(obs, method, info, row.get('action'), logs, planner)
            if 'failure' in row:
                require(status == f'failed_at_{t}' and row['t'] == t and t+1 == len(rows), 'failed_period')
                break
            actual = env.step(row['action'])
            require(actual == {k: v for k, v in row.items() if k != 'planning'}, 'ledger_replay')
            actual['planning'] = info
            rebuilt.append(actual)
        complete = status == 'complete'
        require(complete == (len(rebuilt) == task['public']['periods']), 'trajectory_length')
        if not complete:
            if method == 'LB':
                require(not rows and status in ('failed', 'budget_exhausted_at_0'), 'LB_failure')
            else:
                require(rows and ('failure' in rows[-1] or 'interrupted' in rows[-1]), 'missing_failure')
            failures[method] += 1
        check_ledger(task, rebuilt, complete)
        ledger_rows += len(rebuilt)
        require(result['metrics'] == (metrics(rebuilt) if complete else None), 'path_metrics')
    require(used == list(range(1, len(solves)+1)), 'solve_coverage')
    stop = execution['stop_reason']
    crossed = [m for m in METHODS[:2] if failures[m] > cfg['max_incomplete_per_primary_method']]
    if crossed:
        require(len(crossed) == 1 and stop == 'incomplete_'+crossed[0] and pairs[-1][1] == crossed[0],
                'incomplete_gate')
    elif stop is None:
        require(len(pairs) == len(plan) and execution['wall_seconds'] <= execution['max_wall_seconds'],
                'complete_execution')
    else:
        require(stop == 'max_wall_seconds', 'budget_stop')
    summary, divergences = summarize(results, traces, solves, paths, cfg['bootstrap_seed'],
                                     cfg['v2']['reference_thresholds'])
    require(divergences == closing.read(out/'divergences.json'), 'first_divergences')
    require(summary == closing.read(out/'summary.json'), 'summary_replay')
    return {'solves_run': 0, 'recorded_solves': len(solves), 'paths_regenerated': len(paths),
            'scenario_sets_regenerated': regenerated, 'ledger_rows_replayed': ledger_rows,
            'paired_paths': summary['comparisons']['overall']['M1-M2']['pairs'], 'stop_reason': stop}
