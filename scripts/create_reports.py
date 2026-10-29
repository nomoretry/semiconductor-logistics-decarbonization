"""Build self-contained research HTML and exact paired comparison tables."""
from pathlib import Path
import base64
import csv
import html
import json
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shared.experiments import ROOT,write_json

CASES={"normal":"正常运输","ocean_delay":"已公告运输延误","capacity_restriction":"已公告容量限制"}
POLICIES={"cost_only":"成本最优参照","fast_only":"仅空运（库存仍优化）","slow_only":"仅海运／公路（库存仍优化）","carbon_minus10":"碳预算−10%","carbon_minus25":"碳预算−25%","carbon_minus50":"碳预算−50%"}

def main():
    rows=json.loads((ROOT/"reports/episodes.json").read_text())
    summaries=json.loads((ROOT/"reports/summary.json").read_text())
    projects=sorted({r["project"] for r in rows})
    rng=np.random.default_rng(20261030)
    comparisons=[]
    for project in projects:
        for case in CASES:
            group=[r for r in rows if r["project"]==project and r["case"]==case and r["demand_set"]=="synthetic_weekly"]
            base={r["seed"]:r for r in group if r["policy"]=="cost_only" and r["feasible"]}
            target=[r for r in group if r["policy"]=="carbon_minus25" and r["feasible"] and r["seed"] in base]
            if not target:continue
            c0=np.array([base[r["seed"]]["total_cost"] for r in target]);c1=np.array([r["total_cost"] for r in target])
            e0=np.array([base[r["seed"]]["total_emissions"] for r in target]);e1=np.array([r["total_emissions"] for r in target])
            idx=rng.integers(0,len(target),size=(10000,len(target)))
            cost_boot=100*(c1[idx].mean(axis=1)/c0[idx].mean(axis=1)-1)
            emission_boot=100*(1-e1[idx].mean(axis=1)/e0[idx].mean(axis=1))
            comparisons.append(dict(project=project,case=case,n=len(target),cost_reference=float(c0.mean()),cost_budget25=float(c1.mean()),
                emissions_reference=float(e0.mean()),emissions_budget25=float(e1.mean()),
                cost_increase_pct=float(100*(c1.mean()/c0.mean()-1)),emissions_reduction_pct=float(100*(1-e1.mean()/e0.mean())),
                cost_increase_ci95=np.percentile(cost_boot,[2.5,97.5]).tolist(),emissions_reduction_ci95=np.percentile(emission_boot,[2.5,97.5]).tolist()))
    write_json(ROOT/"reports/paired_tradeoffs.json",comparisons)
    with (ROOT/"reports/paired_tradeoffs.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(comparisons[0]),lineterminator="\n");w.writeheader();w.writerows(comparisons)
    plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False,"figure.facecolor":"#ffffff"})
    fig,axes=plt.subplots(1,len(projects),figsize=(6*len(projects),4.4),squeeze=False)
    for ax,project in zip(axes[0],projects):
        for case,color in zip(CASES,["#126782","#d97706","#7c3aed"]):
            group=[r for r in rows if r["project"]==project and r["case"]==case and r["demand_set"]=="synthetic_weekly"]
            policies=["cost_only","carbon_minus10","carbon_minus25","carbon_minus50"]
            maps={p:{r["seed"]:r for r in group if r["policy"]==p and r["feasible"]} for p in policies}
            paired=set.intersection(*(set(maps[p]) for p in policies))
            xs,ys=[],[]
            for p in policies:
                c0=np.mean([maps["cost_only"][s]["total_cost"] for s in paired]);cp=np.mean([maps[p][s]["total_cost"] for s in paired])
                e0=np.mean([maps["cost_only"][s]["total_emissions"] for s in paired]);ep=np.mean([maps[p][s]["total_emissions"] for s in paired])
                xs.append(100*(1-ep/e0));ys.append(100*(cp/c0-1))
            label={"normal":"Normal","ocean_delay":"Announced delay","capacity_restriction":"Announced capacity"}[case]
            ax.plot(xs,ys,"o-",color=color,label=f"{label} (paired n={len(paired)})",linewidth=2,markersize=5)
        ax.set_title(project.upper()+"-inspired simulation",loc="left",fontweight="bold")
        ax.set_xlabel("Logistics emissions reduction vs cost-only (%)")
        ax.set_ylabel("Planning cost increase (%)")
        ax.grid(alpha=.18);ax.legend(fontsize=8,loc="upper left")
    fig.suptitle("Cost-carbon trade-offs with identical service and terminal stock",fontsize=13,fontweight="bold")
    fig.text(.5,.01,"Scenario assumptions, not company estimates. Complete matched frontiers only; infeasible targets are reported separately.",ha="center",fontsize=8,color="#555")
    fig.tight_layout(rect=(0,.04,1,.94))
    fig.savefig(ROOT/"reports/cost_carbon_frontier.png",dpi=180)
    fig.savefig(ROOT/"reports/cost_carbon_frontier.svg")
    plt.close(fig)
    pilot=json.loads((ROOT/"reports/notice_pilot.json").read_text())
    manifest=json.loads((ROOT/"reports/run_manifest.json").read_text())
    def num(x):return "—" if x is None else f"{x:,.2f}"
    main_table="".join(f"<tr><td>{r['project'].upper()}</td><td>{CASES[r['case']]}</td><td>{r['n']}</td><td>{num(r['cost_reference'])}</td><td>{num(r['cost_budget25'])}</td><td>+{r['cost_increase_pct']:.2f}%</td><td>{num(r['emissions_reference'])}</td><td>{num(r['emissions_budget25'])}</td><td>{r['emissions_reduction_pct']:.2f}%</td></tr>" for r in comparisons)
    complete_tables=""
    for project in projects:
        complete_tables+=f"<h3>{project.upper()}全部策略</h3><table><thead><tr><th>情景</th><th>策略</th><th>可行/总数</th><th>可行方案平均成本USD</th><th>平均kgCO₂e</th><th>空运质量占比</th></tr></thead><tbody>"
        for r in summaries:
            if r["project"]!=project or r["demand_set"]!="synthetic_weekly":continue
            complete_tables+=f"<tr><td>{CASES[r['case']]}</td><td>{POLICIES[r['policy']]}</td><td>{r['feasible_n']}/{r['n']}</td><td>{num(r['total_cost'])}</td><td>{num(r['total_emissions'])}</td><td>{num(None if r['air_mass_share'] is None else 100*r['air_mass_share'])}%</td></tr>"
        complete_tables+="</tbody></table>"
    pilot_rows=""
    for project in projects:
        for method,label in [("correct_structured_input","人工正确结构化输入＋优化器"),("saved_LLM_extraction","保存的会话内LLM抽取＋优化器"),("ignore_notice","忽略公告、沿用旧参数")]:
            group=[r for r in pilot["numerical_replays"] if r["project"]==project and r["method"]==method]
            count=sum(r.get("all_constraints_satisfied",False) for r in group)
            pilot_rows+=f"<tr><td>{project.upper()}</td><td>{label}</td><td>{count}/{len(group)}</td></tr>"
    analogy="".join(f"<tr><td>{POLICIES[r['policy']]}</td><td>{r['feasible_n']}/{r['n']}</td><td>{num(r['total_cost'])}</td><td>{num(r['total_emissions'])}</td></tr>" for r in summaries if r["demand_set"]=="real_carparts_monthly")
    image64=base64.b64encode((ROOT/"reports/cost_carbon_frontier.png").read_bytes()).decode()
    source_links=[("ASML 2025年报：物流、空运转海运", "https://www.sec.gov/Archives/edgar/data/937966/000162828026011377/asml-2025xannualxreportx.htm"),
        ("Marvell FY2026 10-K：fabless及OSAT背景","https://investor.marvell.com/sec-filings/all-sec-filings/content/0001835632-26-000011/mrvl-20260131.htm"),
        ("Marvell供应链碳边界","https://www.marvell.com/company/sustainability/responsible-supply-chain.html"),
        ("UK Government 2026排放因子","https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2026"),
        ("鹿特丹港：苏伊士及绕好望角历史距离","https://www.portofrotterdam.com/en/news-and-press-releases/impact-of-red-sea-unrest-on-rotterdam-throughput-expected-to-be-slight"),
        ("真实汽车备件月度需求，Monash/Zenodo，CC BY4.0","https://zenodo.org/records/4656022"),
        ("OurAirports原始公开坐标","https://ourairports.com/data/")]
    links="".join(f'<li><a href="{url}">{html.escape(label)}</a></li>' for label,url in source_links)
    body=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ASML与Marvell：低碳库存与运输联合优化</title>
