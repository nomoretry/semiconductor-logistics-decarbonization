import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PLANNING = all(importlib.util.find_spec(name) for name in ("pulp", "highspy"))
SETTINGS = {"n_skus": 6, "seed": 3}


class GuardrailTests(unittest.TestCase):
    def test_invented_numbers_are_flagged(self):
        from planning_agent.guardrails import check_answer
        check = check_answer("成本增加 12.38%，约 9,999 美元", [{"cost_change_pct": 12.38, "cost_change_usd": 6842}])
        self.assertFalse(check["ok"])
        self.assertEqual(check["unsupported"], ["9,999"])

    def test_rounding_units_and_user_numbers_are_accepted(self):
        from planning_agent.guardrails import check_answer
        tools = [{"cost_change_usd": 6842, "cost_change_pct": 12.38, "weekly_capacity_kg": 803.8, "air_share": 0.257}]
        answer = "第4到12周：成本多 6.8千美元（约 6,800），涨 12.4%，空运占比 25.7%，运力 803.8 kg"
        self.assertTrue(check_answer(answer, tools, "第4到12周延误")["ok"])


class LLMClientTests(unittest.TestCase):
    def test_temperature_is_dropped_when_the_model_rejects_it(self):
        import io
        import urllib.error
        from unittest import mock
        from planning_agent.llm import OpenAICompatibleClient
        bodies = []

        def fake_urlopen(request, timeout):
            body = json.loads(request.data)
            bodies.append(body)
            if "temperature" in body:
                raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(
                    b'{"error": {"message": "Unsupported value: temperature does not support 0.1"}}'))
            reply = {"choices": [{"message": {"content": "ok"}}],
                     "usage": {"prompt_tokens": 5, "completion_tokens": 7,
                               "completion_tokens_details": {"reasoning_tokens": 4},
                               "prompt_tokens_details": {"cached_tokens": 3}}}
            return io.BytesIO(json.dumps(reply).encode("utf-8"))

        client = OpenAICompatibleClient(api_key="test", model="reasoning-model")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual(client.chat([{"role": "user", "content": "hi"}])["content"], "ok")
            client.chat([{"role": "user", "content": "again"}])
        self.assertEqual(["temperature" in b for b in bodies], [True, False, False])
        self.assertEqual(client.usage, {"prompt_tokens": 10, "cached_tokens": 6, "completion_tokens": 14,
                                        "reasoning_tokens": 8, "calls": 2})

    def test_switches_to_responses_api_and_replays_reasoning_with_tool_calls(self):
        import io
        import urllib.error
        from unittest import mock
        from planning_agent.llm import OpenAICompatibleClient
        sent = []
        replies = [
            {"output": [{"type": "reasoning", "id": "rs_1", "summary": []},
                        {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "solve_plan",
                         "arguments": "{\"network\": \"asml\"}"}],
             "usage": {"input_tokens": 100, "output_tokens": 30, "output_tokens_details": {"reasoning_tokens": 20}}},
            {"output": [{"type": "message", "content": [{"type": "output_text", "text": "done"}]}],
             "usage": {"input_tokens": 150, "output_tokens": 10, "output_tokens_details": {"reasoning_tokens": 0},
                       "input_tokens_details": {"cached_tokens": 90}}},
        ]

        def fake_urlopen(request, timeout):
            sent.append((request.full_url.rsplit("/", 1)[-1], json.loads(request.data)))
            if request.full_url.endswith("chat/completions"):
                raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(
                    b'{"error": {"message": "Function tools with reasoning_effort are not supported for this model '
                    b'in /v1/chat/completions. To use function tools, use /v1/responses."}}'))
            return io.BytesIO(json.dumps(replies.pop(0)).encode("utf-8"))

        tools = [{"type": "function", "function": {"name": "solve_plan", "description": "d", "parameters": {}}}]
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}]
        client = OpenAICompatibleClient(api_key="test", model="reasoning-model")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            first = client.chat(messages, tools)
            messages += [{"role": "assistant", "content": "", "tool_calls": first["tool_calls"]},
                         {"role": "tool", "tool_call_id": "call_1", "content": "{\"plan_id\": \"P1\"}"}]
            second = client.chat(messages, tools)
        self.assertEqual([path for path, _ in sent], ["completions", "responses", "responses"])
        self.assertEqual(first["tool_calls"][0]["function"]["name"], "solve_plan")
        self.assertEqual(sent[1][1]["tools"][0]["name"], "solve_plan")
        replay = sent[2][1]["input"]
        self.assertEqual([i.get("type", i.get("role")) for i in replay],
                         ["system", "user", "reasoning", "function_call", "function_call_output"])
        self.assertEqual(second["content"], "done")
        self.assertEqual(client.api_style, "responses")
        self.assertEqual(client.usage, {"prompt_tokens": 250, "cached_tokens": 90, "completion_tokens": 40,
                                        "reasoning_tokens": 20, "calls": 2})


