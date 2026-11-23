"""Responses API transport, response normalization and cumulative cost journal."""
from __future__ import annotations

import http.client
import ipaddress
import json
import math
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from .data import LlmError, Record, Task, append_jsonl, canonical, read_jsonl, utc_now

DEFAULT_API_BASE = "https://api.openai.com/v1"
STOP_CODES = frozenset(("insufficient_quota", "credit_balance_exhausted", "project_spend_limit_exceeded",
                        "organization_spend_limit_exceeded"))
SECRET = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_.*-]*")
MILLION = Decimal(1_000_000)


def decimal_amount(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
        if result.is_finite() and result >= 0:
            return result
    except (InvalidOperation, ValueError):
        pass
    raise LlmError("Expected a finite nonnegative USD amount")


@dataclass(frozen=True)
class Prices:
    input: Decimal
    cached_input: Decimal
    cache_write: Decimal
    output: Decimal

    def __post_init__(self) -> None:
        for field in fields(self):
            object.__setattr__(self, field.name, decimal_amount(getattr(self, field.name)))

    def as_dict(self) -> dict[str, str]:
        return {field.name: str(getattr(self, field.name)) for field in fields(self)}

    def worst(self, task: Task) -> Decimal:
        return (task.input_tokens() * self.input + task.body["max_output_tokens"] * self.output) / MILLION

    def actual(self, usage: dict[str, int]) -> Decimal:
        cached = usage["cached_tokens"]
        written = usage["cache_write_tokens"]
        uncached = usage["input_tokens"] - cached - written
        if uncached < 0:
            raise LlmError("Cached token counts exceed input tokens")
        return (uncached * self.input + cached * self.cached_input + written * self.cache_write
                + usage["output_tokens"] * self.output) / MILLION


def redact(value: Any, secret: str | None = None) -> Any:
    if isinstance(value, str):
        return SECRET.sub("[redacted]", value.replace(secret, "[redacted]") if secret else value)
    if isinstance(value, dict):
        return {redact(key, secret): redact(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secret) for item in value]
    return value


def _retry_delay(value: str | None) -> float | None:
    if not value:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            delay = max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    return delay if math.isfinite(delay) and delay >= 0 else None


class ApiError(LlmError):
    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None,
                 retry_after: float | None = None, network: bool = False, unknown_charge: bool = False):
        super().__init__(redact(message))
        self.status_code = status_code
        self.code = redact(code)
        self.retry_after = retry_after
        self.stop = status_code in (401, 403) or code in STOP_CODES
        is_server_error = status_code is not None and 500 <= status_code < 600
        self.retryable = not self.stop and (network or status_code == 429 or is_server_error)
        self.unknown_charge = unknown_charge or network or (is_server_error and not self.stop)


def api_error(payload: Any, *, secret: str | None = None, status_code: int | None = None,
              retry_after: float | None = None) -> ApiError:
    information = payload.get("error", payload) if isinstance(payload, dict) else payload
    code = information.get("code") if isinstance(information, dict) else None
    message = information.get("message") if isinstance(information, dict) else information
    prefix = f"HTTP {status_code}" if status_code is not None else "Response error"
    return ApiError(f"{prefix}: {redact(message or 'no error message supplied', secret)}",
                    status_code=status_code, code=redact(code, secret) if isinstance(code, str) else None,
                    retry_after=retry_after)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _loopback_base(value: str) -> str:
    try:
        url = urllib.parse.urlsplit(value)
        host = url.hostname
        local = host == "localhost" or (host is not None and ipaddress.ip_address(host).is_loopback)
        valid = (url.scheme in ("http", "https") and local and url.port is not None and
                 not (url.username or url.password or url.query or url.fragment) and url.path.rstrip("/") == "/v1")
    except ValueError:
        valid = False
    if not valid:
        raise LlmError("DQ3_API_BASE must name a loopback test server with an explicit port and /v1 path")
    return value.rstrip("/")


