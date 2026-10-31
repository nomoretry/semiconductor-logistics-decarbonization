"""Tools the planning agent can call: validated wrappers around network_planning.

Every tool takes JSON arguments, validates them and returns a compact JSON
result with rounded numbers and ids. Full plans stay in the Session so later
tools (compare, explain, memo) reuse them and the language model never has
to copy or recompute numbers itself.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from network_planning.analysis import carbon_frontier, explain_plan, stochastic_value
from network_planning.data import NETWORKS, Disruption, Scenario, build_network
from network_planning.model import solve


class ToolError(ValueError):
    """Invalid tool arguments; the message is returned to the model so it can correct the call."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable

    def schema(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class StoredPlan:
    id: str
    network: str
    label: str
    plan: object
    request: dict


@dataclass
class Session:
    n_skus: int = 12
    weeks: int = 16
    seed: int = 7
    mip_gap: float = 2e-3
    time_limit: float = 30.0
    memo_dir: Path = Path("artifacts/planning_agent/memos")
    networks: dict = field(default_factory=dict)
    custom: dict = field(default_factory=dict)
    plans: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)
    context: dict = field(default_factory=dict)  # last network/scenario, used by the rule agent's follow-ups

    def network(self, name):
        if name not in NETWORKS:
            raise ToolError(f"unknown network '{name}'; use one of {list(NETWORKS)}")
        if name not in self.networks:
            self.networks[name] = build_network(name, self.n_skus, self.weeks, self.seed)
        return self.networks[name]

    def scenario(self, network: str, name: str, probability: float = 1.0) -> Scenario:
        if (network, name) in self.custom:
            return self.custom[network, name].with_probability(probability)
        net = self.network(network)
        if name not in net.scenario_specs:
            known = sorted(set(net.scenario_specs) | {n for (w, n) in self.custom if w == network})
            raise ToolError(f"unknown scenario '{name}' for {network}; known: {known}. "
                            "Create new ones with create_scenario.")
        return net.scenario(name, probability)

    def store(self, network: str, label: str, plan, request: dict) -> str:
        plan_id = f"P{len(self.plans) + 1}"
        self.plans[plan_id] = StoredPlan(plan_id, network, label, plan, request)
        return plan_id

    def get(self, plan_id: str) -> StoredPlan:
        if plan_id not in self.plans:
            raise ToolError(f"unknown plan_id '{plan_id}'; existing: {list(self.plans)}")
        return self.plans[plan_id]

    def call(self, name: str, arguments: dict | str | None) -> dict:
        started = time.perf_counter()
        try:
            if isinstance(arguments, str):
                arguments = json.loads(arguments or "{}")
            arguments = arguments or {}
            if not isinstance(arguments, dict):
                raise ToolError("arguments must be a JSON object")
            arguments = json.loads(json.dumps(arguments))  # private copy: the call log must not change later
            if name not in TOOLS:
                raise ToolError(f"unknown tool '{name}'; available: {list(TOOLS)}")
            result, ok = TOOLS[name].run(self, **arguments), True
        except (ToolError, ValueError, TypeError) as error:
            result, ok = {"error": str(error)}, False
        self.calls.append({"name": name, "arguments": arguments, "ok": ok, "result": result,
                           "seconds": round(time.perf_counter() - started, 3)})
        return result

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in TOOLS.values()]


# ---------------------------------------------------------------------------- helpers

def _kpis(stored: StoredPlan) -> dict:
    plan = stored.plan
    row = {"plan_id": stored.id, "label": stored.label, "network": stored.network,
           "scenario": " + ".join(plan.scenario_names), "status": plan.status}
    if not plan.feasible:
        row["note"] = "no feasible plan under these constraints"
        return row
    k = plan.kpis
    row.update(total_cost_usd=round(k["total_cost_usd"]), emissions_t=round(k["emissions_t"], 2),
               air_share_pct=round(100 * k["air_share_kg"], 1), service_level_pct=round(100 * k["service_level"], 2))
    return row


