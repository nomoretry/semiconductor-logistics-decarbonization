"""Notice-to-memo decision workflow: propose parameters, confirm, solve, compare, write a memo.

Parameters come from one of three sources, and every result records which one was used:

- ``rule``: the deterministic parser in rules.py (offline, no model call);
- ``notice``: the same parser on the planner's words, plus real carrier notices found by retrieval.py; each
  parameter cites its basis and the information the notices leave out is listed (offline, no model call);
- ``replay``: scenario arguments a real model produced in the recorded 24-question evaluation (no model call);
- ``live``: a model proposes arguments through the LangGraph agent, paused before any tool runs (paid, opt-in).

Whatever the source, nothing is solved until the planner confirms, and every number comes from the engine.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import rules

DEMO_NOTICE = ("船公司通知：受红海安全局势影响，第4到12周亚欧航线绕行好望角，海运延误2周，舱位削减30%。"
               "这对我们新加坡备件仓的成本和排放有什么影响？")
RECORDED = Path(__file__).resolve().parents[1] / "benchmark_results" / "planning_agent"
NOTICE_QUESTION = ("红海局势导致船只绕行好望角：第4到12周亚欧海运延误2周，舱位削减30%。"
                   "新加坡备件仓的成本和排放会怎样？")
MODE_LABELS = {
    "rule": "离线规则解析（不调用模型）",
    "notice": "公告检索 + 规则解析（不调用模型）",
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
# Notice wording may select a preset only where the preset models that event; the border_congestion preset is a
# Malaysia-Singapore border, so congestion at a European port must not trigger it.
NOTICE_PRESETS = ("red_sea", "typhoon")
FIELD_EVIDENCE = {"start_week": "周次", "end_week": "周次", "extra_lead_weeks": "延误", "capacity_change_pct": "运力或舱位"}
PLANNER = "计划员输入"
NOTICE_QUANTITY = "公告数值（仅供参考，不自动成为参数）"


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
    references: list[dict[str, Any]] = field(default_factory=list)  # retrieved notices, cited in the memo
    missing: list[str] = field(default_factory=list)  # what the notices do not say, for the planner to settle

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


def missing_labels(references: Sequence[dict[str, Any]]) -> list[str]:
    from .retrieval import MISSING_LABELS
    codes = dict.fromkeys(code for r in references for code in r.get("missing", []))
    return [MISSING_LABELS.get(code, code) for code in codes]


def propose_from_notices(question: str, network: str | None = None, *, k: int = 3, index: Any = None) -> Proposal:
    """Retrieve related carrier notices, then parse the planner's own words; every parameter keeps its basis.

    Notices give context and citations. Their approximate values and ranges are shown, never turned into
    parameters; a notice may only select a preset that models the same event (NOTICE_PRESETS).
    """
    from . import retrieval

    hits = (index or retrieval.default_index()).search(question, k=k)
    proposal = propose_from_rules(question, network)
    proposal.mode, proposal.source = "notice", MODE_LABELS["notice"]
    proposal.notes = [n for n in proposal.notes if not n.startswith("没有识别出扰动参数")]
    for item in proposal.evidence:
        item["source"] = PLANNER
    proposal.references = [retrieval.reference(hit) for hit in hits]
    proposal.missing = missing_labels(proposal.references)
    found: list[tuple[str, str]] = []  # (preset, notice id) in rank order
    for hit in hits:
        cited = f"公告 {hit.notice.id}"
        for name, pattern in rules.SCENARIO_PATTERNS:
            if name not in NOTICE_PRESETS:
                continue
            matches = list(dict.fromkeys(m.group(0) for m in re.finditer(pattern, f"{hit.notice.title} {hit.passage}",
                                                                          rules.FLAGS)))
            if matches:
                proposal.evidence.append({"parameter": f"场景：{name}", "text": "、".join(matches[:3]),
                                          "source": cited})
                found.append((name, hit.notice.id))
        proposal.evidence += [{"parameter": NOTICE_QUANTITY, "text": q, "source": cited} for q in hit.notice.quantities]
    if not proposal.disruptions and proposal.demand_change_pct is None and not proposal.preset:
        usable = [(name, nid) for name, nid in found if network in (None, rules.NETWORK_OF[name])]
        if usable:
            proposal.preset, cited_id = usable[0]
            proposal.network = network or rules.NETWORK_OF[proposal.preset]
            proposal.notes.append(f"你的描述里没有周次和幅度；公告 {cited_id} 提到同类事件，先用预设场景 "
                                  f"{proposal.preset}。预设的幅度是合成假设，请对照公告核对后再确认。")
        else:
            proposal.notes.append("检索到的公告没有给出可直接执行的周次和幅度：请在参数表里填写，"
                                  "下面列出了公告缺少的信息。")
    if not hits:
        proposal.notes.append("没有检索到相关公告：参数只来自你的描述。")
    return proposal


def _cite(item: dict[str, str] | None) -> str | None:
    return f"{item.get('source', '原文')}：“{item['text']}”" if item else None


def parameter_basis(proposal: Proposal, original: Proposal | None = None) -> list[dict[str, str]]:
    """Where each parameter came from: the planner's words, a notice, a preset, a default, or an edit at confirmation."""
    original = original or proposal
    evidence: dict[str, dict[str, str]] = {}
    for item in proposal.evidence:
        evidence.setdefault(item["parameter"], item)
    generated = {"replay": "录制的模型输出", "live": "模型提出"}.get(proposal.mode, "默认值")
    rows = []
    if proposal.preset:
        rows.append({"参数": "预设场景", "取值": proposal.preset,
                     "依据": _cite(evidence.get(f"场景：{proposal.preset}")) or "预设场景"})
    many = len(proposal.disruptions) > 1
    for i, disruption in enumerate(proposal.disruptions):
        before = original.disruptions[i] if i < len(original.disruptions) else {}
        for key in DISRUPTION_FIELDS:
            if key not in disruption:
                continue
            value = disruption[key]
            if before.get(key) != value:
                basis = "计划员在确认时修改"
            elif key == "mode":
                basis = _cite(evidence.get(f"运输方式：{value}")) or f"{generated}（海运）"
            elif key == "distance_factor":
                basis = "数据审计：经好望角与经苏伊士的距离比（红海绕行）"
            else:
                basis = _cite(evidence.get(FIELD_EVIDENCE.get(key, ""))) or generated
            rows.append({"参数": f"扰动{i + 1}.{key}" if many else key, "取值": str(value), "依据": basis})
    if proposal.demand_change_pct is not None:
        rows.append({"参数": "demand_change_pct", "取值": str(proposal.demand_change_pct),
                     "依据": _cite(evidence.get("需求变化")) or generated})
    for key, value, labels in (("carbon_cap_pct", proposal.carbon_cap_pct, ("减排", "排放上限")),
                               ("hedge_probability_pct", proposal.hedge_probability_pct, ("中断概率",))):
        if value:
            changed = value != getattr(original, key)
            cited = next((_cite(evidence[label]) for label in labels if label in evidence), None)
            rows.append({"参数": key, "取值": str(value),
                         "依据": "计划员在确认时修改" if changed else cited or "计划员在确认时填写"})
    return rows


