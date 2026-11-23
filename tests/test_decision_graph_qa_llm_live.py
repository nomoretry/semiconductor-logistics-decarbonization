"""Exercise DQ-3 budget and response handling against an HTTP loopback server."""
from __future__ import annotations

import contextlib
import io
import json
import os
import threading
import time
import unittest
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from decision_graph_qa.llm.data import (
    LlmError,
    Task,
    load_config,
    plan,
    read_jsonl,
    response_path,
)
from decision_graph_qa.llm.live import TIER_BOUND, run
from decision_graph_qa.llm.transport import (
    ApiError,
    Client,
    Ledger,
    Prices,
    decode_response,
)

KEY = "sk-" + "local-dq3-test-sentinel"
PRICES = Prices(Decimal("2.00"), Decimal("0.10"), Decimal("2.50"), Decimal("10.00"))


def task(index: int) -> Task:
    return Task("smoke", "S", "None", "test-stable-5171/mpc_scenarios/0", f"P3.ship.{index}",
                {"model": "gpt-6.2-sol", "instructions": "Reply in JSON.", "input": f"Question {index}",
                 "reasoning": {"effort": "max", "mode": "standard"}, "max_output_tokens": 64000, "store": False})


def reply(text: str = "[[0,0],[0,0],[0,0]]") -> dict:
    return {"status": "completed", "model": "gpt-6.2-sol-snapshot", "reasoning": {"effort": "max", "mode": "standard"},
            "output": [{"type": "reasoning"},
                       {"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 30},
                      "output_tokens": 300, "output_tokens_details": {"reasoning_tokens": 280}}}


@contextlib.contextmanager
def fake_server(respond):
    arrivals = []
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with lock:
                index = len(arrivals)
                arrivals.append((self.path, body, time.monotonic()))
            status, payload, retry_after, delay = respond(index, body)
            if delay:
                time.sleep(delay)
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                if retry_after is not None:
                    self.send_header("Retry-After", retry_after)
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())
            except ConnectionError:
                pass

        def log_message(self, *_args):
            return

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}/v1"
            with patch.dict(os.environ, {"DQ3_API_BASE": base, "OPENAI_API_KEY": KEY}):
                yield arrivals
        finally:
            server.shutdown()
            thread.join()