<style>body{{font:16px/1.75 system-ui,"Microsoft YaHei",sans-serif;color:#18303d;background:#f2f5f7;margin:0}}main{{max-width:1180px;margin:30px auto;background:white;padding:40px 48px;border-radius:14px}}h1{{line-height:1.3;font-size:30px}}h2{{margin-top:36px;border-bottom:2px solid #dce7eb;padding-bottom:8px}}h3{{margin-top:25px}}.tag{{color:#126782;font-weight:700;letter-spacing:.06em}}.note{{background:#edf6f8;border-left:4px solid #126782;padding:14px 18px}}.limit{{background:#fff7e9;padding:14px 18px}}table{{border-collapse:collapse;width:100%;font-size:13px;margin:15px 0}}td,th{{border-bottom:1px solid #dfe7ec;padding:8px;text-align:right}}td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){{text-align:left}}th{{background:#edf3f6}}img{{max-width:100%;height:auto}}code{{background:#edf3f6;padding:2px 4px}}pre{{background:#132e3c;color:#eef6fa;padding:18px;overflow:auto}}a{{color:#126782}}small{{color:#5d6f7a}}@media(max-width:700px){{main{{padding:20px;margin:8px}}table{{font-size:11px;display:block;overflow:auto}}}}</style>
<main><div class="tag">REPRODUCIBLE PILOT · 2026-10-30</div><h1>低碳半导体物流：<br>ASML与Marvell两个子项目的第一轮实测</h1>
<p class="note"><b>结论：</b>两个可独立运行的企业背景仿真已经建立。25%物流碳预算收紧，在六组情景中均10/10可行；成本增幅与库存资金占用、提前期和容量有关。所有金额是情景假设下的计算结果，<b>不是企业实测、预测或减排承诺</b>。</p>
<h2>1. 本轮实际做了什么</h2><p>主实验<b>{len(rows)}次MILP求解</b>：两个项目各3类公告情景、10个合成订单簿、6类策略，共360次；另有40次真实汽车备件月度需求压力测试。{sum(r['feasible'] for r in rows)}次可行且在指定最优间隙内求得最优，{sum(not r['feasible'] for r in rows)}次明确不可行。另运行24次敏感性求解，以及40个信息处理实例的160次数值求解。独立测试共24项通过，核心模型还通过36个小规模穷举案例对照。</p>
<p>第一阶段是<b>完整承诺订单簿＋已公告扰动的计划模型</b>：各组知道相同的客户订单。它不是未知需求预测、在线学习或未知未来扰动的滚动控制。ASML第一版不考虑货损；Marvell只优化物流，不改变晶圆制造、封测工艺或产品隐含碳。</p>
<h2>2. 两个项目与数据边界</h2><table><tr><th>项目</th><th>假设网络</th><th>决策</th><th>公开事实与合成假设</th></tr><tr><td>ASML</td><td>荷兰供货池→新加坡区域仓</td><td>空运/海运发货与库存</td><td>业务及历史路线有依据；4个SKU、价格、质量、需求和容量均为假设</td></tr><tr><td>Marvell</td><td>台湾/马来西亚OSAT供货池→新加坡仓</td><td>台湾空/海运、马来西亚空/公路与库存</td><td>fabless/OSAT布局有依据；具体网络、SKU及商业参数不是公司记录</td></tr></table>
<p>检查了ASML、Applied Materials、Lam、SKF、KLA及Marvell、NXP、TI、Infineon、DigiKey、Mouser等来源。找到了企业流程、财务库存及目录信息；在本轮有界检索中，没有找到可直接匹配的SKU需求＋库存＋运费联合历史记录。完整检索和适配表在两个数据审计文件中，不能扩大为“所有企业都没有数据”。</p>
<h2>3. 同服务与同终端库存的主结果</h2><p>每个项目4类假设SKU，16个周度期间，种子100–109。每期期末积压必须为0，期末库存至少回到所有策略共同的初始库存。以下每行均配对同一组10个订单簿。成本增幅为两组均值之比减1；碳减幅为1减两组排放均值之比。成本单位USD，排放单位kgCO₂e。</p>
<table><thead><tr><th>项目</th><th>情景</th><th>配对数</th><th>参照成本</th><th>碳预算成本</th><th>成本增幅</th><th>参照排放</th><th>碳预算排放</th><th>排放降幅</th></tr></thead><tbody>{main_table}</tbody></table>
<img alt="Matched cost-carbon frontiers" src="data:image/png;base64,{image64}"><p><small>图只保留整条前沿都可行的共同种子，ASML每条线9组，Marvell10组。表中25%预算使用全部10组。成本及排放的配对bootstrap区间保存在paired_tradeoffs.json，反映少量随机订单簿差异，不包含商业参数和模型结构的不确定性。</small></p>
<h2>4. 库存与碳核算模型</h2><p><code>本期净库存 = 上期净库存 + 初始在途到货 + 以前派发而本期到货 − 本期需求</code>。发货数量为整数，按<b>派发期</b>的提前期决定到货时间。各SKU只能走合格路线；同一供货池的空/海运还共享释放容量。</p>
<p>最小化：运费＋在途资金占用＋到仓后资金与仓储成本。约束运输及库存相关仓储排放不超过预算。质量先由kg除以1000转为吨，再乘km与模式因子。主因子：空运0.66646、集装箱船0.01977、普通柴油货车0.12715 kgCO₂e/吨·km，含相应燃料WTT；它们是英国官方均值的跨地域代理，不是企业或承运商实测。航空因子已内含8%距离修正，代码未再加一次。</p>
<p>ASML海运基准采用历史苏伊士8,288海里（15,349km），扰动采用绕好望角约21,770km和合成的额外2周。航空为公开机场坐标的大圆距离。Marvell台湾海路4,000km、马来西亚公路400km是明确假设；不能称为真实公司轨迹。仓储边际排放0.04 kgCO₂e/单位·周为假设，并做0与5倍敏感性。资金持有成本与碳排放分开核算。</p>
<h2>5. 全部策略与不可行性</h2><p>固定模式参照本身也优化发货与库存，区别只是限制可用运输方式。不可行结果保持空值，不用虚构应急动作或放松碳约束补齐。下表成本均值仅针对可行实例；样本数不同时不能直接当成全样本公平比较。</p>{complete_tables}
<h2>6. 真实相似业务数据压力测试</h2><p>Monash Car Parts原始开放数据有2,674条汽车备件月度序列、每条51个月，并非半导体订单。只从无缺失且前39个月足够活跃的序列中选择40条，构成10组4SKU实例；使用最后12个月，月份保持月份，提前期按周转换为月后向上取整。筛选不使用测试段是否活跃。物流路线和商业成本仍是示例假设。</p><table><tr><th>策略</th><th>可行/总数</th><th>可行平均成本</th><th>可行平均kgCO₂e</th></tr>{analogy}</table><p>这证明代码能接入真实间歇需求，不证明ASML或Marvell的成本/需求已经校准。25%碳预算9/10可行；与成本参照比较时必须使用同一9个实例，详细序列编号保存在instances.json。</p>
<h2>7. LLM到底做了什么</h2><p>一次会话内独立LLM抽取：根据保存的提示、路线目录和12条<b>合成</b>通知生成JSON，未读取参考标签。10条完整通知的结构与标签一致；A06/M06缺少关键路线、日期或幅度，均输出需要澄清、不猜参数。输入、提示、输出与哈希均保留。</p>
<p>数值对照只使用A01/A02/M01/M02，两类公告各10个订单簿。每个实例用人工正确输入、保存的LLM抽取及忽略公告三组重放；按真实公告条件独立检查容量、服务、期末库存和碳预算：</p><table><tr><th>项目</th><th>信息处理组</th><th>全部约束满足</th></tr>{pilot_rows}</table>
<p class="limit"><b>正确解释：</b>保存的LLM抽取与人工正确结构化输入给出相同参数，因此得到同等可行的优化结果。相对忽略公告组的改善来自信息更新；不能解释为LLM胜过优化器。没有外部API调用、多模型对比、隐藏文本测试、token/延迟/费用评测。12个简单合成示例不支持泛化结论。代码只能自动重放输出，重新生成文本抽取需要新的LLM运行。</p>
<h2>8. 复现与下一阶段</h2><pre>python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/run_experiments.py --project both
python scripts/evaluate_notice_pilot.py --project both
python scripts/run_sensitivity.py --project both
python scripts/create_reports.py</pre><p>主实验记录耗时{manifest['seconds']:.2f}秒，硬件与负载会影响时间，不构成算法优越性。下一阶段优先：固定模型与提示的真实/合成留出通知集；预测误差下的滚动MPC；期末缓冲和容量/运价/因子不确定性；真实企业数据替换接口。ASML周度服务条件不能冒充其24小时零件支持指标；Marvell采购承诺的26/52周也不等于运输提前期。</p>
<h2>主要原始来源与数据许可证</h2><ul>{links}</ul><p><small>完整出处、原始因子行号、数据审计、哈希及第三方许可在data_sources/。Monash数据CC BY4.0，英国因子按原发布页OGL归属，机场坐标为OurAirports公开数据。未包含任何账户凭据。</small></p></main></html>'''
    (ROOT/"reports/study_report.html").write_text(body,encoding="utf-8")
    print("Created report, paired comparisons and publication figures")

if __name__=="__main__":main()
