"""Budget and offline solve replay in the two-stage experiment."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rolling_inventory.environment import Environment, generate
from rolling_tree import consensus
from rolling_tree.experiment import base_configuration, write_lines


class ConsensusRunnerTests(unittest.TestCase):
    def test_shared_failure_budget_stops_strictly_above_five_percent(self):
        config = {'max_wall_seconds': 5400., 'start_guard_seconds': 45., 'max_failure_rate': .05}
        budget = consensus.Budget(config, None)
        for _ in range(19):
            budget.record(False)
        budget.record(True)
        budget.check()
        budget.record(True)
        with self.assertRaisesRegex(consensus.BudgetReached, 'formal_failure_rate_above_limit'):
            budget.check()

    def test_fixed_and_free_solves_replay_with_the_same_tree(self):
        base = dict(base_configuration(), periods=3, horizon=3, profiles=['stable'])
        task, = generate(base, 'test', [99081])
        env = Environment(task)
        config = {'single_tree_config': {'fitted_variance': .08, 'prior_strength': 192, 'variance_cap': 2.,
                                        'branching': [2, 2], 'paced_carbon': True,
                                        'solver': {'time_limit_seconds': 30.}}}
        key = (task['id'], 0)
        obs = env.observe()
        live = consensus.Evaluation(key, obs, config, {})
        free = live.call(99087, 3)
        fixed = live.call(99087, 3, free['action'])
        self.assertIs(live.call(99087, 3, free['action']), fixed)
        self.assertEqual(len(live.calls), 2)
        self.assertAlmostEqual(free['value'], fixed['value'])
        result = {'calls': live.calls, 'timings': {}, 'result': fixed}
        with patch.object(consensus, 'solve', side_effect=AssertionError('unexpected solve')), \
                patch.object(consensus, 'solve_fixed_first', side_effect=AssertionError('unexpected fixed solve')):
            replay = consensus.Evaluation(key, obs, config, {}, replay=result)
            self.assertEqual(replay.call(99087, 3), free)
            self.assertEqual(replay.call(99087, 3, free['action']), fixed)
            self.assertEqual(replay.calls, live.calls)
            replay = consensus.Evaluation(key, obs, config, {}, replay=result)
            with self.assertRaisesRegex(ValueError, 'solve_record_alignment'):
                replay.call(99087, 12)

    def test_only_amended_budget_binds_amendment(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'amendment.md'
            with patch.object(consensus, 'AMENDMENT', path):
                original, _, _ = consensus._inputs()
                self.assertEqual(original['max_wall_seconds'], 5400.0)
                self.assertNotIn('amendment_sha256', original)
                path.write_bytes(b'test amendment')
                amended, _, _ = consensus._inputs(10800)
                self.assertEqual(amended, dict(original, max_wall_seconds=10800.0,
                                               amendment_sha256=consensus.digest_bytes(path.read_bytes())))
        with self.assertRaisesRegex(ValueError, 'unsupported_max_wall_seconds'):
            consensus._inputs(9000)

    def test_trial_gate_and_verification_use_recorded_budget(self):
        state = ('test-observation', 0)
        module = SimpleNamespace(summary=lambda rows, config: {'observations': len(rows)})
        studies = (('materiality', module), ('consensus', module))

        def inputs(limit):
            config = {'max_wall_seconds': limit, 'start_guard_seconds': 45., 'observations': 1,
                      'trial_periods': [0], 'max_failure_rate': .05}
            if limit == 10800:
                config['amendment_sha256'] = 'test-binding'
            return config, {state: None}, {}

        def phase(module, output, keys, states, archived, config, budget=None):
            if budget is not None:
                budget.check()
            records = [
                {'key': list(key), 'seconds': 3000., 'result': {}, 'calls': [], 'timings': {}}
                for key in keys
            ]
            write_lines(output, records)
            return records

        with TemporaryDirectory() as folder, patch.object(consensus, 'STUDIES', studies), \
                patch.object(consensus, '_inputs', side_effect=inputs), \
                patch.object(consensus, '_phase', side_effect=phase), patch.object(consensus, '_replay'), \
                patch.object(consensus, 'runtime', return_value={}), \
                patch.object(consensus.Budget, 'elapsed', return_value=6000.), \
                patch.object(consensus, 'solve', side_effect=AssertionError('unexpected solve')), \
                patch.object(consensus, 'solve_fixed_first', side_effect=AssertionError('unexpected fixed solve')):
            with patch.object(consensus, 'STUDIES', tuple((name+'_gate1', module) for name, module in studies)):
                original = consensus.run(folder)
            self.assertEqual(original['stop_reason'], 'estimated_formal_wall_above_budget')
            self.assertIsNone(original['formal_wall_seconds'])
            self.assertEqual(consensus.verify(folder, gate1=True)['solves_run'], 0)

            amended = consensus.run(folder, max_wall_seconds=10800)
            self.assertEqual(amended, {'estimated_formal_wall_seconds': 6045., 'formal_wall_seconds': 6000.,
                                       'stop_reason': None})
            self.assertEqual(consensus.verify(folder)['solves_run'], 0)

            output = Path(folder)/'consensus'
            saved = consensus.stability._json(output/'config.json')
            consensus.write_json(output/'config.json', dict(saved, amendment_sha256='different-binding'))
            consensus.write_json(output/'manifest.json', consensus.stability._hashes(output, consensus.FILES))
            with self.assertRaisesRegex(ValueError, 'configuration_changed:consensus'):
                consensus.verify(folder)


if __name__ == '__main__':
    unittest.main()
