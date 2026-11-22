"""Run and replay the materiality and three-tree selection experiments."""
from collections import Counter
import json
from pathlib import Path
import time

from rolling_inventory.environment import validate
from . import ensemble, materiality, stability
from .experiment import ROOT, digest_bytes, read_lines, runtime, write_json
from .experiment_v2 import PILOT
from .planning import solve, solve_fixed_first


OUTPUT = ROOT/'benchmark_results'
PROTOCOL = ROOT/'docs/rolling_tree_consensus_protocol.md'
AMENDMENT = ROOT/'docs/rolling_tree_consensus_protocol_amendment.md'
DEFAULT_MAX_WALL_SECONDS = 5400
AMENDED_MAX_WALL_SECONDS = 10800
WALL_BUDGETS = (DEFAULT_MAX_WALL_SECONDS, AMENDED_MAX_WALL_SECONDS)
STUDIES = (('rolling_tree_materiality', materiality), ('rolling_tree_consensus', ensemble))
FILES = ('config.json', 'trial.jsonl', 'formal.jsonl', 'summary.json', 'runtime.json')


def _inputs(max_wall_seconds=DEFAULT_MAX_WALL_SECONDS):
    if max_wall_seconds not in WALL_BUDGETS:
        raise ValueError(f'unsupported_max_wall_seconds:{max_wall_seconds}')
    source = stability.OUTPUT
    hashes = stability._hashes(source, stability.EVIDENCE_FILES)
    if hashes != stability._json(source/'manifest.json'):
        raise ValueError('single_tree_evidence_hash')
    frozen = stability._json(source/'config.json')
    config, states = stability._inputs(PILOT)
    if config != frozen:
        raise ValueError('single_tree_configuration_changed')
    rows = read_lines(source/'states.jsonl')
    archived = {stability._row_key(row): row for row in rows}
    old = stability._json(source/'summary.json')
    tiers = [3, old['selection']['tier']]
    seeds = frozen['sampler_seeds']
    expected = stability._jobs(states, frozen, [1, *tiers])
    if (list(archived) != expected or len(rows) != len(expected) or
            any(r['action'] is None for r in rows) or old['stop_reason'] is not None):
        raise ValueError('incomplete_single_tree_source')
    if tiers != [3, 12] or seeds != [924601, 924611, 924617] or len(states) != 44:
        raise ValueError('single_tree_scope_changed')
    protocol = {
        'schema': 'rolling-tree-materiality-and-ensemble',
        'protocol_sha256': digest_bytes(PROTOCOL.read_bytes()),
        'single_tree_sha256': hashes,
        'single_tree_config': frozen,
        'tie_tolerance': stability._json(PILOT/'config.json')['rolling_tree_v2']['tie_tolerance'],
        'observations': len(states),
        'groups': {'a': seeds, 'b': [924623, 924629, 924631]},
        'tiers': tiers,
        'trial_periods': [0, 5, 6],
        'max_wall_seconds': float(max_wall_seconds),
        'start_guard_seconds': 45.0,
        'max_failure_rate': .05,
        'max_action_change_rate': .10,
        'baseline_online': {str(tier): old['formal']['tiers'][str(tier)]['online_seconds'] for tier in tiers},
    }
    if max_wall_seconds == AMENDED_MAX_WALL_SECONDS:
        protocol['amendment_sha256'] = digest_bytes(AMENDMENT.read_bytes())
    return protocol, states, archived


class BudgetReached(Exception):
    pass


class Budget:
    """Share time and the cumulative solve-failure limit across both formal studies."""

    def __init__(self, config, progress):
        self.config = config
        self.progress = progress
        self.start = time.perf_counter()
        self.attempts = 0
        self.failures = 0
        self.reason = None
        self.next_report = 900

    def elapsed(self):
        return time.perf_counter()-self.start

    def check(self):
        if self.reason is None and self.elapsed() > self.config['max_wall_seconds']-self.config['start_guard_seconds']:
            self.reason = 'formal_wall_budget'
        if self.reason is not None:
            raise BudgetReached(self.reason)

    def record(self, failed):
        self.attempts += 1
        self.failures += failed
        if self.failures/self.attempts > self.config['max_failure_rate']:
            self.reason = 'formal_failure_rate_above_limit'
        wall = self.elapsed()
        if self.progress is not None and wall >= self.next_report:
            self.progress('formal_progress', {'attempts': self.attempts, 'failures': self.failures, 'wall_seconds': wall})
            self.next_report += 900


