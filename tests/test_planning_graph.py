import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PLANNING = all(importlib.util.find_spec(name) for name in ("pulp", "highspy"))
GRAPH = PLANNING and importlib.util.find_spec("langgraph") is not None
SETTINGS = {"n_skus": 6, "seed": 3}
RECORDED = Path(__file__).resolve().parents[1] / "benchmark_results" / "planning_agent"


def call(i, name, args):
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptedClient:
    """Returns prepared replies in order; a callable reply receives the messages it is shown."""

    def __init__(self, replies):
        self.replies, self.seen, self.usage = list(replies), [], {}

    def chat(self, messages, tools=None, temperature=0.1):
        self.seen.append([dict(m) for m in messages])
        reply = self.replies.pop(0)
        return reply(messages) if callable(reply) else reply


def without_timings(conversations):
    """Tool results carry solver wall times, which differ between runs; everything else must match."""
    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if "seconds" not in k}
        return [strip(v) for v in value] if isinstance(value, list) else value
    return [[dict(m, content=strip(json.loads(m["content"]))) if m["role"] == "tool" else m for m in messages]
            for messages in conversations]


def lanes_answer(messages):
    lanes = json.loads(messages[-1]["content"])["lanes"]
    return {"content": f"{lanes[0]['id']} 周运力 {lanes[0]['weekly_capacity_kg']} kg。", "tool_calls": []}


