import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLANNING = all(importlib.util.find_spec(name) for name in ("pulp", "highspy"))
GRAPH = PLANNING and importlib.util.find_spec("langgraph") is not None
UI = PLANNING and importlib.util.find_spec("streamlit") is not None
SETTINGS = {"n_skus": 6, "seed": 3}
ROOT = Path(__file__).resolve().parents[1]


def call(i, name, args):
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


@unittest.skipUnless(PLANNING, "requires the optional planning extra: pip install -e '.[planning]'")
class DecisionWorkflowTests(unittest.TestCase):
    def session(self):
        from planning_agent.tools import Session
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        return Session(memo_dir=Path(self.tmp.name), **SETTINGS)

    def test_rule_mode_parses_the_demo_notice_with_source_text(self):
        from planning_agent import workflow
        proposal = workflow.propose_from_rules(workflow.DEMO_NOTICE)
        self.assertEqual(proposal.mode, "rule")
        self.assertEqual(proposal.network, "asml")
        self.assertEqual(proposal.disruptions, [{"mode": "ocean", "start_week": 4, "end_week": 12, "extra_lead_weeks": 2,
                                                 "capacity_change_pct": -30, "distance_factor": 1.4183}])
        evidence = {e["parameter"]: e["text"] for e in proposal.evidence}
        self.assertEqual(evidence["周次"], "第4到12周")
        self.assertEqual(evidence["延误"], "延误2周")
        self.assertEqual(evidence["运力或舱位"], "舱位削减30%")
        self.assertIn("海运", evidence["运输方式：ocean"])

    def test_preview_lists_assumptions_and_solves_nothing(self):
        from planning_agent import workflow
        session = self.session()
        checked = workflow.preview(workflow.propose_from_rules(workflow.DEMO_NOTICE), session)
        self.assertIsNone(checked["error"])
        self.assertTrue(any("cost_change_pct" in a for a in checked["assumptions"]))
        self.assertEqual([c["name"] for c in session.calls], ["create_scenario"])
        with self.assertRaises(workflow.ConfirmationRequired):
            workflow.run(workflow.propose_from_rules(workflow.DEMO_NOTICE), session, confirmed=False)
        self.assertNotIn("solve_plan", [c["name"] for c in session.calls])

    def test_confirmed_run_matches_direct_engine_calls_and_writes_a_memo(self):
        from planning_agent import workflow
        proposal = workflow.propose_from_rules(workflow.DEMO_NOTICE).with_changes(carbon_cap_pct=80)
        outcome = workflow.run(proposal, self.session(), confirmed=True)
        self.assertEqual(len(outcome.rows), 3)
        direct = self.session()
        args = proposal.scenario_arguments()
        direct.call("create_scenario", args)
        ids = [direct.call("solve_plan", {"network": "asml"})["plan_id"],
               direct.call("solve_plan", {"network": "asml", "scenario": args["name"]})["plan_id"],
               direct.call("solve_plan", {"network": "asml", "scenario": args["name"], "carbon_cap_pct": 80})["plan_id"]]
        expected = direct.call("compare_plans", {"plan_ids": ids})["rows"]
        for got, want in zip(outcome.rows, expected, strict=True):
            for key in ("total_cost_usd", "emissions_t", "service_level_pct", "air_share_pct"):
                self.assertEqual(got[key], want[key])
        self.assertTrue(Path(outcome.memo_path).exists())
        self.assertIn(outcome.rows[1]["plan_id"], outcome.memo_text)
        self.assertEqual([r["方案"][:2] for r in workflow.summary_rows(outcome)], ["P1", "P2", "P3"])

    def test_edited_parameters_are_solved_again_not_read_from_cache(self):
        from planning_agent import workflow
        session = self.session()
        proposal = workflow.propose_from_rules(workflow.DEMO_NOTICE)
        first = workflow.run(proposal, session, confirmed=True)
        longer = dict(proposal.disruptions[0], extra_lead_weeks=4, capacity_change_pct=-60)
        second = workflow.run(proposal.with_changes(disruptions=[longer]), session, confirmed=True)
        self.assertNotEqual(first.scenario, second.scenario)
        self.assertNotEqual(first.rows[1]["total_cost_usd"], second.rows[1]["total_cost_usd"])

    def test_replay_mode_uses_recorded_model_arguments_and_says_so(self):
        from planning_agent import workflow
        proposal = workflow.propose_from_recording("D13")
        self.assertEqual(proposal.mode, "replay")
        self.assertIn("录制回放", proposal.source)
        self.assertIn("gpt-6.1-sol", proposal.source)
        self.assertIn("本次不调用模型", proposal.source)
        disruption = proposal.disruptions[0]
        self.assertEqual((disruption["start_week"], disruption["end_week"], disruption["extra_lead_weeks"],
                          disruption["capacity_change_pct"]), (5, 10, 3, -40))
        with self.assertRaises(KeyError):
            workflow.propose_from_recording("D01")  # no custom scenario was built in that run

    @unittest.skipUnless(GRAPH, "requires the agent extra")
    def test_live_mode_needs_a_token_cap_and_runs_no_scenario_tool(self):
        from planning_agent import workflow

        class Scripted:
            model = "scripted"

            def __init__(self):
                self.usage = {"prompt_tokens": 1200, "completion_tokens": 80}
                self.replies = [
                    {"content": "", "tool_calls": [call(1, "describe_network", {"network": "asml"})]},
                    {"content": "", "tool_calls": [call(2, "create_scenario", {
                        "network": "asml", "name": "x_notice", "disruptions": [
                            {"mode": "ocean", "start_week": 5, "end_week": 8, "extra_lead_weeks": 1}]})]}]

            def chat(self, messages, tools=None):
                return self.replies.pop(0)

        with self.assertRaises(ValueError):
            workflow.propose_from_model("第5到8周海运延误1周", Scripted(), max_tokens=None)
        with mock.patch("planning_agent.tools.Session.call", autospec=True,
                        side_effect=lambda self, name, args: {"skus": 12, "lanes": []}) as tool:
            proposal = workflow.propose_from_model("第5到8周海运延误1周", Scripted(), max_tokens=5000)
        self.assertEqual([c.args[1] for c in tool.call_args_list], ["describe_network"])  # read-only lookup only
        self.assertEqual(proposal.mode, "live")
        self.assertIn("1,280", proposal.source)
        self.assertEqual(proposal.disruptions[0]["extra_lead_weeks"], 1)

    def test_command_line_flow_runs_to_a_memo_and_live_mode_needs_a_key(self):
        from planning_agent.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(main(["flow", "--yes", "--output", folder, "--carbon-cap", "80"]), 0)
            self.assertTrue(list(Path(folder).glob("memo-*.md")))
            with mock.patch.dict(os.environ):
                os.environ.pop("LLM_API_KEY", None)  # never reach a real model from a test
                self.assertEqual(main(["flow", "--mode", "live", "--yes", "--output", folder]), 2)


@unittest.skipUnless(UI, "requires the ui extra: pip install -e '.[planning,ui]'")
class DecisionPageTests(unittest.TestCase):
    def test_page_confirms_before_solving_and_shows_results(self):
        from streamlit.testing.v1 import AppTest
        with mock.patch.dict(os.environ, {"PLANNING_FLOW_SETTINGS": json.dumps(SETTINGS)}):
            page = AppTest.from_file(str(ROOT / "planning_agent" / "app.py"), default_timeout=180)
            page.run()
            self.assertFalse(page.exception)
            page.button(key="parse").click().run()
            self.assertEqual(len(page.metric), 0)  # parsed, nothing solved yet
            self.assertIn("离线规则", page.info[0].value)
            page.button(key="confirm").click().run()
            self.assertFalse(page.exception)
            labels = [m.label for m in page.metric]
            self.assertIn("服务水平", labels)
            self.assertTrue(any("备忘录" in s.value for s in page.subheader))


if __name__ == "__main__":
    unittest.main()
