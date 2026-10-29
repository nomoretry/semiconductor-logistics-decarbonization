"""Generate the Markdown study report, paired tables, and Matplotlib figures."""

import argparse
import csv
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.experiments import ROOT, summarize, write_json

CASES = {
    "normal": "正常运输",
    "ocean_delay": "已公告运输延误",
    "capacity_restriction": "已公告容量限制",
}
POLICIES = {
    "cost_only": "成本最优参照",
    "fast_only": "仅空运",
    "slow_only": "仅海运／公路",
    "carbon_minus10": "碳预算−10%",
    "carbon_minus25": "碳预算−25%",
    "carbon_minus50": "碳预算−50%",
}
TRADEOFF_FIELDS = [
    "project", "case", "n", "cost_reference", "cost_budget25",
    "emissions_reference", "emissions_budget25", "cost_increase_pct",
    "emissions_reduction_pct", "cost_increase_ci95", "emissions_reduction_ci95",
]


def synthetic_rows(rows):
    """Keep the published weekly experiment separate from external demand."""
    return [row for row in rows if row["demand_set"] == "synthetic_weekly"]


def paired_tradeoffs(rows, bootstrap_samples=10_000):
    """Compare feasible 25% budgets with the same project/case/seed baseline."""
    rows = synthetic_rows(rows)
    rng = np.random.default_rng(20261030)
    comparisons = []
    for project in sorted({row["project"] for row in rows}):
        for case in CASES:
            group = [row for row in rows
                     if row["project"] == project and row["case"] == case]
            base = {row["seed"]: row for row in group
                    if row["policy"] == "cost_only" and row["feasible"]}
            target = sorted(
                (row for row in group if row["policy"] == "carbon_minus25"
                 and row["feasible"] and row["seed"] in base),
                key=lambda row: row["seed"],
            )
            if not target:
                continue
            c0 = np.array([base[row["seed"]]["total_cost"] for row in target])
            c1 = np.array([row["total_cost"] for row in target])
            e0 = np.array([base[row["seed"]]["total_emissions"] for row in target])
            e1 = np.array([row["total_emissions"] for row in target])
            indices = rng.integers(0, len(target), size=(bootstrap_samples, len(target)))
            cost_boot = 100 * (c1[indices].mean(axis=1) / c0[indices].mean(axis=1) - 1)
            emissions_boot = 100 * (1 - e1[indices].mean(axis=1) / e0[indices].mean(axis=1))
            comparisons.append(dict(
                project=project, case=case, n=len(target),
                cost_reference=float(c0.mean()), cost_budget25=float(c1.mean()),
                emissions_reference=float(e0.mean()), emissions_budget25=float(e1.mean()),
                cost_increase_pct=float(100 * (c1.mean() / c0.mean() - 1)),
                emissions_reduction_pct=float(100 * (1 - e1.mean() / e0.mean())),
                cost_increase_ci95=np.percentile(cost_boot, [2.5, 97.5]).tolist(),
                emissions_reduction_ci95=np.percentile(emissions_boot, [2.5, 97.5]).tolist(),
            ))
    return comparisons


def create_frontier_plot(rows, report_dir):
    """Plot only seeds feasible at every point on each cost-carbon frontier."""
    rows = synthetic_rows(rows)
    projects = sorted({row["project"] for row in rows})
    if not projects:
        raise ValueError("The report needs at least one synthetic weekly episode")
    plt.rcParams.update({
        "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
        "figure.facecolor": "#ffffff",
    })
    fig, axes = plt.subplots(1, len(projects), figsize=(6 * len(projects), 4.4), squeeze=False)
    counts = []
    try:
        for ax, project in zip(axes[0], projects):
            for case, color in zip(CASES, ["#126782", "#d97706", "#7c3aed"]):
                group = [row for row in rows
                         if row["project"] == project and row["case"] == case]
                policies = ["cost_only", "carbon_minus10", "carbon_minus25", "carbon_minus50"]
                maps = {policy: {row["seed"]: row for row in group
                                 if row["policy"] == policy and row["feasible"]}
                        for policy in policies}
                paired = sorted(set.intersection(*(set(maps[policy]) for policy in policies)))
                counts.append((project, case, len(paired)))
                if not paired:
                    continue
                c0 = np.mean([maps["cost_only"][seed]["total_cost"] for seed in paired])
                e0 = np.mean([maps["cost_only"][seed]["total_emissions"] for seed in paired])
                xs, ys = [], []
                for policy in policies:
                    cost = np.mean([maps[policy][seed]["total_cost"] for seed in paired])
                    emissions = np.mean([maps[policy][seed]["total_emissions"] for seed in paired])
                    xs.append(100 * (1 - emissions / e0))
                    ys.append(100 * (cost / c0 - 1))
                label = {"normal": "Normal", "ocean_delay": "Announced delay",
                         "capacity_restriction": "Announced capacity"}[case]
                ax.plot(xs, ys, "o-", color=color, label=f"{label} (paired n={len(paired)})",
                        linewidth=2, markersize=5)
            ax.set_title(project.upper() + "-inspired simulation", loc="left", fontweight="bold")
            ax.set_xlabel("Logistics emissions reduction vs cost-only (%)")
            ax.set_ylabel("Planning cost increase (%)")
            ax.grid(alpha=.18)
            if ax.lines:
                ax.legend(fontsize=8, loc="upper left")
        fig.suptitle("Cost-carbon trade-offs with identical service and terminal stock",
                     fontsize=13, fontweight="bold")
        fig.tight_layout(rect=(0, 0, 1, .94))
        fig.savefig(report_dir / "cost_carbon_frontier.png", dpi=180)
        fig.savefig(report_dir / "cost_carbon_frontier.svg")
    finally:
        plt.close(fig)
    return counts


