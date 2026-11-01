from copy import deepcopy
from itertools import product
import unittest

import numpy as np

from rolling_inventory.environment import Environment, carbon, generate, validate
from rolling_inventory.experiment import audit as ledger_audit
from rolling_inventory.planning import path_cost, solve as anchor_solve
from rolling_tree import scenarios as sc
from rolling_tree.experiment import (Budget, BudgetExhausted, Planner, base_configuration,
                                     configuration, forced_zero, rollout)
from rolling_tree.planning import Model, solve, tie_robust, tolerance

RULE = {'relative': 1e-6, 'absolute': 1e-7}
TEST_SEED = 99001  # Outside the fitting, pilot and reserved development/confirmation seeds.


def task(profile='volatile', seed=TEST_SEED):
    return next(t for t in generate(base_configuration(), 'test', [seed]) if t['profile'] == profile)


def state(t, profile='volatile'):
    env = Environment(task(profile))
    for _ in range(t):
        env.step([[0, 0], [0, 0], [0, 0]])
    return env.observe()


def small_state(capacity, carbon_remaining):
    """Real t=9 observation (window 3) with emptied stock and pipeline for enumeration."""
    obs = deepcopy(state(9))
    obs['stock'] = [0, 0, 0]; obs['backlog'] = [0, 0, 0]
    obs['pipeline'] = [[0, 0, 0] for _ in obs['pipeline']]
    obs['carbon_remaining'] = carbon_remaining; obs['public']['capacity'] = capacity
    return obs


