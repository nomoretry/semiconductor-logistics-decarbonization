"""Protocol regression tests for information, physical replay and optimal ties."""
import json
import tempfile
import unittest
from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from decision_graph_qa.dataset import CONFIG, build, read
from decision_graph_qa.graph import compact, context, make_graph, predictions
from decision_graph_qa.planner import (
    AuditFailure,
    Model,
    PlannerMismatch,
    feasible_plan,
    scenarios,
    solve_counts,
)
from decision_graph_qa.replay import recheck, score, verify, verify_forecasts
from decision_graph_qa.scoring import answer_map, grade_graph, matches
from rolling_inventory.environment import Environment, generate
from rolling_inventory.planning import base_stock, decide, solve


class GraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = generate(read(CONFIG), "test", [37])[0]
        env = Environment(cls.task)
        for _ in range(10):
            env.step(base_stock(env.observe(), 0)[0])
        cls.obs = env.observe()
        cls.graph = make_graph(cls.task, "base_stock", cls.obs, Counter())

    def test_future_changes_only_hindsight(self):
        changed = deepcopy(self.task)
        changed["demand"][10:] = [[500, 300, 400], [0, 0, 0]]
        env = Environment(changed)
        for _ in range(10):
            env.step(base_stock(env.observe(), 0)[0])
        other = make_graph(changed, "base_stock", env.observe(), Counter())
        original = deepcopy(self.graph)
        self.assertNotEqual(other.pop("hindsight"), original.pop("hindsight"))
        self.assertEqual(compact(original), compact(other))

    def test_identical_graph_bytes(self):
        other = make_graph(self.task, "base_stock", self.obs, Counter())
        self.assertEqual(compact(other).encode(), compact(self.graph).encode())

    def test_reference_and_scenario_order(self):
        env = Environment(self.task)
        for t in range(11):
            obs = env.observe()
            if t in (0, 6, 9, 10):
                demands = scenarios(obs)
                plan, info = solve(obs, demands)
                model = Model(obs, demands)
                output = model.optimize("comparison")
                self.assertIsNotNone(output)
                self.assertAlmostEqual(model.value(output), info["objective"], places=6)
                self.assertEqual(plan[0], decide(obs, "mpc_scenarios")[0])
            env.step(base_stock(obs, 0)[0])

    def test_mismatch_is_a_hard_failure(self):
        model = Model(self.obs, scenarios(self.obs))
        plan = answer_map(self.graph)["M"]
        with self.assertRaises(PlannerMismatch):
            model.audit(plan, self.graph["objective"] + 1)

    def test_presolve_false_infeasibility(self):
        obs = read(Path(__file__).with_name("fixtures") / "decision_graph_qa_failed_observation.json")
        demands = scenarios(obs)
        plan, info = solve(obs, demands)
        model = Model(obs, demands)
        audit = model.audit(plan, info["objective"])
        self.assertEqual(audit["load_ranges"][1], [4, 4])
        self.assertEqual(audit["emission_range"], [16, 16])
        self.assertFalse(audit["other_action"])
        counts = solve_counts(model.counts)
        recovered = counts["presolve_retry_recovered"].get("face_endpoint", 0)
        self.assertGreaterEqual(recovered, 1)
        self.assertEqual(counts["solves"]["face_endpoint"], 6 + recovered)

    def test_endpoint_failures_report_status_and_cost(self):
        model = Model(self.obs, scenarios(self.obs))
        unavailable = SimpleNamespace(status=2, x=None, fun=None, message="infeasible")
        with patch("decision_graph_qa.planner.milp", return_value=unavailable) as milp, self.assertRaisesRegex(
            AuditFailure, "infeasible after presolve-off retry"
        ) as ctx:
            model.optimize("face_endpoint", endpoint=("load.1.max", 0.0))
        self.assertEqual(ctx.exception.diagnostics, {
            "endpoint": "load.1.max", "statuses": [2, 2], "solver_message": "infeasible",
            "plan": None, "model_objective": None, "physical_cost": None, "ceiling": 0.0,
        })
        self.assertFalse(milp.call_args.kwargs["options"]["presolve"])
        with self.assertRaisesRegex(AuditFailure, "replay above ceiling") as ctx:
            model.optimize("face_endpoint", target={}, endpoint=("load.1.min", -1.0))
        diagnostics = ctx.exception.diagnostics
        self.assertEqual(diagnostics["statuses"], [0])
        self.assertEqual(diagnostics["model_objective"], 0.0)
        self.assertGreater(diagnostics["physical_cost"], diagnostics["ceiling"])
        self.assertTrue(feasible_plan(self.obs, diagnostics["plan"]))

    def test_endpoint_failure_stops_build_and_retains_diagnostics(self):
        failure = AuditFailure("face endpoint infeasible after presolve-off retry", {"statuses": [2, 2]})
        for pilot in (True, False):
            with self.subTest(pilot=pilot), tempfile.TemporaryDirectory() as tmp, (
                    patch("decision_graph_qa.dataset.pilot_gate")
                ), patch("decision_graph_qa.dataset.make_graph", side_effect=failure) as make:
                directory = Path(tmp) / "build"
                summary = build(directory, pilot=pilot, pilot_evidence=Path(tmp))
                self.assertEqual(make.call_count, 1)
                self.assertEqual((summary["status"], summary["failures"]), ("failed", 1))
                row = json.loads((directory / "attempts.jsonl").read_text(encoding="utf-8"))
                self.assertEqual(row["diagnostics"], failure.diagnostics)
                self.assertEqual(summary["stop_reason"], f"{row['id']}: {failure}")

    def test_gold_and_fixed_perturbation(self):
        counts = Counter()
        gold = grade_graph(self.graph, answer_map(self.graph), counts)
        self.assertEqual(len(gold), 31)
        self.assertTrue(all(r["correct"] and not r["violation"] for r in gold))
        self.assertEqual(gold[-1]["l1"], 0)
        self.assertEqual(counts["score_constraint"], 7)
        changed = grade_graph(self.graph, answer_map(self.graph, True), counts)
        self.assertEqual([r["id"] for r in changed if not r["correct"]],
                         ["P1.stock.0", "P2.capacity", "P3.emission", "B", "M"])
        self.assertEqual(sum(r["violation"] for r in changed), 3)

    def test_alternate_optimal_and_suboptimal(self):
        task = deepcopy(self.task)
        p = task["public"]
        p.update(periods=2, horizon=2, initial_inventory=[0, 0, 0], initial_pipeline=[[0]*3]*2,
                 mass=[1, 1, 1], capacity=[0, 1], base_mean=[0., 0., 0.],
                 holding=[1, 1, 1], backlog=[10, 10, 10], terminal_backlog=[0, 0, 0])
        task["demand"] = [[0, 0, 0]]*2
        obs = Environment(task).observe()
        obs["stock"] = [0, 0, 20]
        obs["backlog"] = [4, 4, 0]
        obs["forecast"] = [[0, 0, 0]]*2
        g = make_graph(task, "mpc_scenarios", obs, Counter())
        self.assertEqual(g["ties"]["opposite_flags"], [True, True, False])
        self.assertTrue(g["ties"]["other_action"])
        gold = answer_map(g)
        alternate = [gold["B"][1], gold["B"][0], gold["B"][2]]
        replies = {"B": alternate, "M": [alternate, gold["M"][1]],
                   "P3.ship.0": not gold["P3.ship.0"], "P3.ship.1": not gold["P3.ship.1"]}
        rows = [r for r in grade_graph(g, replies, Counter()) if r["provided"]]
        self.assertTrue(all(r["correct"] for r in rows))
        self.assertEqual(rows[-1]["l1"], 2)
        worse = {"B": [[0, 0]]*3, "P3.load.1": 0}
        for row in grade_graph(g, worse, Counter()):
            if row["provided"]:
                self.assertFalse(row["correct"])
                self.assertFalse(row["violation"])

    def test_window_budget_route_and_types(self):
        obs = deepcopy(self.obs)
        bad = [[1, 0], [0, 0], [0, 0]]
        self.assertFalse(feasible_plan(obs, [bad], first=True))
        obs["carbon_remaining"] = 3
        self.assertFalse(feasible_plan(obs, [[[0, 1], [0, 0], [0, 0]]], first=True))
        for value in (True, 0.5, 10**30, -1):
            self.assertFalse(feasible_plan(obs, [[[0, value], [0, 0], [0, 0]]], first=True))
        self.assertFalse(matches(1, True))
        self.assertFalse(matches(None, False))
        self.assertTrue(matches(1.0, 1.000001))
        self.assertFalse(matches([1], [1.0]))

    def test_edges_and_context(self):
        g = self.graph
        positions = {n["id"]: i for i, n in enumerate(g["nodes"])}
        self.assertTrue(all(positions[e["from"]] < positions[e["to"]] for e in g["edges"]))
        self.assertEqual(Counter(e["layer"] for e in g["edges"]), {"task": 51, "object": 12})
        fake = {key: "REPLY_" + key + "_END" for key in positions}
        for lang in ("zh", "en"):
            no, chain, graph = [context(g, "B", mode, lang, fake) for mode in g["modes"]]
            self.assertNotIn("REPLY_", no)
            self.assertIn("REPLY_P3.ship.2_END", chain)
            self.assertNotIn("REPLY_P1.stock.2_END", chain)
            self.assertEqual(graph.count("REPLY_P1.stock.2_END"), 1)
            self.assertNotIn("REPLY_B_END", graph)
            self.assertNotIn("hindsight", graph)

    def test_scalar_forecast_replay(self):
        obs = deepcopy(self.obs)
        obs.update(stock=[1, 0, 0], backlog=[0, 0, 0], forecast=[[1, 0, 0], [2, 0, 1]])
        obs["pipeline"][11] = [1, 0, 0]
        ans = predictions(obs, obs["forecast"])
        self.assertEqual((ans["P2.first.0"], ans["P2.peak.0"], ans["P2.first.1"]), (1, 1, None))
        verify_forecasts(obs, obs["forecast"], ans)

    def test_offline_manifest_trajectory_scoring_and_sampling(self):
        task = self.task
        with tempfile.TemporaryDirectory() as tmp, (
                patch("decision_graph_qa.dataset.trajectories", return_value=[(task, "base_stock")])
            ), patch("decision_graph_qa.replay.trajectories", return_value=[(task, "base_stock")]):
            directory = Path(tmp) / "pilot"
            result = build(directory, pilot=True)
            self.assertEqual(result["graphs"], 11)
            with patch("decision_graph_qa.planner.milp", side_effect=AssertionError), (
                    patch("decision_graph_qa.planner.solve", side_effect=AssertionError)):
                self.assertEqual(verify(directory)["verified"], 11)
            self.assertEqual(recheck(directory, 0.1)["verified"], 2)
            records = [json.loads(line) for line in (directory / "test.jsonl").read_text(
                encoding="utf-8").splitlines()]
            answers = Path(tmp) / "answers.jsonl"
            answers.write_text("\n".join(compact({"id": g["id"], "answers": answer_map(g)})
                                         for g in records), encoding="utf-8")
            self.assertEqual(score(directory, answers)["accuracy"], 1.)
            with (directory / "test.jsonl").open("a", encoding="utf-8") as file:
                file.write(" ")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                verify(directory)