# ---------------------------------------------------------------------------- tools

def describe_network(session: Session, network: str) -> dict:
    info = session.network(network).describe()
    for (w, name), sc in session.custom.items():
        if w == network:
            info["scenarios"][name] = {"probability": None, "description": sc.description or "custom scenario"}
    return info


def create_scenario(session: Session, network: str, name: str, disruptions: list | None = None,
                    demand_change_pct: float | None = None, demand_weeks: list | None = None,
                    description: str = "") -> dict:
    net = session.network(network)
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", name or ""):
        raise ToolError("name must be snake_case letters/digits, 2-41 characters, starting with a letter")
    if name in net.scenario_specs:
        raise ToolError(f"'{name}' is a predefined scenario; choose another name")
    built, assumptions = [], []
    for item in disruptions or []:
        if not isinstance(item, dict):
            raise ToolError("each disruption must be an object")
        lanes = list(item.get("lanes") or [])
        mode = item.get("mode")
        if mode:
            lanes += [l for l, lane in net.lanes.items() if lane.mode == mode and l not in lanes]
        if not lanes:
            raise ToolError(f"give 'mode' (air/ocean/road) or 'lanes' from {list(net.lanes)}")
        missing = [l for l in lanes if l not in net.lanes]
        if missing:
            raise ToolError(f"unknown lanes {missing}; {network} lanes are {list(net.lanes)}")
        try:
            start, end = int(item["start_week"]), int(item["end_week"])
        except (KeyError, TypeError, ValueError):
            raise ToolError("start_week and end_week are required integers") from None
        capacity = 1 + float(item.get("capacity_change_pct", 0)) / 100
        cost = 1 + float(item.get("cost_change_pct", 0)) / 100
        if capacity < 0:
            raise ToolError("capacity_change_pct cannot be below -100")
        for key, default in (("extra_lead_weeks", 0), ("capacity_change_pct", 0), ("cost_change_pct", 0),
                             ("distance_factor", 1)):
            if key not in item:
                assumptions.append(f"{'/'.join(lanes)} weeks {start}-{end}: {key} not given, assumed {default}")
        built.append(Disruption(tuple(lanes), start, end, int(item.get("extra_lead_weeks", 0)), capacity,
                                float(item.get("distance_factor", 1.0)), cost))
    factor, weeks = 1.0, None
    if demand_change_pct is not None:
        factor = 1 + float(demand_change_pct) / 100
        weeks = tuple(int(w) for w in demand_weeks) if demand_weeks else (1, net.weeks)
        if len(weeks) != 2:
            raise ToolError("demand_weeks must be [start, end]")
    if not built and factor == 1.0:
        raise ToolError("a scenario needs at least one disruption or a demand change")
    scenario = Scenario(name, 1.0, tuple(built), factor, weeks, description or "custom scenario")
    net.validate(scenario)
    session.custom[network, name] = scenario
    return {"scenario": name, "network": network, "definition": scenario.to_dict(), "assumptions": assumptions}


