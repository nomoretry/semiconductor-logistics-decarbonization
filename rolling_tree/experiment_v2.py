"""Development version 2 of the scenario-tree study (docs/rolling_tree_protocol_v2.md).

`tune` uses only the tuning split: the prior strength by the one-step joint energy score, the tree shape by
first-period sample quality and solve time, and the equal-time open-loop scenario count by online time; none of
these looks at a cost. `pilot` then runs four new development paths under three planner sampling seeds:
first-action audits on the rolling baseline's states (dependence, recourse and the baseline itself, each against
its best tie), one-decision swaps on the baseline's path to price the first decision that materially changes, and
full trajectories. Every MILP is charged to one budget before it starts; timeouts and nonoptimal solves are
failures and are never retried. Nothing here generates or reads confirmation data, trains a policy or calls an API.
"""
import json
from pathlib import Path
import time

import numpy as np

from rolling_inventory.environment import Environment, generate
from rolling_inventory.experiment import close
from . import scenarios as sc
from .experiment import (ROOT, Budget, BudgetExhausted, DecisionFailed, Planner, _brief, array_digest,
                         base_configuration, check_ledger, digest_bytes, fitted_variance, forced_zero, metrics,
                         perfect, read_lines, runtime, write_json, write_lines)
from .planning import Model, solve_fixed_first, tolerance

CONFIG = ROOT/'rolling_tree/config_v2.json'
TUNING = ROOT/'benchmark_results/rolling_tree_v2_tuning'
PILOT = ROOT/'benchmark_results/rolling_tree_v2_pilot'
TRAJECTORIES = ('M1', 'M2*', 'B3', 'B4')
COMPARISONS = {'dependence': ('m2', 'm2_tie'), 'recourse': ('b2', 'b2_tie'), 'anchor': ('b1_model', 'b1_tie')}


def configuration():
    return json.loads(CONFIG.read_text(encoding='utf-8'))


def anchor_paths(obs):
    """The rolling baseline's own seven scenarios (rolling_inventory.planning.decide, 'mpc_scenarios')."""
    p = obs['public']; h = min(p['horizon'], len(obs['forecast'])); means = np.asarray(obs['forecast'][:h])
    rng = np.random.default_rng(p['scenario_seed']+obs['t'])
    return rng.poisson(means, size=(p['scenarios'], h, len(p['mass'])))


class PlannerV2(Planner):
    """Planner with the v2 tree, the selected prior strength and one planner sampling seed."""

    def __init__(self, cfg, fitted, budget, shape, prior_strength, sampler_seed, equal_time_scenarios=None):
        super().__init__(cfg, fitted, budget, equal_time_scenarios)
        self.shape, self.prior_strength, self.sampler_seed = shape, prior_strength, sampler_seed

    def variance(self, obs):
        return sc.common_variance(obs, self.fitted, self.prior_strength, self.cfg['common_variance_cap'])

    def joint(self, obs, v):
        return sc.joint_tree_v2(obs, v, self.shape['branching'], self.shape['continuation'], self.sampler_seed)

    def shuffled(self, obs, joint, labels, depth):
        return sc.shuffled_tree_v2(joint, labels, depth, self.shape['branching'], self.shape['continuation'],
                                   self.cfg['permutation_seed'], obs['t'])

    def open_loop(self, obs, v, count):
        return sc.open_loop_paths_v2(obs, v, count, self.sampler_seed)

    def fixed(self, model, action, context):
        return self._charged(context, lambda: solve_fixed_first(model, action, self.limit))


def classify(planner, m1_value, own_action, m1_action, tied):
    excess = tied['value']-m1_value
    if excess > tolerance(m1_value, planner.rule):
        return 'material', excess
    return ('identical' if own_action == m1_action else 'tie'), excess


