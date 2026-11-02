"""Export shareable figures, an animation and the example decision memo.

    python scripts/export_presentation.py --output artifacts/share

Figures read archived evidence in benchmark_results/. The example re-runs the documented rule-mode
workflow (the same parameters as `python -m planning_agent flow` with the built-in notice) and keeps
the solved weekly flows that the animation draws. Nothing is tuned or re-estimated. Every output names
its data source, the code version and the display mode, and a manifest records file hashes.
Requires the planning extra; MP4 export uses the ffmpeg binary shipped with imageio-ffmpeg, and the
PDF memo is printed by a local Chromium-based browser when one is found.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import animation, font_manager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Reference categorical palette (validated: adjacent CVD separation passes; low-contrast slots carry value labels).
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK_2, GRID, SURFACE, BAND = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb", "#ecebe7"
CJK_FONTS = ("Microsoft YaHei", "Noto Sans SC", "Noto Sans CJK SC", "Source Han Sans SC", "SimHei",
             "WenQuanYi Zen Hei")
SCENARIO_NAMES = {"red_sea": "红海绕行", "air_crunch": "空运运力紧张", "demand_surge": "需求激增",
                  "typhoon": "台风", "border_congestion": "边境拥堵", "normal": "正常"}
MODE_SAVED = "展示模式：保存的历史结果（归档证据，本次未重新求解）"
MODE_EXAMPLE = "展示模式：规则解析 + 实时优化（离线，不调用模型）"


def setup_fonts() -> str:
    installed = {f.name for f in font_manager.fontManager.ttflist}
    font = next((name for name in CJK_FONTS if name in installed), None)
    if font is None:
        raise SystemExit("no CJK font found; install one of: " + ", ".join(CJK_FONTS))
    plt.rcParams.update({
        "font.sans-serif": [font, "DejaVu Sans"], "font.family": "sans-serif", "axes.unicode_minus": False,
        "svg.fonttype": "path", "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
        "axes.edgecolor": INK_2, "axes.labelcolor": INK, "xtick.color": INK_2, "ytick.color": INK_2,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y",
        "grid.color": GRID, "grid.linewidth": 0.8, "axes.titleweight": "bold", "axes.titlesize": 12,
    })
    return font


def code_version() -> str:
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    version = head.stdout.strip() or "unknown"
    return version + ("（含未提交修改）" if dirty else "")


def load(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def footer(fig: plt.Figure, lines: list[str]) -> None:
    fig.text(0.01, 0.01, "\n".join(lines), ha="left", va="bottom", fontsize=8, color=INK_2)


def save(fig: plt.Figure, out: Path, stem: str) -> list[Path]:
    paths = [out / f"{stem}.png", out / f"{stem}.svg"]
    fig.savefig(paths[0], dpi=200)
    fig.savefig(paths[1])
    plt.close(fig)
    return paths


def signed(value: float) -> str:
    """Percent change with a sign, without a misleading "-0.0%"."""
    return "0.0%" if abs(value) < 0.05 else f"{value:+.1f}%"


def label_bars(ax: plt.Axes, bars: Any, texts: list[str]) -> None:
    for bar, text in zip(bars, texts, strict=True):
        height = bar.get_height()
        ax.annotate(text, (bar.get_x() + bar.get_width() / 2, height), xytext=(0, 3 if height >= 0 else -11),
                    textcoords="offset points", ha="center", fontsize=8, color=INK)


# ---------------------------------------------------------------------------- figures from archived evidence

def disruption_impact(out: Path, version: str) -> list[Path]:
    source = "benchmark_results/network_planning/results.json"
    results = load(source)
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2), sharey=True)
    for ax, (net, label) in zip(axes, (("asml", "ASML 启发的备件网络"), ("marvell", "Marvell 启发的成品网络")),
                                strict=True):
        rows = [r for r in results["networks"][net]["scenario_impact"] if r["scenario"] != "normal"]
        x = range(len(rows))
        width = 0.38
        cost = [r["cost_change_pct"] for r in rows]
        emissions = [r["emissions_change_pct"] for r in rows]
        b1 = ax.bar([i - width / 2 - 0.01 for i in x], cost, width, color=BLUE, label="总成本变化")
        b2 = ax.bar([i + width / 2 + 0.01 for i in x], emissions, width, color=ORANGE, label="排放变化")
        label_bars(ax, b1, [signed(v) for v in cost])
        label_bars(ax, b2, [signed(v) for v in emissions])
        ax.set_xticks(list(x), [SCENARIO_NAMES.get(r["scenario"], r["scenario"]) for r in rows])
        ax.axhline(0, color=INK_2, linewidth=0.8)
        ax.set_title(label)
    axes[0].set_ylabel("相对正常方案的变化（%）")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, loc="upper center", bbox_to_anchor=(0.5, 0.925), ncol=2)
    settings = results["settings"]
    fig.suptitle("扰动场景对成本与排放的影响（每个场景单独重新优化，与正常方案比较）", fontsize=13, fontweight="bold")
    footer(fig, [f"配置：每个网络 {settings['n_skus']} 个合成 SKU、{settings['weeks']} 周、"
                 f"随机种子 {settings['seed']}；HiGHS 相对 MIP gap ≤ {settings['mip_gap']:.1%}。"
                 "订单、运力、费率和扰动幅度为合成假设。",
                 f"数据：{source}｜代码版本：{version}｜{MODE_SAVED}"])
    fig.subplots_adjust(left=0.07, right=0.98, top=0.8, bottom=0.2, wspace=0.08)
    return save(fig, out, "01_disruption_impact")


def carbon_frontier(out: Path, version: str) -> list[Path]:
    source = "benchmark_results/network_planning/results.json"
    results = load(source)
    fig, ax = plt.subplots(figsize=(9, 5.2))
    for net, label, color in (("asml", "ASML 启发的备件网络", BLUE), ("marvell", "Marvell 启发的成品网络", ORANGE)):
        points = [p for p in results["networks"][net]["frontier"]["points"]
                  if p["status"] in ("optimal", "feasible")]
        x = [100 * p["level"] for p in points]
        y = [p.get("cost_increase_pct", 0.0) for p in points]
        ax.plot(x, y, color=color, linewidth=2, marker="o", markersize=7, label=label,
                markeredgecolor=SURFACE, markeredgewidth=1.5)
        ax.annotate(f"{y[-1]:+.1f}%", (x[-1], y[-1]), xytext=(-6, 6), textcoords="offset points",
                    ha="right", fontsize=8, color=INK)
        for p, xi, yi in zip(points, x, y, strict=True):
            if abs(p["level"] - 0.75) < 1e-9:
                mac = p["mac_vs_baseline_usd_per_t"]
                ax.annotate(f"减排 25%：成本 {yi:+.2f}%\n平均边际减排成本 {mac:,.0f} 美元/吨", (xi, yi),
                            xytext=(14, -40) if net == "asml" else (-14, 22), textcoords="offset points",
                            ha="left" if net == "asml" else "right", fontsize=8, color=INK,
                            arrowprops={"arrowstyle": "-", "color": INK_2, "linewidth": 0.8},
                            bbox={"boxstyle": "round,pad=0.25", "facecolor": SURFACE, "edgecolor": GRID})
    ax.invert_xaxis()
    ax.set_xlabel("排放上限（占不设上限方案排放的 %）")
    ax.set_ylabel("总成本增幅（%）")
    ax.legend(frameon=False, loc="upper left")
    ax.set_title("减排的成本：碳约束前沿（服务水平 ≥ 98%，期末库存硬约束）")
    settings = results["settings"]
    footer(fig, [f"配置：每个网络 {settings['n_skus']} 个合成 SKU、{settings['weeks']} 周；ε-约束法逐级收紧排放上限；"
                 "只画出有可行方案的上限。成本与排放来自求解结果，合成数据。",
                 f"数据：{source}｜代码版本：{version}｜{MODE_SAVED}"])
    fig.subplots_adjust(left=0.09, right=0.97, top=0.9, bottom=0.2)
    return save(fig, out, "02_carbon_frontier")


def agent_evaluation(out: Path, version: str) -> list[Path]:
    rule_src = "benchmark_results/planning_agent/rule_summary.json"
    llm_src = "benchmark_results/planning_agent/llm_rescored_summary.json"
    rule, llm = load(rule_src)["splits"], load(llm_src)["splits"]
    groups = (("dev", "开发集"), ("holdout", "鲁棒性集"))
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    width = 0.36
    for offset, data, label, color in ((-width / 2 - 0.01, rule, "规则 Agent（离线）", BLUE),
                                       (width / 2 + 0.01, llm, "gpt-6.1-sol（xhigh，运行一次，修复护栏后离线重评）",
                                        ORANGE)):
        rates = [100 * data[g]["success_rate"] for g, _ in groups]
        counts = [round(data[g]["success_rate"] * data[g]["cases"]) for g, _ in groups]
        bars = ax.bar([i + offset for i in range(len(groups))], rates, width, color=color, label=label)
        label_bars(ax, bars, [f"{c}/{data[g]['cases']}" for c, (g, _) in zip(counts, groups, strict=True)])
    ax.set_xticks(range(len(groups)), [f"{name}（{rule[g]['cases']} 题）" for g, name in groups])
    ax.set_ylim(0, 110)
    ax.set_ylabel("成功率（%）")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=1)
    ax.set_title("规划 Agent：24 个计划员问题的评测")
    footer(fig, ["24 题由同一作者编写；成功需工具调用、参数和事实数字都正确且通过数字护栏。模型评测只运行一次；",
                 "用 LangGraph Agent 回放录制运行，每题评分与录制一致（成功 18/24），回放不是新的模型运行。",
                 f"数据：{rule_src}、{llm_src}",
                 f"代码版本：{version}｜{MODE_SAVED}"])
    fig.subplots_adjust(left=0.1, right=0.97, top=0.92, bottom=0.38)
    return save(fig, out, "03_planning_agent_evaluation")


def notice_retrieval(out: Path, version: str) -> list[Path]:
    src = "benchmark_results/notice_retrieval_v1/summary.json"
    full_src = "benchmark_results/notice_retrieval_v1/full_text_lead5_summary.json"
    base, full = load(src)["results"], load(full_src)["results"]
    methods = (("BM25 + 中英术语表（摘录）", base["bm25_glossary"], BLUE),
               ("BM25，不扩展（摘录）", base["bm25_plain"], ORANGE),
               ("BM25 + 术语表 + 本地全文前 5 段", full["bm25_glossary_full_text_lead5"], AQUA),
               ("随机排序（精确期望）", base["random"], YELLOW))
    langs = (("zh", "中文问题（19 条）"), ("en", "英文问题（19 条）"))
    fig, ax = plt.subplots(figsize=(10, 5.4))
    width = 0.19
    for j, (label, data, color) in enumerate(methods):
        values = [100 * data[lang]["hit@1"] for lang, _ in langs]
        xs = [i + (j - 1.5) * (width + 0.015) for i in range(len(langs))]
        bars = ax.bar(xs, values, width, color=color, label=label)
        label_bars(ax, bars, [f"{v:.0f}%" for v in values])
    ax.set_xticks(range(len(langs)), [name for _, name in langs])
    ax.set_ylim(0, 112)
    ax.set_ylabel("第一条结果属于正确事件的比例（%）")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2)
    ax.set_title("真实船公司公告检索：38 个问题、19 个事件分组的开发检查")
    footer(fig, ["语料：仓库中 24 条船公司公告摘录。问题与术语表由同一作者在读过语料后编写，结果偏乐观，不是独立测试。",
                 "全文一项使用本地下载的 15/24 个网页（9 个被网站拒绝），网页不随仓库发布，复算需要同样的页面。",
                 f"数据：{src}、{full_src}",
                 f"代码版本：{version}｜{MODE_SAVED}"])
    fig.subplots_adjust(left=0.09, right=0.98, top=0.92, bottom=0.38)
    return save(fig, out, "04_notice_retrieval")


# ---------------------------------------------------------------------------- the rule-mode example

def run_example(memo_dir: Path) -> dict[str, Any]:
    """Solve the documented example and keep what the memo and the animation need."""
    from planning_agent import workflow
    from planning_agent.tools import Session

    session = Session(memo_dir=memo_dir)
    proposal = workflow.propose_from_rules(workflow.DEMO_NOTICE)
    checked = workflow.preview(proposal, session)
    # The command-line flow asks the planner before this call; the export continues as if "y" was answered.
    outcome = workflow.run(proposal, session, confirmed=True)
    net = session.network(proposal.network)
    plans = {}
    for row, name in zip(outcome.rows, ("正常方案", "扰动方案"), strict=True):
        plan = session.get(row["plan_id"]).plan
        scenario = plan.scenarios[0]
        weeks = net.weeks
        loads = {lane: [0.0] * weeks for lane in net.lanes}
        for (_, s, lane, t), units in plan.solution["ship"].items():
            loads[lane][t] += units * net.skus[s].mass_kg
        capacity = {lane: [scenario.capacity(net.lanes[lane], t + 1)
                           + (plan.solution["reserve"].get(lane, 0.0) if net.lanes[lane].is_air else 0.0)
                           for t in range(weeks)] for lane in net.lanes}
        plans[name] = {"plan_id": row["plan_id"], "scenario": scenario.name,
                       "total_cost_usd": row["total_cost_usd"], "emissions_t": row["emissions_t"],
                       "service_level_pct": row["service_level_pct"], "air_share_pct": row["air_share_pct"],
                       "weekly_departures_kg": {k: [round(v, 1) for v in vals] for k, vals in loads.items()},
                       "weekly_capacity_kg": {k: [round(v, 1) for v in vals] for k, vals in capacity.items()},
                       "end_of_week_inventory_units": [round(float(v), 1)
                                                       for v in plan.solution["inv"][0].sum(axis=0)]}
    return {"notice": proposal.notice, "network": proposal.network, "mode": MODE_EXAMPLE,
            "disruption": proposal.disruptions[0], "evidence": proposal.evidence,
            "assumptions": checked["assumptions"], "plans": plans, "memo_markdown": outcome.memo_text,
            "weeks": net.weeks}


def example_comparison(example: dict[str, Any], out: Path, version: str) -> list[Path]:
    plans = example["plans"]
    names = list(plans)
    metrics = (("total_cost_usd", "总成本（美元）", "{:,.0f}"), ("emissions_t", "排放（吨 CO2e）", "{:.2f}"),
               ("air_share_pct", "空运占比（%）", "{:.1f}%"))
    fig, axes = plt.subplots(1, 3, figsize=(11, 4.6))
    for ax, (key, title, fmt) in zip(axes, metrics, strict=True):
        values = [float(plans[n][key]) for n in names]
        bars = ax.bar(range(2), values, 0.55, color=[BLUE, ORANGE])
        if key == "air_share_pct":
            change = f"{values[1] - values[0]:+.1f} 个百分点"
        else:
            change = f"{100 * (values[1] / values[0] - 1):+.2f}%"
        label_bars(ax, bars, [fmt.format(values[0]), f"{fmt.format(values[1])}（{change}）"])
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.set_xticks(range(2), names)
        ax.set_title(title)
        ax.set_ylim(0, max(values) * 1.18)
    d = example["disruption"]
    fig.suptitle("业务示例：红海绕行公告下的正常方案与扰动方案", fontsize=13, fontweight="bold")
    footer(fig, [f"输入：内置公告（第 {d['start_week']}–{d['end_week']} 周海运延误 {d['extra_lead_weeks']} 周、"
                 f"运力 {d['capacity_change_pct']}%、距离系数 {d['distance_factor']}）；两方案服务水平均为 100%。",
                 "ASML 启发网络，12 个合成 SKU、16 周；数据为合成假设。命令：python -m planning_agent flow",
                 f"代码版本：{version}｜{MODE_EXAMPLE}"])
    fig.subplots_adjust(left=0.06, right=0.98, top=0.82, bottom=0.25, wspace=0.28)
    return save(fig, out, "05_example_plan_comparison")


def example_animation(example: dict[str, Any], out: Path, version: str) -> list[Path]:
    plans = example["plans"]
    weeks = example["weeks"]
    d = example["disruption"]
    lanes = (("NL_ocean", "海运 NL_ocean", BLUE), ("NL_air", "空运 NL_air", ORANGE))
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100)
    grid = fig.add_gridspec(2, 2, height_ratios=(1.25, 1), hspace=0.42, wspace=0.12,
                            left=0.06, right=0.98, top=0.86, bottom=0.17)
    tops = [fig.add_subplot(grid[0, i]) for i in range(2)]
    bottom = fig.add_subplot(grid[1, :])
    peak = max(max(max(plans[n]["weekly_capacity_kg"][lane]) for lane, _, _ in lanes) for n in plans) * 1.12
    peak_inv = max(max(plans[n]["end_of_week_inventory_units"]) for n in plans) * 1.15
    title = fig.suptitle("", fontsize=14, fontweight="bold")
    footer(fig, ["每周发运量与周末在库库存来自业务示例两个方案的求解结果"
                 f"（第 {d['start_week']}–{d['end_week']} 周海运延误 {d['extra_lead_weeks']} 周、"
                 f"运力 {d['capacity_change_pct']}%）；虚线为当周可用运力（空运含预留舱位）。",
                 "ASML 启发网络，12 个合成 SKU、16 周；数据为合成假设，不是企业实测。",
                 f"代码版本：{version}｜{MODE_EXAMPLE}；动画按周逐帧播放保存的求解结果，播放本身不重新求解。"])

    def draw(frame: int) -> None:
        shown = min(frame + 1, weeks)
        x = list(range(1, weeks + 1))
        for ax, name in zip(tops, plans, strict=True):
            ax.clear()
            ax.set_facecolor(SURFACE)
            if name == "扰动方案":
                ax.axvspan(d["start_week"] - 0.5, d["end_week"] + 0.5, color=BAND, zorder=0)
                ax.text(d["start_week"] - 0.4, peak * 0.97, "扰动窗口", fontsize=8, color=INK_2, va="top")
            for j, (lane, label, color) in enumerate(lanes):
                values = plans[name]["weekly_departures_kg"][lane]
                ax.bar([w + (j - 0.5) * 0.4 for w in x[:shown]], values[:shown], 0.38, color=color, label=label)
                ax.step(x, plans[name]["weekly_capacity_kg"][lane], where="mid", color=color, linewidth=1.2,
                        linestyle="--")
            ax.set_xlim(0.5, weeks + 0.5)
            ax.set_ylim(0, peak)
            ax.set_xticks(x)
            ax.set_title(f"{name}：每周发运量（kg）", fontsize=11)
            ax.grid(axis="y", color=GRID)
        tops[0].set_ylabel("发运量（kg/周）")
        tops[0].legend(frameon=False, loc="upper right", fontsize=8)
        bottom.clear()
        bottom.set_facecolor(SURFACE)
        bottom.axvspan(d["start_week"] - 0.5, d["end_week"] + 0.5, color=BAND, zorder=0)
        for name, color in zip(plans, (BLUE, ORANGE), strict=True):
            series = plans[name]["end_of_week_inventory_units"]
            bottom.plot(x[:shown], series[:shown], color=color, linewidth=2, marker="o", markersize=6,
                        markeredgecolor=SURFACE, label=name)
            bottom.annotate(f"{series[shown - 1]:,.0f}", (shown, series[shown - 1]), xytext=(6, 0),
                            textcoords="offset points", fontsize=8, color=INK, va="center")
        bottom.set_xlim(0.5, weeks + 0.5)
        bottom.set_ylim(0, peak_inv)
        bottom.set_xticks(x)
        bottom.set_xlabel("周")
        bottom.set_ylabel("周末在库库存（件）")
        bottom.set_title("周末在库库存（全部 SKU 合计）", fontsize=11)
        bottom.legend(frameon=False, loc="upper right", fontsize=8)
        bottom.grid(axis="y", color=GRID)
        title.set_text(f"红海绕行示例：正常方案与扰动方案的逐周运输和库存　第 {shown} / {weeks} 周")

    frames = weeks + 4  # hold the last week for a moment
    anim = animation.FuncAnimation(fig, draw, frames=frames, interval=600)
    paths = []
    try:
        import imageio_ffmpeg
        plt.rcParams["animation.ffmpeg_path"] = imageio_ffmpeg.get_ffmpeg_exe()
        mp4 = out / "06_example_weekly_flows.mp4"
        anim.save(mp4, writer=animation.FFMpegWriter(fps=1.5, bitrate=2400, extra_args=["-pix_fmt", "yuv420p"]))
        paths.append(mp4)
    except ImportError:
        print("imageio-ffmpeg is not installed: MP4 skipped", file=sys.stderr)
    gif = out / "06_example_weekly_flows_preview.gif"
    anim.save(gif, writer=animation.PillowWriter(fps=1.5), dpi=60)
    paths.append(gif)
    plt.close(fig)
    data = out / "06_example_weekly_flows.json"
    data.write_text(json.dumps({k: example[k] for k in ("mode", "network", "disruption", "weeks", "plans")},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return [*paths, data]


# ---------------------------------------------------------------------------- the memo as HTML and PDF

def markdown_to_html(text: str) -> str:
    """Enough Markdown for the generated memo: headings, bullets, tables, bold and italics."""
    def inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        return re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"<em>\1</em>", s)

    out, rows, items = [], [], []

    def flush() -> None:
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()
        if rows:
            cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows if not re.match(r"^\|[-:| ]+\|$", r)]
            head = "".join(f"<th>{inline(c)}</th>" for c in cells[0])
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in cells[1:])
            out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
            rows.clear()

    for line in text.splitlines():
        if line.startswith("|"):
            rows.append(line)
            continue
        if line.startswith("- "):
            items.append(line[2:])
            continue
        flush()
        if line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h2>{inline(line[2:])}</h2>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    flush()
    return "\n".join(out)


def memo_documents(example: dict[str, Any], out: Path, version: str, browser: str | None) -> list[Path]:
    d = example["disruption"]
    params = "".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>" for k, v in d.items())
    evidence = "".join(f"<li>{html.escape(e['parameter'])} ← “{html.escape(e['text'])}”</li>"
                       for e in example["evidence"])
    assumptions = "".join(f"<li>{html.escape(a)}</li>" for a in example["assumptions"])
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>决策备忘录示例</title>
<style>
body {{ font-family: "Microsoft YaHei", "Noto Sans SC", "PingFang SC", sans-serif; color: {INK};
       background: #ffffff; max-width: 860px; margin: 32px auto; padding: 0 24px; line-height: 1.6; }}
h1 {{ font-size: 22px; margin-bottom: 4px; }} h2 {{ font-size: 17px; margin-top: 26px; }}
.mode {{ display: inline-block; background: #e8f0fb; border: 1px solid {BLUE}; border-radius: 4px;
        padding: 2px 8px; font-size: 13px; }}
.meta, footer {{ color: {INK_2}; font-size: 12px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0; }}
th, td {{ border: 1px solid #d9d8d4; padding: 4px 8px; text-align: left; }}
th {{ background: #f3f2ef; }}
.memo {{ border-top: 2px solid {INK}; margin-top: 28px; }}
</style></head><body>
<h1>决策备忘录示例：红海绕行公告</h1>
<p><span class="mode">{html.escape(MODE_EXAMPLE)}</span></p>
<p class="meta">ASML 启发的备件网络（12 个合成 SKU、16 周）。代码版本 {html.escape(version)}。
复现命令：<code>python -m planning_agent flow</code>（命令行在求解前请计划员确认）。</p>
<h2>1. 输入公告</h2><p>{html.escape(example["notice"])}</p>
<h2>2. 解析出的扰动参数</h2><table><thead><tr><th>参数</th><th>取值</th></tr></thead><tbody>{params}</tbody></table>
<p>每个参数对应的公告原文：</p><ul>{evidence}</ul>
<p>默认假设（公告没有给出的参数）：</p><ul>{assumptions}</ul>
<h2>3. 确认</h2><p>交互运行时，命令行和网页在求解前都要求计划员确认参数；确认之前不做任何求解。
本文件由导出脚本生成，在确认步骤按“确认”继续（相当于在命令行提示处回答 y）。</p>
<h2>4. 优化结果与备忘录</h2>
<p>以下内容由 planning_agent 根据 HiGHS 求解结果自动生成，表中数字均直接取自求解结果。</p>
<div class="memo">{markdown_to_html(example["memo_markdown"])}</div>
<footer><p>限制：SKU、承诺需求、运力、费率和扰动幅度为合成情景假设；距离与排放因子来自公开来源。结果用于比较策略，
不代表企业实测，也不代表真实业务验证。</p></footer>
</body></html>
"""
    page_path = out / "07_example_decision_memo.html"
    page_path.write_text(page, encoding="utf-8", newline="\n")
    paths = [page_path]
    if browser:
        pdf = out / "07_example_decision_memo.pdf"
        # A throwaway profile keeps a running browser from absorbing the headless call.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
            subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
                            "--no-pdf-header-footer", f"--print-to-pdf={pdf.resolve()}",
                            page_path.resolve().as_uri()], check=True, capture_output=True, timeout=120)
        if pdf.exists():
            paths.append(pdf)
        else:
            print("the browser did not write the PDF memo", file=sys.stderr)
    else:
        print("no Chromium-based browser found: PDF memo skipped", file=sys.stderr)
    return paths


def find_browser() -> str | None:
    candidates = [shutil.which(n) for n in ("msedge", "google-chrome", "chromium", "chromium-browser", "chrome")]
    candidates += [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                   r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                   r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
    return next((c for c in candidates if c and Path(c).exists()), None)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("artifacts/share"))
    parser.add_argument("--browser", help="Chromium-based browser for the PDF memo (default: search)")
    args = parser.parse_args(argv)
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    font = setup_fonts()
    version = code_version()
    files = []
    files += disruption_impact(out, version)
    files += carbon_frontier(out, version)
    files += agent_evaluation(out, version)
    files += notice_retrieval(out, version)
    example = run_example(out / "_memo")
    files += example_comparison(example, out, version)
    files += example_animation(example, out, version)
    files += memo_documents(example, out, version, args.browser or find_browser())
    shutil.rmtree(out / "_memo", ignore_errors=True)
    manifest = {"code_version": version, "font": font, "command": "python scripts/export_presentation.py",
                "files": [{"name": f.name, "bytes": f.stat().st_size, "sha256": sha256(f)} for f in files]}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                                       newline="\n")
    for f in files:
        print(f"wrote {f.name} ({f.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
