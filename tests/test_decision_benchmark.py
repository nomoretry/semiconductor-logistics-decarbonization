"""Development decision consequences, information boundary and exact-policy checks."""

import copy
import json
from pathlib import Path
import random
import tempfile
import unittest

from decision_benchmark.audit import make_contexts, run_audit, verify_audit
from decision_benchmark.env import DecisionEnv
from decision_benchmark.model import (SOLVERS, candidate_for_solver, loss_table,
                                     physical_outcome, score_outcome, validate_context)
from decision_benchmark.policies import (AdaptivePolicy, PublicPlanner, expected_policy_loss,
                                        run_policy, state_from_observation)


def context():
    value = make_contexts(random.Random(41))[0]
    value["committed_order"]["quantity"] = 10
    value["mass_kg_per_unit"] = 1
    value["routes"]["air"].update(freight_usd_per_kg=10, kgco2e_per_kg=4)
    value["routes"]["ocean"].update(freight_usd_per_kg=1, kgco2e_per_kg=0.2)
    value["holding_usd_per_unit_week"] = 1
    value["warehouse_kgco2e_per_unit_week"] = 0
    value["prior_severe_delay"] = 0.2
    value["query_model"] = {"sensitivity": 0.8, "specificity": 0.8}
    value["goal"].update(late_unit_week_penalty_usd=20, carbon_price_usd_per_kgco2e=0,
                         carbon_budget_kgco2e=100, carbon_excess_penalty_usd_per_kgco2e=0,
                         minimum_on_time_fill_rate=1)
    value["tool_fees_usd"] = {"query_status": 1, "request_clarification": 10,
                             "solve_nominal": 1, "solve_robust": 3, "solve_bayes": 2,
                             "commit_plan": 0, "handoff": 0}
    value["budgets"] = {"max_steps": 5, "max_solver_calls": 2, "max_queries": 2, "tool_budget_usd": 100}
    return value