def audit(planner, obs, context, sink, anchor_action):
    """v1's dependence and recourse audit, plus the rolling baseline (B1) against M1 through B1's best tie."""
    row = planner.audit_state(obs, context, sink)
    row['sampler_seed'] = planner.sampler_seed; row['b1_action'] = anchor_action
    if row.get('forced_zero') or not row.get('complete') or 'value' not in row.get('m1', {}):
        return row
    v = row['common_variance']; joint, labels, depth = planner.joint(obs, v)
    m1, own = Model(obs, joint, depth), Model(obs, anchor_paths(obs), 0)
    row['first_period_error'] = {
        'tree': sc.first_period_error(joint, obs), 'b1': sc.first_period_error(anchor_paths(obs), obs),
        'b4': sc.first_period_error(planner.open_loop(obs, v, planner.equal_time_scenarios), obs)
        if planner.equal_time_scenarios else None,
        'distinct_first_vectors': {'tree': len({tuple(x) for x in joint[:, 0]}),
                                   'b1': len({tuple(x) for x in anchor_paths(obs)[:, 0]})}}
    ctx = dict(context, method='audit', sampler_seed=planner.sampler_seed)
    given, rec, _ = planner.fixed(m1, anchor_action, dict(ctx, purpose='audit:M1|B1'))
    row['m1_given_b1'] = _brief(given, rec)
    s_own, rec, _ = planner.solve(own, dict(ctx, purpose='audit:B1'))
    row['b1_model'] = _brief(s_own, rec)
    if s_own is None:
        row['anchor'] = 'unresolved'; return row
    tied, rec, _ = planner.tie(m1, own, s_own['value'], dict(ctx, purpose='audit:B1*'))
    row['b1_tie'] = _brief(tied, rec)
    if tied is None:
        row['anchor'] = 'unresolved'; return row
    row['anchor'], row['anchor_excess'] = classify(planner, row['m1']['value'], s_own['action'],
                                                   row['m1']['action'], tied)
    if given is not None:
        row['b1_actual_excess'] = given['value']-row['m1']['value']
    return row


def rollout(task, method, planner, swap=None):
    """One trajectory; `swap` replaces the action at one period (the rest of the path re-plans as usual)."""
    env = Environment(task); rows = []; status = 'complete'
    for t in range(task['public']['periods']):
        obs = env.observe(); context = {'path': task['id'], 't': t, 'sampler_seed': planner.sampler_seed}
        try:
            if swap is not None and t == swap['t']:
                action = swap['action']; info = {'method': 'swap', 'swapped_in': swap['label'], 'solves': []}
            else:
                action, info = planner.decide(obs, method, dict(context, trajectory=method))
        except DecisionFailed as failure:
            status = f'failed_at_{t}'; rows.append({'t': t, 'failure': failure.info}); break
        except BudgetExhausted:
            check_ledger(task, rows, False)
            rows.append({'t': t, 'observation': obs, 'interrupted': 'budget'})
            planner.partial = {'id': task['id'], 'method': method, 'rows': rows,
                               'status': f'budget_exhausted_at_{t}'}
            raise
        row = env.step(action); row['planning'] = info; rows.append(row)
    done = [x for x in rows if 'failure' not in x]
    check_ledger(task, done, status == 'complete')
    return {'id': task['id'], 'profile': task['profile'], 'method': method, 'status': status,
            'metrics': metrics(done) if status == 'complete' else None}, rows


# --------------------------------------------------------------------------------------------- tuning

def tuning_tasks(cfg, base):
    return generate(base, 'tuning', cfg['tuning_seeds'])


def energy_scores(cfg, fit, tasks):
    """One-step joint energy score of the common-shock predictive for every prior strength (no solver)."""
    rule = cfg['energy_score']; scores = {}
    for strength in cfg['prior_strength_candidates']:
        values = []
        for task in tasks:
            env = Environment(task)
            for t in range(task['public']['periods']):
                obs = env.observe()
                if t:
                    v = sc.common_variance(obs, fit, strength, cfg['common_variance_cap'])
                    values.append(sc.energy_score(sc.one_step_samples(obs, v, rule['samples'], rule['seed']),
                                                  task['demand'][t]))
                env.step(np.zeros((3, 2), dtype=int).tolist())  # forecasts and history ignore actions
        scores[str(strength)] = {'mean': float(np.mean(values)), 'states': len(values)}
    best = min(cfg['prior_strength_candidates'], key=lambda s: (round(scores[str(s)]['mean'], 9),
                                                               cfg['prior_strength_candidates'].index(s)))
    return {'scores': scores, 'chosen': best}


