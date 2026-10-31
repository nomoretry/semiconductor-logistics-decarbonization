"""Minimal OpenAI-compatible chat client with tool calling (standard library only).

Configure with environment variables, the same names as in many LangChain examples:
    LLM_API_KEY    provider key (never written to files or logs)
    LLM_BASE_URL   e.g. https://api.deepseek.com/v1,
                   https://dashscope.aliyuncs.com/compatible-mode/v1 (Qwen),
                   https://api.openai.com/v1
    LLM_MODEL_ID   e.g. deepseek-chat, qwen-plus, gpt-4o-mini
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
                 timeout: float = 90.0, retries: int = 2):
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        if not self.api_key:
            raise LLMError("LLM_API_KEY is not set")
        self.base_url = (base_url or os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.model = model or os.getenv("LLM_MODEL_ID") or "gpt-4o-mini"
        self.timeout, self.retries = timeout, retries
        self.send_temperature = True  # reasoning models reject a custom temperature; dropped after the first 400
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "calls": 0}

    def chat(self, messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.1) -> dict:
        body = {"model": self.model, "messages": messages}
        if self.send_temperature:
            body["temperature"] = temperature
        if tools:
            body.update(tools=tools, tool_choice="auto")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.load(response)
                break
            except urllib.error.HTTPError as error:
                if error.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                detail = error.read().decode("utf-8", "replace")[:300]
                if error.code == 400 and self.send_temperature and "temperature" in detail:
                    self.send_temperature = False
                    return self.chat(messages, tools, temperature)
                raise LLMError(f"HTTP {error.code} from {self.base_url}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f"cannot reach {self.base_url}: {error}") from None
        usage = data.get("usage") or {}
        self.usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
        self.usage["completion_tokens"] += usage.get("completion_tokens", 0)
        self.usage["reasoning_tokens"] += (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
        self.usage["calls"] += 1
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError):
            raise LLMError(f"unexpected response shape: {str(data)[:300]}") from None
        return {"role": "assistant", "content": message.get("content") or "",
                "tool_calls": message.get("tool_calls") or []}
