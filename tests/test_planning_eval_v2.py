"""The frozen 20-task evaluation: scorer rules, run bookkeeping and what the client records.

No external service is contacted: runs go to the local fake provider from test_llm_safety.py.
"""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_llm_safety import KEY, Base

PLANNING = all(importlib.util.find_spec(name) for name in ("pulp", "highspy"))
GRAPH = PLANNING and importlib.util.find_spec("langgraph") is not None
OK = {"ok": True, "unsupported": [], "checked": 0}


def responses_reply(text="done", *, calls=(), model="gpt-6.1-sol-2026-10-01", effort="max", mode="standard",
                    tier="default", input_tokens=1000, cached=100, written=50, output_tokens=300, reasoning=200,
                    status="completed"):
    output = [{"type": "reasoning", "id": "rs_1", "summary": []}] if calls else []
    output += [{"type": "function_call", "id": f"fc_{i}", "call_id": f"call_{i}", "name": name,
                "arguments": json.dumps(args)} for i, (name, args) in enumerate(calls)]
    if not calls:
        output.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
    return {"id": "resp_1", "model": model, "status": status, "service_tier": tier, "output": output,
            "reasoning": {"effort": effort, "mode": mode},
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                      "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": written},
                      "output_tokens_details": {"reasoning_tokens": reasoning}}}


def run_row(answer, calls=(), error=None, faithful=True):
    return {"answer": answer, "error": error, "guardrail": {**OK, "ok": faithful},
            "tool_calls": [{"name": n, "arguments": a, "ok": ok, "seconds": 0.1, "result": {}} for n, a, ok in calls]}


