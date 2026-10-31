"""Tool-calling planning agent: a ReAct-style loop over OpenAI-compatible function calling.

The model decides which tools to call; the tools do all optimisation and
arithmetic. Before an answer is returned, the numeric guardrail checks that
every number is traceable to a tool result or the user's message; one
automatic rewrite is requested if it is not.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .guardrails import check_answer
from .llm import LLMError

SYSTEM_PROMPT = """你是“半导体物流计划副驾驶”，服务对象是供应链计划员和供应链产品经理。
你可以调用工具：查看网络、把运输公告或假设建模为扰动场景、求解库存—运输优化计划（MILP）、比较方案、
分析减排的成本与边际减排成本、在扰动不确定时做两阶段随机对冲，以及写决策备忘录。

规则：
1. 回答中的所有数字必须来自工具结果或用户原话；不要自己估算或心算差值，需要差值或百分比变化时调用 compare_plans。
2. 用户描述的扰动（周次、延误、运力或运费变化）用 create_scenario 建模，只使用用户给出的数字；
   与预设场景（如 red_sea、typhoon）完全一致时可直接用预设场景。没给的参数保持默认，并在回答里写明是假设。
3. “减排 X%”对应 carbon_cap_pct = 100 - X（相对同一场景不设碳约束的方案）。
4. 先给结论，再用表格列关键数字，最后列假设与局限。用户用中文就用中文，用英文就用英文。
5. 数据是合成情景：SKU、需求、容量、费率和扰动幅度是假设，距离和排放因子有公开来源。不要说成企业真实数据。
6. 与供应链计划无关的请求（订票、股价、写诗等）礼貌拒绝，并说明你能做什么；不要调用工具。
7. 关键信息缺失、无法合理假设时，先问一个简短的澄清问题。
网络：asml = 荷兰→新加坡的光刻机备件；marvell = 台湾/马来西亚→新加坡的芯片成品。"""


@dataclass
class AgentResult:
    question: str
    answer: str
    mode: str
    tool_calls: list
    steps: int
    guardrail: dict
    seconds: float
    usage: dict = field(default_factory=dict)
    error: str | None = None

    def tool_names(self) -> list[str]:
        return [call["name"] for call in self.tool_calls]


def run_llm(question: str, session, client, *, history: list | None = None, max_steps: int = 8,
            max_revisions: int = 1) -> AgentResult:
    started, first = time.perf_counter(), len(session.calls)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *(history or []), {"role": "user", "content": question}]
    tools, revisions = session.schemas(), 0

    def finish(answer, steps, check, error=None):
        return AgentResult(question, answer, "llm", session.calls[first:], steps, check,
                           round(time.perf_counter() - started, 2), dict(getattr(client, "usage", {})), error)

    for step in range(1, max_steps + 1):
        try:
            reply = client.chat(messages, tools)
        except LLMError as error:
            return finish(f"模型调用失败：{error}", step, {"ok": True, "unsupported": [], "checked": 0}, str(error))
        assistant = {"role": "assistant", "content": reply["content"]}
        if reply["tool_calls"]:
            assistant["tool_calls"] = reply["tool_calls"]
        messages.append(assistant)
        if reply["tool_calls"]:
            for call in reply["tool_calls"]:
                function = call.get("function") or {}
                result = session.call(function.get("name", ""), function.get("arguments") or "{}")
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                 "content": json.dumps(result, ensure_ascii=False, default=str)})
            continue
        answer = (reply["content"] or "").strip()
        check = check_answer(answer, [c["result"] for c in session.calls[first:]], question)
        if not check["ok"] and revisions < max_revisions:
            revisions += 1
            messages.append({"role": "user", "content":
                             "[自动审查] 回答中这些数字无法在工具结果中找到：" + "、".join(check["unsupported"])
                             + "。请只使用工具返回的数字重写回答；需要差值或百分比变化请调用 compare_plans。"})
            continue
        if not check["ok"]:
            answer += "\n\n> 自动审查提示：以下数字未能与工具结果核对：" + "、".join(check["unsupported"])
        return finish(answer, step, check)
    return finish("已达到最大推理步数，未能完成。请把问题拆小一些再试。", max_steps,
                  {"ok": True, "unsupported": [], "checked": 0}, "max_steps")
