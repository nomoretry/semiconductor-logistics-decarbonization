"""Select a first action using its mean objective across three trees."""

from math import fsum

from .planning import tolerance
from .stability import _duration


def _mean(values):
    return fsum(values) / len(values) if all(value is not None for value in values) else None


def _fixed_value(evaluator, seed, tier, action):
    solution = evaluator.call(seed, tier, action)
    return None if solution is None else solution['value']


def decide(seeds, tier, evaluator):
    """Generate three first actions and score each distinct action once per tree."""
    free = [evaluator.call(seed, tier) for seed in seeds]
    decision = {'action': None, 'selected_seed': None, 'mean_value': None, 'actions': []}
    if any(solution is None for solution in free):
        return decision

    distinct = {}
    for seed, solution in zip(seeds, free):
        action = solution['action']
        key = tuple(tuple(route_quantities) for route_quantities in action)
        if key not in distinct:
            distinct[key] = (action, {})
        distinct[key][1][seed] = solution['value']

    for action, own_values in distinct.values():
        values = [
            own_values[seed] if seed in own_values else _fixed_value(evaluator, seed, tier, action)
            for seed in seeds
        ]
        decision['actions'].append({
            'action': action, 'origin_seeds': list(own_values), 'values': values, 'mean_value': _mean(values),
        })

    # An unresolved score could change the ranking, so leave the decision unassessed.
    if all(action['mean_value'] is not None for action in decision['actions']):
        selected = min(decision['actions'], key=lambda action: action['mean_value'])
        decision.update(action=selected['action'], selected_seed=selected['origin_seeds'][0],
                        mean_value=selected['mean_value'])
    return decision


def _compare(source, target, target_seeds, target_tier, rule, evaluator):
    result = {
        'changed': None, 'material': None, 'target_tree_values': None,
        'source_on_target_mean': None, 'target_mean': target['mean_value'], 'excess': None, 'tolerance': None,
    }
    if source['action'] is None or target['action'] is None:
        return result

    action = source['action']
    result['changed'] = action != target['action']
    local = next((entry for entry in target['actions'] if entry['action'] == action), None)
    if local is not None:
        values = local['values']
    else:
        values = [_fixed_value(evaluator, seed, target_tier, action) for seed in target_seeds]
    mean = _mean(values)
    limit = tolerance(target['mean_value'], rule)
    result.update(target_tree_values=values, source_on_target_mean=mean, tolerance=limit)
    if mean is not None:
        excess = mean - target['mean_value']
        result.update(excess=excess, material=excess > limit)
    return result


def analyze(key, archived, config, evaluator):
    """Run the four decisions and assess material changes on the target trees."""
    path, t = key
    lower, higher = config['tiers']
    groups = config['groups']
    decisions = {}
    for group in ('a', 'b'):
        for tier in config['tiers']:
            seeds = groups[group]
            label = f'{group}:{tier}'
            decision, seconds = evaluator.timed(label, lambda: decide(seeds, tier, evaluator))
            decisions[label] = dict(decision, online_seconds=seconds)

    a_lower, a_higher, b_higher = (decisions[label] for label in (f'a:{lower}', f'a:{higher}', f'b:{higher}'))
    rule = config['tie_tolerance']
    comparisons = {
        'across_groups': _compare(a_higher, b_higher, groups['b'], higher, rule, evaluator),
        'across_tiers': _compare(a_lower, a_higher, groups['a'], higher, rule, evaluator),
    }
    return {'path': path, 't': t, 'decisions': decisions, 'comparisons': comparisons}


def _comparison_summary(comparisons, expected):
    comparable = sum(row['changed'] is not None for row in comparisons)
    changed = sum(row['changed'] is True for row in comparisons)
    material_comparable = sum(row['material'] is not None for row in comparisons)
    material = sum(row['material'] is True for row in comparisons)
    return {
        'expected': expected, 'comparable': comparable, 'missing': expected-comparable, 'changed': changed,
        'change_rate': changed/comparable if comparable else None,
        'material_comparable': material_comparable, 'material_missing': expected-material_comparable,
        'material': material, 'material_rate': material/material_comparable if material_comparable else None,
    }


def summary(results, config):
    """Recompute decisions' timing distributions and both change-rate gates."""
    expected = config['observations']
    comparisons = {
        key: _comparison_summary([row['comparisons'][key] for row in results], expected)
        for key in ('across_groups', 'across_tiers')
    }
    gates = {}
    for key, row in comparisons.items():
        rate = row['change_rate']
        gates[key] = rate <= config['max_action_change_rate'] if rate is not None else None
    conclusion = 'unassessed'
    if len(results) == expected and all(passed is not None for passed in gates.values()):
        conclusion = 'stable' if all(gates.values()) else 'unstable'

    online = {}
    for tier in config['tiers']:
        by_group = {}
        tier_times = []
        for group in ('a', 'b'):
            decisions = [row['decisions'][f'{group}:{tier}'] for row in results]
            times = [decision['online_seconds'] for decision in decisions]
            tier_times.extend(times)
            by_group[group] = {'count': len(times), 'seconds': _duration(times)}
        online[str(tier)] = {'count': len(tier_times), 'seconds': _duration(tier_times), 'by_group': by_group}
    return {'observations': len(results), 'comparisons': comparisons, 'gates': gates, 'conclusion': conclusion,
            'online_seconds': online}
