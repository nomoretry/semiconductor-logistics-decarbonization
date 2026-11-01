"""Notice-to-memo decision workflow: propose parameters, confirm, solve, compare, write a memo.

Parameters come from one of three sources, and every result records which one was used:

- ``rule``: the deterministic parser in rules.py (offline, no model call);
- ``replay``: scenario arguments a real model produced in the recorded 24-question evaluation (no model call);
- ``live``: a model proposes arguments through the LangGraph agent, paused before any tool runs (paid, opt-in).

Whatever the source, nothing is solved until the planner confirms, and every number comes from the engine.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import rules

DEMO_NOTICE = ("船公司通知：受红海安全局势影响，第4到12周亚欧航线绕行好望角，海运延误2周，舱位削减30%。"
               "这对我们新加坡备件仓的成本和排放有什么影响？")
RECORDED = Path(__file__).resolve().parents[1] / "benchmark_results" / "planning_agent"
MODE_LABELS = {
    "rule": "离线规则解析（不调用模型）",
    "replay": "录制回放（真实模型的历史输出，本次不调用模型）",
    "live": "实时模型（付费调用）",
}
DISRUPTION_FIELDS = ("mode", "start_week", "end_week", "extra_lead_weeks", "capacity_change_pct", "cost_change_pct",
                     "distance_factor")
EVIDENCE_PATTERNS = (
    ("周次", rules.WEEKS), ("延误", rules.DELAY), ("运力或舱位", rules.CAPACITY), ("需求变化", rules.DEMAND),
    ("减排", rules.CAP_CUT), ("排放上限", rules.CAP_LEVEL), ("中断概率", rules.PROBABILITY),
    *((f"场景：{name}", pattern) for name, pattern in rules.SCENARIO_PATTERNS),
    *((f"运输方式：{mode}", pattern) for mode, pattern in rules.MODES),
)
READ_ONLY_TOOLS = {"describe_network"}


class ConfirmationRequired(RuntimeError):
    """Raised when solving is requested before the planner has confirmed the parameters."""


@dataclass
class Proposal:
    """Parameters for one disruption, before confirmation. Editing returns a new proposal."""

    mode: str
    source: str
    notice: str
    network: str
    disruptions: list[dict[str, Any]] = field(default_factory=list)
    demand_change_pct: float | None = None
    demand_weeks: list[int] | None = None
    preset: str | None = None  # a predefined scenario, used when the notice gives no numbers of its own
    carbon_cap_pct: float | None = None
    hedge_probability_pct: float | None = None
    evidence: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def scenario_arguments(self) -> dict[str, Any] | None:
        """create_scenario arguments; the name hashes the parameters so an edit never reuses a cached solve."""
        if not self.disruptions and self.demand_change_pct is None:
            return None
        body: dict[str, Any] = {"disruptions": [dict(d) for d in self.disruptions]}
        if self.demand_change_pct is not None:
            body["demand_change_pct"] = self.demand_change_pct
            if self.demand_weeks:
                body["demand_weeks"] = list(self.demand_weeks)
        digest = hashlib.sha256(json.dumps([self.network, body], sort_keys=True).encode()).hexdigest()[:6]
        if self.disruptions:
            first = self.disruptions[0]
            kind = re.sub(r"[^a-z]", "", str(first.get("mode") or "lanes").lower()) or "lanes"
            readable = f"{kind}_w{int(first.get('start_week', 0))}_{int(first.get('end_week', 0))}"
        else:
            readable = "demand"
        return {"network": self.network, "name": f"notice_{readable}_{digest}", "description": self.notice[:200],
                **body}

    def with_changes(self, **changes: Any) -> Proposal:
        return replace(self, **changes)


@dataclass
class Outcome:
    proposal: Proposal
    scenario: str
    assumptions: list[str]
    rows: list[dict[str, Any]]
    hedge: dict[str, Any] | None
    memo_path: str
    memo_text: str
    tool_calls: list[dict[str, Any]]
    seconds: float


# ---------------------------------------------------------------------------- proposals

def evidence_for(notice: str) -> list[dict[str, str]]:
    """Which words of the notice each recognised parameter came from."""
    found = []
    for label, pattern in EVIDENCE_PATTERNS:
        matches = list(dict.fromkeys(m.group(0) for m in re.finditer(pattern, notice, rules.FLAGS)))
        if matches:
            found.append({"parameter": label, "text": "、".join(matches[:3])})
    return found


def propose_from_rules(notice: str, network: str | None = None) -> Proposal:
    request = rules.parse(notice, {"network": network} if network else None)
    net = network or request["network"]
    proposal = Proposal("rule", MODE_LABELS["rule"], notice, net, evidence=evidence_for(notice),
                        carbon_cap_pct=request["cap_pct"], hedge_probability_pct=request["probability_pct"])
    custom = request["custom"]
    if custom:
        proposal.network = custom["network"]
        proposal.disruptions = [dict(d) for d in custom.get("disruptions") or []]
        if custom.get("demand_change_pct") is not None:
            proposal.demand_change_pct = custom["demand_change_pct"]
            proposal.demand_weeks = custom.get("demand_weeks")
    elif request["scenario"] and request["scenario"] != "normal":
        proposal.preset = request["scenario"]
        proposal.notes.append(f"公告没有给出具体周次和幅度，使用预设场景 {request['scenario']}。")
    else:
        proposal.notes.append("没有识别出扰动参数：请手动填写，或换一种写法（例如“第5到8周海运延误1周，舱位减少20%”）。")
    return proposal


def recorded_cases(source: Path = RECORDED) -> dict[str, dict[str, Any]]:
    """Recorded model runs that built a custom scenario: case id -> question and the scenario finally used."""
    path = source / "llm_rescored_cases.jsonl"
    cases = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        built = [c for c in row.get("tool_calls", []) if c["name"] == "create_scenario" and c["ok"]]
        if built:
            cases[row["id"]] = {"question": row["question"], "arguments": built[-1]["arguments"],
                                "success": row["success"]}
    return cases


def propose_from_recording(case_id: str, source: Path = RECORDED) -> Proposal:
    cases = recorded_cases(source)
    if case_id not in cases:
        raise KeyError(f"no recorded custom scenario for case {case_id}; available: {sorted(cases)}")
    case = cases[case_id]
    summary = json.loads((source / "llm_summary.json").read_text(encoding="utf-8"))
    args = case["arguments"]
    origin = (f"录制回放：{summary.get('model')}（{summary.get('api_style')} 接口，推理强度 "
              f"{summary.get('reasoning_effort')}）在 24 题正式评测中为案例 {case_id} 给出的场景参数；本次不调用模型")
    proposal = Proposal("replay", origin, case["question"], args["network"],
                        disruptions=[dict(d) for d in args.get("disruptions") or []],
                        demand_change_pct=args.get("demand_change_pct"), demand_weeks=args.get("demand_weeks"),
                        evidence=evidence_for(case["question"]))
    proposal.notes.append(f"录制运行在该案例上的评测结果：{'成功' if case['success'] else '失败'}。")
    return proposal


class _Captured(Exception):
    def __init__(self, calls: list[dict[str, Any]]):
        super().__init__("captured tool calls")
        self.calls = calls


def propose_from_model(notice: str, client: Any, *, max_tokens: int | None, network: str | None = None,
                       max_steps: int = 4) -> Proposal:
    """Ask a model for scenario arguments through the LangGraph agent; stop before any scenario tool runs.

    Read-only lookups (describe_network) may run; the first create_scenario or solve_plan call is captured
    and nothing else executes. This is a paid call: a token cap is required.
    """
    from .graph import PlanningGraph
    from .tools import Session

    if not max_tokens:
        raise ValueError("live mode needs a token cap (max_tokens) approved in advance")

    def approve(calls: list[dict[str, Any]]) -> bool:
        names = {(c.get("function") or {}).get("name") for c in calls}
        if names <= READ_ONLY_TOOLS:
            return True
        raise _Captured(calls)

    session = Session()
    question = notice if not network else f"{notice}\n（网络：{network}）"
    try:
        PlanningGraph(session, client, approve=approve, max_steps=max_steps).ask(question)
    except _Captured as captured:
        calls = captured.calls
    else:
        raise ValueError("the model answered without proposing a scenario; rephrase the notice or use rule mode")
    used = sum((getattr(client, "usage", {}) or {}).get(k, 0) for k in ("prompt_tokens", "completion_tokens"))
    model = getattr(client, "model", "unknown model")
    proposal = Proposal("live", f"实时模型：{model}，本次用了 {used:,} 个 token（上限 {max_tokens:,}）", notice,
                        network or "asml", evidence=evidence_for(notice))
    for call in calls:
        function = call.get("function") or {}
        args = json.loads(function.get("arguments") or "{}")
        if function.get("name") == "create_scenario":
            proposal.network = args.get("network", proposal.network)
            proposal.disruptions = [dict(d) for d in args.get("disruptions") or []]
            proposal.demand_change_pct = args.get("demand_change_pct")
            proposal.demand_weeks = args.get("demand_weeks")
        elif function.get("name") == "solve_plan" and args.get("scenario") not in (None, "normal"):
            proposal.network = args.get("network", proposal.network)
            proposal.preset = args["scenario"]
            proposal.carbon_cap_pct = args.get("carbon_cap_pct")
    if used > max_tokens:
        proposal.notes.append(f"注意：用量 {used:,} 超过上限 {max_tokens:,}。")
    return proposal


# ---------------------------------------------------------------------------- preview and run

def preview(proposal: Proposal, session: Any) -> dict[str, Any]:
    """Validate the parameters and list default assumptions without solving anything."""
    args = proposal.scenario_arguments()
    if args is None:
        if proposal.preset:
            return {"scenario": proposal.preset, "assumptions": [f"使用预设场景 {proposal.preset}"], "error": None}
        return {"scenario": None, "assumptions": [], "error": "没有可用的扰动参数"}
    result = session.call("create_scenario", args)
    if "error" in result:
        return {"scenario": None, "assumptions": [], "error": result["error"]}
    return {"scenario": result["scenario"], "assumptions": result["assumptions"], "error": None,
            "definition": result["definition"]}


def run(proposal: Proposal, session: Any, *, confirmed: bool) -> Outcome:
    """Solve and compare after confirmation; every number in the outcome comes from tool results."""
    if not confirmed:
        raise ConfirmationRequired("the planner has not confirmed the parameters")
    started, first = time.perf_counter(), len(session.calls)
    checked = preview(proposal, session)
    if checked["error"]:
        raise ValueError(f"parameters rejected: {checked['error']}")
    scenario, network = checked["scenario"], proposal.network
    plans = [session.call("solve_plan", {"network": network}),
             session.call("solve_plan", {"network": network, "scenario": scenario})]
    if proposal.carbon_cap_pct:
        plans.append(session.call("solve_plan", {"network": network, "scenario": scenario,
                                                 "carbon_cap_pct": proposal.carbon_cap_pct}))
    failed = [p for p in plans if "error" in p or p.get("status") not in ("optimal", "feasible")]
    if failed:
        raise ValueError(f"no feasible plan: {failed[0].get('error') or failed[0].get('status')}")
    rows = session.call("compare_plans", {"plan_ids": [p["plan_id"] for p in plans]})["rows"]
    hedge = None
    plan_ids = [p["plan_id"] for p in plans]
    if proposal.hedge_probability_pct:
        p = float(proposal.hedge_probability_pct)
        hedge = session.call("hedge_disruption_risk", {"network": network, "scenarios": ["normal", scenario],
                                                       "probabilities": [100 - p, p]})
        if "error" not in hedge:
            plan_ids += list(hedge["plan_ids"].values())
    memo = session.call("write_memo", {"plan_ids": plan_ids[:6], "question": proposal.notice})
    memo_text = Path(memo["path"]).read_text(encoding="utf-8") if "path" in memo else ""
    calls = [{"name": c["name"], "arguments": c["arguments"], "ok": c["ok"], "seconds": c["seconds"]}
             for c in session.calls[first:]]
    return Outcome(proposal, scenario, checked["assumptions"], rows, hedge, memo.get("path", ""), memo_text, calls,
                   round(time.perf_counter() - started, 2))


def summary_rows(outcome: Outcome) -> list[dict[str, Any]]:
    """The comparison as planners read it: one row per plan with cost, service, emissions and air share."""
    names = ["正常", "扰动", "扰动 + 减排上限"]
    out = []
    for i, row in enumerate(outcome.rows):
        out.append({"方案": f"{row['plan_id']}（{names[min(i, 2)]}）", "总成本（美元）": row["total_cost_usd"],
                    "成本变化": f"{row.get('cost_change_pct', 0):+.2f}%", "服务水平": f"{row['service_level_pct']}%",
                    "排放（吨）": row["emissions_t"], "排放变化": f"{row.get('emissions_change_pct', 0):+.2f}%",
                    "空运占比": f"{row['air_share_pct']}%"})
    return out


def describe(proposal: Proposal) -> list[str]:
    """Plain-text lines for the command line."""
    lines = [f"参数来源：{proposal.source}", f"网络：{proposal.network}"]
    if proposal.preset:
        lines.append(f"预设场景：{proposal.preset}")
    for i, d in enumerate(proposal.disruptions, 1):
        parts = [f"{key}={d[key]}" for key in (*DISRUPTION_FIELDS, "lanes") if key in d]
        lines.append(f"扰动 {i}：" + "，".join(parts))
    if proposal.demand_change_pct is not None:
        lines.append(f"需求变化：{proposal.demand_change_pct:+}%（周次 {proposal.demand_weeks or '全部'}）")
    if proposal.carbon_cap_pct:
        lines.append(f"排放上限：不设上限方案的 {proposal.carbon_cap_pct}%")
    if proposal.hedge_probability_pct:
        lines.append(f"中断概率：{proposal.hedge_probability_pct}%（做两阶段对冲）")
    lines += [f"原文依据：{e['parameter']} ← “{e['text']}”" for e in proposal.evidence]
    lines += proposal.notes
    return lines


def edit_disruption(proposal: Proposal, index: int, ask: Callable[[str, str], str]) -> Proposal:
    """Command-line editing: ask for each field, keep the current value when the answer is empty."""
    current = dict(proposal.disruptions[index])
    for key in DISRUPTION_FIELDS:
        answer = ask(key, str(current.get(key, ""))).strip()
        if answer:
            current[key] = answer if key == "mode" else float(answer) if "." in answer else int(answer)
    disruptions = [dict(d) for d in proposal.disruptions]
    disruptions[index] = current
    return proposal.with_changes(disruptions=disruptions)
