"""Run every analysis and write the evidence bundle plus a bilingual Markdown report."""
from __future__ import annotations

import csv
import hashlib
import json
import platform
from importlib import metadata
from pathlib import Path

from .analysis import (
    SCALE_VARIANTS,
    carbon_frontier,
    carbon_price_sweep,
    explain_plan,
    scale_benchmark,
    scenario_impact,
    stochastic_value,
)
from .data import CONFIG, NETWORKS, ROOT, build_network
from .model import solve

PRICES = (0, 50, 100, 200, 400, 800, 1600, 3200, 6400)
QUICK_SCALE = (("continuous_flows", {}, (10, 25)), ("integer_units", {"integer_shipments": True}, (10,)))


def run(output: Path, *, n_skus: int = 12, weeks: int = 16, seed: int = 7, quick: bool = False) -> dict:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    results = {"settings": {"n_skus": n_skus, "weeks": weeks, "seed": seed, "quick": quick,
                            "mip_gap": 1e-3, "reveal_week": 3, "frontier_service_level": 0.98},
               "networks": {}}
    for name in NETWORKS:
        net = build_network(name, n_skus, weeks, seed)
        stochastic = stochastic_value(net, reveal_week=3)
        plans = stochastic.pop("plans")
        results["networks"][name] = {
            "description": net.describe(),
            "scenario_impact": scenario_impact(net),
            "frontier": carbon_frontier(net, levels=(0.9, 0.75, 0.6) if quick else (0.9, 0.8, 0.75, 0.7, 0.6, 0.5, 0.4)),
            "price_sweep": carbon_price_sweep(net, prices=(0, 400) if quick else PRICES),
            "stochastic": stochastic,
            "stochastic_plan_explained": explain_plan(net, plans["stochastic"], "normal"),
            "integrality": _integrality(net),
        }
    results["scale"] = scale_benchmark("asml", QUICK_SCALE if quick else SCALE_VARIANTS)
    _write(output, results)
    return results


def _integrality(net) -> list[dict]:
    """Objective and time with integer versus continuous shipment units."""
    rows = []
    base = solve(net, service_level=0.98, terminal_hard=True)
    cases = (("uncapped", {"service_level": 0.98, "terminal_hard": True}),
             ("cap_60pct", {"service_level": 0.98, "terminal_hard": True,
                            "carbon_cap_kg": 0.6 * base.kpis["emissions_t"] * 1000}),
             ("stochastic", {"scenarios": net.scenarios(), "reveal_week": 3}))
    for label, options in cases:
        continuous = solve(net, **options)
        integer = solve(net, integer_shipments=True, **options)
        rows.append({"case": label, "continuous_usd": round(continuous.objective, 2),
                     "integer_usd": round(integer.objective, 2),
                     "integer_premium_pct": round(100 * (integer.objective / continuous.objective - 1), 4),
                     "continuous_seconds": continuous.stats["solve_seconds"],
                     "integer_seconds": integer.stats["solve_seconds"], "integer_status": integer.status})
    return rows


def _write(output: Path, results: dict) -> None:
    (output / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=_json),
                                         encoding="utf-8", newline="\n")
    tables = {"scenario_impact.csv": [], "frontier.csv": [], "price_sweep.csv": [], "integrality.csv": []}
    for name, block in results["networks"].items():
        tables["scenario_impact.csv"] += [{"network": name, **row} for row in block["scenario_impact"]]
        tables["frontier.csv"] += [{"network": name, **row} for row in block["frontier"]["points"]]
        tables["price_sweep.csv"] += [{"network": name, **row} for row in block["price_sweep"]]
        tables["integrality.csv"] += [{"network": name, **row} for row in block["integrality"]]
    tables["scale.csv"] = results["scale"]
    for filename, rows in tables.items():
        _csv(output / filename, rows)
    _figures(output, results)
    (output / "report.md").write_text(_markdown(results), encoding="utf-8", newline="\n")
    files = sorted(p.name for p in output.iterdir() if p.is_file() and p.name != "manifest.json")
    manifest = {
        "command": "python -m network_planning report --output " + output.as_posix(),
        "settings": results["settings"],
        "inputs": {path: _sha256(ROOT / path) for path in (
            "network_planning/config.json", "asml/config.json", "marvell/config.json",
            "data_sources/selected_emission_factors.json")},
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    **{pkg: _version(pkg) for pkg in ("pulp", "highspy", "numpy")}},
        "outputs": {name: _sha256(output / name) for name in files},
        "data_note": CONFIG["description"],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8",
                                          newline="\n")