@unittest.skipUnless(PLANNING, "requires the planning extra")
class ScorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from planning_agent import eval_v2
        cls.eval = eval_v2
        cls.cases = {c["id"]: c for c in eval_v2.load_cases()}

    def scenario_calls(self, **changes):
        disruption = {"mode": "ocean", "start_week": 5, "end_week": 11, "extra_lead_weeks": 2,
                      "capacity_change_pct": -30}
        args = {"network": "asml", "name": "x", "disruptions": [{**disruption, **changes}]}
        return [("create_scenario", args, True), ("solve_plan", {"network": "asml"}, True),
                ("solve_plan", {"network": "asml", "scenario": "x"}, True), ("compare_plans", {"plan_ids": []}, True)]

    def test_the_task_set_matches_the_protocol(self):
        groups = [c["group"] for c in self.cases.values()]
        self.assertEqual([groups.count(g) for g in "ABC"], [8, 6, 6])
        self.assertEqual({c["notice_id"] for c in self.cases.values() if c["kind"] == "notice"},
                         {"real_r009", "real_r015", "real_r016", "real_r011", "real_r003", "real_r008"})
        self.assertIn("4,000 miles", self.cases["C01"]["question"])

    def test_correct_parameters_and_numbers_succeed(self):
        score = self.eval.score_run(self.cases["A01"], run_row("成本 +9.4%，排放 +26.08%", self.scenario_calls()),
                                    [9.4, 26.08])
        self.assertTrue(score["success"], score)
        self.assertEqual(score["param_fields_correct"], score["param_fields_total"])
        self.assertEqual(score["labels"], [])

    def test_a_wrong_field_is_a_parameter_error_even_with_the_right_numbers(self):
        score = self.eval.score_run(self.cases["A01"], run_row("+9.4%，+26.08%", self.scenario_calls(end_week=12)),
                                    [9.4, 26.08])
        self.assertFalse(score["success"])
        self.assertIn("param_error", score["labels"])
        self.assertEqual(score["param_fields_correct"], score["param_fields_total"] - 1)

    def test_a_value_the_notice_does_not_state_counts_as_invented(self):
        calls = self.scenario_calls(cost_change_pct=10)
        score = self.eval.score_run(self.cases["A01"], run_row("+9.4%，+26.08%", calls), [9.4, 26.08])
        self.assertTrue(score["invented_parameter"])
        self.assertFalse(score["success"])

    def test_mode_and_explicit_lanes_are_the_same_on_a_one_lane_mode_but_not_on_a_wider_one(self):
        case = self.cases["A04"]
        whole_mode = {"network": "marvell", "disruptions": [
            {"mode": "air", "start_week": 7, "end_week": 9, "capacity_change_pct": -33, "cost_change_pct": 15}]}
        one_lane = {"network": "marvell", "disruptions": [
            {"lanes": ["TW_air"], "start_week": 7, "end_week": 9, "capacity_change_pct": -33, "cost_change_pct": 15}]}
        self.assertFalse(self.eval.compare_parameters(case, whole_mode)["exact"])
        self.assertTrue(self.eval.compare_parameters(case, one_lane)["exact"])

    def test_a_tool_failure_followed_by_a_correct_call_still_counts_but_lowers_the_call_rate(self):
        calls = [("create_scenario", {"network": "asml", "name": "Bad Name"}, False), *self.scenario_calls()]
        score = self.eval.score_run(self.cases["A01"], run_row("+9.4%，+26.08%", calls), [9.4, 26.08])
        self.assertTrue(score["success"])
        self.assertEqual((score["tool_calls_ok"], score["tool_calls"]), (4, 5))

    def test_an_assumption_must_be_stated_where_the_task_requires_it(self):
        calls = [("create_scenario", {"network": "asml", "name": "x", "disruptions": [
            {"lanes": ["NL_ocean"], "start_week": 6, "end_week": 10, "capacity_change_pct": -40}]}, True),
            ("solve_plan", {"network": "asml"}, True), ("compare_plans", {"plan_ids": []}, True)]
        silent = self.eval.score_run(self.cases["A07"], run_row("Cost rises 1.77%.", calls), [1.77])
        stated = self.eval.score_run(self.cases["A07"], run_row("Cost rises 1.77%, assuming rates stay put.", calls),
                                     [1.77])
        self.assertIn("assumption_not_flagged", silent["labels"])
        self.assertFalse(silent["success"])
        self.assertTrue(stated["success"])

    def test_asking_back_on_an_executable_task_is_an_unnecessary_clarification(self):
        score = self.eval.score_run(self.cases["A01"], run_row("请问是哪条线路？"), [9.4, 26.08])
        self.assertIn("unnecessary_clarification", score["labels"])
        self.assertFalse(score["success"])

    def test_a_missing_information_task_needs_the_gaps_named_and_nothing_invented(self):
        case = self.cases["A08"]
        asks = self.eval.score_run(case, run_row("公告没有说明受影响的周次和舱位减少幅度，请提供。"), [])
        self.assertTrue(asks["success"], asks)
        invented = [("create_scenario", {"network": "asml", "name": "x"}, True),
                    ("solve_plan", {"network": "asml"}, True)]
        guessed = self.eval.score_run(case, run_row("成本会涨 3%。", invented), [])
        self.assertFalse(guessed["success"])
        self.assertIn("wrong_assumption", guessed["labels"])
        self.assertTrue(guessed["invented_parameter"])
        labelled = self.eval.score_run(case, run_row(
            "公告没有给出周次和舱位幅度，请确认。如果按第4到8周、舱位减少20%假设，成本会涨 3%。", invented), [])
        self.assertTrue(labelled["success"])
        self.assertFalse(labelled["invented_parameter"])

    def test_real_notices_check_the_gaps_and_whether_the_stated_quantity_is_cited(self):
        case = self.cases["C01"]
        good = self.eval.score_run(case, run_row(
            "公告只说航程增加约 4,000 英里，没有说明对应我们哪条线路、影响哪几周、延误几周，无法确定成本和排放。"), [])
        self.assertTrue(good["success"], good)
        self.assertTrue(good["cites_notice_quantity"])
        vague = self.eval.score_run(case, run_row("影响不大。"), [])
        self.assertFalse(vague["success"])
        self.assertIn("missing_info_not_stated", vague["labels"])

    def test_an_off_topic_request_must_be_declined_without_tools(self):
        case = self.cases["B06"]
        self.assertTrue(self.eval.score_run(case, run_row("I can't book flights."), [])["success"])
        self.assertFalse(self.eval.score_run(case, run_row(
            "I can't.", [("describe_network", {"network": "asml"}, True)]), [])["success"])

    def test_probabilities_are_compared_after_normalising(self):
        expected = {"network": "asml", "scenarios": ["normal", "red_sea"], "probabilities": [70, 30]}
        self.assertTrue(self.eval._call_matches(expected, {**expected, "probabilities": [0.7, 0.3]}))
        self.assertFalse(self.eval._call_matches(expected, {**expected, "probabilities": [0.5, 0.5]}))

    def test_an_interface_error_or_unsupported_number_fails_the_run_and_is_labelled(self):
        timed_out = self.eval.score_run(self.cases["B06"], run_row("", error="cannot reach host: timed out"), [])
        self.assertEqual(timed_out["labels"][0], "timeout")
        number = self.eval.score_run(self.cases["B06"], run_row("I can't; 42.", faithful=False), [])
        self.assertIn("unsupported_number", number["labels"])
        self.assertFalse(number["success"])

    def test_the_interval_treats_repeats_of_a_task_as_one_unit(self):
        rows = [{"case_id": f"T{i}", "score": {"success": i < 5}} for i in range(10) for _ in range(3)]
        once = [{"case_id": f"T{i}", "score": {"success": i < 5}} for i in range(10)]
        value = self.eval.METRICS["task_success"]
        self.assertEqual(self.eval.bootstrap(self.eval.by_case(rows, value)),
                         self.eval.bootstrap(self.eval.by_case(once, value)))

    def test_list_price_cost_separates_cached_and_written_input(self):
        prices = {"input": 2.0, "cached_input": 0.1, "cache_write": 2.5, "output": 10.0}
        request = {"input_tokens": 1000, "cached_tokens": 100, "cache_write_tokens": 50, "output_tokens": 300}
        self.assertAlmostEqual(self.eval.request_cost(request, prices),
                               (850 * 2 + 100 * 0.1 + 50 * 2.5 + 300 * 10) / 1e6)

    def test_an_effective_configuration_that_differs_from_the_protocol_is_caught(self):
        config = {"model": "gpt-6.1-sol", "reasoning_effort": "max", "reasoning_mode": "standard",
                  "service_tier": "default"}
        good = {"endpoints": ["responses"], "models": ["gpt-6.1-sol-2026-10-01"], "reasoning_efforts": ["max"],
                "reasoning_modes": [None], "service_tiers": ["default"]}
        self.assertIsNone(self.eval.config_mismatch(good, config))
        for key, value in (("models", ["gpt-6-luna"]), ("reasoning_efforts", ["xhigh"]),
                           ("service_tiers", ["priority"]), ("endpoints", ["chat/completions"])):
            with self.subTest(key):
                self.assertIn(key, self.eval.config_mismatch({**good, key: value}, config))