class Client:
    def __init__(self, key: str, base: str, timeout: float, *, loopback: bool = False):
        self._key = key
        self._base = base
        self._timeout = timeout
        handlers = [_NoRedirect()]
        if loopback:
            handlers.append(urllib.request.ProxyHandler({}))
        self._opener = urllib.request.build_opener(*handlers)

    @classmethod
    def from_env(cls, timeout: float = 1800) -> Client:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise LlmError("OPENAI_API_KEY is not set")
        if not key.isascii() or not key.isprintable() or " " in key:
            raise LlmError("OPENAI_API_KEY contains invalid header characters")
        if not math.isfinite(timeout) or timeout <= 0:
            raise LlmError("Timeout must be finite and positive")
        override = os.getenv("DQ3_API_BASE")
        return cls(key, _loopback_base(override) if override else DEFAULT_API_BASE, timeout,
                   loopback=bool(override))

    def redact(self, value: Any) -> Any:
        return redact(value, self._key)

    def request(self, method: str, path: str, body: bytes | None = None, content_type: str | None = None) -> bytes:
        endpoint = path.lstrip("/")
        if not endpoint or any(part in ("", ".", "..") for part in endpoint.split("/")) or (
            any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-/." for char in endpoint)
        ):
            raise LlmError("Invalid API resource path")
        headers = {"Authorization": f"Bearer {self._key}"}
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(f"{self._base}/{endpoint}", data=body, method=method, headers=headers)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            with error:
                try:
                    payload = error.read().decode("utf-8", errors="replace")
                    try:
                        payload = json.loads(payload)
                    except ValueError:
                        pass
                except (OSError, http.client.HTTPException):
                    payload = None
            retry_after = _retry_delay(error.headers.get("Retry-After") if error.headers else None)
            raise api_error(payload, secret=self._key, status_code=error.code, retry_after=retry_after) from None
        except (OSError, http.client.HTTPException) as error:
            raise ApiError(self.redact(f"Transport error: {error}"), network=True) from None

    def json(self, method: str, path: str, body: Record | None = None) -> Record:
        data = self.request(method, path, canonical(body) if body is not None else None,
                            "application/json" if body is not None else None)
        try:
            value = json.loads(data)
        except ValueError:
            raise ApiError("Expected a JSON API response", unknown_charge=True) from None
        if not isinstance(value, dict):
            raise ApiError("Expected an object in the API response", unknown_charge=True)
        return value


def _reject_constant(_value: str) -> Any:
    raise ValueError("Non-JSON number")


def parse_text(text: str) -> Any:
    reply = text.strip()
    opening, newline, remainder = reply.partition("\n")
    if newline:
        fence = re.match(r"([~\x60])\1{2,}", opening)
        content, last_newline, closing = remainder.rpartition("\n")
        if fence and last_newline:
            info = opening[fence.end():]
            closing_pattern = r"[ \t]{0,3}" + re.escape(fence[0]) + re.escape(fence[1]) + r"*[ \t\r]*"
            if (fence[1] != "\x60" or "\x60" not in info) and re.fullmatch(closing_pattern, closing):
                reply = content
    parsed = json.loads(reply, parse_constant=_reject_constant)
    canonical(parsed)
    return parsed


def _usage(raw: Record) -> dict[str, int] | None:
    usage = raw.get("usage")
    if not isinstance(usage, dict):
        return None
    inputs = usage.get("input_tokens_details") or {}
    outputs = usage.get("output_tokens_details") or {}
    if not isinstance(inputs, dict) or not isinstance(outputs, dict):
        return None
    normalized = {"input_tokens": usage.get("input_tokens"), "cached_tokens": inputs.get("cached_tokens", 0),
                  "cache_write_tokens": inputs.get("cache_write_tokens", 0), "output_tokens": usage.get("output_tokens"),
                  "reasoning_tokens": outputs.get("reasoning_tokens", 0)}
    if any(type(value) is not int or value < 0 for value in normalized.values()):
        return None
    if (normalized["cached_tokens"] + normalized["cache_write_tokens"] > normalized["input_tokens"]
            or normalized["reasoning_tokens"] > normalized["output_tokens"]):
        return None
    return normalized


def _output(raw: Record) -> str:
    items = raw.get("output")
    if not isinstance(items, list):
        return ""
    text = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if isinstance(content, list):
            text.extend(part["text"] for part in content if isinstance(part, dict)
                        and part.get("type") == "output_text" and isinstance(part.get("text"), str))
    return "".join(text)


