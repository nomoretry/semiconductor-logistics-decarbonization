"""Workflow safety, observability and physical terminal evaluation tests."""

import copy
import json
import unittest

import numpy as np

from notice_benchmark.tool_env import (
    ToolWorkflowEnv, audit_plan_feasibility, run_fixed_workflow,
)


def ready(changes=None):
    return {"status": "ready", "changes": [] if changes is None else changes}


def change(route="NL_ocean", start=1, end=1, value=2):
    return {"op": "add_lead", "route": route,
            "start_week": start, "end_week": end, "value": value}


def small_config():
    return {
        "company": "synthetic ASML-inspired test", "sku_names": ["synthetic_part"],
        "mass_kg": [1], "unit_value_usd": [1], "mean_order_units": [1],
        "zero_demand_probability": 0, "origin_capacity": [5],
        "route_origin": ["NL", "NL"], "eligibility": [[1], [1]],
        "routes": [
            {"name": "NL_air", "mode": "air", "lead": 1,
             "distance_km": 1000, "freight_usd_per_kg": 10, "capacity": 5},
            {"name": "NL_ocean", "mode": "ocean", "lead": 2,
             "distance_km": 1000, "freight_usd_per_kg": 1, "capacity": 5},
        ],
        "period": "week", "horizon": 5, "annual_carry_rate": 0,
        "warehouse_usd_per_unit_period": 0.01,
        "warehouse_kgco2e_per_unit_period": 0.01,
    }


def make_case(reference=None):
    return {
        "id": "DO_NOT_EXPOSE_CASE_ID", "event_id": "DO_NOT_EXPOSE_EVENT_ID",
        "category": "DO_NOT_EXPOSE_CATEGORY", "synthetic": True,
        "model_input": {"text": "Synthetic logistics notice.", "context": {
            "scope_route": "NL_ocean", "horizon": 5, "period": "week",
            "routes": [{"name": "NL_air", "lead": 1}, {"name": "NL_ocean", "lead": 2}],
        }},
        "reference": ready() if reference is None else reference,
        "annotation": {"hidden_marker": "DO_NOT_EXPOSE_ANNOTATION"},
    }


def make_env(reference=None, extracted=None, **kwargs):
    case = make_case(reference)
    output = case["reference"] if extracted is None else extracted
    return ToolWorkflowEnv(
        case, small_config(), np.array([[0], [0], [1], [0], [0]]),
        lambda text, context=None: copy.deepcopy(output),
        extractor_name="test_reference_upper_bound", initial_inventory=[0], **kwargs,
    )