class ClientRecordTests(Base):
    def test_responses_requests_carry_the_fixed_configuration_and_the_reply_is_recorded(self):
        os.environ.update(LLM_API_STYLE="responses", LLM_REASONING_EFFORT="max", LLM_REASONING_MODE="standard",
                          LLM_SERVICE_TIER="default")
        fake = self.provider(default=(200, responses_reply()))
        client = self.client(fake)
        client.chat([{"role": "user", "content": "hi"}])
        body = fake.requests[0]["body"]
        self.assertEqual(body["reasoning"], {"effort": "max", "mode": "standard"})
        self.assertEqual(body["service_tier"], "default")
        self.assertNotIn("temperature", body)
        log = client.request_log[0]
        self.assertEqual((log["model"], log["reasoning_effort"], log["reasoning_mode"], log["service_tier"]),
                         ("gpt-6.1-sol-2026-10-01", "max", "standard", "default"))
        self.assertEqual((log["input_tokens"], log["cached_tokens"], log["cache_write_tokens"], log["output_tokens"],
                          log["reasoning_tokens"]), (1000, 100, 50, 300, 200))
        self.assertNotIn(KEY, json.dumps(client.request_log))

    def test_failed_attempts_are_recorded_and_retries_are_counted(self):
        os.environ["LLM_API_STYLE"] = "responses"
        fake = self.provider([(503, {"error": {"message": "busy"}})], default=(200, responses_reply()))
        client = self.client(fake)
        client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual([r.get("failure") for r in client.request_log], ["HTTP 503", None])
        self.assertEqual(client.spending()["requests"], 2)

    def test_exhausted_quota_is_not_retried(self):
        from planning_agent.spending import LLMError
        os.environ["LLM_API_STYLE"] = "responses"
        fake = self.provider(default=(429, {"error": {"code": "insufficient_quota", "message": "no credit"}}))
        with self.assertRaisesRegex(LLMError, "insufficient_quota"):
            self.client(fake).chat([{"role": "user", "content": "hi"}])
        self.assertEqual(len(fake.requests), 1)

    def test_a_failed_or_incomplete_response_raises(self):
        from planning_agent.spending import LLMError
        os.environ["LLM_API_STYLE"] = "responses"
        for reply, pattern in ((responses_reply(status="failed"), "the response failed"),
                               ({**responses_reply(status="incomplete"), "incomplete_details": {
                                   "reason": "content_filter"}}, "content_filter"),
                               ({**responses_reply(status="incomplete"), "incomplete_details": {
                                   "reason": "max_output_tokens"}}, "cap of 500")):
            with self.subTest(pattern), self.assertRaisesRegex(LLMError, pattern):
                self.client(self.provider(default=(200, reply))).chat([{"role": "user", "content": "hi"}])


