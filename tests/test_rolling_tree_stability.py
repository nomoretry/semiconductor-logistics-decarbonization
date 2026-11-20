"""Unit and offline replay tests for M1 first-action stability."""
from itertools import product
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rolling_inventory.environment import Environment, generate
from rolling_tree import stability
from rolling_tree.experiment import base_configuration, read_lines, write_json, write_lines
from rolling_tree.experiment_v2 import configuration


TEST_SEED = 99051
SAMPLER_SEEDS = [99061, 99067, 99071]


def write_test_pilot(pilot):
    """Two non-forced B1 observations in the test namespace."""
    pilot.mkdir()
    base = dict(base_configuration(), periods=3, horizon=3, profiles=['stable'])
    task, = generate(base, 'test', [TEST_SEED])
    env = Environment(task)
    zero = [[0, 0], [0, 0], [0, 0]]
    rows = [env.step(zero) for _ in range(base['periods'])]
    audits = [{'path': task['id'], 't': t, 'sampler_seed': seed, 'forced_zero': t == 2}
              for t, seed in product(range(base['periods']), SAMPLER_SEEDS)]
    cfg = dict(configuration(), sampler_seeds=SAMPLER_SEEDS,
               pilot={'split': 'test', 'seed': TEST_SEED, 'profiles': ['stable']})
    selected = {'shape': {'branching': [2, 2], 'continuation': 1}, 'prior_strength': 192}
    write_json(pilot/'config.json', {'rolling_tree_v2': cfg, 'selection': selected})
    write_json(pilot/'summary.json', {'fit': {'fitted_variance': .08}})
    write_json(pilot/'tasks.json', [task])
    write_lines(pilot/'traces.jsonl', [{'id': task['id'], 'method': 'B1', 'rows': rows}])
    write_lines(pilot/'audit.jsonl', audits)
    write_json(pilot/'manifest.json', stability._hashes(pilot, stability.SOURCE_FILES))


class StabilityTests(unittest.TestCase):
    def test_change_rates_count_complete_pairs_and_report_quantity_differences(self):
        zero = [[0, 0], [0, 0], [0, 0]]
        shifted = [[1, 0], [0, 2], [0, 0]]
        result = stability._comparison([
            ('stable', 0, zero, shifted),
            ('stable', 1, zero, zero),
            ('volatile', 0, shifted, None),
        ])
        self.assertEqual((result['changed'], result['comparable'], result['missing']), (1, 2, 1))
        self.assertEqual(result['change_rate'], .5)
        self.assertEqual(result['by_period']['0']['change_rate'], 1.)
        self.assertIsNone(result['by_profile']['volatile']['change_rate'])
        self.assertEqual(result['by_sku_route'][0],
                         {'sku': 1, 'route': 'slow', 'changed_pairs': 1, 'absolute_units': 1})
        self.assertEqual(result['by_sku_route'][3],
                         {'sku': 2, 'route': 'fast', 'changed_pairs': 1, 'absolute_units': 2})

    def test_selection_uses_largest_tier_within_time_and_checks_formal_budget(self):
        cfg = {'reference_tiers': [1, 3], 'larger_tiers': [6, 9, 12], 'audit_states': 132,
               'online_p95_limit_seconds': 10., 'start_guard_seconds': 45, 'max_formal_wall_seconds': 3600}
        timing = {str(tier): {'online_seconds': {'p95': seconds}}
                  for tier, seconds in zip((1, 3, 6, 9, 12), (1., 2., 4., 10., 11.))}
        self.assertEqual(stability._select(cfg, timing), {
            'tier': 9, 'estimated_formal_wall_seconds': 1761., 'stop_reason': None})
        timing['1']['online_seconds']['p95'] = 16.
        self.assertEqual(stability._select(cfg, timing)['stop_reason'], 'estimated_formal_wall_above_budget')
        timing['6']['online_seconds']['p95'] = timing['9']['online_seconds']['p95'] = 11.
        self.assertEqual(stability._select(cfg, timing)['stop_reason'], 'no_tier_within_online_p95')

    def test_formal_failure_stop_is_strictly_above_five_percent(self):
        config = {'max_failure_rate': .05, 'max_formal_wall_seconds': 3600., 'start_guard_seconds': 45.}
        attempts = [{'action': [[0, 0]]} for _ in range(19)] + [{'action': None} for _ in range(3)]
        with tempfile.TemporaryDirectory() as folder, patch.object(stability, '_attempt', side_effect=attempts):
            ledger = Path(folder)/'formal.jsonl'
            rows, _ = stability._run_phase(ledger, range(22), {}, config, None, formal=True)
            self.assertEqual(len(rows), 21)
            self.assertEqual(rows, read_lines(ledger))

    def test_small_m1_run_and_verification_without_solving(self):
        with tempfile.TemporaryDirectory() as folder:
            pilot, out = Path(folder)/'pilot', Path(folder)/'stability'
            write_test_pilot(pilot)
            summary = stability.run(out, pilot)
            self.assertIsNone(summary['stop_reason'])
            self.assertEqual(summary['selection']['tier'], 12)
            self.assertEqual(summary['timing']['attempts'], 15)
            self.assertEqual(summary['formal']['attempts'], 18)
            self.assertEqual(summary['formal']['failures'], 0)
            self.assertEqual(summary['across_tiers']['3_to_12']['comparable'], 6)
            self.assertEqual(summary['across_seeds']['12']['comparable'], 6)
            with patch.object(stability, 'solve', side_effect=AssertionError('verification must not solve')):
                self.assertEqual(stability.verify(out, pilot), {
                    'files': 5, 'timing_attempts': 15, 'formal_attempts': 18, 'trees_regenerated': 33, 'solves_run': 0})
                summary['formal']['attempts'] = 19
                write_json(out/'summary.json', summary)
                with self.assertRaisesRegex(ValueError, 'stability_evidence_hash'):
                    stability.verify(out, pilot)
                write_json(out/'manifest.json', stability._hashes(out, stability.EVIDENCE_FILES))
                with self.assertRaisesRegex(ValueError, 'stability_summary_changed'):
                    stability.verify(out, pilot)


if __name__ == '__main__':
    unittest.main()
