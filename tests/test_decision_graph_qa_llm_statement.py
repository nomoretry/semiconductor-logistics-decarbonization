"""Check the self-contained v2 questions and the program that answers them from their text alone."""
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from collections import Counter
from fractions import Fraction
from itertools import islice
from pathlib import Path

from decision_graph_qa.dataset import records
from decision_graph_qa.llm import (
    independent_reading,
    reader,
    statement,
    statement_check,
)
from decision_graph_qa.llm.data import (
    PROTOCOLS,
    LlmError,
    digest,
    load_config,
    plan,
    prompts_by_graph,
    read_jsonl,
    require_open,
    response_path,
    results_root,
)
from decision_graph_qa.llm.rules import ANSWERED, RULES, SCENARIO_LABEL
from decision_graph_qa.planner import physical_cost, scenarios, tolerance
from decision_graph_qa.scoring import answer_map, grade_graph

DATA = Path(__file__).resolve().parents[1] / "benchmark_results" / "decision_graph_qa_v1"
QUESTIONS = ("P3.ship.0", "P3.load.1", "B")


def sample(split: str, step: int, limit: int) -> list[dict]:
    stream = records(DATA / f"{split}.jsonl")
    try:
        return list(islice((graph for index, graph in enumerate(stream) if index % step == 0), limit))
    finally:
        stream.close()


class StatementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Steps of 13 walk through demand paths, policies and decision periods, including the last one.
        cls.graphs = sample("dev", 13, 12)

    def test_statement_adds_rules_and_scenarios_to_the_frozen_prompt(self):
        config = load_config("v1")
        graph = sample("test", 29, 1)[0]
        old = prompts_by_graph(config, list(statement.MODES))
        for mode in statement.MODES:
            for question in QUESTIONS:
                text = statement.statement(graph, question, mode)
                blocks = text[len(RULES) + 2:].split("\n\n")
                self.assertTrue(text.startswith(f"{RULES}\n\n"))
                self.assertEqual(blocks[0], graph["state_text"]["en"])
                label, _, listed = blocks[1].partition(" = ")
                self.assertEqual(label, SCENARIO_LABEL)
                self.assertEqual(json.loads(listed), scenarios(graph["observation"]).tolist())
                asked = next(node["question"]["en"] for node in graph["nodes"] if node["id"] == question)
                self.assertEqual(blocks[-1], asked)
                self.assertEqual(text.count(ANSWERED), int(mode != "None"))
                self.assertEqual(statement_check.without_additions(text), old[mode][graph["id"]][question])

    def test_statement_does_not_contain_realized_demand_or_the_current_answer(self):
        for graph in self.graphs:
            gold = answer_map(graph)
            for mode in statement.MODES:
                text = statement.statement(graph, "B", mode)
                after = text.rpartition("\n\n")[2]
                self.assertNotIn(json.dumps(gold["B"], separators=(",", ":")), after)
                self.assertNotIn("hindsight", text)
                self.assertNotIn(json.dumps(gold["M"], separators=(",", ":")), text)

    def test_rules_match_the_protocol_document(self):
        document = PROTOCOLS["v2"].document.read_text(encoding="utf-8")
        for wording in (RULES, ANSWERED):
            self.assertEqual(document.count(f"```text\n{wording}\n```"), 1)
        self.assertEqual(document.count(f"`{SCENARIO_LABEL} = …`"), 2)

    def test_export_is_reproducible_and_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "prompts"
            manifest = statement.export(self.graphs[:2], out, {"manifest": "x", "sha256": "0"})
            self.assertEqual(manifest["prompts"], dict.fromkeys(statement.MODES, 14))
            self.assertEqual(statement.verify(self.graphs[:2], out, manifest), {"prompts": 42, "files": 3})
            loaded = statement_check.load_prompts(out)
            self.assertEqual(loaded["Chain"][self.graphs[0]["id"], "B"],
                             statement.statement(self.graphs[0], "B", "Chain"))
            with self.assertRaisesRegex(LlmError, "Rendered prompts differ"):
                statement.verify(self.graphs[1:3], out, manifest)
            (out / statement.prompt_file("None")).write_bytes(b"changed")
            with self.assertRaises((LlmError, OSError)):
                statement.verify(self.graphs[:2], out, manifest)