def solve_plan(session: Session, network: str, scenario: str = "normal", carbon_cap_pct: float | None = None,
               carbon_price_usd_per_t: float | None = None, service_level_pct: float | None = None,
               label: str | None = None) -> dict:
    net = session.network(network)
    sc = session.scenario(network, scenario)
    if carbon_cap_pct is not None and not 5 <= float(carbon_cap_pct) <= 100:
        raise ToolError("carbon_cap_pct must be between 5 and 100 (% of the uncapped plan's emissions)")
    if service_level_pct is not None and not 50 <= float(service_level_pct) <= 100:
        raise ToolError("service_level_pct must be between 50 and 100")
    if carbon_price_usd_per_t is not None and not 0 <= float(carbon_price_usd_per_t) <= 20000:
        raise ToolError("carbon_price_usd_per_t must be between 0 and 20000")
    request = {"network": network, "scenario": scenario, "carbon_cap_pct": carbon_cap_pct,
               "carbon_price_usd_per_t": carbon_price_usd_per_t, "service_level_pct": service_level_pct}
    key = json.dumps(request, sort_keys=True)
    if key in session.cache:
        return dict(session.cache[key], cached=True)
    service = None if service_level_pct is None else float(service_level_pct) / 100
    options = dict(service_level=service, mip_gap=session.mip_gap, time_limit=session.time_limit)
    cap_kg = None
    if carbon_cap_pct is not None:
        reference = solve_plan(session, network, scenario, service_level_pct=service_level_pct)
        if "emissions_t" not in reference:
            raise ToolError("the uncapped reference plan is infeasible, so a relative cap is undefined")
        cap_kg = float(carbon_cap_pct) / 100 * session.get(reference["plan_id"]).plan.kpis["emissions_t"] * 1000
    plan = solve(net, [sc], carbon_cap_kg=cap_kg, carbon_price=float(carbon_price_usd_per_t or 0.0),
                 duals=cap_kg is not None, **options)
    parts = [scenario] + ([f"cap {carbon_cap_pct:g}%"] if carbon_cap_pct is not None else []) + (
        [f"carbon price {carbon_price_usd_per_t:g}"] if carbon_price_usd_per_t else [])
    stored_id = session.store(network, label or " / ".join(parts), plan, request)
    result = _kpis(session.get(stored_id))
    if plan.feasible:
        result["cost_breakdown_usd"] = {k: round(v) for k, v in plan.kpis["cost_breakdown_usd"].items() if v > 0.5}
        result["air_reservation_kg_per_week"] = {l: round(v, 1) for l, v in plan.solution["reserve"].items()}
        if cap_kg is not None:
            result["uncapped_reference_plan_id"] = reference["plan_id"]
            result["carbon_cap_t"] = round(cap_kg / 1000, 2)
            shadow = plan.duals.get("carbon_usd_per_t")
            if shadow is not None:
                result["carbon_shadow_price_usd_per_t"] = round(shadow)
        if carbon_price_usd_per_t:
            result["carbon_tax_usd"] = round(plan.kpis["carbon_tax_usd"])
    result["mip_gap_pct"] = None if plan.stats.get("mip_gap") is None else round(100 * plan.stats["mip_gap"], 3)
    result["solve_seconds"] = plan.stats["solve_seconds"]
    if plan.issues:
        result["accounting_issues"] = plan.issues[:3]
    session.cache[key] = result
    return result


def compare_plans(session: Session, plan_ids: list) -> dict:
    if not isinstance(plan_ids, list) or not 2 <= len(plan_ids) <= 6:
        raise ToolError("plan_ids must list 2-6 plan ids; the first one is the baseline")
    stored = [session.get(pid) for pid in plan_ids]
    base = _kpis(stored[0])
    rows = []
    for item in stored:
        row = _kpis(item)
        if "total_cost_usd" in row and "total_cost_usd" in base:
            row["cost_change_usd"] = row["total_cost_usd"] - base["total_cost_usd"]
            row["cost_change_pct"] = round(100 * (row["total_cost_usd"] / base["total_cost_usd"] - 1), 2)
            row["emissions_change_t"] = round(row["emissions_t"] - base["emissions_t"], 2)
            row["emissions_change_pct"] = round(100 * (row["emissions_t"] / base["emissions_t"] - 1), 2)
            row["service_level_change_pp"] = round(row["service_level_pct"] - base["service_level_pct"], 2)
        rows.append(row)
    return {"baseline": plan_ids[0], "rows": rows}


