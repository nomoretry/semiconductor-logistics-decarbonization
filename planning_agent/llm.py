"""Minimal OpenAI-compatible chat client with tool calling (standard library only).

Configure with environment variables, the same names as in many LangChain examples:
    LLM_API_KEY           provider key (read from the environment only; never written to files or logs)
    LLM_BASE_URL          e.g. https://api.deepseek.com/v1,
                          https://dashscope.aliyuncs.com/compatible-mode/v1 (Qwen),
                          https://api.openai.com/v1 (default)
    LLM_MODEL_ID          required, e.g. deepseek-chat, qwen-plus, gpt-6-luna
    LLM_API_STYLE         "chat" (default) or "responses" (OpenAI /v1/responses)
    LLM_REASONING_EFFORT  optional, e.g. low / medium / high / xhigh for reasoning models
    LLM_TIMEOUT           seconds per request (default 600; high reasoning effort can be slow)

Limits, all checked before a request is sent (see spending.py). No limits, no call:
    LLM_MAX_REQUESTS      required: HTTP requests, retries and fallbacks included
    LLM_MAX_TOTAL_TOKENS  required: input + output
    LLM_MAX_OUTPUT_TOKENS required: output cap of each request, sent to the provider
    LLM_MAX_INPUT_TOKENS  optional: refuse a request whose input bound is above this
    LLM_MAX_USD           optional, with LLM_INPUT_USD_PER_M and LLM_OUTPUT_USD_PER_M
    LLM_LEDGER_PATH       optional: keep the totals in a file so they carry over to later runs

The web page has its own switch and limits; see LiveAccess.

The agent always speaks the chat-completions message format. Some OpenAI
reasoning models refuse function tools on /v1/chat/completions; the client
then switches to /v1/responses by itself and translates messages, tools and
replies, so the rest of the agent does not change.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from .spending import BudgetExceeded, Limits, LLMError, Meter, input_bound, limits_from_env, reserve_all

__all__ = ["BudgetExceeded", "LLMError", "LiveAccess", "OpenAICompatibleClient", "configured", "limits_from_env",
           "problems", "redact", "status"]

DEFAULT_BASE_URL = "https://api.openai.com/v1"
# What each kind of client means for the evidence it produces; results and memos carry this label.
CALL_KINDS = {
    "real": "真实模型调用（外部服务，可能计费）",
    "local": "本机接口（没有访问外部模型服务）",
    "replay": "录制回放（真实模型的历史输出，本次没有调用模型）",
    "simulated": "模拟客户端（测试脚本，没有调用模型）",
    "none": "没有使用模型",
}
SECRET_PATTERNS = (re.compile(r"sk-[A-Za-z0-9_\-*.]{4,}"), re.compile(r"(?i)bearer\s+\S+"),
                   re.compile(r"(?i)(api[_-]?key[\\\"'\s:=]+)[^\s\\\"',}]+"))


def redact(text: str, *secrets: str | None) -> str:
    """Remove credentials from text that may reach a log, a file or a page; providers echo keys in error messages."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + "[redacted]", text)
    return text