class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graphs = [*sample("dev", 13, 10), next(g for g in records(DATA / "dev.jsonl")
                                                   if g["observation"]["t"] == 10)]
        # The presolve failure that led to the second DQ-1 amendment occurred on this training graph.
        cls.hard = next(g for g in records(DATA / "train.jsonl") if g["id"] == "train-volatile-5101/base_stock/5")

    def test_reader_shares_only_the_wording_with_the_project(self):
        tree = ast.parse(Path(reader.__file__).read_text(encoding="utf-8"))
        relative = [(node.level, node.module) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                    and node.level]
        absolute = {name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                    for name in ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                                 else [node.module] if not node.level else [])}
        self.assertEqual(relative, [(1, "rules")])
        self.assertFalse([name for name in absolute if name.startswith(("decision_graph_qa", "rolling_inventory"))])

    def test_text_alone_reproduces_optimum_and_reference_grades(self):
        for graph in [*self.graphs, self.hard]:
            with self.subTest(graph=graph["id"]):
                problem = reader.parse(statement.statement(graph, "B", "None"))
                for mode in ("Chain", "Graph"):
                    self.assertEqual(reader.parse(statement.statement(graph, "P3.ship.1", mode)), problem)
                plan, value = reader.optimize(problem)
                self.assertLessEqual(abs(value - graph["objective"]), tolerance(graph["objective"]))
                self.assertLessEqual(abs(float(reader.exact_cost(problem, plan)) - graph["objective"]),
                                     tolerance(graph["objective"]))
                graded = [row for row in grade_graph(graph, reader.answers(problem, plan), Counter())
                          if row["provided"]]
                self.assertEqual(len(graded), 8)
                self.assertTrue(all(row["correct"] and not row["violation"] for row in graded))

    def test_exact_cost_follows_the_frozen_cost_and_rejects_violations(self):
        for graph in self.graphs:
            problem = reader.parse(statement.statement(graph, "B", "None"))
            plan = answer_map(graph)["M"]
            self.assertAlmostEqual(float(reader.exact_cost(problem, plan)),
                                   physical_cost(graph["observation"], plan, scenarios(graph["observation"])), places=9)
            self.assertIsInstance(reader.exact_cost(problem, plan), Fraction)
            for change, message in ((lambda x: x[0][0].__setitem__(0, 9), "route capacity"),
                                    (lambda x: x[-1][0].__setitem__(1, 1), "arrival after the window")):
                broken = json.loads(json.dumps(plan))
                change(broken)
                with self.assertRaisesRegex(reader.StatementError, message):
                    reader.exact_cost(problem, broken)
            tight = reader.Problem({**problem.state, "carbon_remaining": 0}, problem.demand)
            if any(any(row) for action in plan for row in action):
                with self.assertRaisesRegex(reader.StatementError, "window emissions"):
                    reader.exact_cost(tight, plan)

    def test_incomplete_statements_are_rejected(self):
        graph = self.graphs[0]
        text = statement.statement(graph, "B", "Graph")
        state = graph["state_text"]["en"]
        for changed, message in (
            (text.replace(RULES, ""), "rules"),
            (text.replace("at most public.capacity[j]", "below public.capacity[j]"), "rules"),
            (text.replace(state, state.replace("\nPast demand", "\nPast orders ((history)) = []\nPast demand")), "state"),
            (text.replace(state, "\n".join(state.split("\n")[1:])), "state"),
            (text.replace(SCENARIO_LABEL, "Demand"), "scenarios"),
            (text.replace(f"{SCENARIO_LABEL} = [", f"{SCENARIO_LABEL} = [[[0,0,0]],"), "window"),
            (text.replace(statement.scenario_line(graph["observation"]) + "\n\n", ""), "scenarios"),
        ):
            self.assertNotEqual(changed, text)
            with self.subTest(message=message), self.assertRaisesRegex(reader.StatementError, message):
                reader.parse(changed)

    def test_misreadings_never_beat_the_stated_optimum(self):
        graph = self.graphs[3]
        problem = reader.parse(statement.statement(graph, "B", "None"))
        grade = statement_check.Grader(graph, Counter())
        self.assertEqual(len(reader.MISREADINGS), 10)
        for name, reading in reader.MISREADINGS.items():
            with self.subTest(reading=name):
                changed = [field for field, value in vars(reading).items() if value != vars(reader.Reading())[field]]
                self.assertEqual(len(changed), 1)
                graded = grade(reader.optimize(problem, reading)[0][0])
                if not graded["violation"]:
                    self.assertGreaterEqual(graded["excess"], -tolerance(graph["objective"]))
        self.assertEqual(reader.optimize(problem), reader.optimize(problem, reader.Reading()))

    def test_fixed_dispatches_and_alternative_readings(self):
        graph = self.graphs[3]
        problem = reader.parse(statement.statement(graph, "B", "None"))
        plan, best = reader.optimize(problem)
        self.assertTrue(reader.optimal_under(problem, reader.Reading(), plan[0], best))
        self.assertFalse(reader.optimal_under(problem, reader.Reading(), [[9, 0], [0, 0], [0, 0]], best))
        with self.assertRaises(reader.InfeasibleDispatch):
            reader.optimize(problem, first=[[9, 0], [0, 0], [0, 0]])
        self.assertEqual(reader.optimize(problem, first=plan[0])[1], best)
        self.assertEqual(len(reader.ALTERNATIVES), 5)
        for name, reading in reader.ALTERNATIVES.items():
            with self.subTest(reading=name):
                changed = [field for field, value in vars(reading).items() if value != vars(reader.Reading())[field]]
                self.assertEqual(len(changed), 1)
                self.assertNotIn(reading, reader.MISREADINGS.values())
                self.assertIsInstance(reader.optimize(problem, reading)[1], float)


