"""Development version 2 of the scenario-tree study: generator, fixed-action solve, anchor scenarios, smoke run."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from rolling_inventory.environment import Environment, generate
from rolling_inventory.planning import solve as anchor_solve
from rolling_tree import experiment_v2 as v2
from rolling_tree import scenarios as sc
from rolling_tree.experiment import base_configuration
from rolling_tree.planning import Model, solve, solve_fixed_first

TEST_SEED = 99001  # outside every fitting, tuning, development and confirmation seed


def task(profile='volatile', seed=TEST_SEED):
    return next(t for t in generate(base_configuration(), 'test', [seed]) if t['profile'] == profile)


def state(t, profile='volatile'):
    env = Environment(task(profile))
    for _ in range(t):
        env.step([[0, 0], [0, 0], [0, 0]])
    return env.observe()


class ScenarioTreeV2Tests(unittest.TestCase):
    def test_strata_put_one_uniform_in_every_stratum(self):
        levels = sc._strata(np.random.default_rng(3), 9)
        self.assertEqual(sorted(np.floor(levels*9).astype(int).tolist()), list(range(9)))

    def test_tree_shape_and_wider_first_stage(self):
        obs = state(2)
        paths, labels, depth = sc.joint_tree_v2(obs, 0.1, (9, 3), 3, 913337)
        self.assertEqual(paths.shape, (81, 6, 3)); self.assertEqual(depth, 2)
        model = Model(obs, paths, depth)
        self.assertEqual(model.summary()['nodes_per_stage'][:3], [1, len({tuple(x) for x in paths[:, 0]}),
                                                                 len({tuple(x) for x in paths[:, :2].reshape(81, -1)})])
        old, _, _ = sc.joint_tree(obs, 0.1, 2, 3, 3, 913337)
        self.assertGreater(len({tuple(x) for x in paths[:, 0]}), len({tuple(x) for x in old[:, 0]}))

    def test_children_of_one_node_share_its_period_and_differ_only_below(self):
        obs = state(3)
        paths, labels, depth = sc.joint_tree_v2(obs, 0.2, (4, 2), 2, 5)
        for k, (prefix, _) in enumerate(labels):
            for m, (other, _) in enumerate(labels):
                if prefix[0] == other[0]:
                    np.testing.assert_array_equal(paths[k, 0], paths[m, 0])
                if prefix == other:
                    np.testing.assert_array_equal(paths[k, :2], paths[m, :2])

    def test_shuffle_keeps_each_sku_marginal_tree_and_changes_only_pairing(self):
        obs = state(4)
        paths, labels, depth = sc.joint_tree_v2(obs, 0.3, (9, 3), 3, 913337)
        mixed = sc.shuffled_tree_v2(paths, labels, depth, (9, 3), 3, 917351, obs['t'])
        np.testing.assert_array_equal(mixed[:, :, 0], paths[:, :, 0])
        for sku in range(3):
            self.assertEqual(sorted(map(tuple, paths[:, :, sku])), sorted(map(tuple, mixed[:, :, sku])))
            for u in range(depth):  # the multiset of child values of every node is unchanged
                for node in {label[0][:u] for label in labels}:
                    mine = sorted(tuple(paths[k, u]) for k, (p, _) in enumerate(labels) if p[:u] == node)
                    self.assertEqual(len(mine) % 1, 0)
        self.assertFalse(np.array_equal(mixed, paths))
        a, b = Model(obs, paths, 0), Model(obs, mixed, 0)  # the open-loop problem ignores pairing
        self.assertAlmostEqual(solve(a, 30)[0]['value'], solve(b, 30)[0]['value'], places=9)

    def test_tree_depends_on_the_observation_only(self):
        first, second = task(), deepcopy(task())
        second['demand'][6:] = [[d+5 for d in row] for row in second['demand'][6:]]
        for t in (1, 4):
            obs = []
            for item in (first, second):
                env = Environment(item)
                for _ in range(t):
                    env.step([[0, 0], [0, 0], [0, 0]])
                obs.append(env.observe())
            a = sc.joint_tree_v2(obs[0], 0.2, (9, 3), 1, 7)[0]; b = sc.joint_tree_v2(obs[1], 0.2, (9, 3), 1, 7)[0]
            np.testing.assert_array_equal(a, b)
            sc.check_observation(obs[0])

    def test_stratified_open_loop_matches_the_forecast_better_than_independent_draws(self):
        errors = {'stratified': [], 'independent': []}
        for t in range(1, 9):
            obs = state(t)
            errors['stratified'].append(sc.first_period_error(sc.open_loop_paths_v2(obs, 0.1, 27, 11), obs))
            errors['independent'].append(sc.first_period_error(sc.open_loop_paths(obs, 0.1, 27, 11), obs))
        self.assertLess(np.mean(errors['stratified']), np.mean(errors['independent']))

    def test_fixed_first_action_solve(self):
        obs = state(3)
        paths, labels, depth = sc.joint_tree_v2(obs, 0.1, (3, 2), 1, 13)
        model = Model(obs, paths, depth)
        best, _ = solve(model, 30)
        again, _ = solve_fixed_first(model, best['action'], 30)
        self.assertAlmostEqual(again['value'], best['value'], places=7)
        zero = [[0, 0], [0, 0], [0, 0]]  # shipping nothing is always feasible
        worse, _ = solve_fixed_first(model, zero, 30)
        self.assertGreaterEqual(worse['value'], best['value']-1e-7)
        self.assertEqual(worse['action'], zero)
        too_much = [[99, 0], [0, 0], [0, 0]]  # beyond the route's capacity bound: refused before solving
        refused, record = solve_fixed_first(model, too_much, 30)
        self.assertIsNone(refused); self.assertEqual(record['message'], 'action_outside_model_bounds')

    def test_anchor_paths_reproduce_the_rolling_baseline(self):
        for t in (0, 5):
            obs = state(t)
            schedule, detail = anchor_solve(obs, v2.anchor_paths(obs))
            own, _ = solve(Model(obs, v2.anchor_paths(obs), 0), 30)
            self.assertAlmostEqual(own['value'], detail['objective'], places=6)

    def test_swap_replaces_one_decision_and_replans_the_rest(self):
        cfg = self.smoke_configuration(400)
        fit = v2.fitted_variance(cfg, base_configuration())['fitted_variance']
        budget = v2.Budget(cfg['budget']); planner = v2.PlannerV2(cfg, fit, budget, cfg['shape_candidates'][0], 48,
                                                                  cfg['sampler_seeds'][0])
        item = task()
        base, rows = v2.rollout(item, 'B1', planner)
        swapped, swap_rows = v2.rollout(item, 'B1', planner, swap={'t': 3, 'action': [[0, 0], [0, 0], [0, 0]],
                                                                   'label': 'zero@3'})
        for t in range(3):
            self.assertEqual(rows[t]['action'], swap_rows[t]['action'])
        self.assertEqual(swap_rows[3]['action'], [[0, 0], [0, 0], [0, 0]])
        self.assertEqual(swap_rows[3]['planning']['method'], 'swap')

    def smoke_configuration(self, max_solves):
        cfg = v2.configuration()
        cfg['fit_seeds'] = [99011]; cfg['tuning_seeds'] = [99021]
        cfg['energy_score'] = {'samples': 40, 'seed': 99031}
        cfg['shape_candidates'] = [{'branching': [3, 2], 'continuation': 1}]
        cfg['shape_rule'] = dict(cfg['shape_rule'], states_per_path=1, max_p95_m1_seconds=30.,
                                 max_p95_m2_star_seconds=60.)
        cfg['equal_time_candidates'] = [4, 6]; cfg['sampler_seeds'] = [99041, 99043]
        cfg['pilot'] = {'split': 'smoke', 'seed': TEST_SEED, 'profiles': ['volatile'], 'base_stock_z': 1.0}
        cfg['budget_tuning'] = {'max_solves': max_solves, 'max_wall_seconds': 900, 'start_guard_seconds': 0,
                                'retries': 0}
        cfg['budget'] = dict(cfg['budget_tuning'])
        return cfg

    def test_tuning_and_pilot_smoke_run_end_to_end_and_verify_without_solving(self):
        cfg = self.smoke_configuration(1500)
        with tempfile.TemporaryDirectory() as folder:
            tuned = v2.tune(Path(folder)/'tune', cfg)
            selection = tuned['selection']
            self.assertEqual(selection['shape'], cfg['shape_candidates'][0])
            self.assertIn(selection['prior_strength'], cfg['prior_strength_candidates'])
            out = Path(folder)/'pilot'
            result = v2.pilot(out, cfg, selection)
            self.assertIsNone(result['stop_reason'])
            summary = json.loads((out/'summary.json').read_text(encoding='utf-8'))
            self.assertTrue(all(i['status'] in ('done', 'complete') for i in summary['items']))
            self.assertEqual(sum(summary['audit_counts']['anchor'].values()), 12*2)
            self.assertEqual(v2.verify(out, current_configuration=False)['solves_run'], 0)
            with self.assertRaises(FileExistsError):
                v2.pilot(out, cfg, selection)


if __name__ == '__main__':
    unittest.main()