def actions(obs, routes):
    """All feasible actions using only the listed routes."""
    p = obs['public']; out = []
    per_route = []
    for j in range(len(p['lead'])):
        cap = p['capacity'][j] if j in routes else 0
        per_route.append([q for q in product(*(range(cap//m+1) for m in p['mass']))
                          if np.dot(q, p['mass']) <= cap])
    for combo in product(*per_route):
        out.append(np.array(combo).T.astype(int))
    return out


def tree_value(obs, paths, keys_stage1, a0, budget):
    """Exact optimum for window 3 given the first action: stage-1 nodes separate."""
    total = 0.
    zero = np.zeros_like(a0)
    for key in sorted(set(keys_stage1)):
        members = [k for k, x in enumerate(keys_stage1) if x == key]
        best = np.inf
        for a1 in actions(obs, routes=(1,)):
            if carbon(a0, obs['public'])+carbon(a1, obs['public']) > budget:
                continue
            best = min(best, sum(path_cost(obs, [a0, a1, zero], paths[k]) for k in members))
        total += best
    return total/len(paths)


class ScenarioTreeTests(unittest.TestCase):
    def test_planner_ledger_matches_environment_event_order(self):
        env = Environment(task()); obs = env.observe()
        a0 = [[0, 1], [0, 0], [1, 0]]  # SKU 1 fast, SKU 3 slow.
        env._demand[0] = [5, 1, 0]; env._demand[1] = [0, 0, 0]
        row = env.step(a0)
        self.assertEqual(row['filled_new'], [3, 1, 0]); self.assertEqual(row['backlog_end'], [2, 0, 0])
        self.assertAlmostEqual(row['cost'], 3+1+.25*5+(3*.6+2*.3)+2*7)
        obs1 = env.observe()  # Initial pipeline [1,0,1] plus the fast unit arrive at t=1.
        self.assertEqual(obs1['arrivals'], [2, 0, 1]); self.assertEqual(obs1['served_old'], [2, 0, 0])
        self.assertEqual(obs1['stock'], [0, 3, 3])
        env.step([[0, 0], [0, 0], [0, 0]])
        self.assertEqual(env.observe()['arrivals'], [0, 0, 1])  # The slow unit arrives at t=2.
        # The planner's path ledger equals the environment over the same window.
        env = Environment(task()); obs = env.observe()
        schedule = [[[1, 1], [0, 0], [1, 0]], [[0, 0], [1, 1], [0, 0]], [[2, 0], [0, 0], [0, 1]],
                    [[0, 0], [0, 0], [0, 0]], [[0, 0], [0, 0], [0, 0]], [[0, 0], [0, 0], [0, 0]]]
        demand = [env._demand[t] for t in range(6)]
        realized = sum(env.step(a)['cost'] for a in schedule)
        self.assertAlmostEqual(path_cost(obs, schedule, demand), realized)

    def test_one_step_forecasts_equal_environment_forecasts(self):
        env = Environment(task('upshift')); seen = []
        for _ in range(12):
            obs = env.observe(); seen.append(obs['forecast'][0]); env.step([[0, 0], [0, 0], [0, 0]])
        history = env.history
        for t, value in enumerate(sc.one_step_forecasts(task('upshift')['public'], history)):
            np.testing.assert_allclose(value, seen[t])

    def test_identical_observed_history_shares_decision_not_branch_label(self):
        obs = state(3)
        paths, labels, depth = sc.joint_tree(obs, .3, 2, 3, 3, 913337)
        keys = sc.node_keys(paths, depth)
        for u in range(paths.shape[1]):
            for k in range(len(paths)):
                for l in range(len(paths)):
                    same = np.array_equal(paths[k, :min(u, depth)], paths[l, :min(u, depth)])
                    self.assertEqual(keys[k][u] == keys[l][u], same)
        # Branch (1,0) is forged to show the same first-period demand as branch (0,0): it merges.
        forged = paths.copy(); forged[9:12, 0] = forged[0, 0]
        merged = Model(obs, forged, depth)
        self.assertEqual(merged.node_of[0][1], merged.node_of[9][1])
        if not np.array_equal(paths[0, 0], paths[9, 0]):
            self.assertNotEqual(Model(obs, paths, depth).node_of[0][1], Model(obs, paths, depth).node_of[9][1])
        sol, _ = solve(merged, 30)
        decisions = merged.decisions(sol['x'])
        np.testing.assert_array_equal(decisions[1][merged.node_of[0][1]], decisions[1][merged.node_of[9][1]])
        # Relabelling scenarios changes nothing: labels are not information.
        order = np.random.default_rng(5).permutation(len(paths))
        self.assertAlmostEqual(solve(Model(obs, paths[order], depth), 30)[0]['value'],
                               solve(Model(obs, paths, depth), 30)[0]['value'], places=6)

    def test_shuffle_preserves_marginal_tree_constraints_and_information(self):
        for t in (0, 4, 8):
            obs = state(t)
            joint, labels, depth = sc.joint_tree(obs, .4, 2, 3, 3, 913337)
            shuffled = sc.shuffled_tree(joint, labels, depth, 3, 3, 917351, t)
            np.testing.assert_array_equal(joint[:, :, 0], shuffled[:, :, 0])
            for sku in range(1, 3):
                images = sc.automorphism(labels, 3, 3, depth, 917351, t, sku)
                self.assertEqual(len(set(images)), len(labels))
                for a in range(len(labels)):
                    for b in range(len(labels)):
                        for u in range(depth+1):
                            sa = labels[a][0][:u] == labels[b][0][:u]
                            self.assertEqual(sa, images[a][0][:u] == images[b][0][:u])
                self.assertEqual(sorted(map(tuple, joint[:, :, sku].tolist())),
                                 sorted(map(tuple, shuffled[:, :, sku].tolist())))
                for u in range(joint.shape[1]):
                    self.assertEqual(sorted(map(tuple, joint[:, :u+1, sku].tolist())),
                                     sorted(map(tuple, shuffled[:, :u+1, sku].tolist())))
            m1, m2 = Model(obs, joint, depth), Model(obs, shuffled, depth)
            self.assertEqual(m1.budget, m2.budget); self.assertEqual(m1.shape, m2.shape)
            np.testing.assert_array_equal(m1.c[m1.qn:], m2.c[m2.qn:])

    def test_open_loop_is_invariant_to_pairing_and_reproduces_archived_solver(self):
        for t in (0, 5):
            obs = state(t)
            joint, labels, depth = sc.joint_tree(obs, .5, 2, 3, 3, 913337)
            shuffled = sc.shuffled_tree(joint, labels, depth, 3, 3, 917351, t)
            a = solve(Model(obs, joint, 0), 30)[0]; b = solve(Model(obs, shuffled, 0), 30)[0]
            self.assertAlmostEqual(a['value'], b['value'], places=6)
            schedule, info = anchor_solve(obs, joint)
            self.assertAlmostEqual(a['value'], info['objective'], places=6)

    def test_single_branch_tree_reduces_to_open_loop(self):
        obs = state(2)
        paths, _, depth = sc.joint_tree(obs, .3, 2, 1, 3, 913337)
        self.assertEqual(Model(obs, paths, depth).nodes[3].__len__(), 1)
        self.assertAlmostEqual(solve(Model(obs, paths, depth), 30)[0]['value'],
                               solve(Model(obs, paths, 0), 30)[0]['value'], places=6)

    def test_milp_and_tie_robust_selection_match_enumeration(self):
        # Chosen so the open-loop model has two tied optimal first actions and recourse matters.
        obs = small_state([2, 2], 10)
        paths = np.array([[[0, 1, 0], [1, 0, 0], [1, 1, 2]],
                          [[0, 1, 0], [1, 0, 0], [0, 0, 2]],
                          [[1, 0, 0], [2, 1, 2], [1, 2, 1]],
                          [[1, 0, 0], [1, 0, 0], [1, 0, 0]]])
        tree, open_loop = Model(obs, paths, 1), Model(obs, paths, 0)
        budget = tree.budget; zero = np.zeros((3, 2), dtype=int)
        keys = [tree.node_of[k][1] for k in range(len(paths))]
        first = actions(obs, routes=(0, 1))
        values = {i: tree_value(obs, paths, keys, a0, budget) for i, a0 in enumerate(first)}
        best_tree = min(values.values())
        sol, _ = solve(tree, 30)
        self.assertAlmostEqual(sol['value'], best_tree, places=6)
        own = {}
        for i, a0 in enumerate(first):
            own[i] = min((np.mean([path_cost(obs, [a0, a1, zero], p) for p in paths])
                          for a1 in actions(obs, routes=(1,))
                          if carbon(a0, obs['public'])+carbon(a1, obs['public']) <= budget), default=np.inf)
        best_own = min(own.values())
        self.assertAlmostEqual(solve(open_loop, 30)[0]['value'], best_own, places=6)
        allowed = [i for i in own if own[i] <= best_own+tolerance(best_own, RULE)]
        self.assertEqual(len(allowed), 2)  # The tie rule is exercised, not bypassed.
        self.assertLess(best_tree, best_own-1e-6)
        expected = min(values[i] for i in allowed)
        tied, _ = tie_robust(tree, open_loop, best_own, RULE, 30)
        self.assertAlmostEqual(tied['value'], expected, places=6)
        self.assertIn(tied['action'], [first[i].tolist() for i in allowed])
        self.assertGreater(tied['value']-sol['value'], tolerance(sol['value'], RULE))  # Material here.
        # A model tie-broken by itself is never "material".
        self_tie, _ = tie_robust(tree, Model(obs, paths, 1), sol['value'], RULE, 30)
        self.assertLessEqual(self_tie['value']-sol['value'], tolerance(sol['value'], RULE))

    def test_carbon_is_accumulated_per_path_not_across_branches(self):
        obs = small_state([0, 4], 12)
        paths = np.array([[[0, 0, 0], [0, 0, 0], [0, 0, 3]],
                          [[1, 0, 0], [0, 0, 0], [3, 0, 0]]])
        model = Model(obs, paths, 1)
        sol, _ = solve(model, 30)
        stage1 = model.decisions(sol['x'])[1]
        per_node = [carbon(a, obs['public']) for a in stage1]
        self.assertEqual(len(stage1), 2)
        self.assertGreater(sum(per_node), model.budget)  # Exclusive branches, summed, exceed it.
        for k, sequence in enumerate(model.node_of):
            used = sum(carbon(model.decisions(sol['x'])[u][m], obs['public']) for u, m in enumerate(sequence))
            self.assertLessEqual(used, model.budget)

    def test_future_demand_does_not_change_current_or_earlier_decisions(self):
        cfg = configuration(); cfg['tree'] = {'depth': 1, 'branching': 3, 'continuation': 1}
        planner = Planner(cfg, .2, Budget({'max_solves': 100, 'max_wall_seconds': 600,
                                           'start_guard_seconds': 0, 'retries': 0}))
        base, changed = task(), task()
        for t in range(2, 12):
            changed['demand'][t] = [d+5 for d in changed['demand'][t]]
        for method in ('M1', 'M2*'):
            seen = []
            for case in (base, changed):
                env = Environment(case); taken = []
                for t in range(3):
                    action, _ = planner.decide(env.observe(), method, {'path': case['id'], 't': t})
                    taken.append(action); env.step(action)
                seen.append(taken)
            self.assertEqual(seen[0], seen[1])

    def test_policy_inputs_exclude_hidden_fields(self):
        a, b = task(), deepcopy(task())
        b['id'], b['profile'], b['seed'] = 'other', 'stable', 1
        oa, ob = Environment(a).observe(), Environment(b).observe()
        self.assertEqual(oa, ob)
        sc.check_observation(oa)
        with self.assertRaises(ValueError):
            sc.check_observation(dict(oa, profile='volatile'))
        np.testing.assert_array_equal(sc.joint_tree(oa, .3, 2, 3, 3, 1)[0], sc.joint_tree(ob, .3, 2, 3, 3, 1)[0])

    def test_history_variance_ignores_unrevealed_demand(self):
        a, b = task(), task()
        b['demand'][6] = [9, 9, 9]
        oa, ob = Environment(a), Environment(b)
        for _ in range(6):
            oa.step([[0, 0], [0, 0], [0, 0]]); ob.step([[0, 0], [0, 0], [0, 0]])
        self.assertEqual(sc.common_variance(oa.observe(), .1, 48, 2.), sc.common_variance(ob.observe(), .1, 48, 2.))

    def test_ledger_replay_detects_tampering(self):
        cfg = configuration(); planner = Planner(cfg, .1, None)
        case = task(); result, rows = rollout(case, 'B0', planner)
        self.assertEqual(result['status'], 'complete')
        ledger_audit(case, rows)
        bad = deepcopy(rows); bad[4]['stock_end'][0] += 1
        with self.assertRaises(ValueError):
            ledger_audit(case, bad)
        bad = deepcopy(rows); bad[2]['action'][0][0] += 1
        with self.assertRaises(ValueError):
            ledger_audit(case, bad)

    def test_budget_refuses_extra_solves_and_late_starts(self):
        budget = Budget({'max_solves': 2, 'max_wall_seconds': 3600, 'start_guard_seconds': 30, 'retries': 0})
        budget.charge(); budget.charge()
        with self.assertRaises(BudgetExhausted):
            budget.charge()
        late = Budget({'max_solves': 300, 'max_wall_seconds': 10, 'start_guard_seconds': 30, 'retries': 0})
        with self.assertRaises(BudgetExhausted):
            late.charge()

    def test_last_period_is_forced_zero(self):
        self.assertTrue(forced_zero(state(11)))
        self.assertFalse(forced_zero(state(10)))


if __name__ == '__main__':
    unittest.main()