@unittest.skipUnless(GRAPH, "requires the agent extra")
class RunBookkeepingTests(Base):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.output = self.root / "model"
        (self.root / "gold.json").write_text(json.dumps({"A08": [], "B06": []}), encoding="utf-8")

    def run_eval(self, fake, ids=("B06",), repeats=3, **config):
        from planning_agent import eval_v2
        base = json.loads(eval_v2.CONFIG.read_text(encoding="utf-8"))
        path = self.root / "config.json"
        path.write_text(json.dumps({**base, **config}), encoding="utf-8")
        with mock.patch.object(eval_v2, "CONFIG", path), mock.patch("time.sleep"):
            return eval_v2.run_evaluation("graph", self.output, repeats=repeats, ids=ids, api_key=KEY,
                                          base_url=fake.url, execute=True, progress=lambda line: None)

    def runs(self):
        from planning_agent import eval_v2
        return eval_v2.read_jsonl(self.output / "runs.jsonl")

    def test_each_repeat_is_its_own_run_with_a_label_and_no_credentials(self):
        fake = self.provider(default=(200, responses_reply("I can't help with that.")))
        report = self.run_eval(fake)
        rows = self.runs()
        self.assertIsNone(report["stopped"])
        self.assertEqual([r["repeat"] for r in rows], [1, 2, 3])
        self.assertEqual(len({r["run_id"] for r in rows}), 3)
        self.assertEqual(rows[0]["call_kind"], "local")
        self.assertEqual(rows[0]["effective"]["reasoning_efforts"], ["max"])
        self.assertTrue(all(r["score"]["success"] for r in rows))
        for path in self.output.rglob("*"):
            if path.is_file():
                self.assertNotIn(KEY, path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(len(fake.requests), 3)
        self.assertTrue(all(r["body"]["input"][0]["role"] == "system" for r in fake.requests))
        self.assertTrue(all(len(r["body"]["input"]) == 2 for r in fake.requests))  # nothing carried over

    def test_a_stopped_run_continues_where_it_stopped(self):
        fake = self.provider(default=(200, responses_reply("I can't help with that.")))
        self.run_eval(fake, repeats=2)
        self.run_eval(fake, repeats=3)
        self.assertEqual(len(self.runs()), 3)
        self.assertEqual(len(fake.requests), 3)

    def test_a_transient_failure_is_retried_as_a_new_attempt_and_kept(self):
        from planning_agent import eval_v2
        fake = self.provider([(503, {"error": {"message": "busy"}})], default=(200, responses_reply("I can't.")))
        self.run_eval(fake, repeats=1, client_retries=0)
        attempts = eval_v2.read_jsonl(self.output / "attempts.jsonl")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(self.runs()[0]["attempt"], 2)
        self.assertEqual(len(fake.requests), 2)

    def test_bad_credentials_stop_the_whole_evaluation(self):
        fake = self.provider(default=(401, {"error": {"message": "bad key"}}))
        report = self.run_eval(fake)
        self.assertIn("HTTP 401", report["stopped"]["reason"])
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(self.runs(), [])

    def test_a_different_model_or_effort_stops_the_evaluation(self):
        fake = self.provider(default=(200, responses_reply("I can't.", effort="xhigh")))
        report = self.run_eval(fake)
        self.assertIn("reasoning_efforts", report["stopped"]["reason"])
        self.assertEqual(self.runs(), [])

    def test_the_budget_stops_the_evaluation_and_the_saved_runs_stay(self):
        fake = self.provider(default=(200, responses_reply("I can't.", input_tokens=1000, output_tokens=1000)))
        report = self.run_eval(fake, repeats=3, max_requests=2)
        self.assertIn("budget", report["stopped"]["reason"])
        self.assertEqual(len(self.runs()), 2)
        self.assertEqual(len(fake.requests), 2)

    def test_a_model_run_needs_the_explicit_switch(self):
        from planning_agent import eval_v2
        with self.assertRaises(SystemExit):
            eval_v2.run_evaluation("graph", self.output, ids=("B06",), api_key=KEY, execute=False)


if __name__ == "__main__":
    unittest.main()