class DecisionBenchmarkTests(unittest.TestCase):
    def test_dispatches_reconstruct_arrivals_inventory_cost_and_service(self):
        c = context()
        normal, delayed = physical_outcome(c, 7, 0), physical_outcome(c, 7, 2)
        self.assertEqual(normal["inventory_by_week"], [0, 3, 10, 0, 0, 0])
        self.assertEqual(delayed["inventory_by_week"], [0, 3, 3, 0, 0, 0])
        self.assertEqual(delayed["backlog_by_week"], [0, 0, 0, 7, 0, 0])
        self.assertEqual(normal["freight_usd"], 37)
        self.assertEqual(normal["holding_usd"], 13)
        self.assertEqual(delayed["holding_usd"], 6)
        self.assertAlmostEqual(normal["emissions_kgco2e"], 13.4)
        self.assertEqual(normal["on_time_fill_rate"], 1)
        self.assertEqual(delayed["on_time_fill_rate"], 0.3)
        self.assertEqual(score_outcome(c, delayed)["lateness_penalty_usd"], 140)
        self.assertTrue(delayed["all_committed_orders_delivered"])
        for q in (-1, 11, 1.5, True):
            with self.assertRaises(ValueError):
                physical_outcome(c, q, 0)

    def test_hidden_truth_cannot_change_public_masks_solver_candidates_or_ids(self):
        c = context()
        first, second = [DecisionEnv(c, theta=theta, screen_positive=False) for theta in (0, 2)]
        self.assertEqual(first.observation(), second.observation())
        for tool in ("query_status", "solve_nominal", "solve_robust"):
            self.assertEqual(first.step({"tool": tool}), second.step({"tool": tool}))
        self.assertNotIn("actual_delay", json.dumps(first.observation()))
        with self.assertRaises(RuntimeError):
            first.terminal_evaluation()

    def test_paid_exact_clarification_reveals_delay_and_changes_dispatch(self):
        c = context()
        plans = []
        for theta in (0, 2):
            env = DecisionEnv(c, theta=theta, screen_positive=False)
            reply = env.step({"tool": "request_clarification"})
            self.assertEqual(reply["info"]["response"]["confirmed_ocean_delay_weeks"], theta)
            env.step({"tool": "solve_bayes"})
            candidate = env.observation()["candidates"][0]
            plans.append(candidate["ocean_units"])
            env.step({"tool": "commit_plan", "candidate_id": candidate["candidate_id"]})
            self.assertTrue(env.terminal_evaluation()["task_success"])
            self.assertEqual(env.terminal_evaluation()["tool_fees_usd"], 12)
        self.assertEqual(plans, [10, 0])

    def test_wrong_prediction_is_not_itself_a_physical_failure(self):
        c = context()
        # Three units may be late under this disclosed service target. The
        # actual replay, rather than a nominal inventory prediction, decides.
        c["goal"]["minimum_on_time_fill_rate"] = 0.7
        self.assertTrue(score_outcome(c, physical_outcome(c, 3, 2))["service_success"])

    def test_query_fee_and_budget_can_change_optimal_action(self):
        cheap, expensive = context(), context()
        expensive["tool_fees_usd"]["query_status"] = 1000
        expensive["tool_fees_usd"]["request_clarification"] = 1000
        policy = AdaptivePolicy()
        cheap_obs = DecisionEnv(cheap, theta=0, screen_positive=False).observation()
        expensive_obs = DecisionEnv(expensive, theta=0, screen_positive=False).observation()
        self.assertIn(policy(cheap_obs)["tool"], ("query_status", "request_clarification"))
        self.assertIn(policy(expensive_obs)["tool"], SOLVERS)
        tight = copy.deepcopy(cheap)
        tight["budgets"]["max_steps"] = 2
        self.assertIn(policy(DecisionEnv(tight, theta=0, screen_positive=False).observation())["tool"], SOLVERS)

    def test_terminal_reward_equals_negative_all_in_physical_and_tool_loss(self):
        env = DecisionEnv(context(), theta=2, screen_positive=True)
        rewards = []
        for action in ({"tool": "request_clarification"}, {"tool": "solve_bayes"},
                       {"tool": "commit_plan", "candidate_id": "candidate_0"}):
            rewards.append(env.step(action)["reward"])
        self.assertAlmostEqual(sum(rewards), -env.terminal_evaluation()["all_in_loss_usd"])
        with self.assertRaises(RuntimeError):
            env.step({"tool": "handoff"})

    def test_invalid_actions_cannot_commit_fabricated_or_fractional_dispatches(self):
        env = DecisionEnv(context(), theta=2, screen_positive=False)
        before = env.observation()
        reply = env.step({"tool": "commit_plan", "candidate_id": "candidate_0", "ocean_units": 0.5})
        self.assertFalse(reply["info"]["valid_action"])
        self.assertEqual(before["candidates"], env.observation()["candidates"])
        self.assertEqual(env.observation()["fees_paid_usd"], 2)
        result = env.step({"tool": "handoff"})
        self.assertFalse(result["info"]["evaluation"]["task_success"])
        self.assertFalse(result["info"]["evaluation"]["shipment_committed"])

    def test_step_solver_query_and_money_budgets_are_enforced(self):
        c = context()
        c["budgets"].update(max_steps=5, max_solver_calls=1, max_queries=1, tool_budget_usd=11)
        env = DecisionEnv(c, theta=2, screen_positive=True)
        env.step({"tool": "request_clarification"})
        self.assertFalse(env.action_mask()["query_status"])
        self.assertFalse(env.action_mask()["solve_bayes"])
        env.step({"tool": "solve_nominal"})
        self.assertFalse(any(env.action_mask()[tool] for tool in SOLVERS))
        self.assertEqual(env.observation()["tool_budget_remaining_usd"], 0)
        env.step({"tool": "commit_plan", "candidate_id": "candidate_0"})
        self.assertFalse(env.terminal_evaluation()["task_success"])
        c["budgets"]["max_steps"] = 1
        exhausted = DecisionEnv(c, theta=0, screen_positive=False)
        result = exhausted.step({"tool": "solve_nominal"})
        self.assertEqual(result["info"]["evaluation"]["terminal_reason"], "step_budget_exhausted")

    def test_exact_bayes_matches_exhaustive_world_rollouts_and_exceeds_free_info_bound(self):
        rng = random.Random(312)
        policy = AdaptivePolicy()
        for _ in range(8):
            for c in make_contexts(rng):
                obs = DecisionEnv(c, theta=0, screen_positive=False).observation()
                oracle = PublicPlanner(c).optimal(state_from_observation(obs))[0]
                achieved = expected_policy_loss(c, policy)
                self.assertAlmostEqual(oracle, achieved, places=7)
                table, p = loss_table(c), c["prior_severe_delay"]
                free_info = (1 - p) * min(row[0] for row in table) + p * min(row[1] for row in table)
                self.assertGreaterEqual(oracle + 1e-7, free_info)

    def test_oracle_agrees_with_independent_one_query_action_enumeration(self):
        c = context()
        c["budgets"].update(max_steps=3, max_queries=1, max_solver_calls=1)
        table, p = loss_table(c), c["prior_severe_delay"]
        def direct(posterior, cash):
            return min(c["tool_fees_usd"][tool] + (1 - posterior) * table[candidate_for_solver(c, posterior, tool)][0]
                       + posterior * table[candidate_for_solver(c, posterior, tool)][1]
                       for tool in SOLVERS if c["tool_fees_usd"][tool] <= cash)
        choices = [direct(p, 100)]
        # Enumerate the known screen likelihoods independently of the DP tree.
        pos = p * 0.8 + (1 - p) * 0.2
        choices.append(1 + pos * direct(p * 0.8 / pos, 99)
                       + (1 - pos) * direct(p * 0.2 / (1 - pos), 99))
        choices.append(10 + (1 - p) * direct(0, 90) + p * direct(1, 90))
        obs = DecisionEnv(c, theta=0, screen_positive=False).observation()
        self.assertAlmostEqual(PublicPlanner(c).optimal(state_from_observation(obs))[0], min(choices))

    def test_goal_variants_share_physics_but_change_the_best_dispatch(self):
        contexts = make_contexts(random.Random(8))
        baseline = physical_outcome(contexts[0], 4, 2)
        self.assertTrue(all(physical_outcome(c, 4, 2) == baseline for c in contexts))
        choices = [min(range(len(loss_table(c))), key=lambda q: loss_table(c)[q][1]) for c in contexts]
        self.assertGreater(len(set(choices)), 1)

    def test_context_rejects_unsupported_terminal_fees_and_nonfinite_physics(self):
        c = context()
        c["tool_fees_usd"]["commit_plan"] = 1
        with self.assertRaises(ValueError):
            validate_context(c)
        c = context()
        c["routes"]["air"]["freight_usd_per_kg"] = float("nan")
        with self.assertRaises(ValueError):
            validate_context(c)

    def test_audit_is_deterministic_and_does_not_assert_learning_is_needed(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = run_audit(output, tasks=3, seed=712)
            self.assertEqual(result["api_calls"], 0)
            self.assertEqual(result["trained_policies"], 0)
            self.assertEqual(result["task_configurations"], 9)
            self.assertFalse(result["learned_policy_research_justified"]["passed"])
            self.assertFalse(result["oracle"]["clairvoyant_lower_bound_is_achievable_policy"])
            self.assertTrue(verify_audit(output)["verified"])
            (output / "summary.json").write_text("{}")
            with self.assertRaises(ValueError):
                verify_audit(output)


if __name__ == "__main__":
    unittest.main()
