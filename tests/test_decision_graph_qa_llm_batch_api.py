"""Exercise Batch wire handling against the documented loopback fixtures."""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from decision_graph_qa.llm.batch import (
    export_batches,
    fetch_batches,
    import_batches,
    submit_batch,
)
from decision_graph_qa.llm.data import (
    LlmError,
    append_jsonl,
    canonical,
    load_config,
    plan,
    read_jsonl,
    response_path,
)
from decision_graph_qa.llm.transport import Client, Ledger, Prices, decode_response

SECRET = "sk-dq3-batch-loopback-sentinel"
BATCH_ID = "batch_0001"
USAGE = {
    "input_tokens": 100,
    "input_tokens_details": {"cached_tokens": 10, "cache_write_tokens": 5},
    "output_tokens": 200,
    "output_tokens_details": {"reasoning_tokens": 175},
    "total_tokens": 300,
}


def _body() -> dict:
    return {
        "id": "resp_0001",
        "object": "response",
        "status": "completed",
        "model": "gpt-6.2-sol-2026-10-01",
        "reasoning": {"effort": "max", "mode": "standard"},
        "output": [{"type": "reasoning", "id": "rs_0001", "summary": []}, {
            "type": "message", "content": [{"type": "output_text", "text": "[[1,0],[3,2],[0,1]]"}],
        }],
        "usage": USAGE,
    }


def _row(key: str, number: int, *, body: dict | None = None, status: int = 200, error: dict | None = None) -> dict:
    response = {"status_code": status, "request_id": f"req_{number:04}", "body": body} if body else None
    return {"id": f"batch_req_{number:04}", "custom_id": key, "response": response, "error": error}


class _Service:
    def __init__(self, statuses: list[str]):
        self.statuses = statuses
        self.queries = []
        self.posts = []
        self.upload_parts = {}
        self.create_body = None
        self.content = {}
        self.metadata = {}

    def batch(self, status: str) -> dict:
        return {
            "id": BATCH_ID, "object": "batch", "endpoint": "/v1/responses",
            "input_file_id": "file-in0001", "completion_window": "24h", "status": status,
            "output_file_id": None, "error_file_id": None, "created_at": 1795430060,
            "request_counts": {"total": 0, "completed": 0, "failed": 0},
            **self.metadata.get(status, {}),
        }


@contextmanager
def _server(service: _Service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def reply(self, value, code=200):
            raw = value if isinstance(value, bytes) else canonical(value)
            self.send_response(code)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            service.posts.append(self.path)
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path == "/v1/files":
                header = f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode("ascii")
                for part in BytesParser(policy=policy.default).parsebytes(header + raw).iter_parts():
                    name = part.get_param("name", header="content-disposition")
                    service.upload_parts[name] = (part.get_filename(), part.get_payload(decode=True))
                self.reply({"id": "file-in0001", "object": "file", "purpose": "batch", "status": "processed"})
            elif self.path == "/v1/batches":
                service.create_body = json.loads(raw)
                self.reply(service.batch("validating"))
            elif self.path == f"/v1/batches/{BATCH_ID}/cancel":
                self.reply(service.batch("cancelling"))
            else:
                self.reply({"error": {"code": "unknown_path"}}, 404)

        def do_GET(self):
            if self.path == f"/v1/batches/{BATCH_ID}":
                index = min(len(service.queries), len(service.statuses) - 1)
                status = service.statuses[index]
                service.queries.append(status)
                self.reply(service.batch(status))
            elif self.path in service.content:
                self.reply(b"".join(canonical(row) + b"\n" for row in service.content[self.path]))
            else:
                self.reply({"error": {"code": "unknown_path"}}, 404)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}/v1"
        with patch.dict("os.environ", {"DQ3_API_BASE": base, "OPENAI_API_KEY": SECRET}):
            try:
                yield
            finally:
                server.shutdown()
                thread.join()


class BatchApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()
        cls.pilot = plan(cls.config, "pilot", "S")[0]
        cls.prices = Prices("1.00", "0.05", "1.25", "5.00")

    def _export(self, root: Path, chunk_size: int) -> tuple[Path, list[str]]:
        row = decode_response(self.pilot, _body(), self.prices, transport="sync")
        append_jsonl(response_path(root, "pilot", "S"), row)
        result = export_batches(
            self.config, root, phase="main", arm="S", size="half", pilot_root=root,
            chunk_size=chunk_size, prices=self.prices,
        )
        path = Path(result["chunks"][0]["file"])
        return path, [row["custom_id"] for row in read_jsonl(path)]

    def _submit(self, root: Path, path: Path):
        return submit_batch(self.config, root, file=path, max_usd=Decimal(1), prices=self.prices)

    def _fetch(self, root: Path):
        result = fetch_batches(root, wait_seconds=5, poll_interval=0.01)
        self.assertFalse(result["wait_expired"])
        return result["batches"][0]

    def _import(self, root: Path, result: dict):
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network call on import")):
            return import_batches(
                self.config, root, files=[Path(path) for path in result["import_files"]], prices=self.prices,
            )

    def test_completed_disordered_files_both_failure_shapes_and_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, keys = self._export(root, 5)
            completed, truncated, inner_error, outer_error, absent = keys
            capped = {**_body(), "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
            service = _Service(["validating", "in_progress", "finalizing", "completed"])
            service.metadata["completed"] = {
                "output_file_id": "file-out0001", "error_file_id": "file-err0001",
                "usage": {"input_tokens": 999, "output_tokens": 400, "total_tokens": 1399,
                          "input_tokens_details": {"cached_tokens": 20},
                          "output_tokens_details": {"reasoning_tokens": 350}},
            }
            service.content = {
                "/v1/files/file-out0001/content": [
                    _row(truncated, 2, body=capped), _row(completed, 1, body=_body()),
                    _row(completed, 1, body=_body()), _row("unknown", 6, body=_body()),
                ],
                "/v1/files/file-err0001/content": [
                    _row(outer_error, 4, error={"code": "server_error", "message": SECRET}),
                    _row(inner_error, 3, body={"error": {"message": SECRET, "type": "invalid_request_error",
                                                        "param": None, "code": None}}, status=400),
                ],
            }

            with _server(service):
                with self.assertRaises(LlmError):
                    submit_batch(self.config, root, file=path, max_usd=Decimal(0), prices=self.prices)
                self.assertEqual(service.posts, [])
                submitted = self._submit(root, path)
                self.assertEqual(submitted["batch_id"], BATCH_ID)
                self.assertEqual(service.upload_parts, {"purpose": (None, b"batch"),
                                                        "file": (path.name, path.read_bytes())})
                self.assertEqual(service.create_body["input_file_id"], "file-in0001")
                self.assertEqual(service.create_body["endpoint"], "/v1/responses")
                self.assertEqual(service.create_body["completion_window"], "24h")
                self.assertEqual(Ledger(root).committed_total(), self.prices.actual({
                    "input_tokens": 100, "cached_tokens": 10, "cache_write_tokens": 5,
                    "output_tokens": 200, "reasoning_tokens": 175,
                }) * 5)
                fetched = self._fetch(root)
            self.assertEqual(service.queries, ["validating", "in_progress", "finalizing", "completed"])
            self.assertEqual(len(fetched["files"]), 2)
            summary = self._import(root, fetched)
            self.assertEqual(summary["imported"], 5)
            self.assertEqual(summary["missing"], [absent])
            self.assertEqual(summary["duplicates"], [completed])
            self.assertEqual(len(summary["unknown"]), 1)
            self.assertEqual(len(summary["usage_comparisons"]), 1)
            self.assertIn("999", json.dumps(summary["usage_comparisons"]))
            rows = {row["custom_id"]: row for row in read_jsonl(response_path(root, "main", "S"))}
            self.assertEqual({key: row["status"] for key, row in rows.items()}, {
                completed: "ok", truncated: "truncated", inner_error: "error", outer_error: "error", absent: "error",
            })
            self.assertEqual(rows[completed]["parsed"], [[1, 0], [3, 2], [0, 1]])
            self.assertEqual(rows[completed]["transport"], "batch")
            actual = Decimal(rows[completed]["actual_usd"])
            self.assertEqual(actual, Decimal("0.00109175"))
            self.assertEqual(Ledger(root).committed_total(), actual * 2)
            repeated = self._import(root, fetched)
            self.assertEqual(repeated["imported"], 0)
            self.assertEqual(Ledger(root).committed_total(), actual * 2)
            for file in root.rglob("*"):
                if file.is_file():
                    self.assertNotIn(SECRET.encode(), file.read_bytes())

    def test_failed_validation_and_empty_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, keys = self._export(root, 2)
            service = _Service(["failed"])
            service.metadata["failed"] = {
                "errors": {"object": "list", "data": [{"code": "invalid_json_line", "message": SECRET,
                                                      "param": None, "line": 1}]},
            }
            with _server(service):
                self._submit(root, path)
                fetched = self._fetch(root)
            self.assertEqual(fetched["status"], "failed")
            self.assertEqual(fetched["files"], [])
            self.assertIn("invalid_json_line", json.dumps(fetched["errors"]))
            self.assertNotIn(SECRET, json.dumps(fetched))
            result = self._import(root, fetched)
            self.assertEqual(result["missing"], keys)
            self.assertEqual(Ledger(root).committed_total(), 0)

    def test_expired_and_cancelled_error_files(self):
        scenarios = [
            (["expired"], "batch_expired"),
            (["cancelling", "cancelled"], "server_error"),
        ]
        for statuses, error_code in scenarios:
            with self.subTest(status=statuses[-1]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path, keys = self._export(root, 2)
                service = _Service(statuses)
                service.metadata[statuses[-1]] = {"error_file_id": "file-err0001"}
                service.content = {
                    "/v1/files/file-err0001/content": [
                        _row(keys[1], 2, error={"code": error_code, "message": "Not executed"}),
                        _row(keys[0], 1, body={"error": {"type": "invalid_request_error", "message": "Not executed",
                                                       "param": None, "code": None}}, status=400),
                    ],
                }
                with _server(service):
                    self._submit(root, path)
                    if "cancelling" in statuses:
                        reply = Client.from_env(1).json("POST", f"batches/{BATCH_ID}/cancel")
                        self.assertEqual(reply["status"], "cancelling")
                    fetched = self._fetch(root)
                self.assertEqual(service.queries, statuses)
                self.assertEqual(fetched["status"], statuses[-1])
                result = self._import(root, fetched)
                self.assertEqual(result["imported"], 2)
                self.assertEqual(result["missing"], [])
                rows = list(read_jsonl(response_path(root, "main", "S")))
                self.assertEqual([row["status"] for row in rows], ["error", "error"])
                self.assertTrue(any(row.get("error_code") == error_code for row in rows))
                self.assertEqual(Ledger(root).committed_total(), 0)


if __name__ == "__main__":
    unittest.main()
