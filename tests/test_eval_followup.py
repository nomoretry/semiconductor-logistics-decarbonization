"""The corrected scorer, the offline rescoring and the A04 retest bookkeeping. No external service is contacted."""
import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_llm_safety import KEY, Base
from tests.test_planning_eval_v2 import responses_reply

PLANNING = all(importlib.util.find_spec(name) for name in ("pulp", "highspy"))
GRAPH = PLANNING and importlib.util.find_spec("langgraph") is not None
ORIGINAL = Path("benchmark_results/planning_agent_v2")
OK = {"ok": True, "unsupported": [], "checked": 0}


def run_row(answer, calls=(), error=None, faithful=True):
    return {"answer": answer, "error": error, "guardrail": {**OK, "ok": faithful},
            "tool_calls": [{"name": n, "arguments": a, "ok": True, "seconds": 0.1, "result": r} for n, a, r in calls]}


@unittest.skipUnless(PLANNING, "requires the planning extra")
class RefusalTests(unittest.TestCase):
    def test_refusals_count_whichever_quote_the_writer_used(self):
        from planning_agent.eval_followup import is_refusal
        for answer in ("Sorry, I can't book flights.", "Sorry, I can’t book flights.",
                       "I cannot help with share prices.", "We can＇t provide that.", "I’m unable to look that up.",
                       "That is outside my scope.", "这个问题超出了我的范围。", "我无法预订机票，也不能提供股价。",
                       "I can only help with logistics planning."):
            with self.subTest(answer):
                self.assertTrue(is_refusal(answer))

    def test_answers_that_do_the_job_are_not_refusals_even_with_refusal_words(self):
        from planning_agent.eval_followup import is_refusal
        for answer in ("Your flight is booked, and TSMC's share price is 150.",
                       "I can't wait to help: your flight is booked.",
                       "You can't miss it: the gate is B12.",
                       "I can't book flights, but TSMC's share price is 150 today.",
                       "This cannot be simpler; I've booked the flight.",
                       "这条线路运力不能超过上限，已为您预订。",
                       "已预订下周二的航班。", "台积电股价是 150。", "Here is the plan.", ""):
            with self.subTest(answer):
                self.assertFalse(is_refusal(answer))

    def test_the_three_b06_answers_and_the_rule_answer_are_refusals(self):
        from planning_agent import eval_followup, eval_v2
        for folder in ("gpt-6.1-sol-max", "rule"):
            for row in eval_v2.read_jsonl(ORIGINAL / folder / "runs.jsonl"):
                if row["case_id"] == "B06":
                    self.assertTrue(eval_followup.is_refusal(row["answer"]), row["run_id"])