class ToolWorkflowTests(unittest.TestCase):
    def test_noop_plan_is_solved_audited_and_committed(self):
        result = run_fixed_workflow(make_env())
        evaluation = result["evaluation"]
        self.assertTrue(evaluation["task_success"])
        self.assertTrue(evaluation["successful_shipping"])
        self.assertFalse(evaluation["correct_handoff"])
        self.assertEqual(evaluation["solver_calls"], 1)
        self.assertEqual([row["action"] for row in result["trace"]], [
            "inspect_notice", "extract_notice", "validate_update", "read_state",
            "solve_plan", "audit_plan", "commit_plan",
        ])
        self.assertTrue(evaluation["gate_requires_research"])

    def test_clarification_handoff_never_counts_as_shipping(self):
        result = run_fixed_workflow(make_env(reference={"status": "needs_clarification", "changes": []}))
        self.assertTrue(result["evaluation"]["correct_handoff"])
        self.assertTrue(result["evaluation"]["task_success"])
        self.assertFalse(result["evaluation"]["successful_shipping"])
        self.assertEqual(result["evaluation"]["solver_calls"], 0)
        self.assertEqual(result["trace"][-2]["response_summary"]["mode"], "offline_simulation_no_message_sent")

    def test_all_refusal_cannot_succeed_on_complete_information(self):
        result = run_fixed_workflow(make_env(extracted={"status": "needs_clarification", "changes": []}))
        self.assertFalse(result["evaluation"]["task_success"])
        self.assertFalse(result["evaluation"]["successful_shipping"])
        self.assertTrue(result["evaluation"]["unnecessary_handoff"])

    def test_hidden_reference_never_enters_policy_observations_or_mask(self):
        original = make_case(ready([change()]))
        mutated = make_case({"status": "needs_clarification", "changes": []})
        constructor = lambda case: ToolWorkflowEnv(
            case, small_config(), [[0], [0], [1], [0], [0]],
            lambda text, context=None: ready(), initial_inventory=[0],
        )
        first, second = constructor(original), constructor(mutated)
        self.assertEqual(first.observation(), second.observation())
        for action in ("inspect_notice", "extract_notice", "read_state", "validate_update"):
            a, b = first.step(action), second.step(action)
            self.assertEqual(a, b)
            text = json.dumps(a)
            self.assertNotIn("DO_NOT_EXPOSE", text)
            self.assertNotIn('"reference"', text)
        with self.assertRaises(RuntimeError):
            first.terminal_evaluation()

    def test_wrong_visible_plan_fails_under_true_announced_lead(self):
        result = run_fixed_workflow(make_env(reference=ready([change()]), extracted=ready()))
        self.assertFalse(result["evaluation"]["task_success"])
        self.assertFalse(result["evaluation"]["successful_shipping"])
        self.assertFalse(result["evaluation"]["compiled_parameters_match"])
        self.assertTrue(result["trace"][-2]["response_summary"]["valid"])
        self.assertIn("hard_period_service", result["evaluation"]["true_feasibility"]["violations"])
        self.assertGreater(result["evaluation"]["true_feasibility"]["actual_total_cost"], 1000)

    def test_correct_delayed_plan_succeeds_under_reference_parameters(self):
        result = run_fixed_workflow(make_env(reference=ready([change()])))
        self.assertTrue(result["evaluation"]["successful_shipping"])
        self.assertTrue(result["evaluation"]["compiled_parameters_match"])
        self.assertTrue(result["evaluation"]["true_feasibility"]["valid"])

    def test_unknown_and_unavailable_actions_have_no_business_side_effects(self):
        env = make_env()
        before = env.business_state_hash()
        response = env.step("send_real_email")
        self.assertFalse(response["info"]["valid_action"])
        self.assertEqual(before, env.business_state_hash())
        response = env.step("commit_plan")
        self.assertFalse(response["info"]["valid_action"])
        self.assertEqual(before, env.business_state_hash())
        self.assertFalse(env.terminated)

    def test_reextracting_invalidates_plan_and_prevents_stale_commit(self):
        env = make_env()
        for action in ("inspect_notice", "extract_notice", "validate_update", "read_state", "solve_plan", "audit_plan"):
            env.step(action)
        self.assertTrue(env.action_mask()["commit_plan"])
        env.step("extract_notice")
        self.assertFalse(env.action_mask()["commit_plan"])
        self.assertFalse(env.observation()["flags"]["plan_computed"])
        self.assertFalse(env.step("commit_plan")["info"]["valid_action"])

    def test_step_and_solver_budgets_cannot_be_exceeded(self):
        env = make_env(max_steps=2)
        env.step("read_state")
        result = env.step("read_state")
        self.assertTrue(result["terminated"])
        self.assertEqual(result["info"]["evaluation"]["terminal_reason"], "step_budget_exhausted")
        self.assertFalse(result["info"]["evaluation"]["task_success"])
        with self.assertRaises(RuntimeError):
            env.step("inspect_notice")
        env = make_env(max_solver_calls=1)
        for action in ("inspect_notice", "extract_notice", "validate_update", "read_state", "solve_plan"):
            env.step(action)
        self.assertFalse(env.action_mask()["solve_plan"])
        self.assertFalse(env.step("solve_plan")["info"]["valid_action"])
        result = run_fixed_workflow(env)
        self.assertEqual(result["evaluation"]["solver_calls"], 1)

    def test_valid_unused_reads_are_not_masked_into_an_oracle_sequence(self):
        env = make_env()
        self.assertTrue(env.action_mask()["read_state"])
        env.step("read_state")
        self.assertTrue(env.action_mask()["read_state"])
        env.step("inspect_notice")
        self.assertTrue(env.action_mask()["inspect_notice"])
        self.assertTrue(env.action_mask()["read_state"])
        self.assertTrue(env.action_mask()["request_clarification"])
        self.assertTrue(env.action_mask()["extract_notice"])

    def test_trace_replays_but_walltime_is_separate(self):
        first = run_fixed_workflow(make_env())
        second = run_fixed_workflow(make_env())
        self.assertEqual(first["trace"], second["trace"])
        self.assertEqual(first["evaluation"], second["evaluation"])
        self.assertNotIn("solver_wall_seconds", json.dumps(first["trace"]))
        self.assertGreater(first["runtime"]["solver_wall_seconds"], 0)
        self.assertNotIn("DO_NOT_EXPOSE", json.dumps(first["trace"]))

    def test_audit_ignores_success_claim_and_recomputes_constraints(self):
        plan = {"success": True, "orders": [[[0], [1]]] + [[[0], [0]]] * 4,
                "inventory": [[0], [0], [0], [0], [0]], "backlog": [[0]] * 5,
                "total_cost": -99999, "total_emissions": -99999}
        audit = audit_plan_feasibility(
            small_config(), [[0], [0], [1], [0], [0]], plan,
            initial_inventory=[0], carbon_cap=0,
        )
        self.assertFalse(audit["valid"])
        self.assertIn("carbon_budget", audit["violations"])
        self.assertGreater(audit["actual_total_cost"], 0)
        self.assertGreater(audit["actual_total_emissions"], 0)


if __name__ == "__main__":
    unittest.main()
