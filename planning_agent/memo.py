"""Decision memo writer: every number comes from stored plans, never from the language model.

Single-scenario plans and expected-value (multi-scenario) plans are reported
in separate tables: an expected cost over scenarios is not comparable with
the cost of one scenario, so "cheapest" is only judged within each group.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from network_planning.analysis import explain_plan


def write_memo(session, stored_plans: list, question: str, title: str | None = None) -> tuple[Path, str]:
    single = [p for p in stored_plans if p.plan.feasible and len(p.plan.scenarios) == 1]
    expected = [p for p in stored_plans if p.plan.feasible and len(p.plan.scenarios) > 1]
    infeasible = [p for p in stored_plans if not p.plan.feasible]
    lines = [f"# {title or '物流方案决策备忘录'}", "", f"**问题**：{question}", "", "## 结论", ""]
    headline = []
    if single:
        cheapest = min(single, key=lambda p: p.plan.kpis["total_cost_usd"])
        cleanest = min(single, key=lambda p: p.plan.kpis["emissions_t"])
        lines += [f"- 单一场景方案中成本最低：{cheapest.id}（{cheapest.label}），"
                  f"{cheapest.plan.kpis['total_cost_usd']:,.0f} 美元。",
                  f"- 单一场景方案中排放最低：{cleanest.id}（{cleanest.label}），"
                  f"{cleanest.plan.kpis['emissions_t']:.2f} 吨 CO2e。"]
        headline.append(f"lowest-cost single-scenario plan {cheapest.id}")
    stochastic = next((p for p in expected if p.request.get("fixed_first_stage") != "nominal"), None)
    nominal = next((p for p in expected if p.request.get("fixed_first_stage") == "nominal"), None)
    if stochastic and nominal:
        vss = nominal.plan.kpis["total_cost_usd"] - stochastic.plan.kpis["total_cost_usd"]
        lines.append(f"- 对冲：两阶段随机方案 {stochastic.id} 的期望成本 {stochastic.plan.kpis['total_cost_usd']:,.0f} 美元，"
                     f"按名义预测计划再应变（{nominal.id}）为 {nominal.plan.kpis['total_cost_usd']:,.0f} 美元，"
                     f"差额（VSS）{vss:,.0f} 美元。")
        headline.append(f"VSS {vss:,.0f} USD")
    if infeasible:
        lines.append("- 不可行方案：" + "、".join(f"{p.id}（{p.label}）" for p in infeasible) + "。")
    if single:
        base = single[0]
        lines += ["", "## 单一场景方案对比", "", f"以 {base.id}（{base.label}）为基准。", "",
                  "| 方案 | 说明 | 总成本 USD | 变化 | 排放 t | 变化 | 空运占比 | 服务水平 |",
                  "|---|---|---:|---:|---:|---:|---:|---:|"]
        for p in single:
            k, b = p.plan.kpis, base.plan.kpis
            lines.append(f"| {p.id} | {p.label} | {k['total_cost_usd']:,.0f} | "
                         f"{100 * (k['total_cost_usd'] / b['total_cost_usd'] - 1):+.2f}% | {k['emissions_t']:.2f} | "
                         f"{100 * (k['emissions_t'] / b['emissions_t'] - 1):+.2f}% | {100 * k['air_share_kg']:.1f}% | "
                         f"{100 * k['service_level']:.2f}% |")
    if expected:
        names = expected[0].plan.scenario_names
        lines += ["", "## 对冲方案（按场景概率加权的期望值）", "",
                  "| 方案 | 说明 | 期望成本 USD | 期望排放 t | " + " | ".join(f"{n} 成本 USD" for n in names) + " |",
                  "|---|---|---:|---:|" + "---:|" * len(names)]
        for p in expected:
            costs = " | ".join(f"{p.plan.per_scenario[n]['total_cost_usd']:,.0f}" for n in names)
            lines.append(f"| {p.id} | {p.label} | {p.plan.kpis['total_cost_usd']:,.0f} | "
                         f"{p.plan.kpis['emissions_t']:.2f} | {costs} |")
        probabilities = "，".join(f"{s.name} {100 * s.probability:.0f}%" for s in expected[0].plan.scenarios)
        lines.append(f"\n场景概率：{probabilities}。")
    lines += ["", "## 驱动因素", ""]
    for p in single + expected:
        info = explain_plan(session.network(p.network), p.plan)
        drivers = "，".join(f"{d['item']} {100 * d['share']:.1f}%" for d in info["cost_drivers"][:3])
        binding = "，".join(f"{b['lane']} 第 {b['week']} 周" for b in info["binding_capacity"][:3]) or "无"
        reserve = "，".join(f"{l} {kg:g} kg/周" for l, kg in info["air_reservation_kg_per_week"].items()) or "无"
        lines.append(f"- **{p.id}**（{info['scenario']} 场景）：成本构成 {drivers}；接近满载 {binding}；空运舱位预留 {reserve}。")
    lines += ["", "## 假设与局限", "",
              "- SKU、承诺需求、运力、费率和扰动幅度为合成情景假设；距离与排放因子来自公开来源（见 data_sources/）。",
              "- 优化为期望成本最小（风险中性），需求为已知承诺订单；结果用于比较策略，不代表企业实测。",
              f"- 求解器 HiGHS，相对 MIP gap ≤ {100 * session.mip_gap:.1f}%。", "",
              "*由 planning_agent 根据优化结果自动生成；表中数字均直接取自求解结果。*", ""]
    digest = hashlib.sha256((question + "|".join(p.id for p in stored_plans)).encode("utf-8")).hexdigest()[:10]
    path = Path(session.memo_dir) / f"memo-{digest}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path, "; ".join(headline) or "no feasible plan"