def carbon_frontier_tool(session: Session, network: str, scenario: str = "normal",
                         levels_pct: list | None = None) -> dict:
    net = session.network(network)
    session.scenario(network, scenario)
    levels = [float(x) for x in (levels_pct or [90, 75, 60])]
    if not levels or len(levels) > 8 or any(not 5 <= x < 100 for x in levels):
        raise ToolError("levels_pct must list 1-8 values in [5, 100), e.g. [90, 75, 60]")
    if (network, scenario) in session.custom:
        net.scenario_specs = dict(net.scenario_specs, **{scenario: session.custom[network, scenario].to_dict()})
    result = carbon_frontier(net, scenario, tuple(x / 100 for x in sorted(levels, reverse=True)),
                             mip_gap=session.mip_gap, time_limit=session.time_limit)
    points = [{"emission_cap_pct": round(100 * p["level"]), "status": p["status"],
               "cost_increase_pct": p.get("cost_increase_pct"), "emissions_t": _r(p.get("emissions_t"), 2),
               "air_share_pct": _r(100 * p["air_share_kg"], 1) if p.get("air_share_kg") is not None else None,
               "mac_avg_usd_per_t": _r(p.get("mac_vs_baseline_usd_per_t")),
               "mac_step_usd_per_t": _r(p.get("mac_step_usd_per_t")),
               "shadow_price_usd_per_t": _r(p.get("shadow_price_usd_per_t"))}
              for p in result["points"]]
    return {"network": network, "scenario": scenario, "service_level_pct": 98,
            "baseline_cost_usd": round(result["baseline_cost_usd"]), "baseline_emissions_t": round(
                result["baseline_emissions_t"], 2), "points": points,
            "min_emissions_t": _r(result.get("min_emissions_t"), 2),
            "max_reduction_pct": _r(result.get("max_reduction_pct"), 1),
            "note": "MAC = extra logistics cost per tonne avoided; shadow price = LP dual of the cap at fixed lane activations."}


def hedge_disruption_risk(session: Session, network: str, scenarios: list | None = None,
                          probabilities: list | None = None, reveal_week: int = 3) -> dict:
    net = session.network(network)
    names = list(scenarios or net.stochastic_set)
    if probabilities is None:
        if scenarios is not None and set(names) != set(net.stochastic_set):
            raise ToolError("give probabilities for a custom scenario set")
        probabilities = [net.scenario_specs[n]["probability"] for n in names]
    if len(probabilities) != len(names) or any(float(p) < 0 for p in probabilities) or sum(map(float, probabilities)) <= 0:
        raise ToolError("probabilities must be non-negative, one per scenario, with a positive sum")
    if len(names) < 2:
        raise ToolError("hedging needs at least two scenarios")
    total = sum(float(p) for p in probabilities)
    objects = [session.scenario(network, n, float(p) / total) for n, p in zip(names, probabilities)]
    specs = dict(net.scenario_specs)
    for sc in objects:
        specs.setdefault(sc.name, sc.to_dict())
    net.scenario_specs = specs
    result = stochastic_value(net, names, [sc.probability for sc in objects], reveal_week=int(reveal_week),
                              nominal="normal" if "normal" in names else names[0],
                              mip_gap=min(session.mip_gap, 1e-3), time_limit=max(session.time_limit, 60))
    if "plans" not in result:
        raise ToolError("the stochastic model or one of its scenarios is infeasible")
    plans = result.pop("plans")
    stochastic_id = session.store(network, "stochastic hedge", plans["stochastic"],
                                  {"scenarios": names, "probabilities": probabilities, "reveal_week": reveal_week})
    nominal_id = session.store(network, "nominal plan, adapted after reveal", plans["nominal_evaluated"],
                               {"scenarios": names, "probabilities": probabilities, "fixed_first_stage": "nominal"})
    per = []
    for name, v in result["per_scenario"].items():
        saving = v["nominal_plan_usd"] - v["stochastic_plan_usd"]
        per.append({"scenario": name, "probability_pct": round(100 * v["probability"], 1),
                    "stochastic_usd": round(v["stochastic_plan_usd"]), "nominal_usd": round(v["nominal_plan_usd"]),
                    "perfect_information_usd": round(v["perfect_information_usd"]),
                    "saving_vs_nominal_usd": round(saving),
                    "saving_vs_nominal_pct": round(100 * saving / v["nominal_plan_usd"], 2)})
    stage = result["first_stage"]
    recommendation = []
    for lane, kg in stage["stochastic"]["air_reservation_kg_per_week"].items():
        nominal_kg = stage["nominal"]["air_reservation_kg_per_week"].get(lane, 0.0)
        recommendation.append(f"reserve {kg:g} kg/week of {lane} block space (nominal plan: {nominal_kg:g})")
    for lane, kg in stage["stochastic"]["early_shipments_kg"].items():
        nominal_kg = stage["nominal"]["early_shipments_kg"].get(lane, 0.0)
        if abs(kg - nominal_kg) > 0.5:
            recommendation.append(f"ship {kg:g} kg on {lane} before week {reveal_week} (nominal plan: {nominal_kg:g})")
    return {"network": network, "reveal_week": int(reveal_week),
            "plan_ids": {"stochastic": stochastic_id, "nominal": nominal_id},
            "scenarios": [{"name": s["name"], "probability_pct": round(100 * s["probability"], 1)}
                          for s in result["scenarios"]],
            "expected_cost_usd": {"stochastic_RP": round(result["RP"]), "nominal_EEV": round(result["EEV"]),
                                  "perfect_information_WS": round(result["WS"])},
            "VSS_usd": round(result["VSS"]), "VSS_pct": round(result["VSS_pct_of_RP"], 2),
            "EVPI_usd": round(result["EVPI"]), "EVPI_pct": round(result["EVPI_pct_of_RP"], 2),
            "VSS_interval_usd": [round(x) for x in result["VSS_interval"]],
            "per_scenario": per, "first_stage_recommendation": recommendation,
            "note": "VSS = value of planning with the scenarios instead of the nominal forecast; "
                    "EVPI = most one should pay for knowing the scenario in advance."}