class CheckTests(unittest.TestCase):
    def test_check_rows_lead_to_the_summary_and_the_acceptance(self):
        graphs = sample("dev", 60, 3)
        prompts = {mode: {(graph["id"], node["id"]): statement.statement(graph, node["id"], mode) for graph in graphs
                          for node in graph["nodes"] if node["stage"] in statement.STAGES} for mode in statement.MODES}
        evidence = []
        for graph in graphs:
            grade = statement_check.Grader(graph, Counter())
            solved, misread = statement_check.text_only(graph, prompts, grade)
            picked = statement_check.assembly(graph, grade)
            self.assertEqual(solved["prompts"], 21)
            self.assertGreaterEqual(picked["candidates"], picked["correct"])
            self.assertGreaterEqual(picked["correct"], 1)
            self.assertGreaterEqual(picked["mean_excess"], -tolerance(graph["objective"]))
            hidden = statement_check.ceilings(graph, grade)
            self.assertEqual(len(hidden), 4)
            evidence.append({"id": graph["id"], "objective": graph["objective"], "text_only": solved,
                             "misreadings": misread, "v1_ceilings": hidden, "assembly": picked,
                             "v1_text_kept": 21, "v1_prompts_rejected": 21})
        summary = statement_check.summarize(evidence)
        self.assertEqual(summary["prompts"], {"parsed": 63, "v1_text_kept": 63, "v1_prompts_rejected": 63})
        self.assertEqual(set(summary["text_only_program"]["correct"].values()), {3})
        self.assertTrue(statement_check.accepted(summary))
        for field in ("v1_text_kept", "v1_prompts_rejected"):
            self.assertFalse(statement_check.accepted({**summary, "prompts": {**summary["prompts"], field: 62}}))
        text = summary["text_only_program"]
        for changed in ({"objective_equal": 2}, {"exact_cost_equal": 2}, {"violations": 1},
                        {"correct": {**text["correct"], "B": 2}}):
            self.assertFalse(statement_check.accepted({**summary, "text_only_program": {**text, **changed}}))


class ProtocolVersionTests(unittest.TestCase):
    def test_closed_version_and_foreign_root_are_refused(self):
        with self.assertRaisesRegex(LlmError, "closed to new requests"):
            require_open("v1")
        require_open("v2")
        self.assertEqual(results_root("v2", None), PROTOCOLS["v2"].root)
        for version, other in (("v1", "v2"), ("v2", "v1")):
            with self.assertRaisesRegex(LlmError, "another protocol version"):
                results_root(version, PROTOCOLS[other].root)
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(results_root("v2", Path(directory)), Path(directory))

    def test_v1_requests_are_reproduced_and_v2_changes_only_the_input(self):
        v1, v2 = load_config("v1"), load_config("v2")
        for key in v1.keys() - {"schema_version", "sources"}:
            self.assertEqual(v1[key], v2[key])
        for key in ("dataset_manifest", "dataset_sha256", "evaluation_manifest", "evaluation_sha256"):
            self.assertEqual(v1["sources"][key], v2["sources"][key])
        old, new = plan(v1, "pilot", "S"), plan(v2, "pilot", "S")
        recorded = {row["custom_id"]: row["request_hash"]
                    for row in read_jsonl(response_path(PROTOCOLS["v1"].root, "pilot", "S"))}
        self.assertEqual(len(recorded), 12)
        self.assertEqual({task.custom_id: task.request_hash for task in old if task.custom_id in recorded}, recorded)
        self.assertEqual([task.custom_id for task in old], [task.custom_id for task in new])
        self.assertEqual({task.custom_id for task in new[:12]}, set(recorded))
        for before, after in zip(old, new, strict=True):
            self.assertEqual({**after.body, "input": before.body["input"]}, before.body)
            self.assertEqual(statement_check.without_additions(after.body["input"]), before.body["input"])


