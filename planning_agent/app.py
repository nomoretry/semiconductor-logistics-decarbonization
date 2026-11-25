"""Web page for the notice-to-memo workflow.

    python -m streamlit run planning_agent/app.py

The page only arranges inputs and outputs; parsing, confirmation, solving and the memo live in workflow.py.
Rule and replay modes never call a model. Live mode needs LLM_API_KEY, a token cap and an explicit approval.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# `streamlit run` puts this file's folder, not the repository root, on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from planning_agent import llm, workflow
from planning_agent.tools import Session

INTEGER_FIELDS = {"start_week", "end_week", "extra_lead_weeks"}


def tool_session() -> Session:
    """One tool session per browser session; tests can pass a smaller network through the environment."""
    if "session" not in st.session_state:
        settings = json.loads(os.environ.get("PLANNING_FLOW_SETTINGS") or "{}")
        st.session_state["session"] = Session(memo_dir=Path("artifacts/planning_agent/web"), **settings)
    return st.session_state["session"]  # type: ignore[no-any-return]


def start(proposal: workflow.Proposal) -> None:
    st.session_state["proposal"] = proposal
    st.session_state.pop("outcome", None)


def cleaned(rows: list[dict[str, Any]], original: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Edited table rows back to create_scenario disruptions; blank cells fall back to the tool's defaults."""
    out = []
    for i, row in enumerate(rows):
        item: dict[str, Any] = {}
        for key in workflow.DISRUPTION_FIELDS:
            value = row.get(key)
            if value is None or (isinstance(value, float) and math.isnan(value)) or value == "":
                continue
            item[key] = str(value) if key == "mode" else int(value) if key in INTEGER_FIELDS else float(value)
        if i < len(original) and "lanes" in original[i]:
            item["lanes"] = original[i]["lanes"]
        if item:
            out.append(item)
    return out


st.set_page_config(page_title="物流扰动决策", layout="wide")
st.title("运输公告 → 参数确认 → 方案对比 → 决策备忘录")
mode = st.sidebar.radio("参数来源", list(workflow.MODE_LABELS), format_func=workflow.MODE_LABELS.__getitem__,
                        key="mode")
st.sidebar.caption("规则模式和录制回放模式都不调用大模型；只有实时模式会产生费用。所有方案都在你确认后实时求解。")

if mode == "rule":
    notice = st.text_area("运输公告或扰动描述", workflow.DEMO_NOTICE, key="notice", height=110)
    network = st.selectbox("网络", ["自动识别", "asml", "marvell"], key="network")
    if st.button("解析参数", key="parse"):
        start(workflow.propose_from_rules(notice, None if network == "自动识别" else network))
elif mode == "replay":
    cases = workflow.recorded_cases()
    case = st.selectbox("录制案例", sorted(cases), key="case",
                        format_func=lambda c: f"{c}：{cases[c]['question'][:60]}")
    if st.button("载入录制参数", key="load"):
        start(workflow.propose_from_recording(case))
else:
    notice = st.text_area("运输公告或扰动描述", workflow.DEMO_NOTICE, key="live_notice", height=110)
    if not llm.configured():
        st.warning("没有设置 LLM_API_KEY，实时模式不可用。规则模式和录制回放模式不需要 key。")
    else:
        cap = int(st.number_input("本次 token 上限（需事先批准）", min_value=0, value=0, step=1000, key="cap"))
        approved = st.checkbox("我已批准这次付费调用的预算", key="approved")
        if st.button("调用模型提出参数", key="live", disabled=not (approved and cap > 0)):
            start(workflow.propose_from_model(notice, llm.OpenAICompatibleClient(), max_tokens=cap))

proposal: workflow.Proposal | None = st.session_state.get("proposal")
if proposal is not None:
    st.subheader("① 参数与默认假设（确认之前不做任何求解）")
    st.info(f"参数来源：{proposal.source}")
    st.write(f"公告：{proposal.notice}")
    for note in proposal.notes:
        st.caption(note)
    left, right = st.columns([3, 2])
    with left:
        st.write(f"网络：**{proposal.network}**" + (f"；预设场景：**{proposal.preset}**" if proposal.preset else ""))
        table = pd.DataFrame([{k: d.get(k) for k in workflow.DISRUPTION_FIELDS} for d in proposal.disruptions],
                             columns=list(workflow.DISRUPTION_FIELDS))
        edited = st.data_editor(table, key="editor", num_rows="dynamic", width="stretch")
        rows = edited.to_dict("records") if isinstance(edited, pd.DataFrame) else list(edited)
        cap_pct = st.number_input("排放上限（不设上限方案排放的 %，0 表示不设）", 0, 100,
                                  int(proposal.carbon_cap_pct or 0), key="cap_pct")
        prob = st.number_input("中断发生概率（%，0 表示不做对冲）", 0, 99, int(proposal.hedge_probability_pct or 0),
                               key="prob")
    current = proposal.with_changes(disruptions=cleaned(rows, proposal.disruptions),
                                    carbon_cap_pct=float(cap_pct) or None, hedge_probability_pct=float(prob) or None)
    checked = workflow.preview(current, tool_session())
    with right:
        st.write("**原文依据**")
        evidence = [{"参数": e["parameter"], "原文": e["text"]} for e in current.evidence]
        st.table(pd.DataFrame(evidence or [{"参数": "（无）", "原文": ""}]))
        st.write("**默认假设**")
        for item in checked["assumptions"] or ["（无）"]:
            st.write(f"- {item}")
        if checked["error"]:
            st.error(f"参数不可用：{checked['error']}")
    if st.button("② 确认并求解", key="confirm", disabled=bool(checked["error"]), type="primary"):
        with st.spinner("正在求解正常方案与扰动方案…"):
            st.session_state["outcome"] = workflow.run(current, tool_session(), confirmed=True)

outcome: workflow.Outcome | None = st.session_state.get("outcome")
if outcome is not None:
    st.subheader("③ 方案对比（确认后实时求解，HiGHS）")
    disrupted = outcome.rows[1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("扰动方案总成本（美元）", f"{disrupted['total_cost_usd']:,}", f"{disrupted['cost_change_pct']:+.2f}%",
              delta_color="inverse")
    c2.metric("服务水平", f"{disrupted['service_level_pct']}%")
    c3.metric("排放（吨）", f"{disrupted['emissions_t']}", f"{disrupted['emissions_change_pct']:+.2f}%",
              delta_color="inverse")
    c4.metric("空运占比", f"{disrupted['air_share_pct']}%")
    st.dataframe(pd.DataFrame(workflow.summary_rows(outcome)), width="stretch", hide_index=True)
    if outcome.hedge and "error" not in outcome.hedge:
        hedge = outcome.hedge
        st.write(f"**对冲**：两阶段随机方案期望成本 {hedge['expected_cost_usd']['stochastic_RP']:,} 美元，"
                 f"按正常预测计划、事后再应变 {hedge['expected_cost_usd']['nominal_EEV']:,} 美元，"
                 f"VSS {hedge['VSS_usd']:,} 美元（{hedge['VSS_pct']}%）。")
    st.subheader("④ 决策备忘录")
    st.markdown(outcome.memo_text)
    st.download_button("下载备忘录（Markdown）", outcome.memo_text, file_name=Path(outcome.memo_path).name,
                       key="download")
    with st.expander(f"工具调用记录（{len(outcome.tool_calls)} 次，用时 {outcome.seconds} 秒）"):
        st.json(outcome.tool_calls)