@unittest.skipUnless(PLANNING, "requires the optional planning extra: pip install -e '.[planning]'")
class PlanningAgentTests(unittest.TestCase):
    def session(self):
        from planning_agent.tools import Session
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        return Session(memo_dir=Path(self.tmp.name), **SETTINGS)

    def test_tools_reject_bad_arguments_with_actionable_messages(self):
        s = self.session()
        self.assertIn("unknown lanes", s.call("create_scenario", {
            "network": "asml", "name": "x_test", "disruptions": [{"lanes": ["SG_rail"], "start_week": 2, "end_week": 3}]})["error"])
        self.assertIn("unknown scenario", s.call("solve_plan", {"network": "asml", "scenario": "volcano"})["error"])
        self.assertIn("carbon_cap_pct", s.call("solve_plan", {"network": "asml", "carbon_cap_pct": 150})["error"])
        self.assertIn("unknown tool", s.call("delete_everything", {})["error"])
        self.assertTrue(all(not c["ok"] for c in s.calls))

    def test_custom_scenario_records_assumptions_and_solves(self):
        s = self.session()
        created = s.call("create_scenario", {"network": "asml", "name": "notice_test", "disruptions": [
            {"mode": "ocean", "start_week": 5, "end_week": 9, "extra_lead_weeks": 2}]})
        self.assertTrue(any("capacity_change_pct" in a for a in created["assumptions"]))
        plan = s.call("solve_plan", {"network": "asml", "scenario": "notice_test"})
        self.assertEqual(plan["status"], "optimal")
        self.assertEqual(s.call("solve_plan", {"network": "asml", "scenario": "notice_test"})["cached"], True)

    def test_rule_agent_answer_is_grounded_in_tool_results(self):
        from planning_agent.rules import run_rules
        s = self.session()
        result = run_rules("如果红海航线中断，ASML 备件的物流成本和排放会怎样变化？", s)
        self.assertEqual(result.tool_names(), ["solve_plan", "solve_plan", "compare_plans"])
        self.assertTrue(result.guardrail["ok"])
        change = result.tool_calls[-1]["result"]["rows"][1]["cost_change_pct"]
        self.assertIn(f"{change:+.2f}%", result.answer)
        self.assertEqual(run_rules("帮我订一张机票", s).tool_calls, [])

    def test_llm_loop_executes_tools_and_rewrites_unsupported_numbers(self):
        from planning_agent.agent import run_llm

        class ScriptedClient:
            usage = {}

            def __init__(self):
                self.turn, self.seen = 0, []

            def chat(self, messages, tools=None):
                self.turn += 1
                self.seen.append(messages[-1])
                call = lambda i, name, args: {"id": f"c{i}", "type": "function",
                                              "function": {"name": name, "arguments": json.dumps(args)}}
                if self.turn == 1:
                    return {"content": "", "tool_calls": [call(1, "solve_plan", {"network": "asml"}),
                                                          call(2, "solve_plan", {"network": "asml", "scenario": "red_sea"})]}
                if self.turn == 2:
                    return {"content": "", "tool_calls": [call(3, "compare_plans", {"plan_ids": ["P1", "P2"]})]}
                if self.turn == 3:
                    return {"content": "成本上涨 99.99%。", "tool_calls": []}
                row = json.loads(self.seen[2]["content"])["rows"][1]  # the compare_plans tool message
                return {"content": f"成本上涨 {row['cost_change_pct']}%。", "tool_calls": []}

        client = ScriptedClient()
        result = run_llm("红海中断影响多大？", self.session(), client)
        self.assertEqual(result.tool_names(), ["solve_plan", "solve_plan", "compare_plans"])
        self.assertEqual(result.steps, 4)
        self.assertIn("自动审查", client.seen[3]["content"])
        self.assertTrue(result.guardrail["ok"])
        self.assertNotIn("99.99", result.answer)

    def test_memo_contains_plan_table(self):
        s = self.session()
        a = s.call("solve_plan", {"network": "asml"})
        b = s.call("solve_plan", {"network": "asml", "carbon_cap_pct": 80})
        memo = s.call("write_memo", {"plan_ids": [a["plan_id"], b["plan_id"]], "question": "减排 20% 值不值？"})
        text = Path(memo["path"]).read_text(encoding="utf-8")
        self.assertIn("| P1 |", text)
        self.assertIn(f"{b['total_cost_usd']:,}", text)

    def test_paid_evaluation_saves_each_case_resumes_and_respects_the_budget(self):
        from planning_agent.evaluate import evaluate

        class CountingClient:
            """Answers every question at once and bills 1,000 tokens per call."""
            model, api_style, reasoning_effort = "fake-model", "chat", "xhigh"

            def __init__(self):
                self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "calls": 0}

            def chat(self, messages, tools=None):
                self.usage.update(prompt_tokens=self.usage["prompt_tokens"] + 800,
                                  completion_tokens=self.usage["completion_tokens"] + 200,
                                  calls=self.usage["calls"] + 1)
                return {"content": "超出范围，无法回答。", "tool_calls": []}

        out = Path(self.session().memo_dir) / "eval"
        first = evaluate("llm", ids=["D14", "H09", "D01"], output=out, settings=SETTINGS, client=CountingClient(),
                         max_tokens=2000)
        self.assertEqual([r["id"] for r in first["rows"]], ["D01", "D14"])  # cases run in file order
        self.assertEqual(first["summary"]["stopped_early"]["remaining"], ["H09"])
        self.assertEqual(first["summary"]["usage"]["prompt_tokens"], 1600)
        lines = (out / "llm_cases.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        client = CountingClient()
        resumed = evaluate("llm", ids=["D14", "H09", "D01"], output=out, settings=SETTINGS, client=client, resume=True)
        self.assertEqual(client.usage["calls"], 1)  # only H09 is asked; saved cases are not paid for twice
        self.assertEqual([r["id"] for r in resumed["rows"]], ["D01", "D14", "H09"])
        self.assertIsNone(resumed["summary"]["stopped_early"])
        self.assertEqual(resumed["summary"]["usage"]["calls"], 3)

    def test_evaluation_scores_cases(self):
        from planning_agent.evaluate import evaluate
        result = evaluate("rule", ids=["D01", "D14", "H03"], settings=SETTINGS)
        outcome = {r["id"]: r["success"] for r in result["rows"]}
        self.assertEqual(outcome, {"D01": True, "D14": True, "H03": False})
        self.assertEqual(result["summary"]["overall"]["faithfulness"], 1.0)


if __name__ == "__main__":
    unittest.main()
