"""Check the offline model grader against the frozen evaluator and raw evidence."""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from collections import Counter
from decimal import Decimal
from pathlib import Path

from decision_graph_qa.consequence import Consequences
from decision_graph_qa.evaluation import rule_answers
from decision_graph_qa.llm.data import (
    append_jsonl,
    digest,
    load_config,
    plan,
    read_jsonl,
    response_path,
)
from decision_graph_qa.llm.score import (
    _load_graphs,
    _paired,
    _replay,
    _row,
    _source,
    score,
    score_answers,
)
from decision_graph_qa.llm.transport import Prices, decode_response
from decision_graph_qa.planner import tolerance
from decision_graph_qa.scoring import answer_map


class LlmScoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()
        cls.graphs = _load_graphs(cls.config)

    def assert_close(self, actual, expected, delta):
        """Require equal structure, actions and verdicts; the last digits of a float differ between platforms."""
        if isinstance(expected, dict):
            self.assertEqual(actual.keys(), expected.keys())
            for key, value in expected.items():
                self.assert_close(actual[key], value, delta)
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected))
            for left, right in zip(actual, expected, strict=True):
                self.assert_close(left, right, delta)
        elif isinstance(expected, float):
            self.assertAlmostEqual(actual, expected, delta=delta)
        else:
            self.assertEqual(actual, expected)

    def test_gold_and_rule_match_frozen_scores_and_consequences(self):
        graph_ids = {graph["id"] for graph in self.graphs[:10]}
        path = _source(self.config, "evaluation", "attempts.jsonl.gz")
        with gzip.open(path, "rt", encoding="utf-8") as file:
            raw = {row["id"]: row for row in map(json.loads, file) if row["id"] in graph_ids}
        self.assertEqual(set(raw), graph_ids)
        checked = set()
        for graph, env in _replay(self.graphs, graph_ids):
            graph_id = graph["id"]
            checked.add(graph_id)
            questions = {node["id"] for node in graph["nodes"] if node["stage"] in ("P3", "B")}
            counts = Counter()
            compare = Consequences(env, graph, counts)
            with self.subTest(graph=graph_id):
                gold = score_answers(graph, {key: value for key, value in answer_map(graph).items()
                                             if key in questions}, compare, counts)
                self.assertEqual(set(gold["nodes"]), questions)
                self.assertTrue(all(node["correct"] for node in gold["nodes"].values()))
                self.assertLessEqual(abs(gold["nodes"]["B"]["excess"]), tolerance(graph["objective"]))
                self.assertEqual(gold["consequence"]["delta"], {"cost": 0, "fill_rate": 0, "emissions": 0})
                recorded = raw[graph_id]
                index = recorded["baselines"]["rule"]["None"]["gold"]["index"]
                expected = recorded["response_artifacts"][index]
                replies = {key: value for key, value in rule_answers(graph).items() if key in questions}
                self.assertEqual(replies, {key: expected["answers"][key] for key in questions})
                actual = score_answers(graph, replies, compare, counts)
                self.assertIsNone(actual["error"])
                self.assert_close(actual["nodes"], {node["id"]: node for node in expected["nodes"]
                                                    if node["id"] in questions}, tolerance(graph["objective"]))
                self.assert_close(actual["consequence"], expected["consequence"], 1e-9)
        self.assertEqual(checked, graph_ids)

    def test_pilot_artifacts_distinguish_parse_failure_violation_and_missing(self):
        selected = plan(self.config, "pilot", "S")
        graph_id = selected[0].graph
        graph = next(graph for graph in self.graphs if graph["id"] == graph_id)
        gold = answer_map(graph)["B"]
        texts = {"None": "text before JSON", "Chain": json.dumps(gold), "Graph": "null"}
        prices = Prices(*(Decimal(1) for _ in range(4)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for task in selected:
                if task.graph != graph_id:
                    continue
                body = {"status": "completed", "model": "synthetic-score-test",
                        "output": [{"type": "message", "content": [{"type": "output_text",
                                                                     "text": texts[task.context]}]}],
                        "usage": {"input_tokens": 24, "output_tokens": 10}}
                reply = decode_response(task, body, prices, transport="sync", seconds=0.1)
                append_jsonl(response_path(root, "pilot", "S"), reply)
                attempt = {"phase": "pilot", "task_key": task.custom_id, "request_hash": task.request_hash}
                append_jsonl(root / "ledger.jsonl", {**attempt, "event": "settle", "attempt_id": task.context,
                                                    "actual_usd": "0.000034", "charged_usd": "0.000034"})
                if task.context == "None":
                    # The previous invocation settled an uncertain charge for this same request.
                    append_jsonl(root / "ledger.jsonl", {**attempt, "event": "settle", "attempt_id": "prior",
                                                        "actual_usd": None, "charged_usd": "0.07"})
            result = score(root, "pilot", "S")
            output = response_path(root, "pilot", "S").parent
            self.assertEqual(result["expected_requests"], 96)
            self.assertEqual(result["terminal_requests"], 3)
            billing = result["cumulative_selected_task_ledger"]
            self.assertEqual(billing["settled_attempts"], 4)
            self.assertAlmostEqual(billing["settled_usd"], 0.070102)
            self.assertAlmostEqual(billing["settled_usage_usd"], 0.000102)
            self.assertEqual(billing["decisions_with_settlements"], 3)
            self.assertEqual(len(result["reference_timing"]["cases"]), 32)
            self.assertEqual(result["dq2_baselines"]["gold"]["graphs"], 32)
            references = result["statement_references"]
            self.assertEqual(references["graphs"], 32)
            self.assertEqual(references["text_only_program"]["correct"]["B"], 32)
            report = (output / "summary_pilot_S.md").read_text(encoding="utf-8")
            self.assertIn("| 只读题目文字的程序 | 1 | — |", report)
            self.assertIn("| Text-only program | 1 | — |", report)
            missing = result["contexts"]["None"]
            self.assertEqual(missing["statuses"], {"parse_failure": 1, "unattempted": 31})
            self.assertEqual(missing["primary"]["metrics"]["accuracy"]["mean"], 0)
            self.assertEqual(missing["primary"]["metrics"]["violation"]["n"], 0)
            self.assertEqual(missing["fallback_count"], 1)
            self.assertEqual(missing["fallback"]["metrics"]["cost_delta"]["n"], 1)
            self.assertEqual(missing["fallback"]["metrics"]["relative_plan_excess_pct"]["n"], 1)
            self.assertAlmostEqual(result["contexts"]["Chain"]["primary"]["metrics"]["relative_plan_excess_pct"]["mean"],
                                   0, places=6)
            self.assertEqual(result["contexts"]["Graph"]["violations"], 1)
            self.assertEqual(result["contexts"]["Graph"]["fallback_count"], 0)
            paired = result["paired"]["Chain − None"]["primary"]["metrics"]
            self.assertEqual((paired["accuracy"]["n"], paired["accuracy"]["mean"]), (1, 1))
            self.assertEqual(paired["cost_delta"]["n"], 0)
            null_answer = next(row for row in read_jsonl(output / "answers_pilot_S_Graph.jsonl")
                               if row["id"] == graph_id)
            self.assertEqual(null_answer["answers"], {"B": None})
            manifest = json.loads((output / "manifest_pilot_S.json").read_bytes())
            self.assertEqual(len(manifest["files"]), 6)
            for filename, expected in manifest["files"].items():
                self.assertEqual(digest(output / filename), expected)

    def test_p3_paired_metrics_match_questions_within_graph(self):
        graph = self.graphs[0]
        first, second, third, *_ = [node["id"] for node in graph["nodes"] if node["stage"] == "P3"]
        accepted = {"status": "ok"}
        wrong = {"status": "parse_failure"}
        correct = {"correct": True, "violation": False}
        left = _row(graph, "Chain", {first: wrong, second: accepted, third: None},
                    {"nodes": {second: correct}, "consequence": None, "error": None}, None)
        right = _row(graph, "None", {first: wrong, second: None, third: wrong},
                     {"nodes": {}, "consequence": None, "error": None}, None)
        result = _paired([left], [right], "p3")
        self.assertEqual(left["metrics"]["accuracy"], 0.5)
        self.assertEqual(right["metrics"]["accuracy"], 0)
        self.assertEqual(result["primary"]["metrics"]["accuracy"]["mean"], 0)
        self.assertEqual(result["per_question"][second]["metrics"]["accuracy"]["n"], 0)
        self.assertEqual(result["per_question"][third]["metrics"]["accuracy"]["n"], 0)


if __name__ == "__main__":
    unittest.main()
