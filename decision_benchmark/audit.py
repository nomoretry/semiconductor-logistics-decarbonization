"""Development-only audit: known-order information choices before any training."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import tempfile
import time

from .env import DecisionEnv
from .model import SOLVERS, canonical, clone, digest, loss_table, physical_outcome, score_outcome
from .policies import AdaptivePolicy, PublicPlanner, policies, run_policy, state_from_observation


ROOT = Path(__file__).resolve().parents[1]
GOALS = ("cost", "service", "carbon")


def make_contexts(rng):
    quantity, mass = rng.choice((6, 8, 10, 12, 16)), rng.choice((1, 2, 3))
    air_price, ocean_price = rng.choice((6, 9, 12)), rng.choice((1, 2))
    air_carbon = rng.choice((3.0, 4.0, 5.0))
    air_unit = air_price * mass
    physical = {
        "synthetic": True, "scope": "known committed order; unresolved announced ocean delay; no unknown demand",
        "notice": "Ocean dispatches have an announced unresolved delay of either zero or two additional weeks. The carrier status screen is imperfect; an offline clarification confirms the delay.",
        "committed_order": {"quantity": quantity, "due_week": 3, "sku": "synthetic_spare_part"},
        "horizon_weeks": 5, "mass_kg_per_unit": mass,
        "routes": {"air": {"lead_weeks": 1, "freight_usd_per_kg": air_price, "kgco2e_per_kg": air_carbon},
                   "ocean": {"lead_weeks": 2, "freight_usd_per_kg": ocean_price, "kgco2e_per_kg": 0.2}},
        "holding_usd_per_unit_week": rng.choice((0.25, 0.5)),
        "warehouse_kgco2e_per_unit_week": 0.01,
        "prior_severe_delay": rng.choice((0.03, 0.1, 0.2, 0.35, 0.5, 0.7, 0.9)),
        "query_model": {"sensitivity": rng.choice((0.65, 0.8, 0.9)),
                        "specificity": rng.choice((0.65, 0.8, 0.9))},
        "tool_fees_usd": {"query_status": rng.choice((1, 3, 8)),
                          "request_clarification": rng.choice((3, 10, 30, 80)),
                          "solve_nominal": 1, "solve_robust": rng.choice((3, 6)),
                          "solve_bayes": rng.choice((2, 8, 15)), "commit_plan": 0, "handoff": 0},
        "budgets": {"max_steps": rng.choice((2, 3, 4, 5)), "max_solver_calls": rng.choice((1, 2)),
                    "max_queries": rng.choice((1, 2)), "tool_budget_usd": rng.choice((4, 8, 16, 32, 80, 160))},
        "invalid_action_fee_usd": 2,
    }
    max_carbon = quantity * mass * air_carbon + 1
    goal_parameters = {
        "cost": {"late_unit_week_penalty_usd": 2.5 * air_unit, "carbon_price_usd_per_kgco2e": 0.1,
                 "carbon_budget_kgco2e": max_carbon * 1.1,
                 "carbon_excess_penalty_usd_per_kgco2e": 0, "minimum_on_time_fill_rate": 0.9},
        "service": {"late_unit_week_penalty_usd": 12 * air_unit, "carbon_price_usd_per_kgco2e": 0,
                    "carbon_budget_kgco2e": max_carbon * 1.1,
                    "carbon_excess_penalty_usd_per_kgco2e": 0, "minimum_on_time_fill_rate": 1.0},
        "carbon": {"late_unit_week_penalty_usd": 1.5 * air_unit, "carbon_price_usd_per_kgco2e": 12,
                   "carbon_budget_kgco2e": max_carbon * 0.45,
                   "carbon_excess_penalty_usd_per_kgco2e": 5, "minimum_on_time_fill_rate": 0.8},
    }
    result = []
    for goal_name in GOALS:
        context = clone(physical)
        context["goal"] = {"name": goal_name, **goal_parameters[goal_name]}
        context["unshipped_order_loss_usd"] = 10 * max(max(row) for row in loss_table(context)) + 100
        result.append(context)
    return result


def _enumerate_runs(context, policy):
    prior, model = context["prior_severe_delay"], context["query_model"]
    for theta, probability in ((0, 1 - prior), (2, prior)):
        positive = model["sensitivity"] if theta == 2 else 1 - model["specificity"]
        for signal, conditional in ((False, 1 - positive), (True, positive)):
            weight = probability * conditional
            if weight > 0:
                yield weight, run_policy(DecisionEnv(context, theta=theta, screen_positive=signal), policy)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def _initial(context):
    return DecisionEnv(context, theta=0, screen_positive=False).observation()


def _counterfactual_checks(context):
    """Same public context, changed private truth; same truth, changed public costs."""
    a, b = (DecisionEnv(context, theta=theta, screen_positive=False) for theta in (0, 2))
    if a.observation() != b.observation():
        raise AssertionError("Hidden delay leaked in initial observation or mask")
    # All noninformative solver responses/candidate IDs must be identical.
    legal_solver = next(tool for tool in SOLVERS if a.action_mask()[tool])
    if a.step({"tool": legal_solver}) != b.step({"tool": legal_solver}):
        raise AssertionError("Solver candidate or legal mask leaked private delay")
    planner, initial = PublicPlanner(context), state_from_observation(_initial(context))
    original_value, original_action = planner.optimal(initial)
    cheap, expensive, relaxed = clone(context), clone(context), clone(context)
    for tool in ("query_status", "request_clarification"):
        cheap["tool_fees_usd"][tool] = 1
        expensive["tool_fees_usd"][tool] = 1000
    relaxed["budgets"] = {"max_steps": 6, "max_solver_calls": 3, "max_queries": 2, "tool_budget_usd": 2000}
    cheap_action = PublicPlanner(cheap).optimal(state_from_observation(_initial(cheap)))[1]
    expensive_action = PublicPlanner(expensive).optimal(state_from_observation(_initial(expensive)))[1]
    relaxed_value = PublicPlanner(relaxed).optimal(state_from_observation(_initial(relaxed)))[0]
    normal, delayed = physical_outcome(context, context["committed_order"]["quantity"], 0), physical_outcome(context, context["committed_order"]["quantity"], 2)
    return {"hidden_state_noninterference": True,
            "physical_delay_changes_service": normal["on_time_fill_rate"] != delayed["on_time_fill_rate"],
            "query_price_changes_optimal_first_action": cheap_action != expensive_action,
            "relaxing_budgets_improves_expected_loss": relaxed_value < original_value - 1e-7,
            "budget_relaxation_gain_usd": max(0.0, original_value - relaxed_value),
            "optimal_first_action": original_action[0]}


def run_audit(output: Path, tasks: int = 200, seed: int = 20261031):
    if type(tasks) is not int or tasks < 1:
        raise ValueError("tasks must be a positive number of physical contexts")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    methods = policies()
    task_rows, outcomes, counterfactuals, runtime_rows = [], [], [], []
    aggregate = {name: {"task_success": 0, "shipment_committed": 0, "realized_all_in_loss_usd": 0.0,
                        "expected_all_in_loss_usd": 0.0, "expected_regret_usd": 0.0,
                        "normalized_expected_regret": 0.0, "tool_fees_usd": 0.0,
                        "queries": 0, "solver_calls": 0, "steps": 0,
                        "logistics_cost_usd": 0.0, "emissions_kgco2e": 0.0,
                        "on_time_fill_rate": 0.0} for name in methods}
    first_actions, query_counts = Counter(), Counter()
    adaptive_branch_contexts = goal_change_families = solver_consequence_contexts = 0
    expected_oracle_residual = 0.0
    physical_success_ceiling_sum = realized_physical_success_possible = 0.0
    perfect_information_values, bayes_values, best_fixed_values = [], [], []
    with (output / "traces.jsonl").open("wb") as stream:
        for group in range(tasks):
            contexts = make_contexts(rng)
            prior = contexts[0]["prior_severe_delay"]
            theta = 2 if rng.random() < prior else 0
            query_model = contexts[0]["query_model"]
            positive_probability = query_model["sensitivity"] if theta == 2 else 1 - query_model["specificity"]
            signal = rng.random() < positive_probability
            goal_best_plans = []
            for context in contexts:
                goal = context["goal"]["name"]
                task_id = f"decision-development-{group:05d}-{goal}"
                task_rows.append({"task_id": task_id, "physical_context_group": f"physical-{group:05d}",
                                  "synthetic": True, "context": context,
                                  "private_evaluation_world": {"ocean_delay_weeks": theta, "screen_positive": signal}})
                obs = _initial(context)
                planning_started = time.perf_counter()
                planner, state = PublicPlanner(context), state_from_observation(obs)
                optimal_value, optimal_action = planner.optimal(state)
                runtime_rows.append({"task_id": task_id,
                    "public_bayes_dp_root_compute_wall_seconds": time.perf_counter() - planning_started,
                    "cached_bellman_states": planner._solve.cache_info().currsize})
                bayes_values.append(optimal_value)
                first_actions[optimal_action[0]] += 1
                table = planner.table
                feasible_by_theta = []
                for possible_theta in (0, 2):
                    feasible_by_theta.append(any(
                        all(score_outcome(context, physical_outcome(context, q, possible_theta))[field]
                            for field in ("service_success", "carbon_budget_met"))
                        for q in range(len(table))))
                physical_success_ceiling_sum += (1 - prior) * feasible_by_theta[0] + prior * feasible_by_theta[1]
                realized_physical_success_possible += feasible_by_theta[int(theta == 2)]
                goal_best_plans.append(min(range(len(table)), key=lambda q: (table[q][int(theta == 2)], q)))
                perfect_information_values.append((1 - prior) * min(row[0] for row in table)
                                                  + prior * min(row[1] for row in table))
                nominal, robust = planner.candidate(prior, "solve_nominal"), planner.candidate(prior, "solve_robust")
                solver_consequence_contexts += int(nominal != robust)
                counterfactuals.append({"task_id": task_id, **_counterfactual_checks(context)})
                fixed_values, bayes_branch_actions = [], set()
                for name, policy in methods.items():
                    result = run_policy(DecisionEnv(context, theta=theta, screen_positive=signal), policy)
                    evaluation = result["evaluation"]
                    expected = 0.0
                    for weight, branch in _enumerate_runs(context, policy):
                        expected += weight * branch["evaluation"]["all_in_loss_usd"]
                        if name == "public_bayes_dp":
                            bayes_branch_actions.add(tuple((row["action"]["tool"], row["action"].get("candidate_id"))
                                                           for row in branch["trace"]))
                    if name == "public_bayes_dp":
                        expected_oracle_residual = max(expected_oracle_residual, abs(expected - optimal_value))
                        query_counts[evaluation["queries"]] += 1
                    if name.startswith("fixed_"):
                        fixed_values.append(expected)
                    regret = expected - optimal_value
                    if regret < -1e-6:
                        raise AssertionError("A public policy beat the purported Bayes oracle")
                    row = aggregate[name]
                    for field in ("task_success", "shipment_committed", "tool_fees_usd", "queries", "solver_calls", "steps"):
                        row[field] += evaluation[field]
                    row["realized_all_in_loss_usd"] += evaluation["all_in_loss_usd"]
                    row["expected_all_in_loss_usd"] += expected
                    row["expected_regret_usd"] += max(0.0, regret)
                    row["normalized_expected_regret"] += max(0.0, regret) / max(1.0, optimal_value)
                    physical = evaluation["physical_outcome"]
                    if physical:
                        for field in ("logistics_cost_usd", "emissions_kgco2e", "on_time_fill_rate"):
                            row[field] += physical[field]
                    trace = {"task_id": task_id, "method": name, "trace": result["trace"]}
                    stream.write(canonical(trace) + b"\n")
                    outcomes.append({"task_id": task_id, "method": name, "evaluation": evaluation,
                                     "exact_public_model_expected_loss_usd": expected,
                                     "public_bayes_optimal_expected_loss_usd": optimal_value,
                                     "expected_regret_usd": max(0.0, regret), "trace_sha256": digest(trace)})
                best_fixed_values.append(min(fixed_values))
                adaptive_branch_contexts += int(len(bayes_branch_actions) > 1)
            goal_change_families += int(len(set(goal_best_plans)) > 1)
    configurations = tasks * len(GOALS)
    for row in aggregate.values():
        row["runs"] = configurations
        row["task_success_rate"] = row["task_success"] / configurations
        for key in ("realized_all_in_loss_usd", "expected_all_in_loss_usd", "expected_regret_usd",
                    "normalized_expected_regret", "tool_fees_usd", "queries", "solver_calls", "steps",
                    "logistics_cost_usd", "emissions_kgco2e", "on_time_fill_rate"):
            row[f"mean_{key}"] = row[key] / configurations
    best_fixed_name = min((name for name in aggregate if name.startswith("fixed_")),
                          key=lambda name: aggregate[name]["mean_expected_all_in_loss_usd"])
    query_fraction = sum(count for tool, count in first_actions.items()
                         if tool in ("query_status", "request_clarification")) / configurations
    checks = {
        "all_hidden_state_noninterference_checks_pass": all(row["hidden_state_noninterference"] for row in counterfactuals),
        "physical_delay_changes_service_fraction": sum(row["physical_delay_changes_service"] for row in counterfactuals) / configurations,
        "solver_choice_changes_dispatch_fraction": solver_consequence_contexts / configurations,
        "goal_change_changes_optimal_dispatch_fraction": goal_change_families / tasks,
        "query_price_changes_optimal_action_fraction": sum(row["query_price_changes_optimal_first_action"] for row in counterfactuals) / configurations,
        "budget_relaxation_improves_expected_loss_fraction": sum(row["relaxing_budgets_improves_expected_loss"] for row in counterfactuals) / configurations,
        "bayes_queries_first_fraction": query_fraction,
        "bayes_bypasses_queries_first_fraction": 1 - query_fraction,
        "public_bayes_contingent_action_sequence_fraction": adaptive_branch_contexts / configurations,
        "best_fixed_workflow": best_fixed_name,
        "best_fixed_mean_normalized_regret": aggregate[best_fixed_name]["mean_normalized_expected_regret"],
        "bayes_dp_vs_exact_rollout_max_abs_residual_usd": expected_oracle_residual,
    }
    thresholds = {"minimum_consequence_fraction": 0.1, "minimum_query_and_bypass_fraction": 0.1,
                  "minimum_contingent_sequence_fraction": 0.05, "minimum_best_fixed_normalized_regret": 0.01,
                  "minimum_public_adaptive_normalized_regret_to_justify_learning": 0.01,
                  "oracle_rollout_tolerance_usd": 1e-6}
    gate_conditions = {
        "noninterference": checks["all_hidden_state_noninterference_checks_pass"],
        "physical_consequences": checks["physical_delay_changes_service_fraction"] >= 0.1,
        "solver_consequences": checks["solver_choice_changes_dispatch_fraction"] >= 0.1,
        "goal_consequences": checks["goal_change_changes_optimal_dispatch_fraction"] >= 0.1,
        "query_price_consequences": checks["query_price_changes_optimal_action_fraction"] >= 0.1,
        "budget_consequences": checks["budget_relaxation_improves_expected_loss_fraction"] >= 0.1,
        "query_and_bypass_both_optimal": min(query_fraction, 1 - query_fraction) >= 0.1,
        "contingent_sequences": checks["public_bayes_contingent_action_sequence_fraction"] >= 0.05,
        "strong_fixed_workflow_gap": checks["best_fixed_mean_normalized_regret"] > 0.01,
        "oracle_matches_exhaustive_rollouts": expected_oracle_residual <= 1e-6,
    }
    decision_gate = all(gate_conditions.values())
    # The exact planning oracle is an achievable reference, not a competing
    # non-oracle baseline in this diagnostic; including it makes a gap criterion
    # tautologically impossible. A simple adaptive rule can still close the gate.
    strong_names = ("adaptive_myopic_voi",)
    best_public_gap = min(aggregate[name]["mean_normalized_expected_regret"] for name in strong_names)
    research_conditions = {"decision_tradeoffs_present": decision_gate,
                           "strong_public_adaptive_rules_leave_material_gap": best_public_gap > 0.01}
    summary = {
        "schema_version": "known-order-decision-development-v1", "development_only": True,
        "canonical_final_executed": False, "physical_contexts": tasks, "goal_variants_per_context": len(GOALS),
        "task_configurations": configurations, "method_runs": configurations * len(methods), "seed": seed,
        "api_calls": 0, "trained_policies": 0,
        "scope": "Fixed known committed orders, finite integer air/ocean dispatches, unresolved announced delay, simulated costly information",
        "statistical_unit": "physical context; its goal variants share orders, routes, prior, budgets and sampled physical world",
        "methods": aggregate, "checks": checks, "thresholds": thresholds,
        "bayes_first_actions": dict(sorted(first_actions.items())),
        "bayes_realized_query_counts": {str(key): value for key, value in sorted(query_counts.items())},
        "oracle": {"public_bayes_dp_is_achievable_with_public_model": True,
                   "public_bayes_dp_mean_expected_loss_usd": sum(bayes_values) / configurations,
                   "clairvoyant_free_information_and_solver_lower_bound_mean_usd": sum(perfect_information_values) / configurations,
                   "clairvoyant_lower_bound_is_achievable_policy": False,
                   "expected_physical_service_and_carbon_feasibility_ceiling": physical_success_ceiling_sum / configurations,
                   "realized_physical_service_and_carbon_feasibility_ceiling": realized_physical_success_possible / configurations,
                   "per_context_best_fixed_workflow_mean_expected_loss_usd": sum(best_fixed_values) / configurations},
        "decision_tradeoffs_present": {"passed": decision_gate, "conditions": gate_conditions},
        "learned_policy_research_justified": {"passed": all(research_conditions.values()),
            "conditions": research_conditions, "non_oracle_adaptive_methods": list(strong_names),
            "best_public_adaptive_mean_normalized_regret": best_public_gap,
            "reason": "A substantive tool-choice gap alone does not establish a need for BC/PPO. Compare non-oracle adaptive rules with the exact public Bayes reference; a near-optimal simple adaptive rule keeps the research gate closed. Larger easy sample counts do not resolve this limitation."},
        "runtime_scope": "DP root compute seconds and cached state counts are saved separately in runtime.json; wall time is excluded from deterministic replay and the loss.",
        "limitations": ["Small synthetic finite task; not company data or production readiness evidence.",
                        "Goal scalarization coefficients and fees are disclosed synthetic design parameters.",
                        "No unknown future demand, rolling horizon, live clarification, API calls, or learned policy.",
                        "The development gate describes this generated suite; it is not a frozen held-out final result.",
                        "Policy CPU time is not priced; solver fees represent explicit simulated tool-use fees."],
    }
    _write(output / "tasks.json", task_rows)
    _write(output / "outcomes.json", outcomes)
    _write(output / "counterfactual_checks.json", counterfactuals)
    _write(output / "runtime.json", runtime_rows)
    _write(output / "summary.json", summary)
    sources = sorted((ROOT / "decision_benchmark").glob("*.py"))
    sources += [ROOT / "tests/test_decision_benchmark.py", ROOT / "docs/decision_environment.md"]
    manifest = {"schema_version": "decision-development-artifacts-v1", "api_calls": 0,
                "replay_command": f"python -m decision_benchmark.audit --tasks {tasks} --seed {seed} --output <new-directory>",
                "private_worlds_only_in_evaluation_artifacts": True,
                "deterministic_replay_excludes": ["runtime.json"],
                "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
                "file_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in sorted(output.iterdir()) if path.is_file() and path.name != "manifest.json"}}
    _write(output / "manifest.json", manifest)
    return summary


def verify_audit(output):
    output = Path(output).resolve()
    manifest = json.loads((output / "manifest.json").read_text())
    for field, base in (("source_sha256", ROOT), ("file_sha256", output)):
        for relative, expected in manifest[field].items():
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe audit path")
            target = base / path
            if target.is_symlink() or not target.resolve().is_relative_to(base.resolve()):
                raise ValueError("Audit path escapes its root")
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Audit identity mismatch: {relative}")
    summary = json.loads((output / "summary.json").read_text())
    with tempfile.TemporaryDirectory(prefix="decision-development-replay-") as temporary:
        replay = Path(temporary)
        run_audit(replay, summary["physical_contexts"], summary["seed"])
        for name in ("tasks.json", "outcomes.json", "summary.json", "traces.jsonl", "counterfactual_checks.json"):
            if (replay / name).read_bytes() != (output / name).read_bytes():
                raise ValueError(f"Deterministic decision replay mismatch: {name}")
    return {"verified": True, "physical_contexts": summary["physical_contexts"],
            "task_configurations": summary["task_configurations"], "api_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, default=200, help="Physical contexts, each evaluated under three public goals")
    parser.add_argument("--seed", type=int, default=20261031)
    parser.add_argument("--output", type=Path, default=ROOT / "benchmark_results/decision_development")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = verify_audit(args.output) if args.verify else run_audit(args.output, args.tasks, args.seed)
    if not args.verify:
        result = {key: result[key] for key in ("physical_contexts", "task_configurations", "method_runs",
                  "decision_tradeoffs_present", "learned_policy_research_justified")}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
