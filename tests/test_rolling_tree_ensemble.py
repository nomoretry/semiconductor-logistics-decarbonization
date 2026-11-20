import unittest

from rolling_tree import ensemble


class FakeEvaluator:
    """Value lookup with a record of calls and per-decision timing boundaries."""

    def __init__(self, free, fixed):
        self.free = free
        self.fixed = fixed
        self.calls = []
        self.timing = []

    def call(self, seed, tier, action=None):
        if action is None:
            self.calls.append((seed, tier, None))
            return self.free[seed, tier]
        units = action[0][0]
        self.calls.append((seed, tier, units))
        value = self.fixed[seed, tier, units]
        return None if value is None else {'action': action, 'value': value}

    def timed(self, label, fn):
        before = len(self.calls)
        result = fn()
        solves = len(self.calls)-before
        self.timing.append((label, solves))
        return result, float(solves)


class EnsembleTests(unittest.TestCase):
    def test_reuse_every_origins_value_and_break_exact_ties_by_seed_order(self):
        seeds = [99101, 99107, 99109]
        first, second = [[1, 0]], [[2, 0]]
        evaluator = FakeEvaluator({
            (99101, 12): {'action': first, 'value': 1.0},
            (99107, 12): {'action': first, 'value': 3.0},
            (99109, 12): {'action': second, 'value': 2.0},
        }, {(99109, 12, 1): 5.0, (99101, 12, 2): 2.0, (99107, 12, 2): 5.0})
        decision = ensemble.decide(seeds, 12, evaluator)
        self.assertEqual(decision['action'], first)
        self.assertEqual(decision['selected_seed'], seeds[0])
        self.assertEqual(decision['mean_value'], 3.0)
        self.assertEqual(len(evaluator.calls), 6)
        self.assertEqual(decision['actions'][0]['origin_seeds'], seeds[:2])

    def test_unknown_score_makes_the_decision_unassessed_without_retry(self):
        seeds = [99101, 99107, 99109]
        first, second = [[1, 0]], [[2, 0]]
        evaluator = FakeEvaluator({
            (99101, 3): {'action': first, 'value': 1.0},
            (99107, 3): {'action': first, 'value': 3.0},
            (99109, 3): {'action': second, 'value': 2.0},
        }, {(99109, 3, 1): None, (99101, 3, 2): 2.0, (99107, 3, 2): 5.0})
        decision = ensemble.decide(seeds, 3, evaluator)
        self.assertIsNone(decision['action'])
        self.assertIsNone(decision['actions'][0]['mean_value'])
        self.assertEqual(evaluator.calls.count((99109, 3, 1)), 1)

    def test_materiality_uses_target_trees_and_audits_are_outside_timings(self):
        groups = {'a': [99101, 99107, 99109], 'b': [99131, 99133, 99137]}
        config = {'groups': groups, 'tiers': [3, 12], 'observations': 1,
                  'max_action_change_rate': 0.1, 'tie_tolerance': {'relative': 1e-6, 'absolute': 1e-7}}
        quantities = {('a', 3): 2, ('a', 12): 1, ('b', 3): 3, ('b', 12): 3}
        free = {
            (seed, tier): {'action': [[quantities[group, tier], 0]], 'value': 10.0}
            for group, seeds in groups.items() for tier in config['tiers'] for seed in seeds
        }
        fixed = dict.fromkeys(((seed, 12, 1) for seed in groups['b']), 10.1)
        fixed.update(dict.fromkeys(((seed, 12, 2) for seed in groups['a']), 10.0000001))
        evaluator = FakeEvaluator(free, fixed)
        row = ensemble.analyze(('test', 0), {}, config, evaluator)
        self.assertEqual(evaluator.timing, [('a:3', 3), ('a:12', 3), ('b:3', 3), ('b:12', 3)])
        self.assertEqual(len(evaluator.calls), 18)
        compared = row['comparisons']
        self.assertTrue(compared['across_groups']['material'])
        self.assertFalse(compared['across_tiers']['material'])
        self.assertAlmostEqual(compared['across_groups']['excess'], 0.1)
        result = ensemble.summary([row], config)
        self.assertEqual(result['conclusion'], 'unstable')
        self.assertEqual(result['comparisons']['across_groups']['material_rate'], 1.0)
        self.assertEqual(result['comparisons']['across_tiers']['change_rate'], 1.0)
        self.assertEqual(result['comparisons']['across_tiers']['material_rate'], 0.0)
        self.assertEqual(result['online_seconds']['12']['seconds']['p95'], 3.0)

    def test_exact_gate_limit_passes_and_missing_audits_have_their_own_denominator(self):
        config = {'tiers': [3, 12], 'observations': 10, 'max_action_change_rate': 0.1}
        decisions = {label: {'online_seconds': 1.0} for label in ('a:3', 'a:12', 'b:3', 'b:12')}
        same = {'changed': False, 'material': False}
        rows = [
            {'decisions': decisions, 'comparisons': {'across_groups': same, 'across_tiers': same}}
            for _ in range(9)
        ]
        rows.append({'decisions': decisions, 'comparisons': {
            'across_groups': {'changed': True, 'material': None},
            'across_tiers': {'changed': True, 'material': True},
        }})

        result = ensemble.summary(rows, config)
        self.assertEqual(result['conclusion'], 'stable')
        self.assertEqual(result['comparisons']['across_groups']['change_rate'], 0.1)
        self.assertEqual(result['comparisons']['across_groups']['material_comparable'], 9)
        self.assertEqual(result['comparisons']['across_groups']['material_missing'], 1)
        self.assertEqual(ensemble.summary(rows[:-1], config)['conclusion'], 'unassessed')


if __name__ == '__main__':
    unittest.main()
