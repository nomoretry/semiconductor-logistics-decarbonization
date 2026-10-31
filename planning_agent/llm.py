"""Minimal OpenAI-compatible chat client with tool calling (standard library only).

Configure with environment variables, the same names as in many LangChain examples:
    LLM_API_KEY           provider key (never written to files or logs)
    LLM_BASE_URL          e.g. https://api.deepseek.com/v1,
                          https://dashscope.aliyuncs.com/compatible-mode/v1 (Qwen),
                          https://api.openai.com/v1
    LLM_MODEL_ID          e.g. deepseek-chat, qwen-plus, gpt-4o-mini
    LLM_API_STYLE         "chat" (default) or "responses" (OpenAI /v1/responses)
    LLM_REASONING_EFFORT  optional, e.g. low / medium / high / xhigh for reasoning models
    LLM_TIMEOUT           seconds per request (default 600; high reasoning effort can be slow)

The agent always speaks the chat-completions message format. Some OpenAI
reasoning models refuse function tools on /v1/chat/completions; the client
then switches to /v1/responses by itself and translates messages, tools and
replies, so the rest of the agent does not change.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.getenv("LLM_API_KEY"))


class OpenAICompatibleClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None,
                 timeout: float | None = None, retries: int = 2):
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        if not self.api_key:
            raise LLMError("LLM_API_KEY is not set")
        self.base_url = (base_url or os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.model = model or os.getenv("LLM_MODEL_ID") or "gpt-4o-mini"
        self.api_style = os.getenv("LLM_API_STYLE") or "chat"
        self.reasoning_effort = os.getenv("LLM_REASONING_EFFORT") or None
        self.timeout = timeout or float(os.getenv("LLM_TIMEOUT") or 600)
        self.retries = retries
        self.send_temperature = True  # reasoning models reject a custom temperature; dropped after the first 400
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "calls": 0}
        self._output_items = {}  # call_id -> raw Responses output items (reasoning + function calls) to replay

    def chat(self, messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.1) -> dict:
        if self.api_style == "responses":
            return self._responses(messages, tools)
        body = {"model": self.model, "messages": messages}
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
            raise
        usage = data.get("usage") or {}
        self._count(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                    (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0))
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError):
            raise LLMError(f"unexpected response shape: {str(data)[:300]}") from None
        return {"role": "assistant", "content": message.get("content") or "",
                "tool_calls": message.get("tool_calls") or []}

    def _responses(self, messages, tools) -> dict:
        body = {"model": self.model, "input": self._to_input(messages)}
        if tools:
            body["tools"] = [{"type": "function", **t["function"]} for t in tools]
        if self.reasoning_effort:
            body["reasoning"] = {"effort": self.reasoning_effort}
        data = self._post("responses", body)
        usage = data.get("usage") or {}
        self._count(usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                    (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0))
        output = data.get("output") or []
        text, calls = [], []
        for item in output:
            if item.get("type") == "message":
                text += [part.get("text", "") for part in item.get("content") or [] if part.get("type") == "output_text"]
            elif item.get("type") == "function_call":
                calls.append({"id": item["call_id"], "type": "function",
                              "function": {"name": item["name"], "arguments": item.get("arguments") or "{}"}})
        if calls:
            replay = [i for i in output if i.get("type") in ("reasoning", "function_call")]
            for call in calls:
                self._output_items[call["id"]] = replay
        return {"role": "assistant", "content": "".join(text), "tool_calls": calls}

    def _to_input(self, messages) -> list:
        items, replayed = [], set()
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

    def _post(self, path: str, body: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/{path}", data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                detail = error.read().decode("utf-8", "replace")[:400]
                raise LLMError(f"HTTP {error.code} from {self.base_url}/{path}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f"cannot reach {self.base_url}: {error}") from None
        raise LLMError("unreachable")

    def _count(self, prompt: int, completion: int, reasoning: int) -> None:
        self.usage["prompt_tokens"] += prompt
        self.usage["completion_tokens"] += completion
        self.usage["reasoning_tokens"] += reasoning
        self.usage["calls"] += 1