def measure_shapes(cfg, fit, strength, states, budget):
    """Per candidate shape: first-period error and online times of M1 and of tie-robust M2* on tuning states."""
    out = []
    for shape in cfg['shape_candidates']:
        planner = PlannerV2(cfg, fit, budget, shape, strength, cfg['sampler_seeds'][0])
        record = {'shape': shape, 'states': [], 'failures': 0}
        for obs, context in states:
            g = time.perf_counter(); v = planner.variance(obs); joint, labels, depth = planner.joint(obs, v)
            m1 = Model(obs, joint, depth); built = time.perf_counter()-g
            sol, rec, _ = planner.solve(m1, dict(context, method='tuning', purpose=f'shape:{shape}:M1'))
            entry = {'t': obs['t'], 'path': context['path'], 'm1_online_seconds': built+rec['wall_seconds'],
                     'first_period_error': sc.first_period_error(joint, obs),
                     'b1_first_period_error': sc.first_period_error(anchor_paths(obs), obs),
                     'distinct_first_vectors': len({tuple(x) for x in joint[:, 0]}),
                     'model': m1.summary(), 'm1_status': rec['status']}
            g = time.perf_counter(); shuffled = planner.shuffled(obs, joint, labels, depth)
            own = Model(obs, shuffled, depth)
            s_own, rec2, _ = planner.solve(own, dict(context, method='tuning', purpose=f'shape:{shape}:M2'))
            tie_seconds = None
            if s_own is not None and sol is not None:
                tied, rec3, _ = planner.tie(m1, own, s_own['value'],
                                            dict(context, method='tuning', purpose=f'shape:{shape}:M2*'))
                tie_seconds = rec3['wall_seconds']
                if tied is None:
                    record['failures'] += 1
            else:
                record['failures'] += 1
            entry['m2_star_online_seconds'] = (time.perf_counter()-g if tie_seconds is not None else None)
            record['states'].append(entry)
        ok = [e for e in record['states'] if e['m2_star_online_seconds'] is not None]
        record.update({
            'mean_first_period_error': float(np.mean([e['first_period_error'] for e in record['states']])),
            'mean_b1_first_period_error': float(np.mean([e['b1_first_period_error'] for e in record['states']])),
            'mean_m1_online_seconds': float(np.mean([e['m1_online_seconds'] for e in record['states']])),
            'p95_m1_online_seconds': float(np.percentile([e['m1_online_seconds'] for e in record['states']], 95)),
            'p95_m2_star_online_seconds': float(np.percentile([e['m2_star_online_seconds'] for e in ok], 95))
            if ok else None})
        out.append(record)
    return out


def choose_shape(cfg, measured):
    rule = cfg['shape_rule']
    for record in measured:
        if (record['failures'] == 0 and record['mean_first_period_error'] <= record['mean_b1_first_period_error']
                and record['p95_m1_online_seconds'] <= rule['max_p95_m1_seconds']
                and record['p95_m2_star_online_seconds'] is not None
                and record['p95_m2_star_online_seconds'] <= rule['max_p95_m2_star_seconds']):
            return record['shape']
    return None


def equal_time(cfg, fit, strength, shape, states, budget, m1_seconds):
    planner = PlannerV2(cfg, fit, budget, shape, strength, cfg['sampler_seeds'][0]); measured = {}
    for count in cfg['equal_time_candidates']:
        times = []
        for obs, context in states:
            g = time.perf_counter(); v = planner.variance(obs); model = Model(obs, planner.open_loop(obs, v, count), 0)
            sol, rec, _ = planner.solve(model, dict(context, method='tuning', purpose=f'B4:{count}'))
            if sol is None:
                raise DecisionFailed({'reason': f'equal_time_failed:{count}'})
            times.append(time.perf_counter()-g)
        measured[count] = float(np.mean(times))
    target = float(np.mean(m1_seconds))
    chosen = min(cfg['equal_time_candidates'], key=lambda c: (abs(measured[c]-target), c))
    return {'mean_online_seconds': {str(k): v for k, v in measured.items()}, 'm1_mean_online_seconds': target,
            'chosen': chosen}