class FrozenStatementTests(unittest.TestCase):
    def test_stored_prompts_match_a_fresh_rendering(self):
        config = load_config("v2")
        directory = PROTOCOLS["v2"].root / "prompts"
        manifest = json.loads((directory / "manifest.json").read_bytes())
        self.assertEqual(manifest["dataset"]["sha256"], config["sources"]["dataset_sha256"])
        self.assertEqual(statement.verify(statement_check.load_graphs(config), directory, manifest),
                         {"prompts": 7392, "files": 3})

    def test_saved_check_is_accepted_and_follows_from_its_evidence(self):
        root = PROTOCOLS["v2"].root
        self.assertEqual(statement_check.replay(root / "prompts", root / "statement_check"),
                         {"graphs": 352, "accepted": True, "solves": 0})

    def test_archived_independent_program_repeats_its_answers(self):
        root = PROTOCOLS["v2"].root
        directory = root / "independent_reading"
        program = directory / independent_reading.PROGRAM
        imported = {name for node in ast.walk(ast.parse(program.read_text(encoding="utf-8")))
                    for name in ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                                 else [node.module] if isinstance(node, ast.ImportFrom) else [])}
        self.assertLessEqual(imported, {"itertools", "json", "re", "sys", "time", "fractions", "math", "numpy"})
        repeated = independent_reading.replay(root / "prompts", directory, limit=4)
        self.assertEqual((repeated["graphs"], repeated["questions"], repeated["violations"]), (4, 28, 0))
        self.assertEqual(set(repeated["correct"].values()) | set(repeated["agreement_with_dataset"].values()), {4})
        stored = json.loads((directory / independent_reading.SUMMARY).read_text(encoding="utf-8"))
        self.assertEqual((stored["graphs"], stored["questions"], stored["violations"]), (352, 2464, 0))
        self.assertEqual(set(stored["correct"].values()) | set(stored["agreement_with_dataset"].values()), {352})

    def test_recorded_pilot_is_complete_and_its_scores_match_their_manifest(self):
        root = PROTOCOLS["v2"].root
        listed = {row["id"]: row["dispatches"]
                  for row in read_jsonl(root / "independent_reading" / independent_reading.EVIDENCE)}
        rows = list(read_jsonl(response_path(root, "pilot", "S")))
        tasks = {task.custom_id: task.request_hash for task in plan(load_config("v2"), "pilot", "S")}
        self.assertEqual({row["custom_id"]: row["request_hash"] for row in rows}, tasks)
        self.assertEqual(Counter(row["status"] for row in rows), {"ok": 96})
        self.assertTrue(all(row["parsed"] in listed[row["graph"]] for row in rows))
        directory = root / "pilot_S"
        files = json.loads((directory / "manifest_pilot_S.json").read_bytes())["files"]
        self.assertEqual({name: digest(directory / name) for name in files}, files)
        summary = json.loads((directory / "summary_pilot_S.json").read_text(encoding="utf-8"))
        self.assertEqual((summary["status"], summary["terminal_requests"]), ("complete", 96))
        self.assertEqual([summary["contexts"][mode]["primary"]["metrics"]["accuracy"]["mean"]
                          for mode in statement.MODES], [1, 1, 1])
        alternatives = json.loads((root / "alternative_readings.json").read_text(encoding="utf-8"))
        self.assertEqual(set(alternatives), set(reader.ALTERNATIVES))
        for row in alternatives.values():
            self.assertEqual((row["graphs"], row["recorded_answers"]), (352, 96))
            self.assertGreater(row["recorded_answers_contradicting"], 0)


if __name__ == "__main__":
    unittest.main()
