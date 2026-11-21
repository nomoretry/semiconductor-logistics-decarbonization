"""Sequential paired policy evaluation under the frozen closing protocol."""
from collections import Counter
import json
from pathlib import Path
import time

import numpy as np

from rolling_inventory.environment import generate
from . import experiment_v2 as v2
from .closing_stats import METHODS, is_timeout, summarize
from .experiment import (ROOT, Budget, BudgetExhausted, DecisionFailed, array_digest, base_configuration,
                         digest_bytes, forced_zero, perfect, runtime, write_json)
from .planning import Model


OUTPUT = ROOT / 'benchmark_results/rolling_tree_closing'
PROTOCOL = ROOT / 'docs/rolling_tree_closing_protocol.md'
SEEDS = (75011, 75023, 75037, 75041, 75053, 75067, 75079, 75083, 75097, 75109,
         75113, 75127, 75139, 75151, 75163, 75173, 75187, 75193, 75209, 75217,
         75223, 75239, 75247, 75253, 75269, 75277, 75289, 75307, 75323, 75337,
         75347, 75353, 75367, 75377, 75389, 75391, 75401, 75407, 75431, 75437)
PROFILES = ('stable', 'volatile', 'upshift', 'downshift')
FILES = ('config.json', 'tasks.json', 'timing.json', 'solves.jsonl', 'traces.jsonl', 'results.jsonl',
         'divergences.json', 'summary.json', 'runtime.json', 'execution.json')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def file_hash(path):
    return digest_bytes(Path(path).read_bytes())


def settings():
    return {'split': 'closing', 'path_seeds': list(SEEDS), 'profiles': list(PROFILES),
            'first_sampler': 925101, 'bootstrap_seed': 979301, 'formal_limit': 7200,
            'max_incomplete_per_primary_method': 8, 'environment': base_configuration(),
            'v2': v2.configuration(), 'fit': read(v2.TUNING/'fit.json'),
            'selection': read(v2.TUNING/'selection.json'), 'protocol_sha256': file_hash(PROTOCOL)}


def ordered_tasks(cfg):
    tasks = generate(cfg['environment'], cfg['split'], cfg['path_seeds'])
    by = {(task['seed'], task['profile']): task for task in tasks}
    return [by[seed, profile] for seed in cfg['path_seeds'] for profile in cfg['profiles']]


def path_index(tasks, cfg):
    return [{'id': task['id'], 'k': k, 'profile': task['profile'], 'seed': task['seed'],
             'sampler_seed': cfg['first_sampler']+k,
             'task_sha256': digest_bytes(json.dumps(task, sort_keys=True).encode())}
            for k, task in enumerate(tasks)]


def node_carbon(model, solution):
    """Carbon at each decision node, in the model's first-seen observable-history order."""
    p = model.obs['public']
    weight = np.asarray(p['mass'])[:, None] * np.asarray(p['emissions'])
    actions = np.rint(solution['x'][:model.qn]).astype(int).reshape(-1, *model.shape)
    carbon = (actions*weight).sum(axis=(1, 2)).astype(int)
    sizes = [len(nodes) for nodes in model.nodes]
    return [a.tolist() for a in np.split(carbon, np.cumsum(sizes)[:-1])]


def max_carbon(nodes, node_ids):
    return int(sum(np.asarray(stage)[index] for stage, index in zip(nodes, np.asarray(node_ids).T, strict=True)).max())


class ClosingPlanner(v2.PlannerV2):
    """Extend the frozen policies with an own-only action and a timeout-only tie fallback."""

    def joint(self, obs, variance):
        joint, labels, depth = super().joint(obs, variance)
        self.details['joint_sha256'] = array_digest(joint)
        return joint, labels, depth

    def shuffled(self, obs, joint, labels, depth):
        own = super().shuffled(obs, joint, labels, depth)
        self.details['shuffled_sha256'] = array_digest(own)
        return own

    def solve(self, model, context):
        solution, record, index = super().solve(model, context)
        if solution is not None:
            log = self.budget.log[-1]
            log['first_action'] = solution['action']
            if context['method'] in ('M1', 'M2'):
                nodes = node_carbon(model, solution)
                log['node_carbon'] = nodes
                self.details['max_leaf_carbon'] = max_carbon(nodes, model.node_of)
            if context['purpose'] == 'M2*:own':
                self.own_action = solution['action']
        return solution, record, index

    def tie(self, primary, own, own_value, context):
        result, record, index = super().tie(primary, own, own_value, context)
        if result is None and record['status'] == 1 and is_timeout(record):
            self.details['fallback'] = True
            result = {'action': self.own_action}
        elif result is not None:
            self.budget.log[-1]['first_action'] = result['action']
        return result, record, index

    def decide(self, obs, method, context):
        start, cpu = time.perf_counter(), time.process_time()
        self.details = {}
        self.own_action = None
        try:
            if method == 'M2' and not forced_zero(obs):
                variance = self.variance(obs)
                joint, labels, depth = self.joint(obs, variance)
                own = Model(obs, self.shuffled(obs, joint, labels, depth), depth)
                result, _, index = self.solve(own, dict(context, method=method, purpose='M2:own'))
                info = {'method': method, 'solves': [index], 'forced_zero': False, 'common_variance': variance}
                if result is None:
                    raise DecisionFailed(dict(info, reason='M2_own_failed'))
                action = result['action']
            else:
                action, info = super().decide(obs, method, context)
            if method == 'B1':
                self.details['scenarios_sha256'] = array_digest(v2.anchor_paths(obs))
                self.budget.log[-1]['first_action'] = action
        except DecisionFailed as error:
            error.info.update(self.details, online_seconds=time.perf_counter()-start)
            if method == 'B1':
                error.info['scenarios_sha256'] = array_digest(v2.anchor_paths(obs))
                message = self.budget.log[-1]['message']
                if not message.startswith('MILP_not_optimal:'):
                    raise ValueError(message) from error
            raise
        info.update(self.details, online_seconds=time.perf_counter()-start, online_cpu_seconds=time.process_time()-cpu)
        return action, info