def tune(output=TUNING, cfg=None):
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f'output_not_empty:{out}')
    out.mkdir(parents=True, exist_ok=True)
    cfg, base = cfg or configuration(), base_configuration()
    fit = fitted_variance(cfg, base); tasks = tuning_tasks(cfg, base)
    scores = energy_scores(cfg, fit['fitted_variance'], tasks)
    budget = Budget(cfg['budget_tuning']); strength = scores['chosen']
    anchor = PlannerV2(cfg, fit['fitted_variance'], budget, cfg['shape_candidates'][0], strength,
                       cfg['sampler_seeds'][0])
    states = []
    for task in [t for t in tasks if t['seed'] == cfg['tuning_seeds'][0]]:
        env = Environment(task)
        for t in range(task['public']['periods']):
            obs = env.observe()
            action, _ = anchor.decide(obs, 'B1', {'path': task['id'], 't': t, 'trajectory': 'B1'})
            if not forced_zero(obs) and len([s for s in states if s[1]['path'] == task['id']]) < \
                    cfg['shape_rule']['states_per_path']:
                states.append((obs, {'path': task['id'], 't': t}))
            env.step(action)
    measured = measure_shapes(cfg, fit['fitted_variance'], strength, states, budget)
    shape = choose_shape(cfg, measured)
    timing = None
    if shape is not None:
        record = next(r for r in measured if r['shape'] == shape)
        timing = equal_time(cfg, fit['fitted_variance'], strength, shape, states, budget,
                            [e['m1_online_seconds'] for e in record['states']])
    selection = {'prior_strength': strength, 'shape': shape, 'equal_time': timing['chosen'] if timing else None,
                 'rules': {'prior_strength': 'lowest mean one-step joint energy score on the tuning split',
                           'shape': cfg['shape_rule'], 'equal_time': 'mean online time closest to M1'}}
    write_json(out/'config.json', {'rolling_tree_v2': cfg, 'environment': base})
    write_json(out/'fit.json', fit)
    write_json(out/'energy_scores.json', scores)
    write_json(out/'shapes.json', measured)
    write_json(out/'equal_time.json', timing)
    write_json(out/'selection.json', selection)
    write_json(out/'runtime.json', runtime())
    write_json(out/'usage.json', budget.usage())
    write_lines(out/'solves.jsonl', budget.log)
    files = sorted(p.name for p in out.iterdir() if p.name != 'manifest.json')
    write_json(out/'manifest.json', {name: digest_bytes((out/name).read_bytes()) for name in files})
    return {'output': str(out), 'selection': selection, 'usage': budget.usage()}


# --------------------------------------------------------------------------------------------- pilot

def pilot_tasks(cfg, base):
    return [t for t in generate(base, cfg['pilot']['split'], [cfg['pilot']['seed']])
            if t['profile'] in cfg['pilot']['profiles']]


def first_material(audits, path, seed, name):
    rows = sorted((a for a in audits if a['path'] == path and a.get('sampler_seed') == seed
                   and a.get(name) == 'material'), key=lambda a: a['t'])
    return rows[0] if rows else None


def swap_plan(audits, path, seed):
    """The one-decision swaps priced on the baseline path: first material dependence and anchor states."""
    out = []
    row = first_material(audits, path, seed, 'dependence')
    if row:
        out += [('dependence', row['t'], 'M1', row['m1']['action']),
                ('dependence', row['t'], 'M2*', row['m2_tie']['action'])]
    row = first_material(audits, path, seed, 'anchor')
    if row:
        out += [('anchor', row['t'], 'M1', row['m1']['action']),
                ('anchor', row['t'], 'B1*', row['b1_tie']['action'])]
    return out


