"""Deterministic keyword/regex agent: offline fallback and evaluation baseline.

It maps a request to a fixed tool sequence and fills template answers, so it is
predictable, free to run and faithful by construction. It is also brittle:
paraphrases, numbers written in words, multi-part questions and unfamiliar
wording fall outside its patterns. The evaluation reports it next to the LLM
agent for exactly that reason.
"""
from __future__ import annotations

import re
import time

from .agent import AgentResult
from .guardrails import check_answer

FLAGS = re.IGNORECASE
SCENARIO_PATTERNS = (
    ("red_sea", r"红海|苏伊士|suez|red\s*sea|好望角|cape of good hope"),
    ("air_crunch", r"空运.{0,8}(紧张|短缺|不足|吃紧|运力下降)|air\s*(cargo|freight)?.{0,12}(crunch|shortage|tight)"),
    ("typhoon", r"台风|typhoon"),
    ("border_congestion", r"边境|拥堵|congestion|border"),
    ("demand_surge", r"需求.{0,8}(激增|暴增|增长|上涨|增加|上升)|demand.{0,12}(surge|spike|increase|ramp)"),
)
NETWORK_OF = {"red_sea": "asml", "air_crunch": "asml", "typhoon": "marvell", "border_congestion": "marvell"}
MARVELL = r"marvell|迈威尔|芯片|台湾|马来西亚|taiwan|malaysia|osat|chip"
ASML = r"asml|阿斯麦|光刻|备件|spare"
WEEKS = r"第?\s*(\d{1,2})\s*(?:-|–|~|到|至)\s*第?\s*(\d{1,2})\s*周|weeks?\s*(\d{1,2})\s*(?:-|–|to|through)\s*(\d{1,2})"
DELAY = r"(?:延误|延迟|推迟|晚到|多)\s*(\d)\s*(?:周|个星期)|(?:delay(?:ed)?|late)\s*(?:by\s*)?(\d)\s*weeks?"
CAPACITY = (r"(?:运力|舱位|capacity)\D{0,6}?(?:下降|减少|削减|降低|砍掉|cut|down|reduced?)\s*(?:by\s*)?(\d{1,3})\s*%"
            r"|(\d{1,3})\s*%\s*(?:的)?(?:运力|舱位|capacity)")
DEMAND = r"需求\D{0,6}?(?:增加|增长|上涨|激增)\D{0,3}?(\d{1,3})\s*%"
CAP_CUT = (r"(?:减排|降低排放|减少排放|排放.{0,4}(?:降低|减少|下降|削减)|cut\s+(?:co2|carbon|emissions?)"
           r"|reduce\s+(?:co2|carbon|emissions?))\s*(?:by\s*)?(\d{1,3})\s*%")
CAP_LEVEL = r"排放.{0,8}(?:控制在|不超过|上限|限制在)\D{0,6}(\d{1,3})\s*%"
PRICE = r"(?:碳价|碳税|carbon\s*(?:price|tax))\D{0,10}(\d{2,5})"
FRONTIER = r"边际减排|减排成本曲线|前沿|frontier|abatement|\bmac\b"
HEDGE = r"对冲|预留|提前备货|不确定|概率|hedg|reserv|stochastic|uncertain|probabilit|\bvss\b|\bevpi\b"
EXPLAIN = r"为什么|解释|瓶颈|成本构成|驱动|影子价格|why|explain|bottleneck|binding|driver|shadow price"
DESCRIBE = r"网络概况|介绍.{0,8}网络|有哪些.{0,6}(?:线路|航线|运输方式)|线路和|单位排放|describe|overview|\blanes?\b"
MEMO = r"备忘录|memo|汇报|写.{0,4}(?:总结|报告)"
FOLLOW_UP = r"这种情况|此情况|在此基础上|同样的情况|这个场景|this scenario|same scenario"
PROBABILITY = r"(\d{1,2})\s*%\s*(?:的)?(?:概率|可能)|(?:概率|可能性?)\D{0,4}(\d{1,2})\s*%"
MODES = (("air", r"空运|航空|air"), ("road", r"公路|陆运|卡车|road|truck"), ("ocean", r"海运|海路|船|航运|ocean|sea|vessel"))
OUT_OF_SCOPE = ("这个问题超出了我的范围。我能做的是：查看物流网络，评估运输中断（如红海绕行、台风、边境拥堵）"
                "对成本和排放的影响，计算减排的成本与边际减排成本，做中断风险对冲（两阶段随机规划），以及生成决策备忘录。")
NOTE = "说明：SKU、需求、容量、费率和扰动幅度为合成情景假设；距离与排放因子来自公开来源。"


def _first(pattern, text):
    match = re.search(pattern, text, FLAGS)
    if not match:
        return None
    return next((g for g in match.groups() if g is not None), match.group(0))