@unittest.skipUnless(GRAPH, "requires the planning and agent extras: pip install -e '.[planning,agent]'")
class PlanningGraphTests(unittest.TestCase):
    def session(self):
        from planning_agent.tools import Session
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        return Session(memo_dir=Path(self.tmp.name), **SETTINGS)

    def test_graph_runs_tools_then_answers_from_their_results(self):
        from planning_agent.graph import PlanningGraph
        client = ScriptedClient([{"content": "", "tool_calls": [call(1, "describe_network", {"network": "asml"})]},
                                 lanes_answer])
        steps = []
        result = PlanningGraph(self.session(), client).ask("ASML 有哪些线路？", on_step=lambda n, _: steps.append(n))
        self.assertEqual(result.mode, "graph")
        self.assertEqual(result.tool_names(), ["describe_network"])
        self.assertEqual(steps, ["model", "tools", "model", "review"])
        self.assertTrue(result.guardrail["ok"])
        self.assertEqual(result.steps, 2)
        self.assertEqual(client.seen[0][0]["role"], "system")

    def test_graph_matches_the_plain_loop_including_one_rewrite(self):
        from planning_agent.agent import run_llm
        from planning_agent.graph import PlanningGraph

        def replies():
            return [{"content": "", "tool_calls": [call(1, "solve_plan", {"network": "asml"}),
                                                   call(2, "solve_plan", {"network": "asml", "scenario": "red_sea"})]},
                    {"content": "", "tool_calls": [call(3, "compare_plans", {"plan_ids": ["P1", "P2"]})]},
                    {"content": "成本上涨 99.99%。", "tool_calls": []},
                    lambda messages: {"content": "成本上涨 {}%。".format(json.loads(next(
                        m["content"] for m in reversed(messages) if m["role"] == "tool"))["rows"][1]["cost_change_pct"]),
                        "tool_calls": []}]

        loop_client, graph_client = ScriptedClient(replies()), ScriptedClient(replies())
        loop = run_llm("红海中断影响多大？", self.session(), loop_client)
        graph = PlanningGraph(self.session(), graph_client).ask("红海中断影响多大？")
        self.assertEqual(graph.answer, loop.answer)
        self.assertEqual(graph.tool_names(), loop.tool_names())
        self.assertEqual(graph.steps, loop.steps)
        self.assertEqual(graph.guardrail, loop.guardrail)
        # The model saw identical messages at every step.
        self.assertEqual(without_timings(graph_client.seen), without_timings(loop_client.seen))
        self.assertIn("自动审查", graph_client.seen[3][-1]["content"])
        self.assertNotIn("99.99", graph.answer)

    def test_step_budget_and_model_errors_end_the_turn(self):
        from planning_agent.graph import PlanningGraph
        from planning_agent.llm import LLMError
        looping = ScriptedClient([{"content": "", "tool_calls": [call(i, "describe_network", {"network": "asml"})]}
                                  for i in range(3)])
        result = PlanningGraph(self.session(), looping, max_steps=3).ask("ASML 有哪些线路？")
        self.assertEqual((result.error, result.steps, len(result.tool_calls)), ("max_steps", 3, 3))

        class Failing:
            def __init__(self):
                self.usage = {}

            def chat(self, messages, tools=None):
                raise LLMError("HTTP 503")
        failed = PlanningGraph(self.session(), Failing()).ask("ASML 有哪些线路？")
        self.assertEqual(failed.error, "HTTP 503")
        self.assertIn("模型调用失败", failed.answer)

    def test_follow_up_turn_sees_earlier_tool_results_and_plans(self):
        from planning_agent.graph import PlanningGraph
        session = self.session()
        client = ScriptedClient([
            {"content": "", "tool_calls": [call(1, "solve_plan", {"network": "asml"})]},
            lambda m: {"content": "正常方案成本 {} 美元。".format(json.loads(m[-1]["content"])["total_cost_usd"]),
                       "tool_calls": []},
            lambda m: {"content": "上一轮的方案是 {}。".format(json.loads(next(
                x["content"] for x in m if x["role"] == "tool"))["plan_id"]), "tool_calls": []}])
        conversation = PlanningGraph(session, client)
        conversation.ask("正常情况下 ASML 的成本是多少？")
        second = conversation.ask("刚才那个方案叫什么？")
        self.assertEqual(second.answer, "上一轮的方案是 P1。")
        self.assertEqual(second.tool_calls, [])  # nothing re-solved
        self.assertEqual([m["role"] for m in client.seen[-1]],
                         ["system", "user", "assistant", "tool", "assistant", "user"])
        self.assertEqual(list(session.plans), ["P1"])

    def test_approval_step_can_decline_a_tool_call(self):
        from planning_agent.graph import DECLINED, PlanningGraph
        session = self.session()
        asked = []
        client = ScriptedClient([{"content": "", "tool_calls": [call(1, "solve_plan", {"network": "asml"})]},
                                 {"content": "好的，没有求解。请告诉我要比较哪些场景？", "tool_calls": []}])
        result = PlanningGraph(session, client, approve=lambda calls: asked.append(calls) or False).ask("算一下成本")
        self.assertEqual(len(asked), 1)
        self.assertEqual(session.calls, [])  # the declined tool never ran
        self.assertEqual(client.seen[1][-1], {"role": "tool", "tool_call_id": "c1", "content": DECLINED})
        self.assertTrue(result.answer.startswith("好的"))

        approved = PlanningGraph(self.session(), ScriptedClient([
            {"content": "", "tool_calls": [call(1, "describe_network", {"network": "asml"})]}, lanes_answer]),
            approve=lambda calls: True).ask("ASML 有哪些线路？")
        self.assertEqual(approved.tool_names(), ["describe_network"])

    def test_replay_reproduces_recorded_model_cases(self):
        from planning_agent.graph import replay
        result = replay(RECORDED, ids={"D01", "D14", "H08"})
        self.assertEqual(result["summary"]["cases"], 3)
        self.assertEqual(result["summary"]["mismatches"], [])

    def test_graph_diagram_lists_the_nodes(self):
        from planning_agent.graph import PlanningGraph
        text = PlanningGraph(self.session(), ScriptedClient([])).mermaid()
        for node in ("model", "tools", "review", "stop"):
            self.assertIn(node, text)


if __name__ == "__main__":
    unittest.main()
