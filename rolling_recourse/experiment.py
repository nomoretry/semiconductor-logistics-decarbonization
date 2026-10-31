"""Exact small-tree optimization with decisions indexed by observed history.

The scalar ledger and exhaustive optimizer are independent of the archived MILP.
The archived Environment and MILP provide additional physical/optimality checks.
"""
from collections import defaultdict
from fractions import Fraction
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZERO = (0, 0, 0, 0)


def configuration():
    return json.loads((ROOT / 'rolling_recourse/config.json').read_text())


def matrix(action):
    return [list(action[:2]), list(action[2:])]


def emission(action, cfg):
    return sum(action[2*i+j] * cfg['emissions'][j] for i in range(2) for j in range(2))


def actions(cfg, capacity, budget, period):
    """All feasible actions, including idling, in an explicit stable order."""
    routes = []
    for lead, cap in zip(cfg['lead'], [cfg['slow_capacity'], capacity]):
        routes.append([(a, b) for a in range(cap+1) for b in range(cap+1-a)]
                      if period+lead < 3 else [(0, 0)])
    candidates = [(slow[0], fast[0], slow[1], fast[1])
                  for slow, fast in product(*routes)]
    return sorted(a for a in candidates if emission(a, cfg) <= budget)


def leaves(coupling, accuracy, high):
    """Exact probabilities; the observation is S, never terminal H."""
    p, d = accuracy
    if not 0 < p < d:
        raise ValueError('signal_must_leave_future_uncertainty')
    if coupling not in ('positive', 'independent', 'negative'):
        raise ValueError('unknown_coupling')
    rows = []
    for terminal in product(range(2), repeat=2):
        if coupling == 'positive' and terminal[0] != terminal[1]:
            continue
        if coupling == 'negative' and terminal[0] == terminal[1]:
            continue
        for signal in product(range(2), repeat=2):
            weight = 1 if coupling == 'independent' else 2
            for h, s in zip(terminal, signal):
                weight *= p if h == s else d-p
            rows.append({'signal': list(signal), 'terminal_high': list(terminal),
                         'weight': weight,
                         'demand': [list(signal), [0, 0], [high*h for h in terminal]]})
    assert sum(r['weight'] for r in rows) == 4*d*d
    return rows, 4*d*d


def marginals(rows, denominator):
    out = []
    for i in range(2):
        marginal = defaultdict(int)
        for row in rows:
            marginal[tuple(d[i] for d in row['demand'])] += row['weight']
        out.append({k: Fraction(v, denominator) for k, v in marginal.items()})
    return out


def cost(cfg, first, second, demand):
    """Integer net-stock ledger, with arrivals preceding each period's demand."""
    net = cfg['initial_inventory'].copy()
    arrivals = [[0, 0] for _ in range(3)]
    total = 0
    for t, action in enumerate((first, second, ZERO)):
        for i in range(2):
            net[i] += arrivals[t][i] - demand[t][i]
            total += max(net[i], 0)*cfg['holding'][i]
            total += max(-net[i], 0)*(cfg['backlog'][i] +
                                      (cfg['terminal_backlog'][i] if t == 2 else 0))
            for j, lead in enumerate(cfg['lead']):
                q = action[2*i+j]
                if t+lead >= 3 and q:
                    raise ValueError('late_arrival')
                if t+lead < 3:
                    arrivals[t+lead][i] += q
                total += q*cfg['freight'][j]
    return total


def public(cfg, capacity, budget):
    return {**{k: cfg[k] for k in ('lead', 'freight', 'emissions', 'holding',
                                  'backlog', 'terminal_backlog', 'initial_inventory')},
            'mass': [1, 1], 'carbon_price': 0, 'carbon_budget': budget,
            'periods': 3, 'horizon': 3, 'scenarios': 1, 'forecast_alpha': .35,
            'scenario_seed': 0, 'base_mean': [1, 1],
            'initial_pipeline': [[0, 0] for _ in range(3)],
            'capacity': [cfg['slow_capacity'], capacity]}