class Evaluation:
    """One observation's models, solve records and measured decision times."""

    def __init__(self, key, obs, config, archived, budget=None, replay=None):
        self.key, self.obs, self.config, self.archived = key, obs, config, archived
        self.budget, self.replay = budget, replay
        self.models, self.values = {}, {}
        self.calls, self.timings = [], {}

    def _model(self, seed, tier):
        if (seed, tier) not in self.models:
            model, paths, variance = stability._model(self.obs, self.config['single_tree_config'], seed, tier)
            tree = stability._tree_summary(model, paths, variance)
            archived = self.archived.get((*self.key, seed, tier))
            if archived is not None and archived['tree'] != tree:
                raise ValueError(f'archived_tree_changed:{self.key}:{seed}:{tier}')
            self.models[seed, tier] = model, tree
        return self.models[seed, tier]

    def call(self, seed, tier, action=None):
        fixed = None if action is None else tuple(tuple(row) for row in action)
        key = (seed, tier, fixed)
        if key in self.values:
            return self.values[key]
        if self.budget is not None:
            self.budget.check()
        replaying = self.replay is not None
        if replaying and len(self.calls) == len(self.replay['calls']):
            if self.replay['result'] is None:
                raise BudgetReached('incomplete_observation')
            raise ValueError('missing_solve_record')
        model, tree = self._model(seed, tier)
        fields = {'seed': seed, 'tier': tier, 'fixed_action': action, 'tree': tree}
        if replaying:
            entry = self.replay['calls'][len(self.calls)]
            if any(entry[k] != v for k, v in fields.items()):
                raise ValueError(f'solve_record_alignment:{self.key}:{key}')
            value, record = entry['solution'], entry['solver']
        else:
            limit = self.config['single_tree_config']['solver']['time_limit_seconds']
            result, record = solve(model, limit) if action is None else solve_fixed_first(model, action, limit)
            value = None if result is None else {k: result[k] for k in ('value', 'action')}
        optimal = record['status'] == 0 and record['feasible_solution']
        if optimal != (value is not None):
            raise ValueError(f'solver_status:{self.key}:{key}')
        if value is not None:
            validate(value['action'], self.obs)
            if (action is not None and value['action'] != action) or value['value'] != record['replayed_objective']:
                raise ValueError(f'solver_result:{self.key}:{key}')
        self.calls.append(dict(fields, solution=value, solver=record))
        self.values[key] = value
        if self.budget is not None:
            self.budget.record(value is None)
        return value

    def timed(self, label, function):
        start = time.perf_counter()
        result = function()
        seconds = time.perf_counter()-start if self.replay is None else self.replay['timings'][label]
        self.timings[label] = seconds
        return result, seconds


def _phase(module, output, keys, states, archived, config, budget=None):
    records = []
    with output.open('x', encoding='utf-8') as ledger:
        for key in keys:
            if budget is not None and budget.reason is not None:
                break
            evaluator = Evaluation(key, states[key][1], config, archived, budget=budget)
            start = time.perf_counter()
            result = None
            try:
                result = module.analyze(key, archived, config, evaluator)
            except BudgetReached:
                pass
            finally:
                row = {'key': list(key), 'result': result, 'calls': evaluator.calls, 'timings': evaluator.timings,
                       'seconds': time.perf_counter()-start}
                ledger.write(json.dumps(row, sort_keys=True, allow_nan=False)+'\n')
                ledger.flush()
                records.append(row)
    return records


def _phase_stats(rows):
    calls = [call for row in rows for call in row['calls']]
    return {'observations': len(rows), 'completed_observations': sum(r['result'] is not None for r in rows),
            'solves': len(calls), 'failures': sum(c['solution'] is None for c in calls),
            'status_counts': dict(Counter(str(c['solver']['status']) for c in calls)),
            'observation_seconds': stability._duration([r['seconds'] for r in rows]),
            'active_wall_seconds': sum(r['seconds'] for r in rows)}


def _estimate(trials, config):
    return (config['observations']*sum(stability._duration([row['seconds'] for row in rows])['p95']
                                        for rows in trials) + config['start_guard_seconds'])


def _summary(module, config, trial, formal, execution):
    result = module.summary([row['result'] for row in formal if row['result'] is not None], config)
    if execution['stop_reason'] is not None and 'conclusion' in result:
        result['conclusion'] = 'unassessed'
    return {'trial': _phase_stats(trial), 'formal': _phase_stats(formal), 'results': result, **execution}