def decode_response(task: Task, raw: Record | None, prices: Prices, *, transport: str, attempts: int = 1,
                    started_at: str | None = None, finished_at: str | None = None, seconds: float | None = None,
                    secret: str | None = None, error: object = None) -> Record:
    raw = redact(raw or {}, secret)
    text = _output(raw)
    usage = _usage(raw)
    actual = str(prices.actual(usage)) if usage is not None else None
    parsed = None
    status = "error"
    detail = redact(str(error), secret) if error is not None else None
    if detail is None:
        incomplete = raw.get("incomplete_details")
        reason = incomplete.get("reason") if isinstance(incomplete, dict) else None
        if raw.get("status") == "incomplete" and reason == "max_output_tokens":
            status = "truncated"
            detail = "max_output_tokens"
        elif raw.get("status") == "incomplete":
            detail = f"Incomplete response: {reason}"
        elif raw.get("error"):
            detail = str(api_error(raw))
        elif raw.get("status") not in (None, "completed") or not isinstance(raw.get("output"), list):
            detail = "Unexpected or nonterminal response status"
        else:
            try:
                parsed = parse_text(text)
                status = "ok"
            except (ValueError, OverflowError, RecursionError):
                status = "parse_failure"
                detail = "Expected exactly one JSON value"
    return {"phase": task.phase, "arm": task.arm, "transport": transport, "graph": task.graph,
            "question": task.question, "context": task.context, "custom_id": task.custom_id,
            "request_hash": task.request_hash, "status": status, "text": text, "parsed": parsed,
            "model": raw.get("model"), "reasoning": raw.get("reasoning"), "requested_reasoning": task.body["reasoning"],
            "service_tier": raw.get("service_tier"),
            "usage": usage, "actual_usd": actual, "charged_usd": actual, "seconds": seconds, "attempts": attempts,
            "started_at": started_at, "finished_at": finished_at, "error": detail}


class Ledger:
    """Journal reservations before sending and retain interrupted charges across invocations."""

    def __init__(self, root: Path):
        self.path = root / "ledger.jsonl"
        self.lock = threading.RLock()
        self._pending: dict[str, Decimal] = {}
        self._settled: dict[str, Decimal] = {}
        self._total = Decimal(0)
        for event in read_jsonl(self.path):
            attempt = event["attempt_id"]
            if event["event"] == "reserve" and attempt not in self._pending and attempt not in self._settled:
                amount = decimal_amount(event["reserved_usd"])
                self._pending[attempt] = amount
                self._total += amount
            elif event["event"] == "settle" and attempt not in self._settled:
                amount = decimal_amount(event["charged_usd"])
                self._total += amount - self._pending.pop(attempt, Decimal(0))
                self._settled[attempt] = amount
            else:
                raise LlmError("Invalid cumulative ledger events")

    def committed_total(self) -> Decimal:
        with self.lock:
            return self._total

    def pending(self, attempt_id: str) -> Decimal | None:
        with self.lock:
            return self._pending.get(attempt_id)

    def settled(self, attempt_id: str) -> bool:
        with self.lock:
            return attempt_id in self._settled

    def reserve(self, attempt_id: str, amount: Decimal, fields: Record) -> None:
        amount = decimal_amount(amount)
        with self.lock:
            if self._pending.get(attempt_id) == amount:
                return
            if attempt_id in self._pending or attempt_id in self._settled:
                raise LlmError("Ledger attempt identifier already exists")
            append_jsonl(self.path, {**fields, "attempt_id": attempt_id, "event": "reserve",
                                     "time": utc_now(), "reserved_usd": str(amount)})
            self._pending[attempt_id] = amount
            self._total += amount

    def settle(self, attempt_id: str, amount: Decimal, fields: Record) -> None:
        amount = decimal_amount(amount)
        with self.lock:
            if self._settled.get(attempt_id) == amount:
                return
            if attempt_id in self._settled:
                raise LlmError("Ledger settlement conflicts with the existing charge")
            prior = self._pending.get(attempt_id)
            append_jsonl(self.path, {**fields, "attempt_id": attempt_id, "event": "settle", "time": utc_now(),
                                     "reserved_usd": str(prior) if prior is not None else None,
                                     "charged_usd": str(amount)})
            self._pending.pop(attempt_id, None)
            self._settled[attempt_id] = amount
            self._total += amount - (prior if prior is not None else Decimal(0))
