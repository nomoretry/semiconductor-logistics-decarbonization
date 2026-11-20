"""Unit tests for the two first-action materiality comparisons."""
import unittest

from rolling_tree import materiality


KEY = ('test-stable', 0)
FIRST = [[1, 0], [0, 0], [0, 0]]
SECOND = [[0, 0], [1, 0], [0, 0]]
RULE = {'relative': 1e-6, 'absolute': 1e-7}


def action_key(action):
    return None if action is None else tuple(tuple(row) for row in action)


class StoredValues:
    def __init__(self, entries):
        self.values = {(seed, tier, action_key(action)): value for seed, tier, action, value in entries}

    def call(self, seed, tier, action=None):
        value = self.values[seed, tier, action_key(action)]
        return None if value is None else {'action': action, 'value': value}


def archived_rows(*entries):
    path, t = KEY
    return {(path, t, seed, tier): {'action': action} for seed, tier, action in entries}


class MaterialityTests(unittest.TestCase):
    def setUp(self):
        self.config = {'groups': {'a': [41, 43, 47]}, 'tiers': [3, 12], 'tie_tolerance': RULE}

    def test_tier_change_uses_gap_on_the_larger_tree(self):
        archived = archived_rows((41, 3, SECOND), (41, 12, FIRST),
                                 (43, 3, FIRST), (43, 12, FIRST),
                                 (47, 3, FIRST), (47, 12, FIRST))
        evaluator = StoredValues([(41, 12, None, 100.), (41, 12, SECOND, 100.00001),
                                  (41, 3, None, 100.), (41, 3, FIRST, 101.)])
        result = materiality.analyze(KEY, archived, self.config, evaluator)
        change, = result['tier_changes']
        self.assertFalse(change['material'])
        self.assertTrue(change['reverse']['material'])
        self.assertEqual(change['forward']['target_tier'], 12)
        self.assertEqual(change['reverse']['target_tier'], 3)
        self.assertEqual(result['seed_changes'], [])
        summary = materiality.summary([result], self.config)['across_tiers']
        self.assertEqual(summary['archived_comparisons'], 3)
        self.assertEqual(summary['archived_changed'], 1)
        self.assertEqual(summary['material_changes'], 0)
        self.assertEqual(summary['above_half_percent_pairs'], 0)
        self.assertEqual(summary['reverse']['above_half_percent'], 1)
        self.assertAlmostEqual(summary['reverse']['relative_excess']['median'], .01)
        self.assertAlmostEqual(summary['both_directions']['excess']['p90'], .900001)

    def test_seed_change_can_be_material_with_one_solved_direction(self):
        archived = archived_rows((41, 3, FIRST), (41, 12, FIRST),
                                 (43, 3, SECOND), (43, 12, SECOND),
                                 (47, 3, SECOND), (47, 12, SECOND))
        evaluator = StoredValues([(41, 12, None, 100.), (41, 12, SECOND, None),
                                  (43, 12, None, 100.), (43, 12, FIRST, 101.),
                                  (47, 12, None, 100.), (47, 12, FIRST, 100.00001)])
        result = materiality.analyze(KEY, archived, self.config, evaluator)
        left, right = result['seed_changes']
        self.assertEqual(left['seeds'], [41, 43])
        self.assertTrue(left['material'])
        self.assertIsNone(right['material'])
        summary = materiality.summary([result], self.config)['across_seeds']
        self.assertEqual(summary['archived_comparisons'], 3)
        self.assertEqual(summary['archived_changed'], 2)
        self.assertEqual(summary['resolved_changes'], 1)
        self.assertEqual(summary['unresolved_changes'], 1)
        self.assertEqual(summary['material_changes'], 1)
        self.assertEqual(summary['material_share_of_changes'], 1.)
        self.assertEqual(summary['material_change_rate'], .5)
        self.assertEqual(summary['above_half_percent_pairs'], 1)
        self.assertEqual(summary['reverse']['excess']['count'], 0)
        self.assertEqual(summary['both_directions']['excess']['max'], 1.)

    def test_zero_window_reference_has_no_relative_excess(self):
        evaluator = StoredValues([(41, 12, None, 0.), (41, 12, SECOND, 1.)])
        direction = materiality._direction(evaluator, SECOND, 41, 12, RULE)
        self.assertEqual(direction['excess'], 1.)
        self.assertIsNone(direction['relative_excess'])
        self.assertTrue(direction['material'])

    def test_fixed_value_below_unrestricted_optimum_fails_outside_roundoff(self):
        evaluator = StoredValues([(41, 12, None, 100.), (41, 12, SECOND, 99.)])
        with self.assertRaisesRegex(ValueError, 'fixed_objective_below_optimum'):
            materiality._direction(evaluator, SECOND, 41, 12, RULE)


if __name__ == '__main__':
    unittest.main()