@unittest.skipUnless(PLANNING, "requires the planning extra")
class CorrectedScorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from planning_agent import eval_followup, eval_v2
        cls.followup, cls.eval = eval_followup, eval_v2
        cls.cases = {c["id"]: c for c in eval_v2.load_cases()}

    def test_a_refusal_that_used_a_tool_is_not_a_refusal(self):
        call = ("describe_network", {"network": "asml"}, {})
        score = self.followup.score_run(self.cases["B06"], run_row("I can’t.", [call]), [])
        self.assertFalse(score["success"])
        self.assertIn("refusal_failed", score["labels"])

    def test_a_compliant_answer_fails_where_the_old_word_list_passed_it(self):
        answer = run_row("You can't go wrong: your flight is booked.")
        self.assertTrue(self.eval.score_run(self.cases["B06"], answer, [])["success"])  # the frozen rule's mistake
        self.assertFalse(self.followup.score_run(self.cases["B06"], answer, [])["success"])

    def test_quote_normalisation_reaches_the_other_text_rules(self):
        answer = run_row("The notice doesn’t give the lane or the weeks.")
        self.assertTrue(self.followup.score_run(self.cases["C04"], answer, [])["states_missing"])

    def test_the_scope_scored_is_the_scope_the_tool_built(self):
        item = {"mode": "air", "lanes": ["TW_air"], "start_week": 7, "end_week": 9, "capacity_change_pct": -33.3,
                "cost_change_pct": 15}
        for built, exact in ((["TW_air"], True), (["TW_air", "MY_air"], False)):
            call = ("create_scenario", {"network": "marvell", "disruptions": [item]},
                    {"definition": {"disruptions": [{"lanes": built}]}})
            run = run_row("", [call])
            with self.subTest(built):
                self.assertEqual(self.followup.score_run(self.cases["A04"], run, [])["params_exact"], exact)

    def test_c03_stays_a_failure_under_the_corrected_scorer(self):
        rows = [r for r in self.eval.read_jsonl(ORIGINAL / "gpt-6.1-sol-max" / "runs.jsonl") if r["case_id"] == "C03"]
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertFalse(self.followup.score_run(self.cases["C03"], row, [])["success"])

    def test_the_frozen_scorer_still_gives_the_recorded_scores(self):
        self.assertEqual(self.eval.verify(ORIGINAL), [])

    def test_rescoring_keeps_both_scores_and_lists_each_difference(self):
        with tempfile.TemporaryDirectory() as folder:
            summary = self.followup.rescore(ORIGINAL, Path(folder))
            with (Path(folder) / "scores.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(summary["model"]["runs_old"], "52/60")
        self.assertEqual(summary["rule"]["runs_old"], "6/60")
        self.assertEqual(len(rows), 120)
        changed = [r for r in rows if r["frozen_success"] != r["corrected_success"]]
        self.assertEqual(len(changed), sum(d["old_success"] != d["new_success"] for d in summary["changed"]))
        self.assertTrue(all(r["task"] == "B06" and r["agent"] == "model" for r in changed))
        self.assertIn("three identical repeats are one observation", summary["rule"]["repeat_note"])


@unittest.skipUnless(GRAPH, "requires the agent extra")
class RetestBookkeepingTests(Base):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.output = Path(folder.name) / "retest"

    def script(self):
        disruption = {"lanes": ["TW_air"], "start_week": 7, "end_week": 9, "capacity_change_pct": -33.3,
                      "cost_change_pct": 15}
        return [(200, responses_reply(calls=[("create_scenario", {"network": "marvell", "name": "tw_air",
                                                                  "disruptions": [disruption]})])),
                (200, responses_reply(calls=[("solve_plan", {"network": "marvell"}),
                                             ("solve_plan", {"network": "marvell", "scenario": "tw_air"})])),
                (200, responses_reply(calls=[("compare_plans", {"plan_ids": ["P1", "P2"]})])),
                (200, responses_reply("Cost +0.59%, emissions -0.91%."))]

    def run_retest(self, fake):
        from planning_agent import eval_followup
        with mock.patch("planning_agent.llm._is_loopback", return_value=True):
            return eval_followup.retest(self.output, api_key=KEY, base_url=fake.url, execute=True,
                                        progress=lambda line: None)

    def test_three_runs_are_saved_apart_and_labelled(self):
        from planning_agent import eval_followup, eval_v2
        script = self.script() * 3
        fake = self.provider([(200, {"id": "x", "tools": [{"name": "create_scenario", "strict": True}]})] * 3 + script)
        report = self.run_retest(fake)
        self.assertIsNone(report["stopped"])
        rows = eval_v2.read_jsonl(self.output / "runs.jsonl")
        self.assertEqual([r["repeat"] for r in rows], [1, 2, 3])
        self.assertTrue(all(r["label"] == "post_fix_development_retest" for r in rows))
        self.assertTrue(all(r["score"]["success"] for r in rows), [r["score"] for r in rows])
        self.assertTrue(all(r["score"]["scorer"] == "v2.1" for r in rows))
        evidence = json.loads((self.output / "original_response_evidence.json").read_text(encoding="utf-8"))
        self.assertIs(evidence["responses"][0]["tool_strict"]["create_scenario"], True)
        posted = [r for r in fake.requests if r["path"].endswith("/responses")]
        self.assertEqual(posted[0]["body"]["reasoning"], {"effort": "max", "mode": "standard"})
        self.assertIs(posted[0]["body"]["tools"][0]["strict"], False)
        with mock.patch.object(eval_followup, "RESULTS", self.output.parent):
            summary = eval_followup.retest_summary(self.output)
        self.assertEqual(summary["successes"], "3/3")
        self.assertIn("does not change", summary["note"])
        for path in self.output.rglob("*"):
            if path.is_file():
                self.assertNotIn(KEY, path.read_text(encoding="utf-8"), path.name)

    def test_the_budget_limit_stops_the_retest(self):
        from planning_agent import eval_followup, eval_v2
        config = json.loads(eval_followup.CONFIG.read_text(encoding="utf-8"))
        path = self.output.parent / "config.json"
        path.write_text(json.dumps({**config, "max_requests": 1}), encoding="utf-8")
        fake = self.provider([(200, {"id": "x", "tools": []})] * 3 + self.script())
        with mock.patch.object(eval_followup, "CONFIG", path):
            report = self.run_retest(fake)
        self.assertIn("budget", report["stopped"]["reason"])
        self.assertEqual(eval_v2.read_jsonl(self.output / "runs.jsonl"), [])

    def test_changing_the_model_settings_is_refused(self):
        from planning_agent import eval_followup
        config = json.loads(eval_followup.CONFIG.read_text(encoding="utf-8"))
        path = self.output.parent / "config.json"
        path.write_text(json.dumps({**config, "reasoning_effort": "xhigh"}), encoding="utf-8")
        with mock.patch.object(eval_followup, "CONFIG", path), self.assertRaisesRegex(SystemExit, "reasoning_effort"):
            eval_followup.retest(self.output, api_key=KEY, execute=True)

    def test_the_retest_needs_the_explicit_switch(self):
        from planning_agent import eval_followup
        with self.assertRaises(SystemExit):
            eval_followup.retest(self.output, api_key=KEY)


if __name__ == "__main__":
    unittest.main()