def pilot(output=PILOT, cfg=None, selection=None):
    """`cfg` and `selection` overrides exist for smoke tests in a separate seed namespace only."""
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f'output_not_empty:{out}')
    out.mkdir(parents=True, exist_ok=True)
    cfg, base = cfg or configuration(), base_configuration()
    selection = selection or json.loads((TUNING/'selection.json').read_text(encoding='utf-8'))
    if selection['shape'] is None:
        raise ValueError('no_shape_selected_on_tuning')
    fit = fitted_variance(cfg, base); tasks = pilot_tasks(cfg, base); budget = Budget(cfg['budget'])
    planners = {s: PlannerV2(cfg, fit['fitted_variance'], budget, selection['shape'], selection['prior_strength'], s,
                             selection['equal_time']) for s in cfg['sampler_seeds']}
    anchor = planners[cfg['sampler_seeds'][0]]  # B0, B1 and LB do not use the planner sampling seed
    outcomes, traces, audits, items = [], [], [], []
    plan = [('B0', t, None) for t in tasks]
    for task in tasks:
        plan += [('B1', task, None)]+[('audit', task, s) for s in cfg['sampler_seeds']]
        plan += [('swaps', task, s) for s in cfg['sampler_seeds']]+[('LB', task, None)]
    plan += [(m, t, s) for s in cfg['sampler_seeds'] for t in tasks for m in TRAJECTORIES]
    stop = None
    for position, (kind, task, seed) in enumerate(plan):
        label = {'kind': kind, 'path': task['id'], 'sampler_seed': seed}
        try:
            if kind == 'audit':
                b1 = next(x for x in traces if x['id'] == task['id'] and x['method'] == 'B1')
                for row in b1['rows']:
                    if 'observation' in row and 'action' in row:
                        audit(planners[seed], row['observation'], {'path': task['id'], 't': row['observation']['t']},
                              audits, row['action'])
                items.append(dict(label, status='done')); continue
            if kind == 'swaps':
                for comparison, t, source, action in swap_plan(audits, task['id'], seed):
                    result, rows = rollout(task, 'B1', anchor,
                                           swap={'t': t, 'action': action, 'label': f'{source}@{t}'})
                    result.update(method=f'B1+{source}@{t}', swap={'comparison': comparison, 't': t,
                                                                  'source': source, 'action': action},
                                  sampler_seed=seed)
                    outcomes.append(result)
                    traces.append({'id': task['id'], 'method': result['method'], 'sampler_seed': seed, 'rows': rows})
                items.append(dict(label, status='done')); continue
            if kind == 'LB':
                result, rows = perfect(task, anchor)
            else:
                result, rows = rollout(task, kind, planners[seed] if seed else anchor)
            result['sampler_seed'] = seed
            outcomes.append(result)
            traces.append({'id': task['id'], 'method': result['method'], 'sampler_seed': seed, 'rows': rows})
            items.append(dict(label, status=result['status']))
        except BudgetExhausted as reason:
            stop = str(reason)
            partial = getattr(anchor, 'partial', None) or next(
                (getattr(p, 'partial') for p in planners.values() if getattr(p, 'partial', None)), None)
            if partial:
                traces.append({'id': partial['id'], 'method': partial['method'], 'sampler_seed': seed,
                               'rows': partial['rows']})
            items.append(dict(label, status=f'budget_exhausted:{stop}'))
            items += [{'kind': k, 'path': t['id'], 'sampler_seed': s, 'status': 'not_run_budget'}
                      for k, t, s in plan[position+1:]]
            break
        except DecisionFailed as failure:
            items.append(dict(label, status='failed', reason=failure.info.get('reason')))
    summary = summarize(cfg, selection, fit, budget, stop, items, outcomes, traces, audits)
    write_json(out/'config.json', {'rolling_tree_v2': cfg, 'selection': selection, 'environment': base})
    write_json(out/'tasks.json', tasks)
    write_json(out/'runtime.json', runtime())
    write_json(out/'outcomes.json', outcomes)
    write_json(out/'summary.json', summary)
    write_lines(out/'solves.jsonl', budget.log)
    write_lines(out/'audit.jsonl', audits)
    write_lines(out/'traces.jsonl', traces)
    files = sorted(p.name for p in out.iterdir() if p.name != 'manifest.json')
    write_json(out/'manifest.json', {name: digest_bytes((out/name).read_bytes()) for name in files})
    return {'output': str(out), 'usage': budget.usage(), 'stop_reason': stop,
            'audit_counts': summary['audit_counts']}


# --------------------------------------------------------------------------------------------- analysis

def audit_counts(audits):
    counts = {}
    for name in COMPARISONS:
        values = ['forced_zero' if a.get('forced_zero') else a.get(name, 'incomplete') for a in audits]
        counts[name] = {k: values.count(k) for k in sorted(set(values))}
    return counts


def action_change(m1, other):
    """Units of each SKU on each route that M1 ships beyond (+) or below (-) the other method."""
    return (np.asarray(m1)-np.asarray(other)).tolist()


