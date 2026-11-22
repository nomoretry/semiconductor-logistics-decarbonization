"""Limits, key handling and the paid-mode switch, tested without any external model.

Three kinds of evidence are kept apart: a local HTTP server speaking the OpenAI wire format (simulated provider, real
HTTP path), a scripted client (no HTTP), and replays of recorded runs (test_planning_graph.py). Nothing here leaves
this machine: every client points at 127.0.0.1 and the environment is cleared around each test.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from planning_agent import llm
from planning_agent.spending import BudgetExceeded, Limits, LLMError, Meter, input_bound, limits_from_env

PLANNING = all(importlib.util.find_spec(name) for name in ("pulp", "highspy"))
GRAPH = PLANNING and importlib.util.find_spec("langgraph") is not None
UI = PLANNING and importlib.util.find_spec("streamlit") is not None
ROOT = Path(__file__).resolve().parents[1]
KEY = "sk-unit-test-credential-0123456789"
SETTINGS = {"n_skus": 6, "seed": 3}
SCENARIO_CALL = {"id": "c1", "type": "function", "function": {"name": "create_scenario", "arguments": json.dumps(
    {"network": "asml", "name": "x_notice", "disruptions": [
        {"mode": "ocean", "start_week": 5, "end_week": 8, "extra_lead_weeks": 1}]})}}


def reply(content="ok", prompt=100, completion=20, tool_calls=None, finish="stop"):
    return {"choices": [{"message": {"content": content, "tool_calls": tool_calls}, "finish_reason": finish}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}


class FakeProvider:
    """A local OpenAI-compatible endpoint: plays scripted (status, json) pairs and records what it received."""

    def __init__(self, script=None, default=None):
        self.script, self.default, self.requests = list(script or []), default or (200, reply()), []
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                provider.requests.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
                status, data = provider.script.pop(0) if provider.script else provider.default
                headers = {}
                if status in (301, 302, 303, 307):
                    headers, data = {"Location": data}, {}
                raw = json.dumps(data).encode("utf-8")
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Base(unittest.TestCase):
    def setUp(self):
        clean = {k: v for k, v in os.environ.items() if not k.startswith("LLM_")}
        patcher = mock.patch.dict(os.environ, clean, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def provider(self, script=None, default=None):
        fake = FakeProvider(script, default)
        self.addCleanup(fake.close)
        return fake

    def client(self, fake, limits=None, **options):
        return llm.OpenAICompatibleClient(api_key=KEY, base_url=fake.url, model="m", limits=limits or LIMITS, **options)


LIMITS = Limits(max_requests=10, max_total_tokens=100_000, max_output_tokens=500)
HI = [{"role": "user", "content": "hi"}]


class ConfigurationTests(Base):
    def test_a_client_needs_a_key_a_model_and_limits(self):
        with self.assertRaisesRegex(LLMError, "LLM_API_KEY"):
            llm.OpenAICompatibleClient(model="m", limits=LIMITS)
        with self.assertRaisesRegex(LLMError, "LLM_MODEL_ID"):
            llm.OpenAICompatibleClient(api_key=KEY, limits=LIMITS)
        with self.assertRaisesRegex(LLMError, "LLM_MAX_REQUESTS, LLM_MAX_TOTAL_TOKENS, LLM_MAX_OUTPUT_TOKENS"):
            llm.OpenAICompatibleClient(api_key=KEY, model="m")

    def test_model_and_endpoint_come_from_the_environment(self):
        os.environ.update(LLM_API_KEY=KEY, LLM_BASE_URL="https://api.deepseek.com/v1/", LLM_MODEL_ID="deepseek-chat",
                          LLM_MAX_REQUESTS="3", LLM_MAX_TOTAL_TOKENS="9000", LLM_MAX_OUTPUT_TOKENS="300")
        client = llm.OpenAICompatibleClient()
        self.assertEqual((client.base_url, client.model, client.call_kind),
                         ("https://api.deepseek.com/v1", "deepseek-chat", "real"))
        self.assertEqual(client.max_output_tokens, 300)
        self.assertEqual(llm.problems(), [])

    def test_the_key_only_travels_over_tls_or_stays_on_this_machine(self):
        for bad in ("http://api.example.com/v1", "https://user:pw@api.example.com/v1", "ftp://api.example.com",
                    "https://api.example.com/v1?token=abc", "not a url"):
            with self.subTest(bad), self.assertRaises(LLMError):
                llm.OpenAICompatibleClient(api_key=KEY, base_url=bad, model="m", limits=LIMITS)
        for good in ("https://api.example.com/v1", "http://127.0.0.1:8000/v1", "http://localhost:1/v1"):
            with self.subTest(good):
                llm.OpenAICompatibleClient(api_key=KEY, base_url=good, model="m", limits=LIMITS)

    def test_limits_are_read_as_numbers_and_a_usd_cap_needs_prices(self):
        os.environ.update(LLM_MAX_REQUESTS="many", LLM_MAX_TOTAL_TOKENS="1", LLM_MAX_OUTPUT_TOKENS="1")
        with self.assertRaisesRegex(LLMError, "LLM_MAX_REQUESTS must be a number"):
            limits_from_env()
        os.environ.update(LLM_MAX_REQUESTS="1", LLM_MAX_USD="0.5")
        with self.assertRaisesRegex(LLMError, "USD limit needs"):
            limits_from_env()
        os.environ.update(LLM_INPUT_USD_PER_M="0.1", LLM_OUTPUT_USD_PER_M="0.5")
        self.assertEqual(limits_from_env().max_usd, 0.5)

    @unittest.skipUnless(PLANNING, "requires the planning extra")
    def test_the_check_command_reports_problems_and_never_prints_the_key(self):
        from planning_agent.__main__ import main
        os.environ.update(LLM_API_KEY=KEY)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch("planning_agent.llm._open", side_effect=AssertionError):
            self.assertEqual(main(["llm-check"]), 2)
        report = json.loads(out.getvalue())
        self.assertTrue(report["key_set"])
        self.assertTrue(any("LLM_MODEL_ID" in p for p in report["problems"]))
        self.assertNotIn(KEY, out.getvalue())

    @unittest.skipUnless(PLANNING, "requires the planning extra")
    def test_a_key_alone_never_starts_a_paid_call_from_the_command_line(self):
        from planning_agent.__main__ import _agent, main
        os.environ.update(LLM_API_KEY=KEY, LLM_MODEL_ID="m")
        with mock.patch("planning_agent.llm._open", side_effect=AssertionError("network")):
            with contextlib.redirect_stderr(io.StringIO()) as warning:
                self.assertEqual(_agent("auto"), ("rule", None))  # falls back, and says so
            self.assertIn("离线规则", warning.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--agent", "llm", "ask", "你好"]), 2)
                self.assertEqual(main(["--agent", "graph", "ask", "你好"]), 2)
                self.assertEqual(main(["flow", "--mode", "live", "--yes"]), 2)


class LimitTests(Base):
    def test_the_output_cap_is_sent_with_every_request(self):
        fake = self.provider()
        self.client(fake).chat(HI)
        self.assertEqual(fake.requests[0]["body"]["max_tokens"], 500)

    def test_models_that_rename_the_output_cap_keep_a_cap(self):
        fake = self.provider([(400, {"error": {"message": "Use 'max_completion_tokens' instead of 'max_tokens'."}})])
        client = self.client(fake)
        client.chat(HI)
        self.assertEqual(fake.requests[1]["body"]["max_completion_tokens"], 500)
        self.assertNotIn("max_tokens", fake.requests[1]["body"])
        self.assertEqual(client.spending()["requests"], 2)

    def test_the_responses_api_gets_the_cap_too(self):
        os.environ["LLM_API_STYLE"] = "responses"
        fake = self.provider(default=(200, {"output": [], "usage": {"input_tokens": 1, "output_tokens": 1}}))
        self.client(fake).chat(HI)
        self.assertEqual(fake.requests[0]["body"]["max_output_tokens"], 500)

    def test_a_request_that_could_pass_the_total_is_refused_before_it_is_sent(self):
        fake = self.provider()
        client = self.client(fake, Limits(10, 1200, 500))
        with self.assertRaises(BudgetExceeded):
            for _ in range(10):
                client.chat(HI)
        sent = len(fake.requests)
        self.assertGreaterEqual(sent, 2)  # each reservation is about 600 tokens, each settled use is 120
        self.assertLess(sent, 10)
        self.assertLessEqual(client.spending()["tokens"], 1200)
        self.assertIn("token limit", client.budget_stop)
        with self.assertRaises(BudgetExceeded):
            client.chat(HI)
        self.assertEqual(len(fake.requests), sent)  # nothing new on the wire

    def test_retries_and_fallbacks_count_as_requests(self):
        fake = self.provider(default=(503, {"error": {"message": "overloaded"}}))
        client = self.client(fake, Limits(2, 100_000, 500), retries=5)
        with self.assertRaises(BudgetExceeded):
            client.chat(HI)
        self.assertEqual(len(fake.requests), 2)

    def test_a_request_with_too_much_input_is_refused_without_ending_the_run(self):
        fake = self.provider()
        client = self.client(fake, Limits(10, 100_000, 500, max_input_tokens=200))
        with self.assertRaisesRegex(BudgetExceeded, "per-request"):
            client.chat([{"role": "user", "content": "货" * 200}])
        self.assertEqual(fake.requests, [])
        self.assertIsNone(client.budget_stop)

    def test_a_usd_limit_is_enforced_before_sending(self):
        fake = self.provider(default=(200, reply(prompt=1000, completion=1000)))
        limits = Limits(10, 10_000_000, 1000, max_usd=0.003, input_usd_per_m=1.0, output_usd_per_m=1.0)
        client = self.client(fake, limits)
        client.chat(HI)  # reserves about 0.0011; settles at 0.002
        with self.assertRaisesRegex(BudgetExceeded, "USD limit"):
            client.chat(HI)  # 0.002 + 0.0011 could pass 0.003
        self.assertEqual(len(fake.requests), 1)

    def test_rejected_requests_cost_no_tokens_and_unknown_outcomes_stay_charged(self):
        fake = self.provider([(401, {"error": {"message": "bad key"}}), (500, {"error": {"message": "boom"}})])
        client = self.client(fake, retries=0)
        with self.assertRaises(LLMError):
            client.chat(HI)
        self.assertEqual(client.spending()["tokens"], 0)
        with self.assertRaises(LLMError):
            client.chat(HI)  # a 500 may have run the model
        after = client.spending()
        self.assertEqual(after["unconfirmed_requests"], 1)
        self.assertGreaterEqual(after["tokens"], 500)

    def test_a_reply_without_usage_is_charged_at_the_reservation(self):
        data = reply()
        del data["usage"]
        client = self.client(self.provider(default=(200, data)))
        client.chat(HI)
        self.assertEqual(client.spending()["unconfirmed_requests"], 1)
        self.assertGreaterEqual(client.spending()["tokens"], 500)

    def test_a_provider_that_ignores_the_cap_is_visible_and_ends_the_run(self):
        fake = self.provider(default=(200, reply(prompt=100, completion=5000)))
        client = self.client(fake, Limits(10, 5200, 500))
        client.chat(HI)
        self.assertGreater(client.spending()["overrun_tokens"], 0)
        with self.assertRaises(BudgetExceeded):
            client.chat(HI)
        self.assertEqual(len(fake.requests), 1)

    def test_truncated_output_is_an_error_and_not_a_partial_tool_call(self):
        client = self.client(self.provider(default=(200, reply(tool_calls=[SCENARIO_CALL], finish="length"))))
        with self.assertRaisesRegex(LLMError, "cap of 500"):
            client.chat(HI)
        self.assertEqual(client.spending()["tokens"], 120)  # what it did use is still counted

    @unittest.skipUnless(PLANNING, "requires the planning extra")
    def test_the_input_bound_covers_the_recorded_single_request_usage(self):
        """Recorded one-call cases, gpt-6.1-sol: 1,348 to 1,359 input tokens. The bound must not be below them."""
        from planning_agent.agent import SYSTEM_PROMPT
        from planning_agent.tools import Session
        rows = [json.loads(line) for line in (ROOT / "benchmark_results/planning_agent/llm_cases.jsonl")
                .read_text(encoding="utf-8").splitlines() if line.strip()]
        checked = 0
        for row in rows:
            if row["usage"]["calls"] != 1:
                continue
            body = {"model": "m", "input": [{"role": "system", "content": SYSTEM_PROMPT},
                                            {"role": "user", "content": row["question"]}],
                    "tools": [{"type": "function", **t["function"]} for t in Session().schemas()]}
            self.assertGreaterEqual(input_bound(json.dumps(body, ensure_ascii=False).encode("utf-8")),
                                    row["usage"]["prompt_tokens"])
            checked += 1
        self.assertGreater(checked, 0)


class LedgerTests(Base):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "nested" / "ledger.jsonl"

    def test_totals_carry_over_to_a_later_run(self):
        limits = Limits(2, 100_000, 500)
        fake = self.provider()
        self.client(fake, meters=[Meter(limits, self.path)]).chat(HI)
        later = self.client(fake, meters=[Meter(limits, self.path)])
        later.chat(HI)
        with self.assertRaises(BudgetExceeded):
            self.client(fake, meters=[Meter(limits, self.path)]).chat(HI)
        self.assertEqual(len(fake.requests), 2)
        self.assertEqual(later.spending()["tokens"], 240)

    def test_a_crash_leaves_the_reservation_charged(self):
        limits = Limits(5, 2000, 500)
        Meter(limits, self.path).reserve(1000)  # the process dies here
        self.assertEqual(Meter(limits, self.path).snapshot()["tokens"], 1500)
        self.assertEqual(Meter(limits, self.path).snapshot()["unconfirmed_requests"], 1)
        with self.assertRaises(BudgetExceeded):
            Meter(limits, self.path).reserve(100)

    def test_an_unreadable_ledger_refuses_calls(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"id": "a", "day"\n', encoding="utf-8")
        fake = self.provider()
        with self.assertRaisesRegex(LLMError, "unreadable"):
            self.client(fake, meters=[Meter(LIMITS, self.path)]).chat(HI)
        self.assertEqual(fake.requests, [])

    def test_a_daily_ledger_starts_again_on_the_next_utc_day(self):
        now = [1_800_000_000.0]
        meter = Meter(Limits(1, 100_000, 500), self.path, daily=True, clock=lambda: now[0])
        meter.reserve(10)
        with self.assertRaises(BudgetExceeded):
            meter.reserve(10)
        now[0] += 86_400
        meter.reserve(10)

    def test_every_meter_must_agree_and_a_refusal_leaves_no_hold_behind(self):
        fake = self.provider()
        wide, narrow = Meter(LIMITS), Meter(Limits(1, 100_000, 400))
        client = self.client(fake, meters=[wide, narrow])
        client.chat(HI)
        self.assertEqual(fake.requests[0]["body"]["max_tokens"], 400)  # the stricter output cap wins
        with self.assertRaises(BudgetExceeded):
            client.chat(HI)
        self.assertEqual(wide.snapshot()["requests"], 1)

    def test_the_ledger_holds_counts_only(self):
        fake = self.provider()
        self.client(fake, meters=[Meter(LIMITS, self.path)]).chat([{"role": "user", "content": "机密货物清单"}])
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("机密", text)
        self.assertNotIn(KEY, text)


class KeyHandlingTests(Base):
    def test_a_key_echoed_by_the_provider_never_reaches_the_error(self):
        echoes = [f"Incorrect API key provided: {KEY}", "Incorrect API key provided: sk-abc***xyz",
                  "bad header Authorization: Bearer abc.def", 'config had api_key="s3cret-value"']
        for text in echoes:
            with self.subTest(text):
                client = self.client(self.provider(default=(401, {"error": {"message": text}})))
                with self.assertRaises(LLMError) as caught:
                    client.chat(HI)
                message = str(caught.exception)
                for secret in (KEY, "sk-abc", "abc.def", "s3cret-value"):
                    self.assertNotIn(secret, message)

    def test_the_client_does_not_show_the_key_when_printed(self):
        client = self.client(self.provider())
        self.assertNotIn(KEY, repr(client))
        self.assertNotIn(KEY, str(client))
        self.assertNotIn("api_key", vars(client))

    def test_a_redirect_is_not_followed_so_the_key_stays_with_the_configured_host(self):
        other = self.provider()
        fake = self.provider(default=(302, other.url + "/stolen"))
        with self.assertRaisesRegex(LLMError, "HTTP 302"):
            self.client(fake, retries=0).chat(HI)
        self.assertEqual(other.requests, [])
        self.assertEqual(fake.requests[0]["auth"], f"Bearer {KEY}")

    @unittest.skipUnless(PLANNING, "requires the planning extra")
    def test_no_output_file_of_a_failed_evaluation_contains_the_key(self):
        from planning_agent.evaluate import evaluate
        fake = self.provider(default=(401, {"error": {"message": f"Incorrect API key provided: {KEY}"}}))
        with tempfile.TemporaryDirectory() as folder:
            evaluate("llm", ids=["D01"], output=Path(folder), settings=SETTINGS, client=self.client(fake, retries=0))
            files = list(Path(folder).iterdir())
            self.assertTrue(files)
            for path in files:
                self.assertNotIn(KEY, path.read_text(encoding="utf-8"), path.name)
            self.assertNotIn("sk-", (Path(folder) / "llm_summary.json").read_text(encoding="utf-8"))


@unittest.skipUnless(GRAPH, "requires the agent extra")
class WorkflowTests(Base):
    def test_live_flow_over_http_is_labelled_and_runs_nothing_before_confirmation(self):
        from planning_agent.tools import Session
        from planning_agent.workflow import propose_from_model
        fake = self.provider(default=(200, reply("", tool_calls=[SCENARIO_CALL])))
        with mock.patch.object(Session, "call", side_effect=AssertionError("no tool may run")):
            proposal = propose_from_model("第5到8周海运延误1周", self.client(fake))
        self.assertEqual(len(fake.requests), 1)
        self.assertIn("本机接口", proposal.source)
        self.assertNotIn("真实模型调用", proposal.source)
        self.assertEqual(proposal.disruptions[0]["extra_lead_weeks"], 1)

    def test_a_truncated_or_failed_call_raises_instead_of_proposing(self):
        from planning_agent.workflow import propose_from_model
        fake = self.provider(default=(200, reply("", tool_calls=[SCENARIO_CALL], finish="length")))
        with self.assertRaisesRegex(LLMError, "cap of 500"):
            propose_from_model("第5到8周海运延误1周", self.client(fake))

    def test_broken_tool_arguments_are_reported_as_such(self):
        from planning_agent.workflow import propose_from_model
        broken = {"id": "c1", "type": "function", "function": {"name": "create_scenario", "arguments": "{\"net"}}
        fake = self.provider(default=(200, reply("", tool_calls=[broken])))
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            propose_from_model("第5到8周海运延误1周", self.client(fake))

    def test_the_graph_stops_on_the_budget_and_replay_keeps_its_label(self):
        from planning_agent.graph import PlanningGraph, ReplayClient
        from planning_agent.tools import Session
        fake = self.provider(default=(200, reply("", tool_calls=[
            {"id": "c1", "type": "function", "function": {"name": "describe_network",
                                                          "arguments": '{"network": "asml"}'}}])))
        client = self.client(fake, Limits(2, 100_000, 500))
        result = PlanningGraph(Session(**SETTINGS), client, max_steps=8).ask("网络有哪些线路？")
        self.assertEqual(len(fake.requests), 2)
        self.assertIn("request limit", result.error)
        self.assertEqual(ReplayClient([], "x").call_kind, "replay")

    def test_an_evaluation_stops_on_the_budget_saves_no_row_for_that_case_and_says_what_it_used(self):
        from planning_agent.evaluate import evaluate
        answer = reply("ASML 备件网络的线路见工具结果。")
        fake = self.provider(default=(200, answer))
        with tempfile.TemporaryDirectory() as folder:
            report = evaluate("llm", ids=["D01", "D02", "D03"], output=Path(folder), settings=SETTINGS,
                              client=self.client(fake, Limits(2, 100_000, 500)))
            rows = (Path(folder) / "llm_cases.jsonl").read_text(encoding="utf-8").splitlines()
        summary = report["summary"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(summary["stopped_early"]["remaining"], ["D03"])
        self.assertEqual(summary["call_kind"], "local")
        self.assertEqual(summary["spending"]["requests"], 2)


@unittest.skipUnless(UI, "requires the ui extra")
class PaidModeSwitchTests(Base):
    CODE = "correct-horse"

    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.ledger = str(Path(folder.name) / "web.jsonl")

    def opened(self, fake, **changes):
        settings = {"LLM_WEB_LIVE": "on", "LLM_API_KEY": KEY, "LLM_MODEL_ID": "m", "LLM_BASE_URL": fake.url,
                    "LLM_WEB_ACCESS_CODE_SHA256": hashlib.sha256(self.CODE.encode()).hexdigest(),
                    "LLM_WEB_MAX_REQUESTS": "20", "LLM_WEB_MAX_TOTAL_TOKENS": "100000",
                    "LLM_WEB_MAX_OUTPUT_TOKENS": "500", "LLM_WEB_SESSION_MAX_REQUESTS": "2",
                    "LLM_WEB_LEDGER_PATH": self.ledger, **changes}
        os.environ.update({k: v for k, v in settings.items() if v is not None})

    def page(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        st.cache_resource.clear()
        os.environ["PLANNING_FLOW_SETTINGS"] = json.dumps(SETTINGS)
        page = AppTest.from_file(str(ROOT / "planning_agent" / "app.py"), default_timeout=180)
        page.run()
        self.assertFalse(page.exception)
        return page

    def page_text(self, page):
        parts = [e.value for group in (page.error, page.warning, page.info, page.markdown, page.caption)
                 for e in group]
        return " ".join(str(p) for p in parts)

    def test_every_missing_setting_keeps_the_paid_mode_closed(self):
        fake = self.provider()
        required = ["LLM_WEB_LIVE", "LLM_API_KEY", "LLM_MODEL_ID", "LLM_WEB_ACCESS_CODE_SHA256", "LLM_WEB_MAX_REQUESTS",
                    "LLM_WEB_MAX_TOTAL_TOKENS", "LLM_WEB_MAX_OUTPUT_TOKENS", "LLM_WEB_SESSION_MAX_REQUESTS"]
        self.opened(fake)
        self.assertTrue(llm.LiveAccess.from_env().open)
        for name in required:
            with self.subTest(name), mock.patch.dict(os.environ):
                del os.environ[name]
                access = llm.LiveAccess.from_env()
                self.assertFalse(access.open)
                self.assertFalse(access.check_code(self.CODE))
                self.assertNotIn(KEY, " ".join(access.problems))

    def test_a_key_alone_does_not_put_a_paid_entry_on_the_page(self):
        os.environ.update(LLM_API_KEY=KEY, LLM_MODEL_ID="m", LLM_MAX_REQUESTS="9", LLM_MAX_TOTAL_TOKENS="9999",
                          LLM_MAX_OUTPUT_TOKENS="99")
        page = self.page()
        self.assertEqual(list(page.radio(key="mode").options), [
            "离线规则解析（不调用模型）", "公告检索 + 规则解析（不调用模型）",
            "录制回放（真实模型的历史输出，本次不调用模型）"])
        self.assertIn("没有开放", self.page_text(page))

    def test_wrong_code_sends_nothing_and_right_code_works_within_the_server_limits(self):
        fake = self.provider(default=(200, reply("", tool_calls=[SCENARIO_CALL])))
        self.opened(fake)
        page = self.page()
        page.radio(key="mode").set_value("live").run()
        self.assertEqual(len(page.number_input), 0)  # no budget widget for visitors
        page.text_input(key="live_code").set_value("guess").run()
        page.button(key="live").click().run()
        self.assertEqual(fake.requests, [])
        self.assertIn("访问码不正确", self.page_text(page))
        page.text_input(key="live_code").set_value(self.CODE).run()
        page.button(key="live").click().run()
        self.assertFalse(page.exception)
        self.assertEqual(len(fake.requests), 1)
        self.assertIn("本机接口", page.info[0].value)
        page.button(key="live").click().run()
        self.assertEqual(len(fake.requests), 2)
        page.button(key="live").click().run()  # session limit is 2
        self.assertEqual(len(fake.requests), 2)
        self.assertIn("额度已用完", self.page_text(page))
        self.assertNotIn(KEY, json.dumps(self.page_text(page)))

    def test_the_daily_limit_holds_across_sessions_and_restarts(self):
        fake = self.provider(default=(200, reply("", tool_calls=[SCENARIO_CALL])))
        self.opened(fake, LLM_WEB_MAX_REQUESTS="1")
        for _ in range(2):  # each page() starts a new session and clears the cached server object
            page = self.page()
            page.radio(key="mode").set_value("live").run()
            page.text_input(key="live_code").set_value(self.CODE).run()
            page.button(key="live").click().run()
            self.assertFalse(page.exception)
        self.assertEqual(len(fake.requests), 1)

    def test_repeated_wrong_codes_lock_the_paid_mode_for_a_while(self):
        self.opened(self.provider())
        access = llm.LiveAccess.from_env()
        for _ in range(llm.MAX_CODE_FAILURES):
            self.assertFalse(access.check_code("guess"))
        self.assertFalse(access.check_code(self.CODE))

    def test_a_failed_call_shows_a_plain_message_with_no_provider_detail(self):
        fake = self.provider(default=(401, {"error": {"message": f"Incorrect API key provided: {KEY}"}}))
        self.opened(fake)
        page = self.page()
        page.radio(key="mode").set_value("live").run()
        page.text_input(key="live_code").set_value(self.CODE).run()
        page.button(key="live").click().run()
        self.assertFalse(page.exception)
        text = self.page_text(page)
        self.assertIn("没有生成参数", text)
        self.assertNotIn("sk-", text)
        self.assertNotIn(fake.url, text)

    def test_public_modes_run_without_the_agent_framework(self):
        with mock.patch.dict(sys.modules, {"langgraph": None, "langgraph.graph": None}):
            page = self.page()
            page.button(key="parse").click().run()
            self.assertFalse(page.exception)
            page.button(key="confirm").click().run()
            self.assertFalse(page.exception)
            self.assertIn("服务水平", [m.label for m in page.metric])
            self.assertIn("当前模式：离线规则解析", self.page_text(page))
            self.assertIn("参数来源：离线规则解析", page.session_state["outcome"].memo_text)

    def test_overlong_input_is_cut_on_the_server(self):
        page = self.page()
        page.text_area(key="notice").set_value("红海" * 2000).run()
        page.button(key="parse").click().run()
        self.assertFalse(page.exception)
        self.assertEqual(len(page.session_state["proposal"].notice), 2000)


if __name__ == "__main__":
    unittest.main()