def run(output=OUTPUT, progress=None, *, max_wall_seconds=DEFAULT_MAX_WALL_SECONDS):
    config, states, archived = _inputs(max_wall_seconds)
    outputs = [Path(output)/name for name, _ in STUDIES]
    for out in outputs:
        if out.exists() and any(out.iterdir()):
            raise FileExistsError(f'output_not_empty:{out}')
    for out in outputs:
        out.mkdir(parents=True, exist_ok=True)
        write_json(out/'config.json', config)
    trial_keys = [key for key in states if key[1] in config['trial_periods']]
    trials = []
    for out, (_, module) in zip(outputs, STUDIES):
        rows = _phase(module, out/'trial.jsonl', trial_keys, states, archived, config)
        trials.append(rows)
        if progress is not None:
            progress('trial_complete', dict(study=out.name, **_phase_stats(rows)))
    estimate = _estimate(trials, config)
    stop = 'estimated_formal_wall_above_budget' if estimate > config['max_wall_seconds'] else None
    if progress is not None:
        progress('timing_gate', {'estimated_formal_wall_seconds': estimate, 'reason': stop})
    budget = None if stop is not None else Budget(config, progress)
    formals = []
    for out, (_, module) in zip(outputs, STUDIES):
        if budget is None or budget.reason is not None:
            (out/'formal.jsonl').touch()
            formals.append([])
            continue
        if progress is not None:
            progress('formal_start', {'study': out.name, 'observations': len(states)})
        rows = _phase(module, out/'formal.jsonl', states, states, archived, config, budget=budget)
        formals.append(rows)
        if progress is not None:
            progress('formal_complete', dict(study=out.name, **_phase_stats(rows)))
    wall = None if budget is None else budget.elapsed()
    if budget is not None:
        stop = budget.reason
        if stop is None and wall > config['max_wall_seconds']:
            stop = 'formal_wall_budget'
    execution = {'estimated_formal_wall_seconds': estimate, 'formal_wall_seconds': wall, 'stop_reason': stop}
    environment = dict(runtime(), execution=execution)
    for out, (_, module), trial, formal in zip(outputs, STUDIES, trials, formals):
        write_json(out/'runtime.json', environment)
        write_json(out/'summary.json', _summary(module, config, trial, formal, execution))
        write_json(out/'manifest.json', stability._hashes(out, FILES))
    return execution


def _replay(module, records, keys, states, archived, config):
    if [tuple(row['key']) for row in records] != list(keys)[:len(records)]:
        raise ValueError('observation_order')
    for row in records:
        key = tuple(row['key'])
        evaluator = Evaluation(key, states[key][1], config, archived, replay=row)
        try:
            result = module.analyze(key, archived, config, evaluator)
        except BudgetReached:
            result = None
        if (result != row['result'] or evaluator.calls != row['calls'] or
                evaluator.timings != row['timings']):
            raise ValueError(f'analysis_replay_changed:{key}')


def verify(output=OUTPUT, *, gate1=False):
    suffix = '_gate1' if gate1 else ''
    packages = []
    for name, module in STUDIES:
        out = Path(output)/(name+suffix)
        if stability._json(out/'manifest.json') != stability._hashes(out, FILES):
            raise ValueError(f'evidence_hash:{out.name}')
        packages.append((out, module, stability._json(out/'config.json')))
    config, states, archived = _inputs(packages[0][2]['max_wall_seconds'])
    for out, _, saved in packages:
        if saved != config:
            raise ValueError(f'configuration_changed:{out.name}')

    trial_keys = [key for key in states if key[1] in config['trial_periods']]
    trials, formals, summaries, executions = [], [], [], []
    attempts = failures = 0
    for out, module, _ in packages:
        trial = read_lines(out/'trial.jsonl')
        formal = read_lines(out/'formal.jsonl')
        if len(trial) != len(trial_keys) or any(row['result'] is None for row in trial):
            raise ValueError(f'trial_observation_count:{out.name}')
        _replay(module, trial, trial_keys, states, archived, config)
        _replay(module, formal, states, states, archived, config)
        for row in formal:
            for call in row['calls']:
                if attempts and failures/attempts > config['max_failure_rate']:
                    raise ValueError('formal_continued_after_failure_gate')
                attempts += 1
                failures += call['solution'] is None
        trials.append(trial)
        formals.append(formal)
        summaries.append(stability._json(out/'summary.json'))
        executions.append(stability._json(out/'runtime.json')['execution'])
    estimate = _estimate(trials, config)
    execution = executions[0]
    wall = execution['formal_wall_seconds']
    stop = None
    if estimate > config['max_wall_seconds']:
        if any(formals) or wall is not None:
            raise ValueError('formal_run_after_timing_gate')
        stop = 'estimated_formal_wall_above_budget'
    elif wall is None:
        raise ValueError('missing_formal_wall_time')
    elif attempts and failures/attempts > config['max_failure_rate']:
        stop = 'formal_failure_rate_above_limit'
    elif any(len(rows) != len(states) or any(r['result'] is None for r in rows) for rows in formals) or wall > config['max_wall_seconds']:
        stop = 'formal_wall_budget'
    expected = {'estimated_formal_wall_seconds': estimate, 'formal_wall_seconds': wall, 'stop_reason': stop}
    if any(record != expected for record in executions):
        raise ValueError('execution_summary_changed')
    for (_, module), trial, formal, summary in zip(STUDIES, trials, formals, summaries):
        if _summary(module, config, trial, formal, expected) != summary:
            raise ValueError('experiment_summary_changed')
    tree_replays = sum(len({(c['seed'], c['tier']) for c in r['calls']})
                       for rows in [*trials, *formals] for r in rows)
    return {'manifests': len(STUDIES), 'files': len(STUDIES)*len(FILES), 'trees_regenerated': tree_replays,
            'formal_attempts': attempts, 'solves_run': 0}
