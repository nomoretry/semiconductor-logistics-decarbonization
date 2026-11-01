"""LangGraph orchestration of the planning agent.

The model client, tools, system prompt and numeric guardrail are the ones the plain loop in agent.py uses;
only the control flow is expressed as a state graph:

    START -> model --tool calls--> tools --> model ...
                   --answer------> review --ok / no rewrite left--> END
                                          --untraceable number----> model (one rewrite)

Compared with the loop, the graph adds three things a planning service needs:
- an in-process checkpointer (InMemorySaver) keeps the turns of each conversation while the process runs, so
  follow-up questions see earlier tool results; nothing persists after the process exits;
- an optional approval step pauses before tools run (human in the loop) and can decline them;
- step-by-step streaming of node updates for a command line or web front end.
"""
from __future__ import annotations

import json
import operator
import os
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Callable, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .agent import SYSTEM_PROMPT, AgentResult
from .guardrails import check_answer
from .llm import LLMError

NO_CHECK = {"ok": True, "unsupported": [], "checked": 0}
MAX_STEPS_ANSWER = "已达到最大推理步数，未能完成。请把问题拆小一些再试。"
DECLINED = "计划员没有批准执行这个工具调用。请说明需要哪些信息，或换一种做法。"


class TurnState(TypedDict, total=False):
    messages: Annotated[list[dict], operator.add]  # chat-completions messages; appended across turns
    question: str
    answer: str
    steps: int  # model calls in this turn
    revisions: int
    rewrite: bool
    first_call: int  # index in session.calls where this turn's tool calls start
    guardrail: dict
    error: str | None


class PlanningGraph:
    """One planning conversation: a tool session, a model client and a compiled graph with memory."""

    def __init__(self, session, client, *, max_steps: int | None = None, max_revisions: int = 1,
                 approve: Callable[[list[dict]], bool] | None = None, thread_id: str | None = None):
        self.session, self.client, self.approve = session, client, approve
        self.max_steps = max_steps or int(os.getenv("LLM_MAX_STEPS") or 16)
        self.max_revisions = max_revisions
        self.thread_id = thread_id or uuid.uuid4().hex
        builder = StateGraph(TurnState)
        builder.add_node("model", self._model)
        builder.add_node("tools", self._tools)
        builder.add_node("review", self._review)
        builder.add_node("stop", self._stop)
        builder.add_edge(START, "model")
        builder.add_conditional_edges("model", self._after_model, {"tools": "tools", "review": "review", END: END})
        builder.add_conditional_edges("tools", self._within_budget, {"model": "model", "stop": "stop"})
        builder.add_conditional_edges("review", self._after_review, {"model": "model", "stop": "stop", END: END})
        builder.add_edge("stop", END)
        self.graph = builder.compile(checkpointer=InMemorySaver(),
                                     interrupt_before=["tools"] if approve else None)

    # ------------------------------------------------------------------ nodes

    def _model(self, state: TurnState) -> dict:
        steps = state["steps"] + 1
        try:
            reply = self.client.chat(state["messages"], self.session.schemas())
        except LLMError as error:
            return {"steps": steps, "error": str(error), "answer": f"模型调用失败：{error}", "guardrail": NO_CHECK}
        message: dict[str, Any] = {"role": "assistant", "content": reply["content"]}
        if reply["tool_calls"]:
            message["tool_calls"] = reply["tool_calls"]
        answer = "" if reply["tool_calls"] else (reply["content"] or "").strip()
        return {"messages": [message], "steps": steps, "answer": answer, "rewrite": False}

    def _tools(self, state: TurnState) -> dict:
        results = []
        for call in state["messages"][-1].get("tool_calls") or []:
            function = call.get("function") or {}
            result = self.session.call(function.get("name", ""), function.get("arguments") or "{}")
            results.append({"role": "tool", "tool_call_id": call.get("id", ""),
                            "content": json.dumps(result, ensure_ascii=False, default=str)})
        return {"messages": results}

    def _review(self, state: TurnState) -> dict:
        tool_results = [c["result"] for c in self.session.calls[state["first_call"]:]]
        check = check_answer(state["answer"], tool_results, state["question"])
        if check["ok"]:
            return {"guardrail": check}
        if state["revisions"] < self.max_revisions:
            feedback = ("[自动审查] 回答中这些数字无法在工具结果中找到：" + "、".join(check["unsupported"])
                        + "。请只使用工具返回的数字重写回答；需要差值或百分比变化请调用 compare_plans。")
            return {"guardrail": check, "rewrite": True, "revisions": state["revisions"] + 1,
                    "messages": [{"role": "user", "content": feedback}]}
        note = "\n\n> 自动审查提示：以下数字未能与工具结果核对：" + "、".join(check["unsupported"])
        return {"guardrail": check, "answer": state["answer"] + note}

    def _stop(self, state: TurnState) -> dict:
        return {"answer": MAX_STEPS_ANSWER, "error": "max_steps", "guardrail": NO_CHECK}

    # ------------------------------------------------------------------ routing

    def _after_model(self, state: TurnState) -> str:
        if state.get("error"):
            return END
        return "tools" if state["messages"][-1].get("tool_calls") else "review"

    def _within_budget(self, state: TurnState) -> str:
        return "model" if state["steps"] < self.max_steps else "stop"

    def _after_review(self, state: TurnState) -> str:
        return self._within_budget(state) if state.get("rewrite") else END

    # ------------------------------------------------------------------ public interface

    def config(self) -> dict:
        # Each model step is followed by at most one tools or review step.
        return {"configurable": {"thread_id": self.thread_id}, "recursion_limit": 3 * self.max_steps + 10}

    def ask(self, question: str, on_step: Callable[[str, dict], None] | None = None) -> AgentResult:
        """Answer one turn; earlier turns of this conversation stay in the checkpointed messages."""
        started, first, config = time.perf_counter(), len(self.session.calls), self.config()
        history = self.graph.get_state(config).values.get("messages") or []
        opening = [] if history else [{"role": "system", "content": SYSTEM_PROMPT}]
        payload: dict | None = {"messages": opening + [{"role": "user", "content": question}],
                                "question": question, "answer": "", "steps": 0, "revisions": 0,
                                "rewrite": False, "first_call": first, "guardrail": NO_CHECK, "error": None}
        while True:
            for update in self.graph.stream(payload, config, stream_mode="updates"):
                for node, change in update.items():
                    if on_step and node != "__interrupt__":
                        on_step(node, change or {})
            snapshot = self.graph.get_state(config)
            if not snapshot.next:
                break
            payload = None  # resume after the approval pause
            pending = snapshot.values["messages"][-1].get("tool_calls") or []
            if self.approve is not None and not self.approve(pending):
                declined = [{"role": "tool", "tool_call_id": c.get("id", ""), "content": DECLINED} for c in pending]
                self.graph.update_state(config, {"messages": declined}, as_node="tools")
        state = snapshot.values
        return AgentResult(question, state["answer"], "graph", self.session.calls[first:], state["steps"],
                           state["guardrail"], round(time.perf_counter() - started, 2),
                           dict(getattr(self.client, "usage", {})), state.get("error"))

    def mermaid(self) -> str:
        return self.graph.get_graph().draw_mermaid()