def make_planner(cfg, budget, seed):
    selection = cfg['selection']
    return ClosingPlanner(cfg['v2'], cfg['fit']['fitted_variance'], budget, selection['shape'],
                          selection['prior_strength'], seed)


def trajectory(task, method, planner):
    if method != 'LB':
        return v2.rollout(task, method, planner)
    result, rows = perfect(task, planner)
    if result['status'] != 'complete':
        message = planner.budget.log[-1]['message']
        if not message.startswith('MILP_not_optimal:'):
            raise ValueError(message)
    return result, rows


def budget_for(seconds):
    # Six listed methods need at most 5 per-period solves plus one offline solve per path.
    return Budget({'max_solves': 160*(5*12+1), 'max_wall_seconds': seconds, 'start_guard_seconds': 30})


def timing_gate(cfg, progress):
    budget = budget_for(cfg['formal_limit'])
    pilot = cfg['v2']['pilot']
    sampler = cfg['v2']['sampler_seeds'][0]
    timings = []
    for task in generate(cfg['environment'], pilot['split'], [pilot['seed']]):
        start = time.perf_counter()
        planner = make_planner(cfg, budget, sampler)
        for method in METHODS:
            trajectory(task, method, planner)
        timing = {'id': task['id'], 'wall_seconds': time.perf_counter()-start}
        timings.append(timing)
        progress('timing_path', timing)
    estimate = 160*max(x['wall_seconds'] for x in timings)+60
    gate = {'development': timings, 'sampler_seed': sampler, 'estimated_seconds': estimate,
            'limit_seconds': cfg['formal_limit'], 'passed': estimate <= cfg['formal_limit']}
    progress('timing_gate', gate)
    return gate


def append_line(path, record):
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(record, sort_keys=True, allow_nan=False, separators=(',', ':'))+'\n')


def formal(output, cfg, gate, progress, max_wall_seconds):
    budget = budget_for(max_wall_seconds)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise FileExistsError(out)
    tasks = ordered_tasks(cfg)
    paths = path_index(tasks, cfg)
    write_json(out/'tasks.json', paths)
    write_json(out/'config.json', cfg)
    write_json(out/'timing.json', gate)
    write_json(out/'runtime.json', runtime())
    for name in ('solves.jsonl', 'results.jsonl', 'traces.jsonl'):
        (out/name).touch(exist_ok=False)
    results, traces = [], []
    failures = Counter()
    stop = None
    for task, item in zip(tasks, paths, strict=True):
        planner = make_planner(cfg, budget, item['sampler_seed'])
        for method in METHODS:
            begin = len(budget.log)
            planner.partial = None
            try:
                result, rows = trajectory(task, method, planner)
            except BudgetExhausted as error:
                stop = str(error)
                partial = planner.partial
                rows = partial['rows'] if partial else []
                result = {'id': task['id'], 'method': method, 'profile': task['profile'],
                          'status': partial['status'] if partial else 'budget_exhausted_at_0', 'metrics': None}
            finally:
                for solve in budget.log[begin:]:
                    append_line(out/'solves.jsonl', solve)
            trace = {'id': task['id'], 'method': method, 'sampler_seed': item['sampler_seed'], 'rows': rows}
            append_line(out/'results.jsonl', result)
            append_line(out/'traces.jsonl', trace)
            results.append(result)
            traces.append(trace)
            if result['status'] != 'complete' and method in ('M1', 'M2'):
                failures[method] += 1
                if failures[method] > cfg['max_incomplete_per_primary_method']:
                    stop = f'incomplete_{method}'
            if stop:
                break
        progress('formal_path', {'k': item['k'], 'id': task['id'], 'solves': budget.solves,
                                 'wall_seconds': budget.elapsed(), 'stop_reason': stop})
        if stop:
            break
    summary, divergences = summarize(results, traces, budget.log, paths, cfg['bootstrap_seed'],
                                     cfg['v2']['reference_thresholds'])
    write_json(out/'summary.json', summary)
    write_json(out/'divergences.json', divergences)
    if budget.elapsed() > max_wall_seconds and stop is None:
        stop = 'max_wall_seconds'
    execution = {'stop_reason': stop, 'scheduled_paths': len(paths), 'recorded_trajectories': len(results),
                 'max_wall_seconds': max_wall_seconds, **budget.usage()}
    write_json(out/'execution.json', execution)
    write_json(out/'manifest.json', {name: file_hash(out/name) for name in FILES})
    return execution


def run(output=OUTPUT, *, max_wall_seconds=7200, progress=lambda event, data: None):
    if not 30 < max_wall_seconds <= 7200:
        raise ValueError('closing_wall_budget_must_be_above_30_and_at_most_7200')
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(out)
    cfg = settings()
    if v2.fitted_variance(cfg['v2'], cfg['environment']) != cfg['fit']:
        raise ValueError('frozen_fit_replay')
    gate = timing_gate(cfg, progress)
    if not gate['passed'] or gate['estimated_seconds'] > max_wall_seconds:
        return {'stop_reason': 'timing_gate', 'formal_paths_run': 0, 'formal_solves': 0, 'timing': gate}
    return formal(out, cfg, gate, progress, max_wall_seconds)
