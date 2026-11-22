"""Regression tests for the decision graph evaluation protocol."""
import gzip
import tempfile
import unittest
from collections import Counter
from copy import deepcopy
from itertools import islice
from pathlib import Path
from unittest.mock import patch

from decision_graph_qa.ablation import ablation_action, split_by_sku, substitute
from decision_graph_qa.consequence import (
    Consequences,
    replay_trajectory,
    verify_comparison,
)
from decision_graph_qa.dataset import (
    CONFIG,
    POLICIES,
    SEEDS,
    digest,
    read,
    records,
    write,
)
from decision_graph_qa.eval_run import (
    ANSWER_FILE,
    ATTEMPTS,
    _pack,
    verify_eval,
    write_summary,
)
from decision_graph_qa.eval_statistics import bootstrap_clusters
from decision_graph_qa.evaluation import (
    ABSENT,
    MISSING_CONTEXT,
    empty_graph,
    evaluate_graph,
    render_answers,
)
from decision_graph_qa.graph import compact, context
from decision_graph_qa.planner import allowance, feasible_plan, tolerance
from decision_graph_qa.scoring import answer_map, grade_graph
from rolling_inventory.environment import generate

DATA = Path(__file__).resolve().parents[1] / "benchmark_results" / "decision_graph_qa_v1"


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = generate(read(CONFIG), "test", SEEDS["test"][:1])[0]
        graph_count = cls.task["public"]["periods"] - 1
        stream = records(DATA / "test.jsonl")
        try:
            first_path = list(islice(stream, len(POLICIES) * graph_count))
        finally:
            stream.close()
        cls.by_policy = {policy: [g for g in first_path if g["policy"] == policy] for policy in POLICIES}
        cls.graph = cls.by_policy["base_stock"][-1]

    def test_replay_reconstructs_both_frozen_behavior_trajectories(self):
        for policy, graphs in self.by_policy.items():
            with self.subTest(policy=policy):
                replayed = list(replay_trajectory(self.task, policy, graphs))
                self.assertEqual([graph["id"] for graph, _ in replayed], [g["id"] for g in graphs])
                for graph, env in replayed:
                    self.assertEqual(env.observe(), graph["observation"])

    def test_replay_rejects_a_changed_saved_observation(self):
        graphs = deepcopy(self.by_policy["base_stock"])
        graphs[1]["observation"]["carbon_remaining"] += 1
        with self.assertRaisesRegex(ValueError, "observation"):
            list(replay_trajectory(self.task, "base_stock", graphs))

    def test_gold_and_perturbed_actions(self):
        policy = self.graph["policy"]
        graph, env = list(replay_trajectory(self.task, policy, self.by_policy[policy]))[-1]
        counts = Counter()
        scorer = Consequences(env, graph, counts)
        gold = answer_map(graph)
        score = grade_graph(graph, gold, counts)
        self.assertTrue(all(row["correct"] for row in score))
        dispatch = next(row for row in score if row["id"] == "B")
        self.assertLessEqual(abs(dispatch["excess"]), tolerance(graph["objective"]))
        result = scorer.compare(gold["B"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reference"], result["actual"])
        self.assertEqual(result["delta"], {"cost": 0, "fill_rate": 0, "emissions": 0})
        verify_comparison(result)
        counter_before = counts.copy()
        hits_before = scorer.cache_hits
        self.assertEqual(scorer.compare(deepcopy(gold["B"])), result)
        self.assertEqual(scorer.cache_hits, hits_before + 1)
        self.assertEqual(counts, counter_before)
        bad = answer_map(graph, perturb=True)
        changed = grade_graph(graph, {"B": bad["B"]}, counts)
        self.assertTrue(next(row for row in changed if row["id"] == "B")["violation"])
        rejected = scorer.compare(bad["B"])
        self.assertEqual(rejected["status"], "violation")
        self.assertIsNone(rejected["delta"])

    def test_context_contains_direct_parent_questions_and_answers(self):
        graph = self.graph
        gold = answer_map(graph)
        own = {node["id"]: f"answer for {node['id']}" for node in graph["nodes"]}
        by_id = {node["id"]: node for node in graph["nodes"]}
        for answers in (gold, own):
            for lang in ("zh", "en"):
                for node in graph["nodes"]:
                    node_id = node["id"]
                    none, chain, full = (context(graph, node_id, mode, lang, answers) for mode in graph["modes"])
                    self.assertLessEqual(len(none), len(chain))
                    self.assertLessEqual(len(chain), len(full))
                    for edge in graph["edges"]:
                        if edge["to"] == node_id:
                            parent = edge["from"]
                            pair = by_id[parent]["question"][lang] + "\n" + compact(answers[parent])
                            self.assertIn(pair, chain)
                            self.assertIn(pair, full)

    def test_own_context_distinguishes_a_missing_reply_from_json_null(self):
        graph = self.graph
        by_id = {node["id"]: node["question"]["en"] for node in graph["nodes"]}
        reply = {"P2.first.0": None}
        prompts = {}

        def respond(key, prompt):
            prompts[key] = prompt
            return reply.get(key, ABSENT)

        answers, characters = render_answers(graph, "Chain", "own", "en", respond)
        self.assertEqual(answers, reply)
        self.assertEqual(characters, sum(map(len, prompts.values())))
        self.assertIn(by_id["P1.stock.0"] + "\n" + compact(MISSING_CONTEXT), prompts["P2.first.0"])
        self.assertIn(by_id["P2.first.0"] + "\nnull", prompts["P3.ship.0"])

    def test_substitutions_change_only_the_registered_inputs(self):
        obs = deepcopy(self.graph["observation"])
        # Use nonzero stock flows so the single-field replacement is observable.
        obs["backlog"][0] = 3
        obs["pipeline"][-1][0] = 4
        obs["carbon_remaining"] = 5
        frozen = deepcopy(obs)
        p = obs["public"]
        expected = {
            "I1": ("pipeline", [[0] * len(row) for row in obs["pipeline"]]),
            "I2": ("backlog", [0] * len(obs["backlog"])),
            "I3": ("forecast", [p["base_mean"]] * len(obs["forecast"])),
            "I4": ("carbon_remaining", p["carbon_budget"] * (p["periods"] - obs["t"]) / 12),
        }
        for item, (field, value) in expected.items():
            with self.subTest(item=item):
                modified = substitute(obs, item)
                self.assertEqual(modified, dict(obs, **{field: value}))
                self.assertEqual(obs, frozen)

    def test_sku_allocations_respect_original_caps(self):
        obs = self.graph["observation"]
        frozen = deepcopy(obs)
        parts = split_by_sku(obs)
        public = obs["public"]
        weights = [mean * mass for mean, mass in zip(public["base_mean"], public["mass"])]
        self.assertEqual(len(parts), len(weights))
        for part, weight in zip(parts, weights):
            fraction = weight / sum(weights)
            self.assertEqual(part["public"]["capacity"], [int(cap * fraction) for cap in public["capacity"]])
            self.assertAlmostEqual(allowance(part), allowance(obs) * fraction)
        for route, cap in enumerate(public["capacity"]):
            self.assertLessEqual(sum(part["public"]["capacity"][route] for part in parts), cap)
        self.assertLessEqual(sum(allowance(part) for part in parts), allowance(obs) + 1e-9)
        self.assertEqual(obs, frozen)

    def test_hindsight_action_is_taken_from_the_frozen_graph(self):
        counts = Counter()
        self.assertEqual(
            ablation_action(self.graph, "H", counts),
            self.graph["hindsight"]["first_action_with_known_demand"],
        )
        self.assertFalse(counts)

    def test_sku_plans_combine_into_a_feasible_dispatch(self):
        counts = Counter()
        graph = self.by_policy["base_stock"][0]
        action = ablation_action(graph, "I5", counts)
        self.assertTrue(feasible_plan(graph["observation"], [action], first=True))
        self.assertEqual(sum(counts.values()), len(graph["observation"]["public"]["mass"]))

    def test_bootstrap_keeps_both_policies_in_the_demand_path_cluster(self):
        rows = [
            {"split": "test", "profile": "stable", "seed": 1, "policy": "mpc_scenarios", "cost": 0},
            {"split": "test", "profile": "stable", "seed": 1, "policy": "base_stock", "cost": 2},
            {"split": "test", "profile": "volatile", "seed": 1, "policy": "base_stock", "cost": 10},
        ]
        for row in rows:
            row["unavailable"] = None
        metrics = ("cost", "unavailable")
        result = bootstrap_clusters(rows, metrics)
        self.assertEqual(result, bootstrap_clusters(list(reversed(rows)), metrics))
        self.assertEqual(result, {
            "paths": 2, "graphs": 3,
            "metrics": {
                "cost": {"n": 3, "mean": 4, "lower": 1, "upper": 10},
                "unavailable": {"n": 0, "mean": None, "lower": None, "upper": None},
            },
        })

    def test_verify_eval_rejects_summary_tampering_even_after_rehash(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            with gzip.open(out / ATTEMPTS, "wt", encoding="utf-8"):
                pass
            (out / ANSWER_FILE).write_text("", encoding="utf-8")
            write(out / "config.json", {"phase": "pilot", "periods": 12, "graph_ids": [], "prompt_files": []})
            write(out / "completion.json", {"status": "failed", "stop_reason": "fixture", "wall_seconds": 0.0})
            write(out / "environment.json", {})
            summary = write_summary(out)
            with (
                patch("decision_graph_qa.planner.milp", side_effect=AssertionError),
                patch("rolling_inventory.planning.milp", side_effect=AssertionError),
            ):
                self.assertEqual(verify_eval(out)["solver_calls"], 0)
                summary["attempted"] += 1
                summary_path = out / "summary.json"
                write(summary_path, summary)
                with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                    verify_eval(out)
                manifest_path = out / "manifest.json"
                manifest = read(manifest_path)
                manifest["files"]["summary.json"] = digest(summary_path)
                write(manifest_path, manifest)
                with self.assertRaisesRegex(ValueError, "recomputed evaluation summary differs"):
                    verify_eval(out)

    def test_evaluated_graph_round_trips_through_solver_free_artifacts(self):
        policy = self.graph["policy"]
        graph, env = list(replay_trajectory(self.task, policy, self.by_policy[policy]))[-1]
        gold = answer_map(graph)
        counts = Counter()
        row = {**empty_graph(graph), "baselines": {}, "ablations": {}, "errors": [],
               "failed_calls": 0, "cache_hits": 0}
        evaluate_graph(graph, env, gold, row, counts, 0, 0)
        row.update(solves=dict(counts), seconds=0.0)
        self.assertEqual(row["failed_calls"], 0)
        self.assertGreater(row["cache_hits"], 0)
        packed = _pack(row)
        self.assertEqual(len(packed["response_artifacts"]), 3)
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            with gzip.open(out / ATTEMPTS, "wt", encoding="utf-8", newline="\n") as raw:
                raw.write(compact(packed) + "\n")
            (out / ANSWER_FILE).write_text(compact({"id": graph["id"], "answers": gold}) + "\n", encoding="utf-8")
            write(out / "config.json", {"phase": "pilot", "periods": graph["observation"]["public"]["periods"],
                                         "graph_ids": [graph["id"]], "prompt_files": []})
            write(out / "completion.json", {"status": "complete", "stop_reason": "", "wall_seconds": 0.0})
            write(out / "environment.json", {})
            with (
                patch("decision_graph_qa.planner.milp", side_effect=AssertionError),
                patch("rolling_inventory.planning.milp", side_effect=AssertionError),
            ):
                summary = write_summary(out)
                verified = verify_eval(out)
            self.assertEqual(verified["verified"], 1)
            self.assertEqual(verified["solver_calls"], 0)
            gold_baseline = summary["baselines"]["gold"]["Graph"]["own"]
            self.assertEqual(gold_baseline["B"]["metrics"]["cost_delta"], {"n": 1, "mean": 0.0})
            self.assertEqual(gold_baseline["stages"]["P3"]["accuracy"], 1.0)
            self.assertEqual(summary["ablations"]["test"]["all"]["I5"]["graphs"], 1)