def optimize(cfg, capacity, budget, coupling, accuracy):
    rows, denominator = leaves(coupling, accuracy, cfg['high_terminal_demand'])
    groups = defaultdict(list)
    for k, row in enumerate(rows):
        groups[tuple(row['signal'])].append(k)
    histories = sorted(groups)
    weights = [r['weight'] for r in rows]
    firsts = actions(cfg, capacity, budget, 0)
    candidates = []
    clairvoyant = [None] * len(rows)
    evaluation_count = 0
    for first in firsts:
        seconds = actions(cfg, capacity, budget-emission(first, cfg), 1)
        values = {second: [cost(cfg, first, second, r['demand']) for r in rows]
                  for second in seconds}
        evaluation_count += len(seconds)*len(rows)
        open_value, open_second = min((sum(w*c for w, c in zip(weights, cs)), second)
                                      for second, cs in values.items())
        chosen, recourse_value = {}, 0
        for history in histories:
            indices = groups[history]
            value, second = min((sum(weights[k]*cs[k] for k in indices), second)
                                for second, cs in values.items())
            chosen[history] = second
            recourse_value += value
        candidates.append((first, open_value, recourse_value, open_second, chosen))
        for k in range(len(rows)):
            best = min((cs[k], first, second) for second, cs in values.items())
            if clairvoyant[k] is None or best < clairvoyant[k]:
                clairvoyant[k] = best
    open_best = min(candidates, key=lambda x: (x[1], x[0]))
    recourse_best = min(candidates, key=lambda x: (x[2], x[0]))
    tied = [x for x in candidates if x[1] == open_best[1]]
    best_open_tie = min(tied, key=lambda x: (x[2], x[0]))
    methods = {}
    for name, best in [('open_loop', open_best), ('rolling_open_loop', open_best),
                       ('rolling_best_open_tie', best_open_tie),
                       ('history_recourse', recourse_best)]:
        first, _, _, open_second, chosen = best
        nodes = {h: open_second if name == 'open_loop' else chosen[h] for h in histories}
        leaf_costs = [cost(cfg, first, nodes[tuple(r['signal'])], r['demand']) for r in rows]
        numerator = sum(w*c for w, c in zip(weights, leaf_costs))
        methods[name] = {'first': list(first),
                         'nodes': [{'history': list(h), 'second': list(nodes[h])} for h in histories],
                         'leaf_costs': leaf_costs, 'cost_numerator': numerator,
                         'expected_cost': numerator/denominator}
    methods['perfect_information'] = {
        'leaf_first': [list(x[1]) for x in clairvoyant],
        'leaf_second': [list(x[2]) for x in clairvoyant],
        'leaf_costs': [x[0] for x in clairvoyant],
        'cost_numerator': sum(w*x[0] for w, x in zip(weights, clairvoyant))}
    methods['perfect_information']['expected_cost'] = methods['perfect_information']['cost_numerator']/denominator
    order = [methods[n]['cost_numerator'] for n in
             ('perfect_information', 'history_recourse', 'rolling_best_open_tie',
              'rolling_open_loop', 'open_loop')]
    if order != sorted(order):
        raise ValueError('information_value_order')
    return {'fast_capacity': capacity, 'carbon_budget': budget, 'coupling': coupling,
            'signal_accuracy': accuracy, 'leaves': rows, 'probability_denominator': denominator,
            'methods': methods, 'candidate_first_actions': len(firsts),
            'path_cost_evaluations': evaluation_count,
            'rolling_cost_range_across_open_optima':
                [min(x[2] for x in tied)/denominator, max(x[2] for x in tied)/denominator],
            'open_loop_optimal_first_actions': [list(x[0]) for x in candidates if x[1] == open_best[1]],
            'recourse_optimal_first_actions': [list(x[0]) for x in candidates if x[2] == recourse_best[2]]}


def audit_physics(cfg, result, check_milp=True):
    """Independent simulator replay; only the evaluator reads future leaves."""
    from rolling_inventory.environment import Environment
    from rolling_sensitivity.planning import solve
    import numpy as np
    p = public(cfg, result['fast_capacity'], result['carbon_budget'])
    for name, method in result['methods'].items():
        nodes = {tuple(n['history']): n['second'] for n in method.get('nodes', [])}
        for k, leaf in enumerate(result['leaves']):
            env = Environment({'public': p, 'demand': leaf['demand']})
            # A deployable policy dispatches before any demand is revealed.
            first = method['leaf_first'][k] if name == 'perfect_information' else method['first']
            ledger = [env.step(matrix(first))]
            observed = tuple(env.observe()['history'][0])
            second = method['leaf_second'][k] if name == 'perfect_information' else nodes[observed]
            ledger.append(env.step(matrix(second)))
            ledger.append(env.step(matrix(ZERO)))
            if sum(r['cost'] for r in ledger) != method['leaf_costs'][k]:
                raise ValueError('physical_replay_cost')
            if any(any(v) for v in env.pipeline.tolist()):
                raise ValueError('unfinished_pipeline')
    if check_milp:
        obs = Environment({'public': p, 'demand': result['leaves'][0]['demand']}).observe()
        # Repetition converts exact rational probability masses to equal weights.
        ensemble = [r['demand'] for r in result['leaves'] for _ in range(r['weight'])]
        _, info = solve(obs, np.asarray(ensemble), allocation='free', terminal_fraction=0.)
        if abs(info['objective'] - result['methods']['open_loop']['expected_cost']) > 1e-7:
            raise ValueError('enumeration_MILP_mismatch')