def _figures(output: Path, results: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, (name, block) in zip(axes, results["networks"].items(), strict=False):
        frontier = block["frontier"]
        e0, c0 = frontier["baseline_emissions_t"], frontier["baseline_cost_usd"]
        pts = [p for p in frontier["points"] if p.get("total_cost_usd") is not None]
        ax.plot([100 * (1 - p["emissions_t"] / e0) for p in pts],
                [100 * (p["total_cost_usd"] / c0 - 1) for p in pts], marker="o", color="#2a6f97")
        for p in pts[1:]:
            if p.get("mac_vs_baseline_usd_per_t"):
                ax.annotate(f"${p['mac_vs_baseline_usd_per_t']:,.0f}/t",
                            (100 * (1 - p["emissions_t"] / e0), 100 * (p["total_cost_usd"] / c0 - 1)),
                            textcoords="offset points", xytext=(4, -10), fontsize=7)
        ax.set_title(f"{name}: cost of cutting CO2e (service >= 98%)", fontsize=10)
        ax.set_xlabel("emission reduction vs cost-optimal plan (%)")
        ax.set_ylabel("logistics cost increase (%)")
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output / "frontier.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 4))
    for name, block in results["networks"].items():
        rows = [r for r in block["price_sweep"] if r.get("emissions_t") is not None]
        e0 = rows[0]["emissions_t"]
        ax.plot([max(r["carbon_price_usd_per_t"], 10) for r in rows],
                [100 * (1 - r["emissions_t"] / e0) for r in rows], marker="o", label=name)
    ax.set_xscale("log")
    ax.axvspan(60, 100, color="#f4a261", alpha=0.3, label="EU ETS order of magnitude")
    ax.set_xlabel("carbon price (USD/t CO2e, log scale; 0 drawn at 10)")
    ax.set_ylabel("emission reduction (%)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output / "price_sweep.png", dpi=150)
    plt.close(fig)


def _markdown(results: dict) -> str:
    s = results["settings"]
    lines = ["# 网络规划引擎实验报告 / Network planning engine report", "",
             "本文提供中英文版本，中文在前，英文在后。",
             "This report is available in Chinese and English; the English summary follows the Chinese text.", "",
             "## 中文", "",
             f"设置：每个网络 {s['n_skus']} 个合成 SKU、{s['weeks']} 周、种子 {s['seed']}；HiGHS 相对 MIP gap ≤ "
             f"{s['mip_gap']:.1%}；随机规划在第 {s['reveal_week']} 周揭示扰动。发货量为连续流量，线路周启用为 0/1 变量；"
             "整数发货对照见“整数性代价”。距离、排放因子来自仓库已有来源；SKU、需求、容量、费率和扰动幅度均为情景假设。", ""]
    for name, block in results["networks"].items():
        d, st, fr = block["description"], block["stochastic"], block["frontier"]
        lines += [f"### {name}：{d['label']}", "",
                  f"{d['skus']} 个 SKU，承诺需求 {d['demand_units']:,} 件 / {d['demand_kg']:,.0f} kg；"
                  f"价值密度 {d['value_density_usd_per_kg'][0]:,}–{d['value_density_usd_per_kg'][1]:,} USD/kg。", "",
                  "**扰动影响（各场景按完全信息重新规划）**", "",
                  "| 场景 | 总成本 USD | 成本变化 | 排放 t | 空运占比 | 服务水平 |", "|---|---:|---:|---:|---:|---:|"]
        for r in block["scenario_impact"]:
            lines.append(f"| {r['scenario']} | {r.get('total_cost_usd', float('nan')):,.0f} | "
                         f"{r.get('cost_change_pct', 0):+.2f}% | {r.get('emissions_t', float('nan')):.2f} | "
                         f"{r.get('air_share_kg', 0):.1%} | {r.get('service_level', 0):.2%} |")
        lines += ["", "**碳约束前沿（服务水平 ≥ 98%，期末库存硬约束）**", "",
                  "| 排放上限 | 状态 | 成本增幅 | 排放 t | 空运占比 | 平均边际减排成本 USD/t | 分段 USD/t | LP 影子价格 USD/t |",
                  "|---:|---|---:|---:|---:|---:|---:|---:|"]
        for p in fr["points"]:
            lines.append(f"| {p['level']:.0%} | {p['status']} | {_pct(p.get('cost_increase_pct'))} | "
                         f"{_num(p.get('emissions_t'), 2)} | {_share(p.get('air_share_kg'))} | "
                         f"{_num(p.get('mac_vs_baseline_usd_per_t'), 0)} | {_num(p.get('mac_step_usd_per_t'), 0)} | "
                         f"{_num(p.get('shadow_price_usd_per_t'), 0)} |")
        lines += ["", f"在该服务水平下，最低可达排放 {_num(fr.get('min_emissions_t'), 2)} t"
                      f"（比成本最优方案低 {_num(fr.get('max_reduction_pct'), 1)}%）。", "",
                  "**碳价扫描**：" + "；".join(
                      f"{r['carbon_price_usd_per_t']} USD/t → {_num(r.get('emissions_t'), 2)} t"
                      for r in block["price_sweep"]), "",
                  "**两阶段随机规划**（第 3 周前的发货与空运舱位预留须在不知道场景时决定）", "",
                  "- 场景与概率：" + "，".join(f"{x['name']} {x['probability']:.0%}" for x in st["scenarios"]),
                  f"- RP（随机规划期望成本）{st['RP']:,.0f}；EEV（按名义场景计划再应变）{st['EEV']:,.0f}；"
                  f"WS（完全信息）{st['WS']:,.0f} USD",
                  f"- VSS = {st['VSS']:,.0f} USD（{st['VSS_pct_of_RP']:.2f}%），考虑 MIP gap 的区间 "
                  f"[{st['VSS_interval'][0]:,.0f}, {st['VSS_interval'][1]:,.0f}]",
                  f"- EVPI = {st['EVPI']:,.0f} USD（{st['EVPI_pct_of_RP']:.2f}%），区间 "
                  f"[{st['EVPI_interval'][0]:,.0f}, {st['EVPI_interval'][1]:,.0f}]", "",
                  "| 场景 | 概率 | 随机方案 USD | 名义方案 USD | 完全信息 USD |", "|---|---:|---:|---:|---:|"]
        for sc, v in st["per_scenario"].items():
            lines.append(f"| {sc} | {v['probability']:.0%} | {v['stochastic_plan_usd']:,.0f} | "
                         f"{v['nominal_plan_usd']:,.0f} | {v['perfect_information_usd']:,.0f} |")
        fs = st["first_stage"]
        lines += ["", f"第一阶段差异：空运舱位预留（kg/周）随机方案 {_pairs(fs['stochastic']['air_reservation_kg_per_week'])}，"
                      f"名义方案 {_pairs(fs['nominal']['air_reservation_kg_per_week'])}；揭示前发货（kg）随机方案 "
                      f"{_pairs(fs['stochastic']['early_shipments_kg'])}，名义方案 {_pairs(fs['nominal']['early_shipments_kg'])}。", "",
                  "**整数性代价**", "", "| 情形 | 连续 USD | 整数 USD | 整数溢价 | 连续 s | 整数 s |",
                  "|---|---:|---:|---:|---:|---:|"]
        for r in block["integrality"]:
            lines.append(f"| {r['case']} | {r['continuous_usd']:,.0f} | {r['integer_usd']:,.0f} | "
                         f"{r['integer_premium_pct']:+.3f}% | {r['continuous_seconds']:.2f} | {r['integer_seconds']:.2f} |")
        lines.append("")
    lines += ["### 规模测试（ASML 网络，16 周，单场景）", "",
              "| 变体 | SKU | 变量 | 整数变量 | 约束 | 建模 s | 求解 s | 状态 | gap |", "|---|---:|---:|---:|---:|---:|---:|---|---:|"]
    for r in results["scale"]:
        lines.append(f"| {r['variant']} | {r['skus']} | {r['variables']:,} | {r['integer_variables']:,} | "
                     f"{r['constraints']:,} | {r['build_seconds']:.2f} | {r['solve_seconds']:.2f} | {r['status']} | "
                     f"{_num(r['mip_gap'], 4)} |")
    lines += ["", "![碳约束前沿](frontier.png)", "", "![碳价扫描](price_sweep.png)", "",
              "### 局限", "",
              "- 需求为已知承诺订单；不确定性只来自离散扰动场景，没有连续需求分布。",
              "- 风险中性（期望成本）；未建模 CVaR 等尾部风险偏好。",
              "- 单一目的仓（新加坡）；未做多仓选址。容量、费率和扰动幅度为情景假设，不代表企业实测。", "",
              "## English", "",
              f"Setting: {s['n_skus']} synthetic SKUs per network, {s['weeks']} weeks, seed {s['seed']}, HiGHS relative "
              f"MIP gap <= {s['mip_gap']:.1%}, disruptions revealed in week {s['reveal_week']}. Shipments are continuous "
              "flows with binary lane-week activations; the integrality table compares integer units. Distances and "
              "emission factors reuse the repository's sourced inputs; SKUs, demand, capacities, rates and disruption "
              "magnitudes are scenario assumptions.", ""]
    for name, block in results["networks"].items():
        st, fr = block["stochastic"], block["frontier"]
        pts = [p for p in fr["points"] if p.get("mac_vs_baseline_usd_per_t")]
        lines.append(f"- **{name}**: cost-optimal plan {fr['baseline_cost_usd']:,.0f} USD and "
                     f"{fr['baseline_emissions_t']:.2f} t CO2e. Average marginal abatement cost ranges from "
                     f"{min(p['mac_vs_baseline_usd_per_t'] for p in pts):,.0f} to "
                     f"{max(p['mac_vs_baseline_usd_per_t'] for p in pts):,.0f} USD/t across the tested caps; the "
                     f"minimum feasible emissions at 98% service are {_num(fr.get('min_emissions_t'), 2)} t. "
                     f"Two-stage plan: VSS {st['VSS']:,.0f} USD ({st['VSS_pct_of_RP']:.2f}% of RP, gap-aware interval "
                     f"{st['VSS_interval']}), EVPI {st['EVPI']:,.0f} USD ({st['EVPI_pct_of_RP']:.2f}%).")
    lines += ["", "Limitations: known committed demand, discrete disruption scenarios, risk-neutral objective, single "
                  "destination warehouse, synthetic parameters. Results compare policies under stated assumptions and "
                  "are not company measurements.", ""]
    return "\n".join(lines)


def _csv(path: Path, rows: list[dict]) -> None:
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def _json(value):
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (set, tuple)):
        return list(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def _pairs(mapping: dict) -> str:
    return "、".join(f"{key} {value:,.1f}" for key, value in mapping.items()) or "无"


def _num(value, digits):
    return "–" if value is None else f"{value:,.{digits}f}"


def _pct(value):
    return "–" if value is None else f"{value:+.2f}%"


def _share(value):
    return "–" if value is None else f"{value:.1%}"
