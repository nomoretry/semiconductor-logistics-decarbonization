"""Bounded development pilot: anchor trajectories with per-state audits, then policy rollouts.

Every MILP is charged to one budget (solve count and wall time) before it starts. Timeouts and
nonoptimal solves are recorded as failures and never retried. Nothing here generates or reads
confirmation data.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import time

import numpy as np
import scipy

from rolling_inventory.environment import Environment, generate
from rolling_inventory.experiment import audit as ledger_audit, close
from rolling_inventory.planning import base_stock, decide as anchor_decide, solve as anchor_solve
from . import scenarios as sc
from .planning import Model, solve, tie_robust, tolerance

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT/'benchmark_results/rolling_tree_pilot'
TRAJECTORY_METHODS = ('M1', 'M2*', 'B3', 'B4')


def configuration():
    return json.loads((ROOT/'rolling_tree/config.json').read_text(encoding='utf-8'))


def base_configuration():
    return json.loads((ROOT/'rolling_inventory/config.json').read_text(encoding='utf-8'))


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def array_digest(array):
    return digest_bytes(np.ascontiguousarray(np.asarray(array, dtype=np.int64)).tobytes())


class BudgetExhausted(Exception):
    pass


class DecisionFailed(Exception):
    def __init__(self, info):
        super().__init__(info.get('reason', 'decision_failed')); self.info = info


class Budget:
    """Charges a solve before it starts; a started solve counts even if it fails."""

    def __init__(self, rule):
        self.rule = rule; self.solves = 0; self.log = []
        self.start, self.cpu_start = time.perf_counter(), time.process_time()

    def elapsed(self):
        return time.perf_counter()-self.start

    def charge(self):
        if self.solves >= self.rule['max_solves']:
            raise BudgetExhausted('max_solves')
        if self.elapsed() > self.rule['max_wall_seconds']-self.rule['start_guard_seconds']:
            raise BudgetExhausted('max_wall_seconds')
        self.solves += 1
        return self.solves

    def usage(self):
        return {'solves': self.solves, 'wall_seconds': self.elapsed(),
                'process_cpu_seconds': time.process_time()-self.cpu_start}


def forced_zero(obs):
    """No dispatch can arrive inside the window (last period): the only action is zero."""
    p = obs['public']
    return sc.window(obs) <= min(p['lead'])


class Planner:
    def __init__(self, cfg, fitted, budget, equal_time_scenarios=None):
        self.cfg, self.fitted, self.budget = cfg, fitted, budget
        self.limit = cfg['solver']['time_limit_seconds']; self.rule = cfg['tie_tolerance']
        self.equal_time_scenarios = equal_time_scenarios

    def variance(self, obs):
        return sc.common_variance(obs, self.fitted, self.cfg['prior_strength'],
                                  self.cfg['common_variance_cap'])

    def joint(self, obs, v):
        tree = self.cfg['tree']
        return sc.joint_tree(obs, v, tree['depth'], tree['branching'], tree['continuation'],
                             self.cfg['sampler_seed'])

    def shuffled(self, obs, joint, labels, depth):
        tree = self.cfg['tree']
        return sc.shuffled_tree(joint, labels, depth, tree['branching'], tree['continuation'],
                                self.cfg['permutation_seed'], obs['t'])

    def _charged(self, context, call):
        index = self.budget.charge()
        result, record = call()
        self.budget.log.append(dict(context, solve=index, **record))
        return result, record, index

    def solve(self, model, context):
        return self._charged(context, lambda: solve(model, self.limit))

    def tie(self, primary, own, own_value, context):
        return self._charged(context, lambda: tie_robust(primary, own, own_value, self.rule, self.limit))

    def decide(self, obs, method, context):
        """Action and timing for one decision; raises DecisionFailed on a failed solve."""
        start = time.perf_counter(); cpu = time.process_time()
        info = {'method': method, 'solves': [], 'forced_zero': False}
        n, r = len(obs['public']['mass']), len(obs['public']['lead'])
        if method == 'B0':
            action, _ = base_stock(obs, self.cfg['pilot']['base_stock_z'])
        elif method == 'B1':
            index = self.budget.charge(); wall, c0 = time.perf_counter(), time.process_time()
            try:
                action, detail = anchor_decide(obs, 'mpc_scenarios')
                record = {'status': detail['status'], 'mip_gap': detail['mip_gap'],
                          'objective': detail['objective'], 'feasible_solution': True}
            except ValueError as error:  # The archived planner raises on nonoptimal solves.
                action, record = None, {'status': None, 'message': str(error), 'feasible_solution': None}
            record.update({'wall_seconds': time.perf_counter()-wall, 'cpu_seconds': time.process_time()-c0,
                           'scenarios': obs['public']['scenarios']})
            self.budget.log.append(dict(context, purpose='B1', solve=index, **record))
            info['solves'].append(index)
            if action is None:
                info['reason'] = 'B1_solve_failed'; raise DecisionFailed(info)
        elif forced_zero(obs):
            action = np.zeros((n, r), dtype=int).tolist(); info['forced_zero'] = True
        else:
            g = time.perf_counter(); v = self.variance(obs); info['common_variance'] = v
            if method == 'B4':
                paths = sc.open_loop_paths(obs, v, self.equal_time_scenarios, self.cfg['sampler_seed']); depth = 0
            else:
                paths, labels, depth = self.joint(obs, v)
                if method == 'M2*':
                    own_paths = self.shuffled(obs, paths, labels, depth)
            info['generation_seconds'] = time.perf_counter()-g
            ctx = dict(context, method=method)
            if method in ('M1', 'B4'):
                model = Model(obs, paths, depth)
                sol, record, index = self.solve(model, dict(ctx, purpose=method))
                info['solves'].append(index)
                if sol is None:
                    info['reason'] = f'{method}_solve_failed'; raise DecisionFailed(info)
                action = sol['action']
            else:
                own = Model(obs, own_paths, depth) if method == 'M2*' else Model(obs, paths, 0)
                sol, record, index = self.solve(own, dict(ctx, purpose=method+':own'))
                info['solves'].append(index)
                if sol is None:
                    info['reason'] = f'{method}_own_failed'; raise DecisionFailed(info)
                t0 = time.perf_counter()
                tied, record, index = self.tie(Model(obs, paths, depth), own, sol['value'],
                                               dict(ctx, purpose=method+':tie'))
                info['solves'].append(index); info['tie_seconds'] = time.perf_counter()-t0
                if tied is None:
                    info['reason'] = f'{method}_tie_failed'; raise DecisionFailed(info)
                action = tied['action']
        info['online_seconds'] = time.perf_counter()-start
        info['online_cpu_seconds'] = time.process_time()-cpu
        return np.asarray(action, dtype=int).tolist(), info

    def audit_state(self, obs, context, sink):
        """Classify M1 against M2 (dependence) and against B2 (recourse) on one state.

        The row is appended before any solve so a budget stop leaves a visible partial record.
        """
        row = dict(context, forced_zero=forced_zero(obs), complete=False); sink.append(row)
        if row['forced_zero']:
            row['complete'] = True; return row
        g = time.perf_counter(); v = self.variance(obs); joint, labels, depth = self.joint(obs, v)
        row['m1_generation_seconds'] = time.perf_counter()-g
        shuffled = self.shuffled(obs, joint, labels, depth)
        row.update({'common_variance': v, 'depth': depth, 'joint_digest': array_digest(joint),
                    'shuffled_digest': array_digest(shuffled), 'generation_seconds': time.perf_counter()-g})
        ctx = dict(context, method='audit')
        b = time.perf_counter(); m1 = Model(obs, joint, depth); row['m1_build_seconds'] = time.perf_counter()-b
        m2, b2 = Model(obs, shuffled, depth), Model(obs, joint, 0)
        row.update({'m1_model': m1.summary(), 'm2_model': m2.summary(), 'b2_model': b2.summary()})
        s1, rec, _ = self.solve(m1, dict(ctx, purpose='audit:M1'))
        row['m1'] = _brief(s1, rec)
        if s1 is None:
            row['dependence'] = row['recourse'] = 'unresolved'; return row
        row['m1_online_seconds'] = row['m1_generation_seconds']+row['m1_build_seconds']+rec['wall_seconds']
        for name, own in (('dependence', m2), ('recourse', b2)):
            label = 'M2' if name == 'dependence' else 'B2'
            s_own, rec, _ = self.solve(own, dict(ctx, purpose=f'audit:{label}'))
            row[label.lower()] = _brief(s_own, rec)
            if s_own is None:
                row[name] = 'unresolved'; continue
            tied, rec, _ = self.tie(m1, own, s_own['value'], dict(ctx, purpose=f'audit:{label}*'))
            row[label.lower()+'_tie'] = _brief(tied, rec)
            if tied is None:
                row[name] = 'unresolved'; continue
            excess = tied['value']-s1['value']
            row[name+'_excess'] = excess
            if excess > tolerance(s1['value'], self.rule):
                row[name] = 'material'
            else:
                row[name] = 'identical' if s_own['action'] == s1['action'] else 'tie'
        row['complete'] = True
        return row


def _brief(solution, record):
    out = {k: record.get(k) for k in ('status', 'objective', 'dual_bound', 'mip_gap', 'nodes',
                                      'wall_seconds', 'cpu_seconds', 'feasible_solution')}
    if solution is not None:
        out.update({'value': solution['value'], 'action': solution['action']})
    return out


def metrics(rows):
    costs = {k: float(sum(x['costs'][k] for x in rows)) for k in rows[0]['costs']}
    demand = sum(sum(x['demand']) for x in rows)
    online = [x['planning'].get('online_seconds', 0.) for x in rows]
    return {'total_cost': sum(costs.values()), 'costs': costs,
            'immediate_fill_rate': sum(sum(x['filled_new']) for x in rows)/demand if demand else 1.,
            'backlog_unit_periods': sum(sum(x['backlog_end']) for x in rows),
            'emissions': sum(x['emissions'] for x in rows), 'final_stock': sum(rows[-1]['stock_end']),
            'final_backlog': sum(rows[-1]['backlog_end']),
            'online_seconds_total': float(sum(online)), 'online_seconds_mean': float(np.mean(online)),
            'online_seconds_p95': float(np.percentile(online, 95)),
            'solves': sum(len(x['planning'].get('solves', [])) for x in rows)}


def check_ledger(task, rows, complete):
    try:
        ledger_audit(task, rows)
    except ValueError as error:
        if complete or str(error) != 'incomplete_episode':
            raise


def rollout(task, method, planner, audits=None):
    env = Environment(task); rows = []; status = 'complete'
    for t in range(task['public']['periods']):
        obs = env.observe(); context = {'path': task['id'], 't': t}
        try:
            action, info = planner.decide(obs, method, dict(context, trajectory=method))
            if audits is not None:
                planner.audit_state(obs, context, audits)
        except DecisionFailed as failure:
            status = f'failed_at_{t}'; rows.append({'t': t, 'failure': failure.info}); break
        except BudgetExhausted:
            check_ledger(task, rows, False)
            # Keep the interrupted state: its audit row and trees must stay reproducible.
            rows.append({'t': t, 'observation': obs, 'interrupted': 'budget'})
            planner.partial = {'id': task['id'], 'method': method, 'rows': rows, 'status': f'budget_exhausted_at_{t}'}
            raise
        row = env.step(action); row['planning'] = info; rows.append(row)
    done = [x for x in rows if 'failure' not in x]
    check_ledger(task, done, status == 'complete')
    return {'id': task['id'], 'profile': task['profile'], 'method': method, 'status': status,
            'metrics': metrics(done) if status == 'complete' else None}, rows


def perfect(task, planner):
    env = Environment(task); obs = env.observe(); index = planner.budget.charge()
    wall, cpu = time.perf_counter(), time.process_time()
    try:
        schedule, detail = anchor_solve(obs, [task['demand']], paced=False)
        record = {'status': detail['status'], 'mip_gap': detail['mip_gap'], 'objective': detail['objective']}
    except ValueError as error:
        schedule, record = None, {'status': None, 'message': str(error)}
    record.update({'wall_seconds': time.perf_counter()-wall, 'cpu_seconds': time.process_time()-cpu})
    planner.budget.log.append({'path': task['id'], 't': 0, 'purpose': 'LB', 'method': 'LB', 'solve': index, **record})
    if schedule is None:
        return {'id': task['id'], 'profile': task['profile'], 'method': 'LB', 'status': 'failed', 'metrics': None}, []
    rows = []
    for t in range(task['public']['periods']):
        row = env.step(schedule[t]); row['planning'] = {'solves': [index] if t == 0 else []}; rows.append(row)
    check_ledger(task, rows, True)
    return {'id': task['id'], 'profile': task['profile'], 'method': 'LB', 'status': 'complete',
            'metrics': metrics(rows)}, rows


def calibrate(planner, states, candidates, m1_seconds):
    """Equal-time open-loop scenario count: mean online time closest to M1 on the same states."""
    measured = {}
    for count in candidates:
        times = []
        for obs, context in states:
            g = time.perf_counter(); v = planner.variance(obs)
            paths = sc.open_loop_paths(obs, v, count, planner.cfg['sampler_seed'])
            model = Model(obs, paths, 0)
            sol, record, _ = planner.solve(model, dict(context, method='calibration', purpose=f'B4:{count}'))
            if sol is None:
                raise DecisionFailed({'reason': f'calibration_failed:{count}'})
            times.append(time.perf_counter()-g)
        measured[count] = float(np.mean(times))
    target = float(np.mean(m1_seconds))
    chosen = min(candidates, key=lambda c: (abs(measured[c]-target), c))
    return {'candidates': candidates, 'mean_online_seconds': {str(k): v for k, v in measured.items()},
            'm1_mean_online_seconds': target, 'chosen': chosen}


def runtime():
    cpu = platform.processor()
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0')
        cpu = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
    except (ImportError, OSError):
        pass
    try:
        import highspy
        highs = getattr(highspy, '__version__', 'unknown')
    except ImportError:
        highs = None
    return {'python': platform.python_version(), 'numpy': np.__version__, 'scipy': scipy.__version__,
            'highspy_package': highs, 'platform': platform.platform(), 'cpu': cpu,
            'logical_cpus': os.cpu_count(),
            'parallel': 'one sequential process; scipy.optimize.milp (bundled HiGHS) with default threads',
            'timers': 'wall=time.perf_counter, cpu=time.process_time (all threads of this process)'}


def contrasts(outcomes, cfg):
    by = {(x['id'], x['method']): x for x in outcomes}; ref = cfg['reference_thresholds']; out = []
    for path in sorted({x['id'] for x in outcomes}):
        for a, b, question in (('M1', 'M2*', 'dependence'), ('M1', 'B3', 'recourse'),
                               ('M1', 'B4', 'equal_time'), ('M1', 'B1', 'anchor'), ('M1', 'B0', 'rule')):
            x, y = by.get((path, a)), by.get((path, b))
            if not x or not y or x['status'] != 'complete' or y['status'] != 'complete':
                out.append({'path': path, 'contrast': f'{a}-{b}', 'question': question, 'available': False})
                continue
            mx, my = x['metrics'], y['metrics']
            relative = (mx['total_cost']-my['total_cost'])/my['total_cost']
            emissions = (mx['emissions']-my['emissions'])/my['emissions'] if my['emissions'] else None
            fill = mx['immediate_fill_rate']-my['immediate_fill_rate']
            out.append({'path': path, 'contrast': f'{a}-{b}', 'question': question, 'available': True,
                        'cost_difference': mx['total_cost']-my['total_cost'], 'cost_relative': relative,
                        'fill_difference': fill, 'emissions_relative': emissions,
                        'meets_practical_reference': relative <= -ref['practical_cost_reduction'],
                        'fill_guardrail': fill >= -ref['fill_rate_absolute_drop'],
                        'emissions_guardrail': emissions is None or emissions <= ref['emissions_relative_increase']})
    return out


def audit_counts(audits):
    counts = {}
    for name in ('dependence', 'recourse'):
        values = ['forced_zero' if a.get('forced_zero') else a.get(name, 'incomplete_budget')
                  for a in audits]
        counts[name] = {k: values.count(k) for k in sorted(set(values))}
    return counts


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n',
                          encoding='utf-8')


def write_lines(path, records):
    Path(path).write_text(''.join(json.dumps(r, sort_keys=True, allow_nan=False)+'\n' for r in records),
                          encoding='utf-8')


def read_lines(path):
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x]


def pilot_tasks(cfg, base):
    return [t for t in generate(base, cfg['pilot']['split'], [cfg['pilot']['seed']])
            if t['profile'] in cfg['pilot']['profiles']]


def fitted_variance(cfg, base):
    tasks = generate(base, 'fit', cfg['fit_seeds'])
    value, count = sc.fit_common_variance(tasks, cfg['common_variance_cap'])
    return {'seeds': cfg['fit_seeds'], 'paths': len(tasks), 'products': count, 'fitted_variance': value,
            'tasks_digest': digest_bytes(json.dumps(tasks, sort_keys=True).encode())}


def pilot(output=DEFAULT, cfg=None):
    """`cfg` overrides exist for smoke tests in a separate seed namespace only."""
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f'output_not_empty:{out}')
    out.mkdir(parents=True, exist_ok=True)
    cfg, base = cfg or configuration(), base_configuration()
    fit = fitted_variance(cfg, base); tasks = pilot_tasks(cfg, base)
    budget = Budget(cfg['budget']); planner = Planner(cfg, fit['fitted_variance'], budget)
    outcomes, traces, audits, items = [], [], [], []
    for task in tasks:  # Rules need no solver and run first.
        result, rows = rollout(task, 'B0', planner); outcomes.append(result)
        traces.append({'id': task['id'], 'method': 'B0', 'rows': rows})
    plan = ([('anchor', t) for t in tasks]+[('LB', t) for t in tasks]+[('calibration', None)]
            + [(m, t) for t in tasks for m in TRAJECTORY_METHODS])
    stop = calibration = None
    for position, (kind, task) in enumerate(plan):
        label = {'kind': kind, 'path': task['id'] if task else None}
        try:
            if kind == 'anchor':
                result, rows = rollout(task, 'B1', planner, audits)
            elif kind == 'LB':
                result, rows = perfect(task, planner)
            elif kind == 'calibration':
                first = tasks[0]['id']
                states = [(row['observation'], {'path': first, 't': row['observation']['t']})
                          for x in traces if x['id'] == first and x['method'] == 'B1'
                          for row in x['rows'][:cfg['pilot']['equal_time_calibration_states']]]
                m1 = [a['m1_online_seconds'] for a in audits if a['path'] == first and 'm1_online_seconds' in a]
                m1 = m1[:cfg['pilot']['equal_time_calibration_states']]
                calibration = calibrate(planner, states, cfg['pilot']['equal_time_candidates'], m1)
                planner.equal_time_scenarios = calibration['chosen']
                items.append(dict(label, status='done')); continue
            else:
                if planner.equal_time_scenarios is None and kind == 'B4':
                    items.append(dict(label, status='skipped_no_calibration')); continue
                result, rows = rollout(task, kind, planner)
            outcomes.append(result); traces.append({'id': task['id'], 'method': result['method'], 'rows': rows})
            items.append(dict(label, status=result['status']))
        except BudgetExhausted as reason:
            stop = str(reason)
            partial = getattr(planner, 'partial', None)
            if partial:
                traces.append({'id': partial['id'], 'method': partial['method'], 'rows': partial['rows']})
                outcomes.append({'id': partial['id'], 'profile': task['profile'], 'method': partial['method'],
                                 'status': partial['status'], 'metrics': None})
            items.append(dict(label, status=f'budget_exhausted:{stop}'))
            items += [{'kind': k, 'path': t['id'] if t else None, 'status': 'not_run_budget'}
                      for k, t in plan[position+1:]]
            break
        except DecisionFailed as failure:
            items.append(dict(label, status='failed', reason=failure.info.get('reason')))
    usage = budget.usage()
    timing = {}
    for method in sorted({x['method'] for x in outcomes}):
        values = [r['planning'].get('online_seconds') for x in traces if x['method'] == method
                  for r in x['rows'] if 'planning' in r and r['planning'].get('online_seconds') is not None]
        if values:
            timing[method] = {'decisions': len(values), 'mean_online_seconds': float(np.mean(values)),
                              'p95_online_seconds': float(np.percentile(values, 95))}
    solves = budget.log
    summary = {'scope': cfg['scope'], 'tree': cfg['tree'], 'fit': fit, 'budget_rule': cfg['budget'],
               'usage': usage, 'stop_reason': stop, 'items': items, 'equal_time': calibration,
               'audit_counts': audit_counts(audits), 'contrasts': contrasts(outcomes, cfg),
               'decision_timing': timing,
               'solve_failures': [s for s in solves if s.get('status') != 0],
               'solve_status_counts': {str(k): sum(1 for s in solves if s.get('status') == k)
                                       for k in sorted({s.get('status') for s in solves}, key=str)},
               'confirmation': 'not_generated_not_viewed', 'learning_trained': False}
    write_json(out/'config.json', {'rolling_tree': cfg, 'environment': base})
    write_json(out/'tasks.json', tasks)
    write_json(out/'runtime.json', runtime())
    write_json(out/'outcomes.json', outcomes)
    write_json(out/'summary.json', summary)
    write_lines(out/'solves.jsonl', solves)
    write_lines(out/'audit.jsonl', audits)
    write_lines(out/'traces.jsonl', traces)
    files = sorted(p.name for p in out.iterdir() if p.name != 'manifest.json')
    write_json(out/'manifest.json', {name: digest_bytes((out/name).read_bytes()) for name in files})
    return {'output': str(out), 'usage': usage, 'stop_reason': stop, 'audit_counts': summary['audit_counts']}


def verify(output=DEFAULT, current_configuration=True):
    """Recompute everything that needs no solver: tasks, trees, ledgers, metrics and hashes."""
    out = Path(output); cfg = json.loads((out/'config.json').read_text(encoding='utf-8'))
    manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    for name, value in manifest.items():
        if digest_bytes((out/name).read_bytes()) != value:
            raise ValueError(f'hash:{name}')
    tree_cfg, base = cfg['rolling_tree'], cfg['environment']
    if base != base_configuration() or (current_configuration and tree_cfg != configuration()):
        raise ValueError('configuration_changed')
    summary = json.loads((out/'summary.json').read_text(encoding='utf-8'))
    fit = fitted_variance(tree_cfg, base)
    if fit != summary['fit']:
        raise ValueError('fit_changed')
    tasks = pilot_tasks(tree_cfg, base)
    if json.loads((out/'tasks.json').read_text(encoding='utf-8')) != tasks:
        raise ValueError('tasks_changed')
    by_id = {t['id']: t for t in tasks}; traces = read_lines(out/'traces.jsonl')
    outcomes = json.loads((out/'outcomes.json').read_text(encoding='utf-8'))
    checked = 0
    for trace in traces:
        rows = [r for r in trace['rows'] if 'failure' not in r and 'interrupted' not in r]
        outcome = next(x for x in outcomes if x['id'] == trace['id'] and x['method'] == trace['method'])
        check_ledger(by_id[trace['id']], rows, outcome['status'] == 'complete')
        for row in rows:
            sc.check_observation(row['observation'])
        if outcome['status'] == 'complete':
            close(metrics(rows), outcome['metrics'])
        checked += 1
    planner = Planner(tree_cfg, fit['fitted_variance'], None)
    anchor = {(x['id'], r['observation']['t']): r['observation'] for x in traces if x['method'] == 'B1'
              for r in x['rows'] if 'observation' in r}
    trees = 0
    for row in read_lines(out/'audit.jsonl'):
        if row.get('forced_zero') or 'joint_digest' not in row:
            continue
        obs = anchor[(row['path'], row['t'])]; v = planner.variance(obs)
        joint, labels, depth = planner.joint(obs, v)
        if array_digest(joint) != row['joint_digest'] or \
                array_digest(planner.shuffled(obs, joint, labels, depth)) != row['shuffled_digest']:
            raise ValueError(f'tree_changed:{row["path"]}:{row["t"]}')
        trees += 1
    if contrasts(outcomes, tree_cfg) != summary['contrasts']:
        raise ValueError('contrasts_changed')
    return {'files': len(manifest), 'trajectories': checked, 'trees_regenerated': trees, 'solves_run': 0}