def run(cfg=None):
    cfg = cfg or configuration()
    results = []
    cross_evaluations = []
    for capacity, budget, accuracy in product(cfg['fast_capacities'], cfg['carbon_budgets'],
                                             cfg['signal_accuracies']):
        reference, objective = None, None
        family = []
        for coupling in cfg['couplings']:
            result = optimize(cfg, capacity, budget, coupling, accuracy)
            audit_physics(cfg, result)
            marginal = marginals(result['leaves'], result['probability_denominator'])
            value = result['methods']['open_loop']['cost_numerator']
            if reference is not None and (reference != marginal or objective != value):
                raise ValueError('fixed_marginal_invariance')
            reference, objective = marginal, value
            results.append(result)
            family.append(result)
        # A change in optimal expected value alone need not change the policy.
        # Score each coupling's selected policy under every other joint model.
        for trained, truth in product(family, repeat=2):
            policy = trained['methods']['history_recourse']
            nodes = {tuple(n['history']): n['second'] for n in policy['nodes']}
            numerator = sum(r['weight']*cost(cfg, policy['first'], nodes[tuple(r['signal'])],
                                             r['demand']) for r in truth['leaves'])
            optimal = truth['methods']['history_recourse']['cost_numerator']
            if numerator < optimal:
                raise ValueError('cross_evaluation_below_exact_optimum')
            cross_evaluations.append({'fast_capacity': capacity, 'carbon_budget': budget,
                'signal_accuracy': accuracy, 'policy_coupling': trained['coupling'],
                'evaluation_coupling': truth['coupling'], 'cost_numerator': numerator,
                'optimal_cost_numerator': optimal, 'denominator': truth['probability_denominator'],
                'regret': (numerator-optimal)/truth['probability_denominator']})
    gains = [r['methods']['rolling_open_loop']['cost_numerator'] -
             r['methods']['history_recourse']['cost_numerator'] for r in results]
    summary = {'finite_models': len(results), 'independent_test_paths': 0,
               'strict_recourse_improvements_over_rolling': sum(g > 0 for g in gains),
               'equal_recourse_and_rolling': sum(g == 0 for g in gains),
               'worse_recourse_than_rolling': sum(g < 0 for g in gains),
               'strict_improvements_over_best_open_tie': sum(
                   r['methods']['history_recourse']['cost_numerator'] <
                   r['methods']['rolling_best_open_tie']['cost_numerator'] for r in results),
               'cross_coupling_evaluations': len(cross_evaluations),
               'mismatched_coupling_evaluations': sum(x['policy_coupling'] !=
                                                    x['evaluation_coupling'] for x in cross_evaluations),
               'positive_misspecification_regrets': sum(x['regret'] > 0 for x in cross_evaluations),
               'physics_replayed_leaf_episodes': sum(len(r['leaves'])*5 for r in results),
               'open_loop_MILP_crosschecks': len(results), 'learning_trained': False,
               'new_heldout_confirmation': False, 'teacher_for_original_rolling_environment': False}
    return {'schema': cfg['schema'], 'scope': cfg['scope'], 'config': cfg,
            'summary': summary, 'models': results, 'cross_coupling': cross_evaluations}


def identity():
    paths = ['rolling_recourse/__init__.py', 'rolling_recourse/__main__.py',
             'rolling_recourse/config.json', 'rolling_recourse/experiment.py',
             'docs/rolling_recourse_protocol.md', 'rolling_inventory/environment.py',
             'rolling_inventory/planning.py', 'rolling_sensitivity/planning.py']
    return {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}


def write(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('output_must_be_empty')
    result = run()
    data = (json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
    (output / 'results.json').write_bytes(data)
    (output / 'manifest.json').write_text(json.dumps({
        'sources': identity(), 'files': {'results.json': sha256(data).hexdigest()}}, indent=2)+'\n')
    return result['summary']


def verify(output):
    output = Path(output)
    if {p.name for p in output.iterdir()} != {'results.json', 'manifest.json'}:
        raise ValueError('artifact_coverage')
    if any(p.is_symlink() or not p.is_file() for p in output.iterdir()):
        raise ValueError('regular_files_required')
    manifest = json.loads((output / 'manifest.json').read_text())
    data = (output / 'results.json').read_bytes()
    if manifest != {'sources': identity(), 'files': {'results.json': sha256(data).hexdigest()}}:
        raise ValueError('source_or_artifact_identity')
    actual = json.loads(data)
    if actual != run():
        raise ValueError('full_policy_reexecution_mismatch')
    return {'verified': True, **actual['summary']}