def first_changes(audits):
    out = []
    for (path, seed) in sorted({(a['path'], a.get('sampler_seed')) for a in audits}):
        for name, (own, tie) in COMPARISONS.items():
            row = first_material(audits, path, seed, name)
            if row is None:
                out.append({'path': path, 'sampler_seed': seed, 'comparison': name, 't': None}); continue
            out.append({'path': path, 'sampler_seed': seed, 'comparison': name, 't': row['t'],
                        'm1_action': row['m1']['action'], 'other_best_tie_action': row[tie]['action'],
                        'other_own_action': row[own]['action'],
                        'change_m1_minus_other': action_change(row['m1']['action'], row[tie]['action']),
                        'excess': row[name+'_excess'], 'm1_window_objective': row['m1']['value'],
                        'excess_share': row[name+'_excess']/row['m1']['value'] if row['m1']['value'] else None,
                        'common_variance': row['common_variance'],
                        'b1_actual_action': row['b1_action']})
    return out


def _difference(x, y):
    mx, my = x['metrics'], y['metrics']
    return {'cost': mx['total_cost']-my['total_cost'],
            'cost_relative': (mx['total_cost']-my['total_cost'])/my['total_cost'],
            'fill': mx['immediate_fill_rate']-my['immediate_fill_rate'],
            'emissions': mx['emissions']-my['emissions'],
            'backlog_unit_periods': mx['backlog_unit_periods']-my['backlog_unit_periods']}


def contrasts(outcomes):
    def find(path, method, seed):
        return next((x for x in outcomes if x['id'] == path and x['method'] == method
                     and x.get('sampler_seed') == seed and x['status'] == 'complete'), None)
    rows = []
    for path in sorted({x['id'] for x in outcomes}):
        b1 = find(path, 'B1', None)
        for seed in sorted({x.get('sampler_seed') for x in outcomes if x.get('sampler_seed')}):
            pairs = [('M1-M2*', find(path, 'M1', seed), find(path, 'M2*', seed)),
                     ('M1-B3', find(path, 'M1', seed), find(path, 'B3', seed)),
                     ('M1-B4', find(path, 'M1', seed), find(path, 'B4', seed)),
                     ('M1-B1', find(path, 'M1', seed), b1), ('B4-B1', find(path, 'B4', seed), b1)]
            swaps = [x for x in outcomes if x['id'] == path and x.get('sampler_seed') == seed and 'swap' in x
                     and x['status'] == 'complete']
            for comparison, other in (('dependence', 'M2*'), ('anchor', 'B1*')):
                mine = next((x for x in swaps if x['swap']['comparison'] == comparison
                             and x['swap']['source'] == 'M1'), None)
                theirs = next((x for x in swaps if x['swap']['comparison'] == comparison
                               and x['swap']['source'] == other), None)
                if mine:
                    pairs.append((f'swap:{comparison}:M1-{other}@{mine["swap"]["t"]}', mine, theirs))
                    if comparison == 'anchor':
                        pairs.append((f'swap:anchor:M1-B1@{mine["swap"]["t"]}', mine, b1))
            for name, x, y in pairs:
                row = {'path': path, 'sampler_seed': seed, 'contrast': name, 'available': bool(x and y)}
                if x and y:
                    row.update(_difference(x, y))
                rows.append(row)
    return rows


def aggregate(rows):
    out = {}
    for name in sorted({r['contrast'].split('@')[0] for r in rows}):
        mine = [r for r in rows if r['contrast'].split('@')[0] == name and r['available']]
        if not mine:
            continue
        costs = [r['cost'] for r in mine]; seeds = sorted({r['sampler_seed'] for r in mine})
        out[name] = {'cases': len(mine), 'mean_cost': float(np.mean(costs)),
                     'mean_cost_relative': float(np.mean([r['cost_relative'] for r in mine])),
                     'better': sum(c < -1e-9 for c in costs), 'worse': sum(c > 1e-9 for c in costs),
                     'same': sum(abs(c) <= 1e-9 for c in costs),
                     'mean_fill': float(np.mean([r['fill'] for r in mine])),
                     'mean_emissions': float(np.mean([r['emissions'] for r in mine])),
                     'mean_cost_by_seed': {str(s): float(np.mean([r['cost'] for r in mine if r['sampler_seed'] == s]))
                                           for s in seeds}}
    return out