def number(value):
    return "—" if value is None else f"{value:,.2f}"


def markdown_table(headers, rows):
    def line(values):
        return "| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |"
    return "\n".join([line(headers), line(["---"] * len(headers)), *(line(row) for row in rows)])


def render_report(rows, archived_summary, manifest, pilot, comparisons, frontier_counts,
                  sensitivity_count):
    """Render populations explicitly; archived monthly means are never paired."""
    weekly = synthetic_rows(rows)
    summaries = summarize(weekly)
    projects = sorted({row["project"] for row in weekly})
    feasible = sum(row["feasible"] for row in weekly)
    optimal = sum(row["optimal"] for row in weekly)
    external = [row for row in archived_summary if row["demand_set"] == "real_carparts_monthly"]
    archived_n = sum(row["n"] for row in archived_summary)
    external_n = sum(row["n"] for row in external)
    external_detail_n = sum(row["demand_set"] == "real_carparts_monthly" for row in rows)
    cost_range = [row["cost_increase_pct"] for row in comparisons]
    if cost_range:
        finding = (f"25%物流碳预算在{len(comparisons)}组配对情景中均有可行结果，"
                   f"成本均值增幅为{min(cost_range):.2f}%–{max(cost_range):.2f}%。")
    else:
        finding = "当前结果中没有可供比较的25%碳预算配对样本。"
    main_table = markdown_table(
        ["项目", "情景", "配对数", "参照成本 USD", "碳预算成本 USD", "成本增幅",
         "参照排放 kgCO₂e", "碳预算排放 kgCO₂e", "排放降幅"],
        [[row["project"].upper(), CASES[row["case"]], row["n"], number(row["cost_reference"]),
          number(row["cost_budget25"]), f"{row['cost_increase_pct']:+.2f}%",
          number(row["emissions_reference"]), number(row["emissions_budget25"]),
          f"{row['emissions_reduction_pct']:.2f}%"] for row in comparisons],
    )
    policy_tables = []
    for project in projects:
        table = markdown_table(
            ["情景", "策略", "可行/总数", "可行均值成本 USD", "可行均值 kgCO₂e", "空运质量占比"],
            [[CASES[row["case"]], POLICIES[row["policy"]], f"{row['feasible_n']}/{row['n']}",
              number(row["total_cost"]), number(row["total_emissions"]),
              "—" if row["air_mass_share"] is None else f"{100 * row['air_mass_share']:.2f}%"]
             for row in summaries if row["project"] == project],
        )
        policy_tables.append(f"### {project.upper()}\n\n{table}")
    frontier_table = markdown_table(
        ["项目", *CASES.values()],
        [[project.upper(), *(next(n for p, c, n in frontier_counts if p == project and c == case)
                               for case in CASES)] for project in projects],
    )
    analogue_table = markdown_table(
        ["项目", "策略", "可行/总数", "可行均值成本 USD", "可行均值 kgCO₂e"],
        [[row["project"].upper(), POLICIES[row["policy"]], f"{row['feasible_n']}/{row['n']}",
          number(row["total_cost"]), number(row["total_emissions"])] for row in external],
    )
    replay_rows = []
    replays = pilot["numerical_replays"]
    for project in projects:
        for method, label in [
            ("correct_structured_input", "人工正确结构化输入＋优化器"),
            ("saved_LLM_extraction", "保存的会话内LLM抽取＋优化器"),
            ("ignore_notice", "忽略公告、沿用旧参数"),
        ]:
            group = [row for row in replays if row["project"] == project and row["method"] == method]
            count = sum(row.get("all_constraints_satisfied", False) for row in group)
            replay_rows.append([project.upper(), label, f"{count}/{len(group)}"])
    replay_table = markdown_table(["项目", "信息处理组", "全部约束满足"], replay_rows)
    instance_count = len({(row["project"], row["case"], row["seed"]) for row in replays})
    policies = "\n\n".join(policy_tables)
    return f"""# 低碳半导体物流：库存与运输联合优化

{finding}比较使用同一订单簿、逐期零积压和共同终端库存要求。企业背景来自公开资料，SKU、需求、价格和容量采用情景假设；结果用于分析物流规划权衡，不代表企业经营数据。

## 实验范围与数据口径

- **当前合成实验明细**：`episodes.json`含{len(weekly)}次周度求解，其中{feasible}次可行、{optimal}次达到设定最优间隙，{len(weekly) - feasible}次不可行。下文主表、全部策略表与前沿图均由这些明细计算。
- **归档汇总**：`summary.json`合计{archived_n}次求解，`run_manifest.json`记录{manifest['total_solves']}次；其中{external_n}次来自汽车备件月度需求压力测试。该部分单独列出，不计入合成实验配对结果。当前明细含{external_detail_n}条外部月度求解记录；公开导出不含这些需求序列或所选序列ID。
- **独立实验**：参数敏感性保存{sensitivity_count}条求解记录；通知输入试验保存{instance_count}个场景的{len(replays)}条重放记录。它们不计入上述主实验样本量。

模型面向完整承诺订单簿与已公告扰动：各策略知道相同订单，不涉及未知需求预测或在线控制。两个网络均以新加坡为仓储终点：ASML背景为荷兰供货池的空／海运；Marvell背景为台湾OSAT供货池的空／海运和马来西亚供货池的空运／公路。具体网络及商业参数见[项目配置](../asml/config.json)与[Marvell配置](../marvell/config.json)。数据适配过程见[ASML审计](../data_sources/data_audit_asml.md)和[Marvell审计](../data_sources/data_audit_marvell.md)。

## 同服务水平下的25%碳预算结果

各项目4类SKU、16个周度期间，种子100–109。每期期末积压为0，终端库存不低于各策略共同的初始库存。每行只比较同项目、同情景、同种子的可行方案。成本增幅为“预算组成本均值／参照组成本均值−1”；排放降幅为“1−预算组排放均值／参照组排放均值”。

{main_table}

![相同服务和终端库存要求下的成本—排放前沿](cost_carbon_frontier.png)

图中各条前沿使用在0%、10%、25%、50%预算收紧下均可行的共同种子，其样本数为：

{frontier_table}

因此，前沿图与25%主表可能采用不同样本。配对bootstrap的95%区间保存在[JSON](paired_tradeoffs.json)，完整精度另见[CSV](paired_tradeoffs.csv)。区间只反映订单簿抽样差异，不覆盖成本参数或模型结构的不确定性。

## 规划与碳核算

净库存按“上期净库存＋初始在途到货＋以前派发而本期到货−本期需求”递推。发货量为整数，到货期由派发时生效的提前期决定。SKU受路线资格限制，同一供货池的运输方式共享释放容量。

目标最小化运费、在途资金占用及到仓后资金与仓储成本。碳预算约束运输及库存相关仓储排放；质量由kg除以1000转为吨，再乘距离km与模式因子。空运、集装箱船和普通柴油货车的因子分别为0.66646、0.01977、0.12715 kgCO₂e／吨·km，包含相应燃料WTT。航空因子已含8%距离修正，代码不重复加成。仓储边际因子假设为0.04 kgCO₂e／单位·周，另测试0与5倍取值。

ASML海运基准使用历史苏伊士距离15,349km，扰动改用绕好望角约21,770km并额外增加2周；航空使用公开机场坐标的大圆距离。Marvell台湾海路4,000km与马来西亚公路400km为假设。模型不含货损、制造／封测工艺及产品隐含碳。排放因子原始行与组合方式见[因子记录](../data_sources/selected_emission_factors.json)。

## 全部策略与不可行性

固定运输模式的参照仍优化发货与库存。不可行结果保持空值；下表均值仅使用可行实例，样本数不同的行不能直接作为全样本成本比较。

{policies}

## 外部月度需求：归档压力测试

Monash Car Parts提供汽车备件月度需求，原始数据有2,674条、每条51个月。从无缺失且前39个月足够活跃的序列中选择40条，构成10组4SKU实例，使用最后12个月；筛选不看测试段活跃度。时间单位保留为月，周提前期转为月后向上取整。物流路线和成本仍沿用示例假设。

以下仅转录归档汇总的{external_n}次求解，未从公开合成明细重算：

{analogue_table}

各行均值对应各自可行子集。缺少外部逐实例明细时，不能从这些均值计算配对成本变化；下载原始数据并重跑后才能逐实例核对。数据说明见[Car Parts说明](../data_sources/carpartsREADME.md)。

## 保存的通知抽取与优化器重放

会话内一次LLM抽取保存了{pilot['notices']}条合成通知的JSON，结构匹配{pilot['exact_matches']}条，其中{pilot['ambiguity_abstentions']}条缺少关键字段并要求澄清。输入、提示、输出与哈希均保留在[llm目录](../llm/)。数值重放只使用A01/A02/M01/M02，并在公告实际生效的容量、服务、库存和碳条件下检查计划。

{replay_table}

保存的抽取与人工输入产生相同参数；相对忽略公告组的差异来自参数更新。这组小型合成试验说明已保存输出可重放，不能据此判断模型的留出泛化能力。后续冻结通知基准与外部API推理采用独立样本和指标，见[通知评测](../docs/notice_benchmark_stage1.md)与[API小样本结果](../docs/results/api_smoke.md)；其样本量与准确率不并入物流优化结果。

## 复现

从仓库根目录运行：

```bash
python -m pip install -r requirements.txt
python scripts/create_reports.py
python -m unittest discover -s tests -v
```

报告生成器只读取已保存结果，用Matplotlib输出图片和Markdown表格，不发起API调用。重新求解时先执行`python scripts/download_source_data.py`，再运行：

```bash
python scripts/run_experiments.py --project both
python scripts/evaluate_notice_pilot.py --project both
python scripts/run_sensitivity.py --project both
python scripts/create_reports.py
```

[原始运行清单](run_manifest.json)保留原实验的环境、输入与源码哈希，报告重新排版不会更新该历史记录。[公开导出清单](public_export_manifest.json)记录发布明细的范围。后续可检验预测误差下的滚动规划、终端缓冲和成本／容量／排放因子不确定性，再通过真实企业数据接口校准。

## 原始来源与许可

- [ASML 2025年报：物流、空运转海运](https://www.sec.gov/Archives/edgar/data/937966/000162828026011377/asml-2025xannualxreportx.htm)
- [Marvell FY2026 10-K：fabless及OSAT背景](https://investor.marvell.com/sec-filings/all-sec-filings/content/0001835632-26-000011/mrvl-20260131.htm)；[供应链碳边界](https://www.marvell.com/company/sustainability/responsible-supply-chain.html)
- [英国政府2026排放因子](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2026)，按原发布页OGL归属。
- [鹿特丹港：苏伊士及绕好望角历史距离](https://www.portofrotterdam.com/en/news-and-press-releases/impact-of-red-sea-unrest-on-rotterdam-throughput-expected-to-be-slight)
- [Monash／Zenodo汽车备件月度需求](https://zenodo.org/records/4656022)，CC BY4.0。
- [OurAirports公开机场坐标](https://ourairports.com/data/)。完整出处与下载哈希见[来源清单](../data_sources/source_manifest.json)。
"""


def main(argv=()):
    parser = argparse.ArgumentParser(
        description="Generate the Markdown study report and Matplotlib figures from saved results."
    )
    parser.parse_args(argv)
    report_dir = ROOT / "reports"
    rows = json.loads((report_dir / "episodes.json").read_text(encoding="utf-8"))
    archived_summary = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
    pilot = json.loads((report_dir / "notice_pilot.json").read_text(encoding="utf-8"))
    manifest = json.loads((report_dir / "run_manifest.json").read_text(encoding="utf-8"))
    sensitivity = json.loads((report_dir / "sensitivity.json").read_text(encoding="utf-8"))
    comparisons = paired_tradeoffs(rows)
    write_json(report_dir / "paired_tradeoffs.json", comparisons)
    with (report_dir / "paired_tradeoffs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRADEOFF_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(comparisons)
    counts = create_frontier_plot(rows, report_dir)
    report = render_report(rows, archived_summary, manifest, pilot, comparisons, counts, len(sensitivity))
    (report_dir / "study_report.md").write_text(report, encoding="utf-8")
    print("Created reports/study_report.md, paired comparisons and Matplotlib figures")


if __name__ == "__main__":
    main(sys.argv[1:])