def explain_plan_tool(session: Session, plan_id: str, scenario: str | None = None) -> dict:
    stored = session.get(plan_id)
    result = explain_plan(session.network(stored.network), stored.plan, scenario)
    result["plan_id"] = plan_id
    result["mode_kg_by_week"] = result.get("mode_kg_by_week", [])[:8]
    return result


def write_memo_tool(session: Session, plan_ids: list, question: str, title: str | None = None) -> dict:
    from .memo import write_memo
    if not isinstance(plan_ids, list) or not 1 <= len(plan_ids) <= 6:
        raise ToolError("plan_ids must list 1-6 plan ids")
    path, headline = write_memo(session, [session.get(pid) for pid in plan_ids], question, title)
    return {"path": path.as_posix(), "headline": headline}


def _r(value, digits=0):
    if value is None:
        return None
    return round(value) if digits == 0 else round(value, digits)


NETWORK = {"type": "string", "enum": list(NETWORKS),
           "description": "asml = ASML-inspired spare parts NL->Singapore; "
                          "marvell = Marvell-inspired chips Taiwan/Malaysia->Singapore"}
TOOLS = {tool.name: tool for tool in (
    Tool("describe_network",
         "Describe a network: SKUs, lanes (mode, lead time, freight rate, weekly capacity, reservable air space, "
         "kg CO2e per kg shipped) and predefined scenarios.",
         {"type": "object", "properties": {"network": NETWORK}, "required": ["network"]}, describe_network),
    Tool("create_scenario",
         "Define a custom disruption or demand scenario from a notice or a what-if question. Only use numbers "
         "stated by the user; omitted fields keep normal values and are reported as assumptions.",
         {"type": "object", "properties": {
             "network": NETWORK,
             "name": {"type": "string", "description": "snake_case id, e.g. suez_closure_w5_10"},
             "description": {"type": "string"},
             "disruptions": {"type": "array", "items": {"type": "object", "properties": {
                 "mode": {"type": "string", "enum": ["air", "ocean", "road"], "description": "every lane of this mode"},
                 "lanes": {"type": "array", "items": {"type": "string"}, "description": "explicit lane ids"},
                 "start_week": {"type": "integer", "minimum": 1},
                 "end_week": {"type": "integer", "minimum": 1},
                 "extra_lead_weeks": {"type": "integer", "minimum": 0, "maximum": 8},
                 "capacity_change_pct": {"type": "number", "description": "-30 = capacity falls 30%; -100 closes it"},
                 "cost_change_pct": {"type": "number", "description": "+60 = freight x1.6 (air: spot price)"},
                 "distance_factor": {"type": "number", "description": "reroute distance multiplier, e.g. 1.42"}},
                 "required": ["start_week", "end_week"]}},
             "demand_change_pct": {"type": "number", "description": "+30 = committed demand x1.3"},
             "demand_weeks": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2}},
          "required": ["network", "name"]}, create_scenario),
    Tool("solve_plan",
         "Optimise one deterministic inventory-transport plan (MILP, HiGHS) for a scenario, optionally with a "
         "carbon cap (% of the uncapped plan's emissions), a carbon price or a service-level floor. Returns a "
         "plan_id and KPIs.",
         {"type": "object", "properties": {
             "network": NETWORK,
             "scenario": {"type": "string", "description": "predefined or created scenario name; default normal"},
             "carbon_cap_pct": {"type": "number", "description": "75 = emissions at most 75% of uncapped plan"},
             "carbon_price_usd_per_t": {"type": "number"},
             "service_level_pct": {"type": "number", "description": "floor on 1 - backlog unit-weeks / demand"},
             "label": {"type": "string"}},
          "required": ["network"]}, solve_plan),
    Tool("compare_plans",
         "Compare 2-6 plans against the first one: cost, emissions, air share, service, with absolute and % "
         "changes. Use this instead of computing differences yourself.",
         {"type": "object", "properties": {"plan_ids": {"type": "array", "items": {"type": "string"}}},
          "required": ["plan_ids"]}, compare_plans),
    Tool("carbon_frontier",
         "Cost of cutting emissions: epsilon-constraint frontier at several caps with marginal abatement cost "
         "(USD per tonne CO2e) and LP shadow prices, at a 98% service floor.",
         {"type": "object", "properties": {
             "network": NETWORK, "scenario": {"type": "string"},
             "levels_pct": {"type": "array", "items": {"type": "number"}, "description": "e.g. [90, 75, 60]"}},
          "required": ["network"]}, carbon_frontier_tool),
    Tool("hedge_disruption_risk",
         "Two-stage stochastic plan when it is unknown which scenario will happen: early shipments and air "
         "block-space reservation are fixed before reveal_week, later decisions adapt. Returns VSS, EVPI, "
         "per-scenario costs versus the nominal plan and a first-stage recommendation.",
         {"type": "object", "properties": {
             "network": NETWORK,
             "scenarios": {"type": "array", "items": {"type": "string"}, "description": "default: configured set"},
             "probabilities": {"type": "array", "items": {"type": "number"}},
             "reveal_week": {"type": "integer", "minimum": 1}},
          "required": ["network"]}, hedge_disruption_risk),
    Tool("explain_plan",
         "Explain a plan: binding capacities, cost drivers, weekly mode mix, air reservation and shadow prices.",
         {"type": "object", "properties": {"plan_id": {"type": "string"}, "scenario": {"type": "string"}},
          "required": ["plan_id"]}, explain_plan_tool),
    Tool("write_memo",
         "Write a decision memo (Markdown) comparing plans for a planner or manager; returns its file path.",
         {"type": "object", "properties": {
             "plan_ids": {"type": "array", "items": {"type": "string"}},
             "question": {"type": "string"}, "title": {"type": "string"}},
          "required": ["plan_ids", "question"]}, write_memo_tool),
)}