def parse(question: str, context: dict | None = None) -> dict:
    context = context or {}
    scenario = next((name for name, pattern in SCENARIO_PATTERNS if re.search(pattern, question, FLAGS)), None)
    if re.search(MARVELL, question, FLAGS):
        network = "marvell"
    elif re.search(ASML, question, FLAGS):
        network = "asml"
    else:
        network = NETWORK_OF.get(scenario) or context.get("network", "asml")
    if scenario in NETWORK_OF and NETWORK_OF[scenario] != network:
        network = NETWORK_OF[scenario]
    weeks = re.search(WEEKS, question, FLAGS)
    delay, capacity = _first(DELAY, question), _first(CAPACITY, question)
    custom = None
    if weeks and (delay or capacity):
        start, end = [int(g) for g in weeks.groups() if g is not None][:2]
        mode = next((m for m, pattern in MODES if re.search(pattern, question, FLAGS)), "ocean")
        disruption = {"mode": mode, "start_week": start, "end_week": end}
        if delay:
            disruption["extra_lead_weeks"] = int(delay)
        if capacity:
            disruption["capacity_change_pct"] = -int(capacity)
        if scenario == "red_sea" and mode == "ocean":
            disruption["distance_factor"] = 1.4183  # Suez -> Cape distance ratio from the ASML data audit
        custom = {"network": network, "name": f"custom_{scenario or mode}_w{start}_{end}",
                  "disruptions": [disruption]}
    if not scenario and not custom and re.search(FOLLOW_UP, question, FLAGS):
        scenario = context.get("scenario")
    demand = _first(DEMAND, question)
    if scenario == "demand_surge" and demand and int(demand) != 30:
        custom = {"network": network, "name": f"custom_demand_{demand}", "demand_change_pct": int(demand),
                  "demand_weeks": [int(g) for g in weeks.groups() if g][:2] if weeks else None}
    cut, level = _first(CAP_CUT, question), _first(CAP_LEVEL, question)
    cap = 100 - int(cut) if cut else (int(level) if level else None)
    price = _first(PRICE, question)
    probability = _first(PROBABILITY, question)
    flags = {name: bool(re.search(pattern, question, FLAGS)) for name, pattern in (
        ("frontier", FRONTIER), ("hedge", HEDGE), ("explain", EXPLAIN), ("describe", DESCRIBE), ("memo", MEMO))}
    request = {"network": network, "scenario": scenario, "custom": custom, "cap_pct": cap,
               "price": int(price) if price else None,
               "probability_pct": int(probability) if probability else None, **flags}
    request["in_scope"] = bool(scenario or custom or cap or price or any(flags.values()))
    return request


