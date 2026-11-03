"""Web page for the notice-to-memo workflow.

    python -m streamlit run planning_agent/app.py

The page only arranges inputs and outputs; parsing, confirmation, solving and the memo live in workflow.py.
Rule, notice and replay modes never call a model. Live mode does not exist on the page unless the operator opened it
on the server (llm.LiveAccess): a key alone is not enough, and visitors cannot raise any limit.
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# `streamlit run` puts this file's folder, not the repository root, on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from planning_agent import llm, retrieval, workflow
from planning_agent.tools import Session

INTEGER_FIELDS = {"start_week", "end_week", "extra_lead_weeks"}
MAX_TEXT_CHARS = 2000  # max_chars also cuts the value on the server


@st.cache_resource
def live_access() -> llm.LiveAccess:
    """One per server process: the daily meter and the access-code lockout are shared by all visitors."""
    return llm.LiveAccess.from_env()


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
access = live_access()
modes = [m for m in workflow.MODE_LABELS if m != "live" or access.open]
mode = st.sidebar.radio("参数来源", modes, format_func=workflow.MODE_LABELS.__getitem__, key="mode")
live_note = "实时模型模式会产生费用，需要访问码，额度由服务端限定。" if access.open else "实时模型模式没有开放。"
st.sidebar.caption(f"规则、公告检索和录制回放模式都不调用大模型。所有方案都在你确认后实时求解。{live_note}")
st.caption(f"当前模式：{workflow.MODE_LABELS[mode]}")  # the sidebar starts collapsed on a phone

if mode == "rule":
    notice = st.text_area("运输公告或扰动描述", workflow.DEMO_NOTICE, key="notice", height=110,
                          max_chars=MAX_TEXT_CHARS)
    network = st.selectbox("网络", ["自动识别", "asml", "marvell"], key="network")
    if st.button("解析参数", key="parse"):
        start(workflow.propose_from_rules(notice, None if network == "自动识别" else network))
elif mode == "notice":
    question = st.text_area("问题或扰动描述（会先检索真实船公司公告）", workflow.NOTICE_QUESTION, key="notice_question",
                            height=110, max_chars=MAX_TEXT_CHARS)
    network = st.selectbox("网络", ["自动识别", "asml", "marvell"], key="notice_network")
    downloaded = retrieval.RAW.exists() and any(retrieval.RAW.glob("*.html"))
    full_text = st.checkbox("同时检索本地下载的公告原文", key="full_text", disabled=not downloaded,
                            help=None if downloaded else "需要先运行 python -m planning_agent corpus fetch --yes")
    st.caption("语料是仓库里已有的 24 条公告摘录（离线 BM25，不调用模型）；中文问题用术语表扩展成英文后检索。"
               "勾选原文时，每个下载页面只用前 5 段，避免长页面占优。")
    if st.button("检索公告并解析参数", key="retrieve"):
        start(workflow.propose_from_notices(question, None if network == "自动识别" else network,
                                            index=retrieval.default_index(full_text)))
elif mode == "replay":
    cases = workflow.recorded_cases()
    case = st.selectbox("录制案例", sorted(cases), key="case",
                        format_func=lambda c: f"{c}：{cases[c]['question'][:60]}")
    if st.button("载入录制参数", key="load"):
        start(workflow.propose_from_recording(case))
else:
    notice = st.text_area("运输公告或扰动描述", workflow.DEMO_NOTICE, key="live_notice", height=110,
                          max_chars=MAX_TEXT_CHARS)
    rag = st.checkbox("把检索到的公告附在提示里（检索增强）", key="live_rag")
    code = st.text_input("访问码", type="password", key="live_code")
    meter = st.session_state.setdefault("live_meter", access.session_meter())
    used = meter.snapshot()
    st.caption(f"本会话已发送 {used['requests']} / {used['limit_requests']} 次请求；"
               "每日总额度由服务端限定，页面上不能修改。")
    if st.button("调用模型提出参数", key="live"):
        if not access.check_code(code):
            st.error("访问码不正确，或错误次数过多，请稍后再试。没有调用模型。")
        else:
            try:
                references = ([retrieval.reference(h) for h in retrieval.default_index().search(notice, k=3)]
                              if rag else [])
                start(workflow.propose_from_model(notice, access.client(meter), references=references))
            except llm.LLMError as error:
                logging.getLogger(__name__).warning("live call failed: %s", llm.redact(str(error)))
                stopped = meter.stopped or (access.daily.stopped if access.daily else None)
                st.error("额度已用完，没有调用模型。" if stopped else "模型调用没有完成，没有生成参数。")
            except ValueError:
                st.error("模型没有给出可用的参数，请改写公告，或使用规则模式。")

proposal: workflow.Proposal | None = st.session_state.get("proposal")
if proposal is not None:
    st.subheader("① 参数与默认假设（确认之前不做任何求解）")
    st.info(f"参数来源：{proposal.source}")
    st.write(f"公告：{proposal.notice}")
    for note in proposal.notes:
        st.caption(note)
    if proposal.references:
        st.write(f"**检索到的公告**（{len(proposal.references)} 条，离线 BM25；文本权利属于各船公司）")
        for r in proposal.references:
            where = "本地原文" if r["local_full_text"] else "摘录"
            st.markdown(f"- **{r['id']}** {r['publisher']}《[{r['title']}]({r['url']})》"
                        f"{r['date'] or '发布日期未标注'}，得分 {r['score']}  \n  {where}：*{r['passage']}*")
        if proposal.missing:
            st.warning("公告没有给出、需要你确认的信息：" + "；".join(proposal.missing))
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
        evidence = [{"参数": e["parameter"], "来源": e.get("source", "原文"), "原文": e["text"]}
                    for e in current.evidence]
        st.table(pd.DataFrame(evidence or [{"参数": "（无）", "来源": "", "原文": ""}]))
        basis = workflow.parameter_basis(current, proposal)
        if basis:
            st.write("**参数依据**")
            st.table(pd.DataFrame(basis))
        st.write("**默认假设**")
        for item in checked["assumptions"] or ["（无）"]:
            st.write(f"- {item}")
        if checked["error"]:
            st.error(f"参数不可用：{checked['error']}")
    if st.button("② 确认并求解", key="confirm", disabled=bool(checked["error"]), type="primary"):
        with st.spinner("正在求解正常方案与扰动方案…"):
            st.session_state["outcome"] = workflow.run(current, tool_session(), confirmed=True, original=proposal)

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