def _is_loopback(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_base_url(url: str) -> str:
    """The key travels in a header, so it may only go over TLS, or stay on this machine."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme not in ("https", "http") or not host:
        raise LLMError("LLM_BASE_URL must be an https URL")
    if parts.scheme == "http" and not _is_loopback(host):
        raise LLMError(f"LLM_BASE_URL must use https for {host}; the key would travel unencrypted")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise LLMError("LLM_BASE_URL must not contain credentials, a query or a fragment")
    return url.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib would repeat the Authorization header to wherever a redirect points; treat a redirect as an error."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _open(request: urllib.request.Request, timeout: float) -> Any:
    return _OPENER.open(request, timeout=timeout)


def configured() -> bool:
    return bool(os.getenv("LLM_API_KEY"))


def problems() -> list[str]:
    """What stops a paid call from being allowed; empty means ready. Names variables, never their values."""
    found = []
    if not configured():
        found.append("LLM_API_KEY is not set")
    if not os.getenv("LLM_MODEL_ID"):
        found.append("LLM_MODEL_ID is not set")
    try:
        check_base_url(os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URL)
        limits_from_env()
    except LLMError as error:
        found.append(str(error))
    return found


def status() -> dict[str, Any]:
    """The live-call configuration as far as it is safe to print; does not touch the network."""
    base_url = os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URL
    parts = urllib.parse.urlsplit(base_url)
    try:
        limits: Any = limits_from_env().__dict__
    except LLMError:
        limits = None
    return {"key_set": configured(), "endpoint": f"{parts.scheme}://{parts.hostname}{parts.path}",
            "call_kind": "local" if _is_loopback(parts.hostname or "") else "real",
            "model": os.getenv("LLM_MODEL_ID"), "api_style": os.getenv("LLM_API_STYLE") or "chat",
            "reasoning_effort": os.getenv("LLM_REASONING_EFFORT"), "limits": limits,
            "ledger": os.getenv("LLM_LEDGER_PATH"), "problems": problems()}


class OpenAICompatibleClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None,
                 timeout: float | None = None, retries: int = 2, *, limits: Limits | None = None,
                 meters: Sequence[Meter] = ()):
        self._api_key = api_key or os.getenv("LLM_API_KEY")
        if not self._api_key:
            raise LLMError("LLM_API_KEY is not set")
        self.base_url = check_base_url(base_url or os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URL)
        self.model = model or os.getenv("LLM_MODEL_ID")
        if not self.model:
            raise LLMError("LLM_MODEL_ID is not set")
        if not meters:
            meters = [Meter(limits or limits_from_env(), os.getenv("LLM_LEDGER_PATH") or None)]
        self.meters = list(meters)
        self.max_output_tokens = min(m.limits.max_output_tokens for m in self.meters)
        self.output_param = "max_tokens"  # some models accept only max_completion_tokens; switched on their 400
        self.call_kind = "local" if _is_loopback(urllib.parse.urlsplit(self.base_url).hostname or "") else "real"
        self.api_style = os.getenv("LLM_API_STYLE") or "chat"
        self.reasoning_effort = os.getenv("LLM_REASONING_EFFORT") or None
        self.timeout = timeout or float(os.getenv("LLM_TIMEOUT") or 600)
        self.retries = retries
        self.send_temperature = True  # reasoning models reject a custom temperature; dropped after the first 400
        self.usage: dict[str, int] = {"prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0,
                                      "reasoning_tokens": 0, "calls": 0}
        # call_id -> raw Responses output items (reasoning + function calls) to replay
        self._output_items: dict[str, list[dict[str, Any]]] = {}

    def __repr__(self) -> str:
        return f"OpenAICompatibleClient(base_url={self.base_url!r}, model={self.model!r})"

    @property
    def budget_stop(self) -> str | None:
        """Why the budget ended this run, if it did."""
        return next((m.stopped for m in self.meters if m.stopped), None)

    def spending(self) -> dict[str, Any]:
        return self.meters[0].snapshot()

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             temperature: float = 0.1) -> dict[str, Any]:
        if self.api_style == "responses":
            return self._responses(messages, tools)
        body: dict[str, Any] = {"model": self.model, "messages": messages, self.output_param: self.max_output_tokens}
        if self.send_temperature:
            body["temperature"] = temperature
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        if tools:
            body.update(tools=tools, tool_choice="auto")
        try:
            data = self._post("chat/completions", body)
        except LLMError as error:
            detail = str(error)
            if "HTTP 400" in detail and "/v1/responses" in detail:
                self.api_style = "responses"
                return self._responses(messages, tools)
            if "HTTP 400" in detail and self.send_temperature and "temperature" in detail:
                self.send_temperature = False
                return self.chat(messages, tools, temperature)
            if "HTTP 400" in detail and self.output_param == "max_tokens" and "max_completion_tokens" in detail:
                self.output_param = "max_completion_tokens"
                return self.chat(messages, tools, temperature)
            raise
        usage = data.get("usage") or {}
        self._count(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                    (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
                    (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0))
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError):
            raise LLMError("unexpected response shape: " + redact(str(data), self._api_key)[:300]) from None
        if choice.get("finish_reason") == "length":
            raise LLMError(f"output stopped at the cap of {self.max_output_tokens:,} tokens; reply discarded")
        return {"role": "assistant", "content": message.get("content") or "",
                "tool_calls": message.get("tool_calls") or []}

    def _responses(self, messages: list[dict[str, Any]],
                   tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "input": self._to_input(messages),
                                "max_output_tokens": self.max_output_tokens}
        if tools:
            body["tools"] = [{"type": "function", **t["function"]} for t in tools]
        if self.reasoning_effort:
            body["reasoning"] = {"effort": self.reasoning_effort}
        data = self._post("responses", body)
        usage = data.get("usage") or {}
        self._count(usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                    (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0),
                    (usage.get("input_tokens_details") or {}).get("cached_tokens", 0))
        if data.get("status") == "incomplete":
            raise LLMError(f"output stopped at the cap of {self.max_output_tokens:,} tokens; reply discarded")
        output = data.get("output") or []
        text, calls = [], []
        for item in output:
            if item.get("type") == "message":
                text += [part.get("text", "") for part in item.get("content") or []
                         if part.get("type") == "output_text"]
            elif item.get("type") == "function_call":
                calls.append({"id": item["call_id"], "type": "function",
                              "function": {"name": item["name"], "arguments": item.get("arguments") or "{}"}})
        if calls:
            replay = [i for i in output if i.get("type") in ("reasoning", "function_call")]
            for call in calls:
                self._output_items[call["id"]] = replay
        return {"role": "assistant", "content": "".join(text), "tool_calls": calls}

    def _to_input(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        replayed: set[str] = set()
        for m in messages:
            role = m.get("role")
            if role == "tool":
                items.append({"type": "function_call_output", "call_id": m.get("tool_call_id", ""),
                              "output": m.get("content") or ""})
            elif role == "assistant" and m.get("tool_calls"):
                first = m["tool_calls"][0]["id"]
                raw = self._output_items.get(first)
                if raw is not None and first not in replayed:
                    items += raw  # reasoning items must travel with their function calls
                    replayed.update(c["id"] for c in m["tool_calls"])
                elif raw is None:
                    items += [{"type": "function_call", "call_id": c["id"], "name": c["function"]["name"],
                               "arguments": c["function"].get("arguments") or "{}"} for c in m["tool_calls"]]
            elif m.get("content"):
                items.append({"role": role, "content": m["content"]})
        return items

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/{path}", data=payload,
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"})
        bound = input_bound(payload)
        for attempt in range(self.retries + 1):
            held = reserve_all(self.meters, bound, self.max_output_tokens)  # raises before anything is sent
            try:
                with _open(request, self.timeout) as response:
                    data = cast(dict[str, Any], json.load(response))
            except urllib.error.HTTPError as error:
                if error.code < 500:  # rejected before the model ran
                    self._settle(held, 0, 0)
                if error.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                detail = redact(error.read().decode("utf-8", "replace"), self._api_key)[:400]
                raise LLMError(f"HTTP {error.code} from {self.base_url}/{path}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as error:  # may have run and been billed: stays charged
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f"cannot reach {self.base_url}: " + redact(str(error), self._api_key)) from None
            except ValueError:
                raise LLMError(f"unreadable reply from {self.base_url}/{path}") from None
            usage = data.get("usage") or {}
            used_input = usage.get("prompt_tokens", usage.get("input_tokens"))
            used_output = usage.get("completion_tokens", usage.get("output_tokens"))
            if used_input is not None and used_output is not None:  # otherwise the reservation stays charged
                self._settle(held, used_input, used_output)
            return data
        raise LLMError("unreachable")

    @staticmethod
    def _settle(held: list[tuple[Meter, str]], input_tokens: int, output_tokens: int) -> None:
        for meter, hold in held:
            meter.settle(hold, input_tokens, output_tokens)

    def _count(self, prompt: int, completion: int, reasoning: int, cached: int = 0) -> None:
        """Cached prompt tokens are a subset of prompt tokens (billed at the cached-input rate)."""
        self.usage["prompt_tokens"] += prompt
        self.usage["cached_tokens"] += cached
        self.usage["completion_tokens"] += completion
        self.usage["reasoning_tokens"] += reasoning
        self.usage["calls"] += 1


MAX_CODE_FAILURES = 5
CODE_LOCK_SECONDS = 900


@dataclass
class LiveAccess:
    """Server-side switch and limits for the paid mode of the web page; closed unless every setting is present.

    The page never sets a budget itself: a visitor can only enter the access code and use what the operator
    configured here. All of these live in the host's secret settings or the local environment:

        LLM_WEB_LIVE=on                     explicit switch; a key alone does not open the paid mode
        LLM_API_KEY, LLM_MODEL_ID           as for the command line
        LLM_WEB_ACCESS_CODE_SHA256          SHA-256 hex digest of the access code; the code itself is not stored
        LLM_WEB_MAX_REQUESTS                per day (UTC), across all visitors
        LLM_WEB_MAX_TOTAL_TOKENS            per day (UTC), across all visitors
        LLM_WEB_MAX_OUTPUT_TOKENS           per request
        LLM_WEB_SESSION_MAX_REQUESTS        per browser session
        LLM_WEB_MAX_INPUT_TOKENS            optional, per request
        LLM_WEB_MAX_USD                     optional, per day, with LLM_INPUT_USD_PER_M and LLM_OUTPUT_USD_PER_M
        LLM_WEB_LEDGER_PATH                 optional, default artifacts/planning_agent/web_llm_ledger.jsonl

    A session limit can be avoided by opening a new session, and a host may wipe the ledger when it restarts, so the
    daily limit is the second layer and the provider's own spending cap on a dedicated key remains the last one.
    """

    problems: list[str]
    code_sha256: str = ""
    session_requests: int = 0
    limits: Limits | None = None
    daily: Meter | None = None
    _failures: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_env(cls) -> LiveAccess:
        found = [] if os.getenv("LLM_WEB_LIVE") == "on" else ["LLM_WEB_LIVE is not on"]
        for name in ("LLM_API_KEY", "LLM_MODEL_ID"):
            if not os.getenv(name):
                found.append(f"{name} is not set")
        code = os.getenv("LLM_WEB_ACCESS_CODE_SHA256") or ""
        if not re.fullmatch(r"[0-9a-f]{64}", code):
            found.append("LLM_WEB_ACCESS_CODE_SHA256 is not a SHA-256 hex digest")
        sessions = os.getenv("LLM_WEB_SESSION_MAX_REQUESTS") or ""
        if not (sessions.isdigit() and int(sessions) > 0):
            found.append("LLM_WEB_SESSION_MAX_REQUESTS is not a positive integer")
        limits = None
        try:
            check_base_url(os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URL)
            limits = limits_from_env("LLM_WEB_")
        except LLMError as error:
            found.append(str(error))
        if found or limits is None:
            return cls(found)
        ledger = os.getenv("LLM_WEB_LEDGER_PATH") or Path("artifacts/planning_agent/web_llm_ledger.jsonl")
        return cls([], code, int(sessions), limits, Meter(limits, ledger, daily=True))

    @property
    def open(self) -> bool:
        return not self.problems

    def check_code(self, code: str) -> bool:
        """Constant-time check; after repeated failures every attempt fails for a while, which cannot cost money."""
        now = time.monotonic()
        with self._lock:
            self._failures = [t for t in self._failures if now - t < CODE_LOCK_SECONDS]
            if not self.open or len(self._failures) >= MAX_CODE_FAILURES:
                return False
            ok = hmac.compare_digest(hashlib.sha256(code.encode("utf-8")).hexdigest(), self.code_sha256)
            if not ok:
                self._failures.append(now)
            return ok

    def session_meter(self) -> Meter:
        assert self.limits is not None
        return Meter(Limits(self.session_requests, self.limits.max_total_tokens, self.limits.max_output_tokens,
                            self.limits.max_input_tokens))

    def client(self, session: Meter) -> OpenAICompatibleClient:
        """Fails fast on the web: no retries, so one click is one request unless a documented fallback applies."""
        assert self.daily is not None
        return OpenAICompatibleClient(timeout=float(os.getenv("LLM_WEB_TIMEOUT") or 60), retries=0,
                                      meters=[session, self.daily])