def run_rules(question: str, session) -> AgentResult:
    started, first = time.perf_counter(), len(session.calls)
    req = parse(question, session.context)
    lines = []
    if not req["in_scope"]:
        return _result(question, OUT_OF_SCOPE, session, first, started)
    net = req["network"]
    session.context["network"] = net
    if req["describe"]:
        info = session.call("describe_network", {"network": net})
        lines.append(f"{net} 网络：{info['skus']} 个 SKU，{info['weeks']} 周承诺需求 {info['demand_units']:,} 件。线路：")
        for lane in info["lanes"]:
            lines.append(f"- {lane['id']}（{lane['mode']}）：提前期 {lane['lead_weeks']} 周，运费 "
                         f"{lane['freight_usd_per_kg']} 美元/kg，周运力 {lane['weekly_capacity_kg']:,} kg，"
                         f"每 kg 货物排放 {lane['kgco2e_per_kg']} kgCO2e")
    scenario = req["scenario"]
    if req["custom"]:
        created = session.call("create_scenario", req["custom"])
        if "error" in created:
            lines.append(f"无法按公告建模：{created['error']}")
        else:
            scenario = created["scenario"]
            if created["assumptions"]:
                lines.append("建模假设：" + "；".join(created["assumptions"]))
    if scenario:
        session.context["scenario"] = scenario
    plan_ids = []
    needs_plan = scenario or req["cap_pct"] or req["price"] or (req["explain"] and not req["hedge"]) or (
        req["memo"] and not session.plans)
    if needs_plan:
        base = session.call("solve_plan", {"network": net})
        plan_ids.append(base["plan_id"])
        target = {"network": net, "scenario": scenario or "normal"}
        if req["cap_pct"]:
            target["carbon_cap_pct"] = req["cap_pct"]
        if req["price"]:
            target["carbon_price_usd_per_t"] = req["price"]
        if len(target) > 2 or target["scenario"] != "normal":
            plan = session.call("solve_plan", target)
            if "error" in plan:
                lines.append(f"求解失败：{plan['error']}")
            elif plan.get("status") not in ("optimal", "feasible"):
                lines.append(f"在这些约束下没有可行方案（状态：{plan.get('status')}）。")
            else:
                plan_ids.append(plan["plan_id"])
                row = session.call("compare_plans", {"plan_ids": list(plan_ids)})["rows"][1]
                change = "增加" if row["cost_change_usd"] >= 0 else "减少"
                lines.append(f"方案 {plan['plan_id']}（{plan['label']}）：总物流成本 {row['total_cost_usd']:,} 美元，"
                             f"比正常方案 {base['plan_id']} {change} {abs(row['cost_change_usd']):,} 美元"
                             f"（{row['cost_change_pct']:+.2f}%）；排放 {row['emissions_t']} 吨（{row['emissions_change_pct']:+.2f}%）；"
                             f"空运占比 {row['air_share_pct']}%；服务水平 {row['service_level_pct']}%。")
                if "carbon_shadow_price_usd_per_t" in plan:
                    lines.append(f"碳约束的影子价格约 {plan['carbon_shadow_price_usd_per_t']:,} 美元/吨，"
                                 "即在该上限下每多减 1 吨的边际成本。")
        else:
            lines.append(f"正常方案 {base['plan_id']}：总物流成本 {base['total_cost_usd']:,} 美元，排放 "
                         f"{base['emissions_t']} 吨，空运占比 {base['air_share_pct']}%。")
        if req["explain"] and plan_ids:
            info = session.call("explain_plan", {"plan_id": plan_ids[-1]})
            drivers = "，".join(f"{d['item']} {d['usd']:,.0f} 美元（{100 * d['share']:.1f}%）"
                               for d in info.get("cost_drivers", [])[:3])
            lines.append(f"主要成本项：{drivers}。")
            binding = info.get("binding_capacity", [])[:3]
            if binding:
                lines.append("接近满载的线路：" + "，".join(
                    f"{b['lane']} 第 {b['week']} 周（{100 * b['utilisation']:.1f}%）" for b in binding) + "。")
            else:
                lines.append("没有线路周达到 95% 以上的利用率。")
    if req["frontier"]:
        fr = session.call("carbon_frontier", {"network": net})
        lines.append(f"{net} 减排成本（服务水平 ≥ 98%）：成本最优方案 {fr['baseline_cost_usd']:,} 美元、"
                     f"{fr['baseline_emissions_t']} 吨。")
        for p in fr["points"][1:]:
            if p["cost_increase_pct"] is None:
                lines.append(f"- 排放上限 {p['emission_cap_pct']}%：{p['status']}")
            else:
                lines.append(f"- 排放上限 {p['emission_cap_pct']}%：成本 {p['cost_increase_pct']:+.2f}%，平均边际减排成本 "
                             f"{p['mac_avg_usd_per_t']:,} 美元/吨，影子价格 {p['shadow_price_usd_per_t']} 美元/吨")
        lines.append(f"在该服务水平下最多可减排 {fr['max_reduction_pct']}%（最低 {fr['min_emissions_t']} 吨）。")
    if req["hedge"]:
        args = {"network": net}
        target = req["scenario"] if req["scenario"] and req["scenario"] != "normal" else None
        if req["probability_pct"] and target:
            args.update(scenarios=["normal", target],
                        probabilities=[100 - req["probability_pct"], req["probability_pct"]])
        hedge = session.call("hedge_disruption_risk", args)
        if "error" in hedge:
            lines.append(f"对冲分析失败：{hedge['error']}")
        else:
            e = hedge["expected_cost_usd"]
            lines.append(f"两阶段随机方案（第 {hedge['reveal_week']} 周才知道是否中断）：期望成本 {e['stochastic_RP']:,} 美元；"
                         f"按正常预测计划、事后再应变为 {e['nominal_EEV']:,} 美元；VSS = {hedge['VSS_usd']:,} 美元"
                         f"（{hedge['VSS_pct']}%），EVPI = {hedge['EVPI_usd']:,} 美元（{hedge['EVPI_pct']}%）。")
            for row in hedge["per_scenario"]:
                lines.append(f"- {row['scenario']}（{row['probability_pct']}%）：随机方案 {row['stochastic_usd']:,}，"
                             f"名义方案 {row['nominal_usd']:,}，差额 {row['saving_vs_nominal_usd']:,} 美元")
            lines += ["第一阶段建议：" + "；".join(hedge["first_stage_recommendation"])]
            plan_ids += list(hedge["plan_ids"].values())
    if req["memo"]:
        ids = plan_ids
        if not ids:
            # Whole conversation: the normal plan first as the baseline, then the most recent plans.
            normal = [p.id for p in session.plans.values() if p.network == net and p.label == "normal"]
            ids = normal[:1] + [pid for pid in session.plans if pid not in normal[:1]][-5:]
        if ids:
            memo = session.call("write_memo", {"plan_ids": ids, "question": question})
            lines.append(f"备忘录已写入 {memo.get('path', '（失败）')}。")
    lines.append(NOTE)
    return _result(question, "\n".join(lines), session, first, started)


def _result(question, answer, session, first, started) -> AgentResult:
    calls = session.calls[first:]
    check = check_answer(answer, [c["result"] for c in calls], question)
    return AgentResult(question, answer, "rule", calls, len(calls), check, round(time.perf_counter() - started, 2))