def run_graph(question: str, session, client, **options) -> AgentResult:
    """Single-question entry point with the same signature as agent.run_llm."""
    return PlanningGraph(session, client, **options).ask(question)


# ---------------------------------------------------------------------- offline replay of recorded runs

class ReplayClient:
    """Plays back a recorded model run: one turn per recorded tool call, then the recorded answer.

    The engine is deterministic, so the tools return what the model saw at run time. This checks the graph's
    wiring on real trajectories without calling (or paying for) a model.
    """

    model = "replay"

    def __init__(self, tool_calls: list[dict], answer: str):
        self.turns = [{"content": "", "tool_calls": [{"id": f"call_{i}", "type": "function", "function": {
            "name": c["name"], "arguments": c["arguments"] if isinstance(c["arguments"], str)
            else json.dumps(c["arguments"], ensure_ascii=False)}}]} for i, c in enumerate(tool_calls)]
        self.turns.append({"content": answer, "tool_calls": []})
        self.usage = {"prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0,
                      "calls": 0}

    def chat(self, messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.1) -> dict:
        if not self.turns:
            raise LLMError("replay exhausted")
        self.usage["calls"] += 1
        return {"role": "assistant", **self.turns.pop(0)}


def replay(source: Path, output: Path | None = None, *, recorded: str = "llm_rescored", ids=None,
           settings: dict | None = None, progress=None) -> dict:
    """Replay recorded model runs through the graph and compare per-case scores with the recording.

    Rewrites are disabled because the recorded answer is already final; the current guardrail then judges it,
    exactly as `eval --rescore` does for the plain loop.
    """
    from .evaluate import Gold, load_cases, score
    from .tools import Session
    settings = settings or {}
    rows = [json.loads(line) for line in (Path(source) / f"{recorded}_cases.jsonl").read_text(encoding="utf-8")
            .splitlines() if line.strip()]
    cases = {c["id"]: c for c in load_cases()}
    gold, compared = Gold(settings), []
    for row in rows:
        if ids and row["id"] not in ids:
            continue
        session = Session(**settings)
        result = PlanningGraph(session, ReplayClient(row["tool_calls"], row["answer"]), max_revisions=0,
                               max_steps=len(row["tool_calls"]) + 2).ask(row["question"])
        new = score(cases[row["id"]], result, gold)
        same = {"success": new["success"] == row["success"], "tools": new["tools"] == row["tools"],
                "facts": new.get("facts_found") == row.get("facts_found"),
                "faithful": new["faithful"] == row["faithful"]}
        compared.append({"id": row["id"], "split": row["split"], "recorded_success": row["success"],
                         "graph_success": new["success"], "graph_tools": new["tools"],
                         "graph_facts_found": new.get("facts_found"), "graph_faithful": new["faithful"],
                         "identical": all(same.values()), "differences": [k for k, v in same.items() if not v]})
        if progress:
            progress(f"{row['id']} recorded={row['success']} graph={new['success']} "
                     f"{'same' if compared[-1]['identical'] else 'DIFFERENT ' + str(compared[-1]['differences'])}")
    summary = {"source": f"{recorded}_cases.jsonl", "cases": len(compared),
               "identical": sum(r["identical"] for r in compared),
               "recorded_successes": sum(r["recorded_success"] for r in compared),
               "graph_successes": sum(r["graph_success"] for r in compared),
               "mismatches": [r["id"] for r in compared if not r["identical"]],
               "method": "recorded tool calls replayed one per model turn on a fresh session; rewrites disabled; "
                         "scored with the current guardrail and engine-computed gold numbers"}
    if output:
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        (output / "graph_replay_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                                                          encoding="utf-8", newline="\n")
        with (output / "graph_replay_cases.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for record in compared:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"summary": summary, "rows": compared}