def reference_section(proposal: Proposal, basis: list[dict[str, str]]) -> list[str]:
    """Memo lines that cite the retrieved notices, the open questions and the basis of each parameter."""
    def cell(text: Any) -> str:
        return str(text).replace("|", "\\|")

    lines = ["", "## 参考公告", "", "| 编号 | 船公司 | 标题 | 发布日期 | 链接 |", "|---|---|---|---|---|"]
    lines += [f"| {r['id']} | {cell(r['publisher'])} | {cell(r['title'])} | {r['date'] or '未标注'} | {r['url']} |"
              for r in proposal.references]
    lines += ["", "公告摘录保存在仓库的公告数据集中，文本权利属于各船公司；检索为离线 BM25，不调用模型。"]
    if proposal.missing:
        lines += ["", "## 公告没有给出、由计划员确认的信息", "", *(f"- {m}" for m in proposal.missing)]
    if basis:
        lines += ["", "## 参数依据", "", *(f"- {b['参数']} = {b['取值']}：{b['依据']}" for b in basis)]
    return [*lines, ""]


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
                       max_steps: int = 4, references: Sequence[dict[str, Any]] = ()) -> Proposal:
    """Ask a model for scenario arguments through the LangGraph agent; stop before any scenario tool runs.

    Read-only lookups (describe_network) may run; the first create_scenario or solve_plan call is captured
    and nothing else executes. This is a paid call: a token cap is required. Retrieved notices, when given,
    are quoted in the question with their ids so the model can cite them (retrieval-augmented prompt).
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
    if references:
        quoted = "\n".join(f"[{r['id']}] {r['publisher']}《{r['title']}》：“{r['passage']}”" for r in references)
        question += ("\n\n检索到的船公司公告（原文摘录，作为依据；其中的近似值和区间不要直接当作确定参数，"
                     f"公告没有给出的周次和幅度不要编造）：\n{quoted}")
    try:
        PlanningGraph(session, client, approve=approve, max_steps=max_steps).ask(question)
    except _Captured as captured:
        calls = captured.calls
    else:
        raise ValueError("the model answered without proposing a scenario; rephrase the notice or use rule mode")
    used = sum((getattr(client, "usage", {}) or {}).get(k, 0) for k in ("prompt_tokens", "completion_tokens"))
    model = getattr(client, "model", "unknown model")
    proposal = Proposal("live", f"实时模型：{model}，本次用了 {used:,} 个 token（上限 {max_tokens:,}）", notice,
                        network or "asml", evidence=evidence_for(notice), references=list(references),
                        missing=missing_labels(references))
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


def run(proposal: Proposal, session: Any, *, confirmed: bool, original: Proposal | None = None) -> Outcome:
    """Solve and compare after confirmation; every number in the outcome comes from tool results.

    ``original`` is the proposal before the planner's edits, so the memo can say which values were changed.
    """
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
    if memo_text and proposal.references:
        cited = reference_section(proposal, parameter_basis(proposal, original))
        memo_text = memo_text.rstrip("\n") + "\n" + "\n".join(cited)
        Path(memo["path"]).write_text(memo_text, encoding="utf-8", newline="\n")
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
    lines += [f"原文依据：{e['parameter']} ← {e.get('source', '')}“{e['text']}”" for e in proposal.evidence]
    for r in proposal.references:
        lines.append(f"参考公告 {r['id']}（得分 {r['score']}）：{r['publisher']}《{r['title']}》"
                     f"{r['date'] or '发布日期未标注'}  {r['url']}")
        lines.append(f"    摘录：{r['passage']}")
    lines += [f"公告没有给出：{m}" for m in proposal.missing]
    if proposal.references:
        lines += [f"参数依据：{b['参数']} = {b['取值']} ← {b['依据']}" for b in parameter_basis(proposal)]
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