def summarize(cfg, selection, fit, budget, stop, items, outcomes, traces, audits):
    timing = {}
    for method in sorted({x['method'] for x in traces if '+' not in x['method']}):
        values = [r['planning'].get('online_seconds') for x in traces if x['method'] == method
                  for r in x['rows'] if 'planning' in r and r['planning'].get('online_seconds') is not None]
        if values:
            timing[method] = {'decisions': len(values), 'mean_online_seconds': float(np.mean(values)),
                              'p95_online_seconds': float(np.percentile(values, 95))}
    quality = [a['first_period_error'] for a in audits if 'first_period_error' in a]
    rows = contrasts(outcomes); solves = budget.log
    return {'scope': cfg['scope'], 'selection': selection, 'fit': fit, 'budget_rule': cfg['budget'],
            'usage': budget.usage(), 'stop_reason': stop, 'items': items,
            'audit_counts': audit_counts(audits), 'first_changes': first_changes(audits),
            'first_period_error': {k: float(np.mean([q[k] for q in quality if q.get(k) is not None]))
                                   for k in ('tree', 'b1', 'b4') if any(q.get(k) is not None for q in quality)},
            'contrasts': rows, 'aggregate': aggregate(rows), 'decision_timing': timing,
            'solve_failures': [s for s in solves if s.get('status') != 0],
            'confirmation': 'not_generated_not_viewed', 'learning_trained': False}


def verify(output=PILOT, current_configuration=True):
    """Recompute without solving: hashes, tasks, ledgers, metrics, regenerated trees and every summary table."""
    out = Path(output); saved = json.loads((out/'config.json').read_text(encoding='utf-8'))
    manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    for name, value in manifest.items():
        if digest_bytes((out/name).read_bytes()) != value:
            raise ValueError(f'hash:{name}')
    cfg, base, selection = saved['rolling_tree_v2'], saved['environment'], saved['selection']
    if base != base_configuration() or (current_configuration and cfg != configuration()):
        raise ValueError('configuration_changed')
    summary = json.loads((out/'summary.json').read_text(encoding='utf-8'))
    fit = fitted_variance(cfg, base)
    if fit != summary['fit']:
        raise ValueError('fit_changed')
    tasks = pilot_tasks(cfg, base)
    if json.loads((out/'tasks.json').read_text(encoding='utf-8')) != tasks:
        raise ValueError('tasks_changed')
    by_id = {t['id']: t for t in tasks}; traces = read_lines(out/'traces.jsonl')
    outcomes = json.loads((out/'outcomes.json').read_text(encoding='utf-8')); checked = 0
    for trace in traces:
        rows = [r for r in trace['rows'] if 'failure' not in r and 'interrupted' not in r]
        outcome = next((x for x in outcomes if x['id'] == trace['id'] and x['method'] == trace['method']
                        and x.get('sampler_seed') == trace.get('sampler_seed')), None)
        complete = outcome is not None and outcome['status'] == 'complete'
        check_ledger(by_id[trace['id']], rows, complete)
        for row in rows:
            sc.check_observation(row['observation'])
        if complete:
            close(metrics(rows), outcome['metrics'])
        checked += 1
    anchor = {(x['id'], r['observation']['t']): r['observation'] for x in traces if x['method'] == 'B1'
              for r in x['rows'] if 'observation' in r}
    planners = {s: PlannerV2(cfg, fit['fitted_variance'], None, selection['shape'], selection['prior_strength'], s,
                             selection['equal_time']) for s in cfg['sampler_seeds']}
    audits = read_lines(out/'audit.jsonl'); trees = 0
    for row in audits:
        if row.get('forced_zero') or 'joint_digest' not in row:
            continue
        planner = planners[row['sampler_seed']]; obs = anchor[(row['path'], row['t'])]
        joint, labels, depth = planner.joint(obs, planner.variance(obs))
        if array_digest(joint) != row['joint_digest'] or \
                array_digest(planner.shuffled(obs, joint, labels, depth)) != row['shuffled_digest']:
            raise ValueError(f'tree_changed:{row["path"]}:{row["t"]}')
        trees += 1
    if audit_counts(audits) != summary['audit_counts'] or first_changes(audits) != summary['first_changes']:
        raise ValueError('audit_summary_changed')
    rows = contrasts(outcomes)
    if rows != summary['contrasts'] or aggregate(rows) != summary['aggregate']:
        raise ValueError('contrasts_changed')
    return {'files': len(manifest), 'trajectories': checked, 'trees_regenerated': trees, 'solves_run': 0}
