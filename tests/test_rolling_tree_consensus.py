"""Budget and offline solve replay in the two-stage experiment."""
import unittest
from unittest.mock import patch

from rolling_inventory.environment import Environment, generate
from rolling_tree import consensus
from rolling_tree.experiment import base_configuration


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


if __name__ == '__main__':
    unittest.main()
