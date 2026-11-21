"""Closing policy, inference, time gate and solve-free archive replay."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from rolling_inventory.environment import Environment, generate
from rolling_tree import closing, closing_replay, closing_stats as stats, experiment_v2 as v2
from rolling_tree.experiment import DecisionFailed, read_lines, write_json, write_lines
from rolling_tree.planning import Model, solve


def fixture():
    cfg = closing.settings()
    cfg.update(split='test', path_seeds=[99001], first_sampler=99041, profiles=['volatile'])
    cfg['selection']['shape'] = {'branching': [3, 2], 'continuation': 1}
    task = closing.ordered_tasks(cfg)[0]
    planner = closing.make_planner(cfg, closing.budget_for(600), cfg['first_sampler'])
    return cfg, task, planner


class ClosingTests(unittest.TestCase):
    def test_own_action_and_each_sku_marginal_on_the_same_tree(self):
        cfg, task, planner = fixture()
        obs = Environment(task).observe()
        reference = v2.PlannerV2(cfg['v2'], planner.fitted, None, planner.shape, planner.prior_strength,
                                 planner.sampler_seed)
        joint, labels, depth = reference.joint(obs, reference.variance(obs))
        own = reference.shuffled(obs, joint, labels, depth)
        for i in range(3):
            self.assertEqual(sorted(map(tuple, own[:, :, i])), sorted(map(tuple, joint[:, :, i])))
        expected, _ = solve(Model(obs, own, depth), 30)
        action, info = planner.decide(obs, 'M2', {})
        self.assertEqual(action, expected['action'])
        self.assertEqual(info['shuffled_sha256'], closing.array_digest(own))
        self.assertEqual([x['purpose'] for x in planner.budget.log], ['M2:own'])

    def test_tie_timeout_uses_own_optimum_and_counts_one_fallback(self):
        cfg, task, planner = fixture()
        obs = Environment(task).observe()
        own, _ = planner.decide(obs, 'M2', {})
        log = {'status': 1, 'message': 'Time limit reached.', 'wall_seconds': 30.0}
        with patch('rolling_tree.experiment.tie_robust', return_value=(None, log)):
            action, info = planner.decide(obs, 'M2*', {})
        self.assertTrue(info['fallback'])
        self.assertEqual(action, own)
        path = {'id': task['id'], 'profile': task['profile']}
        summary, _ = stats.summarize([], [{'id': task['id'], 'method': 'M2*', 'rows': [{'planning': info}]}],
                                     planner.budget.log, [path], 1, cfg['v2']['reference_thresholds'])
        self.assertEqual(summary['computation']['M2*']['fallbacks'], 1)
        self.assertEqual(summary['computation']['M2*']['timeouts'], 1)
        with patch('rolling_tree.experiment.tie_robust',
                   return_value=(None, dict(log, status=2, message='Infeasible'))):
            with self.assertRaises(DecisionFailed):
                planner.decide(obs, 'M2*', {})

    def test_actual_future_is_hidden_through_current_action(self):
        _, task, planner = fixture()
        other = deepcopy(task)
        other['demand'][2:] = [[x+8 for x in row] for row in other['demand'][2:]]
        for method in ('M1', 'M2', 'M2*'):
            a, b = Environment(task), Environment(other)
            for _ in range(3):
                actions = [planner.decide(env.observe(), method, {})[0] for env in (a, b)]
                self.assertEqual(*actions)
                a.step(actions[0])
                b.step(actions[1])

    def test_paired_intervals_have_hand_checkable_endpoints(self):
        x = [[1, .2, 0], [3, .6, 4]]
        b = [[0, 0, 0], [0, 0, 0]]
        cost = stats.paired(x, b, 321)['metrics']['total_cost']
        self.assertEqual(cost['mean_difference'], 2)
        np.testing.assert_allclose(cost['t95'], [2-12.7062047364, 2+12.7062047364])
        self.assertEqual(cost['bootstrap95'], [1, 3])
        self.assertIsNone(cost['relative'])
        self.assertEqual(stats.paired(x, b, 321), stats.paired(x, b, 321))
        self.assertIsNone(stats.paired(x[:1], b[:1], 321)['metrics']['total_cost']['t95'])

    def test_decision_strict_margins_and_inclusive_guardrails(self):
        thresholds = v2.configuration()['reference_thresholds']
        def category(bounds, fill=-.005, emissions=2):
            return stats.decision(bounds, 2, fill, emissions, 100, thresholds)
        self.assertEqual(category([-4, -3]), 'practical_benefit')
        self.assertEqual(category([-4, -3], -.00501), 'uncertain')
        self.assertEqual(category([-4, -3], emissions=2.001), 'uncertain')
        self.assertEqual(category([-1.9, 1.9]), 'equivalent')
        self.assertEqual(category([2.01, 4]), 'harm')
        for bounds in ([-4, -2], [-2, 1], [-1, 2], [2, 3], [-3, 3], None):
            self.assertEqual(category(bounds), 'uncertain')

    def test_first_divergence_uses_the_common_pre_dispatch_state(self):
        _, task, _ = fixture()
        a, b = Environment(task), Environment(task)
        zero = [[0, 0], [0, 0], [0, 0]]
        left, right = [a.step(zero)], [b.step(zero)]
        left.append(a.step([[2, 0], [3, 0], [0, 0]]))
        right.append(b.step([[1, 0], [3, 0], [0, 0]]))
        for rows, value in [(left, 72), (right, 71)]:
            rows[-1]['planning'] = {'max_leaf_carbon': value}
        found = stats.first_divergence(left, right, 2.5)
        self.assertEqual(found['t'], 1)
        self.assertEqual(found['D'], 2.5)
        self.assertEqual(found['unit_difference'], [[1, 0], [0, 0], [0, 0]])
        self.assertEqual(found['resources']['M1']['load_fraction'], [1, 0])
        self.assertTrue(found['resources']['M1']['carbon_binding'])
        self.assertEqual(stats.first_divergence(left, left, 0), {'D': 0, 't': None})

    def test_timing_gate_uses_max_and_never_opens_formal_paths_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            with (patch.object(closing, 'trajectory'), patch.object(closing, 'formal') as formal,
                  patch.object(closing, 'ordered_tasks', side_effect=AssertionError),
                  patch('rolling_tree.closing.time.perf_counter', side_effect=[0, 0, 10, 10, 30, 30, 80, 80, 81])):
                outcome = closing.run(folder)
            self.assertEqual(outcome['stop_reason'], 'timing_gate')
            self.assertEqual(outcome['timing']['estimated_seconds'], 8060)
            self.assertEqual(outcome['formal_solves'], 0)
            formal.assert_not_called()
            self.assertFalse(any(Path(folder).iterdir()))

    def test_archive_replay_detects_rehashed_trace_and_summary_changes(self):
        cfg, _, _ = fixture()
        development = generate(cfg['environment'], 'development', [cfg['v2']['pilot']['seed']])
        gate = {'development': [{'id': t['id'], 'wall_seconds': 1} for t in development],
                'estimated_seconds': 220, 'sampler_seed': cfg['v2']['sampler_seeds'][0],
                'limit_seconds': 7200, 'passed': True}
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            run = closing.formal(out, cfg, gate, lambda *args: None, 600)
            self.assertIsNone(run['stop_reason'])
            with patch('scipy.optimize.milp', side_effect=AssertionError), patch('rolling_tree.planning._milp',
                       side_effect=AssertionError), patch('rolling_inventory.planning.milp', side_effect=AssertionError):
                audit = closing_replay.verify(out, expected_config=cfg)
            self.assertEqual(audit['solves_run'], 0)
            self.assertEqual(audit['ledger_rows_replayed'], 72)
            def rehash():
                write_json(out/'manifest.json', {n: closing.file_hash(out/n) for n in closing.FILES})
            saved = (out/'traces.jsonl').read_bytes()
            records = read_lines(out/'traces.jsonl')
            records[0]['rows'][0]['planning']['joint_sha256'] = 'altered'
            write_lines(out/'traces.jsonl', records)
            with self.assertRaisesRegex(ValueError, 'manifest'):
                closing_replay.verify(out, expected_config=cfg)
            rehash()
            with self.assertRaisesRegex(ValueError, 'joint_tree'):
                closing_replay.verify(out, expected_config=cfg)
            (out/'traces.jsonl').write_bytes(saved)
            summary = closing.read(out/'summary.json')
            summary['comparisons']['overall']['M1-M2']['metrics']['total_cost']['bootstrap95'][0] += 1
            write_json(out/'summary.json', summary)
            rehash()
            with self.assertRaisesRegex(ValueError, 'summary_replay'):
                closing_replay.verify(out, expected_config=cfg)
