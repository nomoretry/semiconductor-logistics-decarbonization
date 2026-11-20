"""Cross-evaluate the changed actions in the archived first-action stability run."""
from itertools import combinations

import numpy as np

from .planning import tolerance


def _direction(evaluator, action, seed, tier, rule):
    reference = evaluator.call(seed, tier)
    fixed = evaluator.call(seed, tier, action)
    optimum = None if reference is None else reference['value']
    fixed_value = None if fixed is None else fixed['value']
    excess = ratio = material = None
    if optimum is not None and fixed_value is not None:
        excess = fixed_value-optimum
        threshold = tolerance(optimum, rule)
        if excess < -threshold:
            raise ValueError(f'fixed_objective_below_optimum:{seed}:{tier}')
        ratio = excess/abs(optimum) if optimum != 0 else None
        material = excess > threshold
    return {'target_seed': seed, 'target_tier': tier, 'action': action, 'optimum': optimum,
            'fixed_value': fixed_value, 'excess': excess, 'relative_excess': ratio,
            'material': material}


def _either(forward, reverse):
    """An observed excess can establish materiality even if the other solve failed."""
    if forward is True or reverse is True:
        return True
    if forward is False and reverse is False:
        return False
    return None


def analyze(key, archived, config, evaluator):
    """Evaluate only archived changes. Both directions refer to their own target tree."""
    path, t = key
    low, high = config['tiers']
    seeds = config['groups']['a']
    rule = config['tie_tolerance']
    actions = {(seed, tier): archived[path, t, seed, tier]['action']
               for seed in seeds for tier in (low, high)}
    tier_changes = []
    for seed in seeds:
        small, large = actions[seed, low], actions[seed, high]
        if small != large:
            forward = _direction(evaluator, small, seed, high, rule)
            reverse = _direction(evaluator, large, seed, low, rule)
            tier_changes.append({'seed': seed, 'forward': forward, 'reverse': reverse,
                                 'material': forward['material']})

    seed_changes = []
    for left, right in combinations(seeds, 2):
        first, second = actions[left, high], actions[right, high]
        if first != second:
            forward = _direction(evaluator, first, right, high, rule)
            reverse = _direction(evaluator, second, left, high, rule)
            seed_changes.append({'seeds': [left, right], 'forward': forward, 'reverse': reverse,
                                 'material': _either(forward['material'], reverse['material'])})
    return {'path': path, 't': t, 'tier_changes': tier_changes, 'seed_changes': seed_changes}


def _distribution(values):
    if not values:
        return {'count': 0, 'median': None, 'p90': None, 'max': None}
    return {'count': len(values), 'median': float(np.median(values)),
            'p90': float(np.quantile(values, .90)), 'max': max(values)}


def _direction_summary(directions):
    excesses = [d['excess'] for d in directions if d['excess'] is not None]
    ratios = [d['relative_excess'] for d in directions if d['relative_excess'] is not None]
    return {'planned': len(directions), 'resolved': len(excesses),
            'excess': _distribution(excesses), 'relative_excess': _distribution(ratios),
            'above_half_percent': sum(ratio > .005 for ratio in ratios),
            'material': sum(d['material'] is True for d in directions)}


def _above_half_percent(direction):
    ratio = direction['relative_excess']
    return None if ratio is None else ratio > .005


def _group(results, changes_key, comparisons, two_way):
    changes = [change for row in results for change in row[changes_key]]
    resolved = sum(change['material'] is not None for change in changes)
    material = sum(change['material'] is True for change in changes)
    forward = [change['forward'] for change in changes]
    reverse = [change['reverse'] for change in changes]

    above = [_either(_above_half_percent(fwd), _above_half_percent(rev)) if two_way
             else _above_half_percent(fwd) for fwd, rev in zip(forward, reverse)]
    unresolved = len(changes)-resolved
    comparable = comparisons-unresolved
    return {
        'archived_comparisons': comparisons, 'archived_changed': len(changes),
        'resolved_changes': resolved, 'unresolved_changes': unresolved,
        'material_changes': material,
        'material_share_of_changes': material/resolved if resolved else None,
        'material_change_rate': material/comparable if comparable else None,
        'above_half_percent_pairs': sum(flag is True for flag in above),
        'half_percent_resolved_pairs': sum(flag is not None for flag in above),
        'forward': _direction_summary(forward), 'reverse': _direction_summary(reverse),
        'both_directions': _direction_summary(forward+reverse),
    }


def summary(results, config):
    """Summarize raw directions and distinguish changed pairs from evaluated directions."""
    count = len(config['groups']['a'])
    return {'observations': len(results),
            'across_tiers': _group(results, 'tier_changes', len(results)*count, two_way=False),
            'across_seeds': _group(results, 'seed_changes', len(results)*count*(count-1)//2, two_way=True)}