class LiveRunnerTest(unittest.TestCase):
    def test_parallel_budget_and_attempt_caps_apply_before_send(self):
        tasks = [task(index) for index in range(8)]

        def respond(_index, _body):
            payload = reply()
            del payload["usage"]
            return 200, payload, None, 0.03

        with TemporaryDirectory() as tmp, fake_server(respond) as arrivals:
            root = Path(tmp)
            exact = PRICES.worst(tasks[0])
            result = run(root, tasks, PRICES, workers=8, max_usd=exact)
            self.assertEqual(result["stop_reason"], "max_usd")
            self.assertEqual(result["attempted"], 1)
            self.assertEqual(Ledger(root).committed_total(), exact)
            self.assertEqual(len(arrivals), 1)
            result = run(root, tasks, PRICES, workers=8, max_usd=Decimal(10), max_calls=2)
            self.assertEqual(result["stop_reason"], "max_calls")
            self.assertEqual(result["previous"], 1)
            self.assertEqual(result["attempted"], 2)
            self.assertEqual(len(arrivals), 3)
            self.assertEqual(Ledger(root).committed_total(), exact * 3)

    def test_stops_for_auth_and_spend_codes_regardless_of_http_status(self):
        cases = [(401, None), (403, None), (429, "insufficient_quota"), (400, "credit_balance_exhausted"),
                 (500, "project_spend_limit_exceeded"), (200, "organization_spend_limit_exceeded")]
        for status, code in cases:
            with self.subTest(status=status, code=code):
                def respond(_index, _body, status=status, code=code):
                    return status, {"error": {"code": code, "message": "stopped"}}, "0", 0

                with TemporaryDirectory() as tmp, fake_server(respond) as arrivals:
                    result = run(Path(tmp), [task(0), task(1)], PRICES, workers=1, max_usd=Decimal(100))
                    self.assertEqual(result["stop_reason"], code or f"http_{status}")
                    self.assertEqual(result["attempted"], 1)
                    self.assertEqual(len(arrivals), 1)

    def test_retry_after_and_server_retry_limit(self):
        def respond(index, _body):
            return (429, {"error": {"message": "limited"}}, "0.05", 0) if index == 0 else (200, reply(), None, 0)

        with TemporaryDirectory() as tmp, fake_server(respond) as arrivals:
            root = Path(tmp)
            result = run(root, [task(0)], PRICES, workers=1, max_usd=Decimal(100))
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["attempted"], 2)
            self.assertGreaterEqual(arrivals[1][2] - arrivals[0][2], 0.045)
            saved = list(read_jsonl(response_path(root, "smoke", "S")))
            self.assertEqual(saved[0]["attempts"], 2)
            self.assertEqual(Decimal(saved[0]["actual_usd"]), Decimal("0.003177"))
            self.assertEqual(Decimal(saved[0]["charged_usd"]), Decimal("0.003177"))

        def unavailable(_index, _body):
            return 503, {"error": {"message": "unavailable"}}, "0", 0

        with TemporaryDirectory() as tmp, fake_server(unavailable) as arrivals:
            root = Path(tmp)
            result = run(root, [task(0)], PRICES, workers=1, max_usd=Decimal(100))
            self.assertEqual(result["statuses"], {"error": 1})
            self.assertEqual(len(arrivals), 3)
            self.assertEqual(Ledger(root).committed_total(), PRICES.worst(task(0)) * 3)

    def test_unknown_timeout_charged_and_reserved_attempt_survives_restart(self):
        def respond(_index, _body):
            return 200, reply(), None, 0.15

        with TemporaryDirectory() as tmp, fake_server(respond):
            root = Path(tmp)
            case = task(0)
            exact = PRICES.worst(case)
            result = run(root, [case], PRICES, max_usd=Decimal(10), max_calls=1, workers=1, timeout=0.025)
            self.assertEqual(result["statuses"], {"error": 1})
            self.assertEqual(Ledger(root).committed_total(), exact)
            ledger = Ledger(root)
            ledger.reserve("unfinished", exact, {})
            self.assertEqual(Ledger(root).committed_total(), exact * 2)
            result = run(root, [case], PRICES, max_usd=exact * 2, workers=1)
            self.assertEqual(result["attempted"], 0)
            self.assertEqual(result["stop_reason"], "max_usd")

    def test_resume_skips_terminal_records_and_retries_errors(self):
        truncated = {**reply(), "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
        responses = [(200, reply()), (200, reply("prefix {}")), (200, truncated),
                     (400, {"error": {"message": "failed"}}), (200, reply())]

        def respond(index, _body):
            status, payload = responses[index]
            return status, payload, None, 0

        with TemporaryDirectory() as tmp, fake_server(respond) as arrivals:
            root = Path(tmp)
            tasks = [task(index) for index in range(4)]
            result = run(root, tasks, PRICES, workers=1, max_usd=Decimal(100))
            self.assertEqual(result["statuses"], {"ok": 1, "parse_failure": 1, "truncated": 1, "error": 1})
            first = Ledger(root).committed_total()
            result = run(root, tasks, PRICES, workers=1, max_usd=Decimal(100))
            self.assertEqual((result["previous"], result["attempted"], result["remaining"]), (3, 1, 0))
            self.assertEqual([row[1] for row in arrivals], [case.body for case in tasks] + [tasks[-1].body])
            self.assertEqual(Ledger(root).committed_total(), first + Decimal("0.003177"))

    def test_secret_does_not_reach_files_streams_or_exception(self):
        def respond(index, _body):
            if index == 0:
                return 200, reply(json.dumps(KEY)), None, 0
            return 400, {"error": {"message": f"Echoed {KEY} and sk-other-credential"}}, None, 0

        stdout, stderr = io.StringIO(), io.StringIO()
        with TemporaryDirectory() as tmp, fake_server(respond):
            root = Path(tmp)
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                run(root, [task(0), task(1)], PRICES, workers=1, max_usd=Decimal(100))
                with self.assertRaises(ApiError) as context:
                    Client.from_env().json("POST", "/responses", task(0).body)
            texts = [str(context.exception), stdout.getvalue(), stderr.getvalue()]
            texts.extend(file.read_text(encoding="utf-8") for file in root.rglob("*") if file.is_file())
            for text in texts:
                self.assertNotIn(KEY, text)
                self.assertNotIn("sk-other-credential", text)

    def test_decode_plain_fence_and_nonterminal_status(self):
        backticks = chr(96) * 3
        inputs = [(" true ", "ok", True), (f"{backticks}json\n[0,1]\n{backticks}", "ok", [0, 1]),
                  ("before true", "parse_failure", None), ("null", "ok", None)]
        for text, status, value in inputs:
            with self.subTest(text=text):
                row = decode_response(task(0), reply(text), PRICES, transport="sync")
                self.assertEqual((row["status"], row["parsed"]), (status, value))
        incomplete = {**reply(), "status": "incomplete", "incomplete_details": {"reason": "content_filter"}}
        self.assertEqual(decode_response(task(0), incomplete, PRICES, transport="sync")["status"], "error")

    def test_disallow_external_override_before_network(self):
        override = {"DQ3_API_BASE": "https://example.invalid/v1", "OPENAI_API_KEY": KEY}
        with patch.dict(os.environ, override), self.assertRaisesRegex(LlmError, "loopback"):
            Client.from_env()

    def test_protocol_requests_default_service_tier(self):
        config = load_config()
        self.assertEqual({arm["request"]["service_tier"] for arm in config["arms"].values()}, {"default"})
        self.assertEqual({case.body["service_tier"] for case in plan(config, "smoke", "S")}, {"default"})

    def test_service_tier_mismatch_stops_dispatch_and_books_upper_bound(self):
        def respond(index, _body):
            payload = reply()
            payload["service_tier"] = "default" if index == 0 else "priority"
            return 200, payload, None, 0

        with TemporaryDirectory() as tmp, fake_server(respond) as arrivals:
            root = Path(tmp)
            result = run(root, [task(index) for index in range(3)], PRICES, workers=1, max_usd=Decimal(100))
            self.assertEqual((result["stop_reason"], result["attempted"], len(arrivals)), ("service_tier", 2, 2))
            saved = list(read_jsonl(response_path(root, "smoke", "S")))
            self.assertEqual([row["service_tier"] for row in saved], ["default", "priority"])
            self.assertEqual([row["status"] for row in saved], ["ok", "ok"])
            self.assertEqual(Decimal(saved[0]["charged_usd"]), Decimal("0.003177"))
            self.assertEqual(Decimal(saved[1]["charged_usd"]), Decimal("0.003177") * TIER_BOUND)
            self.assertEqual(TIER_BOUND, 6)
            self.assertEqual(Ledger(root).committed_total(), Decimal("0.003177") * (1 + TIER_BOUND))
