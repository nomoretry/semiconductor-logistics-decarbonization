"""Two-stage stochastic MILP for multi-SKU, multi-modal semiconductor logistics.

One formulation covers three uses:

* deterministic planning: one scenario with probability 1;
* two-stage stochastic planning: decisions departing before ``reveal_week``
  and the seasonal air block-space reservation are shared by every scenario
  (non-anticipativity); later decisions adapt to the realised scenario;
* evaluation of a given first stage (EEV) through ``fixed_first_stage``.

Decisions per scenario k, SKU s, lane l (``lane_id`` in the code) and departure week t:
  x[k,s,l,t]  units shipped, arriving at t + lead(l, t, k); continuous by default
              (tactical flows), integer with ``integer_shipments=True``
  y[k,l,t]    binary lane-week activation (pays the lane's fixed cost)
  a_res, a_spot  air kg on reserved block space / on the spot market
  R[l]        first-stage reserved air kg per week (fee paid every week)
  I, B        end-of-week inventory and backlog; U terminal shortfall

Units: SKU units, kg per week of capacity, USD and kg CO2e (reported in t).
Weeks are 1-based in the API and 0-based inside this module.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pulp

from .accounting import evaluate
from .data import Network, Scenario

STATUS = {1: "optimal", 2: "feasible", 0: "not_solved", -1: "infeasible", -2: "unbounded", -3: "undefined"}


@dataclass
class Plan:
    network: str
    scenarios: list[Scenario]
    reveal_week: int
    status: str
    objective: float | None
    kpis: dict | None
    per_scenario: dict
    solution: dict
    duals: dict
    stats: dict
    settings: dict
    issues: list[str] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return self.status in ("optimal", "feasible")

    @property
    def scenario_names(self) -> list[str]:
        return [s.name for s in self.scenarios]

    def first_stage(self, reveal_week: int) -> dict:
        """Decisions departing before ``reveal_week`` (scenario 0) plus the air reservation."""
        cut = reveal_week - 1

        def early(part):
            return {key[1:]: v for key, v in self.solution.get(part, {}).items() if key[0] == 0 and key[-1] < cut}

        return {"ship": early("ship"), "act": early("act"), "air_res": early("air_res"),
                "air_spot": early("air_spot"), "order": early("order"),
                "reserve": dict(self.solution.get("reserve", {}))}


def solve(net: Network, scenarios=None, *, reveal_week: int = 1, carbon_cap_kg: float | None = None,
          carbon_price: float = 0.0, service_level: float | None = None, objective: str = "cost",
          terminal_hard: bool = False, sku_order_fee: float = 0.0, fixed_first_stage: dict | None = None,
          duals: bool = False, tighten: bool = False, integer_shipments: bool = False,
          time_limit: float = 60.0, mip_gap: float = 1e-3) -> Plan:
    scenarios = list(scenarios) if scenarios else [net.scenario("normal")]
    total = sum(sc.probability for sc in scenarios)
    if total <= 0:
        raise ValueError("scenario probabilities must sum to a positive number")
    scenarios = [sc.with_probability(sc.probability / total) for sc in scenarios]
    for sc in scenarios:
        net.validate(sc)
    if not 1 <= reveal_week <= net.weeks:
        raise ValueError(f"reveal_week must be within 1..{net.weeks}")
    if len(scenarios) > 1:
        for sc in scenarios:
            starts = [d.start_week for d in sc.disruptions] + ([sc.demand_weeks[0]] if sc.demand_weeks else [])
            if any(start < reveal_week for start in starts):
                raise ValueError(f"scenario '{sc.name}' starts before reveal_week {reveal_week}; "
                                 "a disruption must be revealed no later than it begins")
    if objective not in ("cost", "emissions"):
        raise ValueError("objective must be 'cost' or 'emissions'")
    if service_level is not None and not 0 < service_level <= 1:
        raise ValueError("service_level must be in (0, 1]")

    started = time.perf_counter()
    S, T, K, cut = len(net.skus), net.weeks, len(scenarios), reveal_week - 1
    lanes, skus = net.lanes, net.skus
    users = {lane_id: [s for s, sku in enumerate(skus) if lane_id in sku.lanes] for lane_id in lanes}
    demands = [net.demand_for(sc) for sc in scenarios]
    model = pulp.LpProblem("network_planning", pulp.LpMinimize)

    def staged(prefix, keys, **bounds):
        """One variable per scenario; a single shared variable for weeks before the reveal."""
        out = {}
        for key in keys:
            label = "_".join(map(str, key))
            if key[-1] < cut:
                shared = model.add_variable(f"{prefix}0_{label}", **bounds)
                out.update({(k, *key): shared for k in range(K)})
            else:
                out.update({(k, *key): model.add_variable(f"{prefix}_{k}_{label}", **bounds) for k in range(K)})
        return out

    ship_keys = [(s, lane_id, t) for s, sku in enumerate(skus) for lane_id in sku.lanes for t in range(T)]
    air_keys = [(lane_id, t) for lane_id, lane in lanes.items() if lane.is_air for t in range(T)]
    ship = staged("x", ship_keys, lowBound=0, cat="Integer" if integer_shipments else "Continuous")
    act = staged("y", [(lane_id, t) for lane_id in lanes for t in range(T)], cat="Binary")
    air_res = staged("ar", air_keys, lowBound=0)
    air_spot = staged("as", air_keys, lowBound=0)
    order = staged("z", ship_keys, cat="Binary") if sku_order_fee > 0 else {}
    reserve = {lane_id: model.add_variable(f"R_{lane_id}", 0, lane.reservable_kg) for lane_id, lane in lanes.items() if lane.is_air}
    inv = {(k, s, t): model.add_variable(f"I_{k}_{s}_{t}", 0) for k in range(K) for s in range(S) for t in range(T)}
    back = {(k, s, t): model.add_variable(f"B_{k}_{s}_{t}", 0) for k in range(K) for s in range(S) for t in range(T)}
    short = {} if terminal_hard else {(k, s): model.add_variable(f"U_{k}_{s}", 0) for k in range(K) for s in range(S)}

    if fixed_first_stage:
        def fix(var, value):
            var.lowBound = var.upBound = value
        for part, variables in (("ship", ship), ("act", act), ("air_res", air_res),
                                ("air_spot", air_spot), ("order", order)):
            for key, var in variables.items():
                if key[0] == 0 and key[-1] < cut:
                    fix(var, fixed_first_stage.get(part, {}).get(key[1:], 0))
        for lane_id, var in reserve.items():
            fix(var, fixed_first_stage.get("reserve", {}).get(lane_id, 0.0))

    capacity_rows = {}
    expected_cost, expected_emissions = [], []
    for k, sc in enumerate(scenarios):
        demand = demands[k]
        arrivals = [[[] for _ in range(T)] for _ in range(S)]
        cost, emissions = [], []
        for s, lane_id, t in ship_keys:
            lane, sku, week = lanes[lane_id], skus[s], t + 1
            x, lead = ship[k, s, lane_id, t], sc.lead(lane, week)
            if t + lead < T:
                arrivals[s][t + lead].append(x)
            cost.append(sku.value_usd * net.carry_rate_week * lead * x)
            emissions.append(sku.mass_kg / 1000 * sc.distance(lane, week) * lane.ef_kg_per_tkm * x)
            if not lane.is_air:
                cost.append(lane.freight_usd_per_kg * sc.cost_factor(lane, week) * sku.mass_kg * x)
            if (order or tighten) and (k == 0 or t >= cut):
                # Disaggregated linking x <= U * flag: U is the most units this SKU can usefully
                # ship on this lane-week, which tightens the LP relaxation versus load <= cap * y alone.
                room = sc.capacity(lane, week) + (lane.reservable_kg if lane.is_air else 0.0)
                useful = max(d[s].sum() for d in demands) + net.terminal_target[s]
                bound = int(min(room / sku.mass_kg, useful)) + 1
                if order:
                    model += (x <= bound * order[k, s, lane_id, t], f"order_{k}_{s}_{lane_id}_{t}")
                if tighten:
                    model += (x <= bound * act[k, lane_id, t], f"link_{k}_{s}_{lane_id}_{t}")
            if order:
                cost.append(sku_order_fee * order[k, s, lane_id, t])
        for lane_id, lane in lanes.items():
            for t in range(T):
                week = t + 1
                cost.append(lane.fixed_usd * act[k, lane_id, t])
                if lane.is_air:
                    cost.append(lane.freight_usd_per_kg * (
                        air_res[k, lane_id, t] + net.air_spot_premium * sc.cost_factor(lane, week) * air_spot[k, lane_id, t]))
                if k > 0 and t < cut:
                    continue  # shared decisions: their constraints are already in the model
                load = pulp.lpSum(skus[s].mass_kg * ship[k, s, lane_id, t] for s in users[lane_id])
                name = f"cap_{k}_{lane_id}_{t}"
                capacity_rows[name] = (sc.name, lane_id, week)
                if lane.is_air:
                    spot_cap = sc.capacity(lane, week)
                    model += (load == air_res[k, lane_id, t] + air_spot[k, lane_id, t], f"air_{k}_{lane_id}_{t}")
                    model += (air_res[k, lane_id, t] <= reserve[lane_id], f"res_{k}_{lane_id}_{t}")
                    model += (air_spot[k, lane_id, t] <= spot_cap, name)
                    model += (load <= (lane.reservable_kg + spot_cap) * act[k, lane_id, t], f"use_{k}_{lane_id}_{t}")
                else:
                    model += (load <= sc.capacity(lane, week) * act[k, lane_id, t], name)
        for s, sku in enumerate(skus):
            prev_inv, prev_back = float(net.initial_inventory[s]), 0.0
            for t in range(T):
                model += (inv[k, s, t] - back[k, s, t] == prev_inv - prev_back + pulp.lpSum(arrivals[s][t])
                          + float(net.pipeline[s, t]) - int(demand[s, t]), f"bal_{k}_{s}_{t}")
                prev_inv, prev_back = inv[k, s, t], back[k, s, t]
            position = inv[k, s, T - 1] - back[k, s, T - 1]
            if terminal_hard:
                model += (position >= float(net.terminal_target[s]), f"term_{k}_{s}")
            else:
                model += (position + short[k, s] >= float(net.terminal_target[s]), f"term_{k}_{s}")
                cost.append(sku.backlog_usd * net.terminal_penalty_weeks * short[k, s])
            holding = sku.value_usd * net.carry_rate_week + net.warehouse_usd
            cost.append(pulp.lpSum(holding * inv[k, s, t] + sku.backlog_usd * back[k, s, t] for t in range(T)))
            emissions.append(net.warehouse_kg * pulp.lpSum(inv[k, s, t] for t in range(T)))
        expected_cost.append(sc.probability * pulp.lpSum(cost))
        expected_emissions.append(sc.probability * pulp.lpSum(emissions))

    total_cost = net.reservation_usd_per_kg_week * T * pulp.lpSum(reserve.values()) + pulp.lpSum(expected_cost)
    total_emissions = pulp.lpSum(expected_emissions)
    if service_level is not None:
        allowed = (1 - service_level) * sum(sc.probability * float(d.sum()) for sc, d in zip(scenarios, demands, strict=True))
        model += (pulp.lpSum(sc.probability * pulp.lpSum(back[k, s, t] for s in range(S) for t in range(T))
                             for k, sc in enumerate(scenarios)) <= allowed, "service")
    if carbon_cap_kg is not None:
        model += (total_emissions <= float(carbon_cap_kg), "carbon_cap")
    if objective == "cost":
        model += total_cost + carbon_price / 1000 * total_emissions
    else:
        model += total_emissions + 1e-4 * total_cost  # tie-break among minimum-emission plans

    build_seconds = time.perf_counter() - started
    # Extra primal heuristics: on these instances HiGHS otherwise spends most of its time
    # improving incumbents (capped ASML instance: 60 s time-out -> 12-25 s to proven optimum).
    model.solve(pulp.HiGHS(msg=False, timeLimit=time_limit, gapRel=mip_gap, mip_heuristic_effort=0.3))
    solve_seconds = time.perf_counter() - started - build_seconds
    status = STATUS.get(model.sol_status, "undefined")
    variables = model.variables()
    info = getattr(getattr(model, "solverModel", None), "getInfo", lambda: None)()
    stats = {"variables": len(variables), "integer_variables": sum(v.cat == pulp.LpInteger for v in variables),
             "binary_variables": sum(v.cat == pulp.LpInteger and v.lowBound == 0 and v.upBound == 1
                                     for v in variables),
             "constraints": model.numConstraints(), "build_seconds": round(build_seconds, 3),
             "solve_seconds": round(solve_seconds, 3), "solver": f"HiGHS via PuLP {pulp.__version__}",
             "mip_gap": _finite(getattr(info, "mip_gap", None)),
             "dual_bound": _finite(getattr(info, "mip_dual_bound", None))}
    settings = {"reveal_week": reveal_week, "carbon_cap_kg": carbon_cap_kg, "carbon_price": carbon_price,
                "service_level": service_level, "objective": objective, "terminal_hard": terminal_hard,
                "sku_order_fee": sku_order_fee, "fixed_first_stage": bool(fixed_first_stage),
                "tighten": tighten, "integer_shipments": integer_shipments, "time_limit": time_limit,
                "mip_gap": mip_gap}
    if status not in ("optimal", "feasible"):
        return Plan(net.name, scenarios, reveal_week, status, None, None, {}, {}, {}, stats, settings)

    def value(var):
        return 0.0 if var.varValue is None else float(var.varValue)

    def keep(variables, integer=False):
        out = {}
        for key, var in variables.items():
            v = value(var)
            if abs(v) > 1e-9:
                out[key] = round(v) if integer else v
        return out

    solution = {"ship": keep(ship, integer_shipments), "act": keep(act, True), "air_res": keep(air_res),
                "air_spot": keep(air_spot), "order": keep(order, True),
                "reserve": {lane_id: value(v) for lane_id, v in reserve.items()},
                "inv": np.array([[[value(inv[k, s, t]) for t in range(T)] for s in range(S)] for k in range(K)]),
                "back": np.array([[[value(back[k, s, t]) for t in range(T)] for s in range(S)] for k in range(K)])}
    objective_value = float(pulp.value(model.objective))
    accounting = evaluate(net, scenarios, solution, carbon_price=carbon_price, sku_order_fee=sku_order_fee,
                          carbon_cap_kg=carbon_cap_kg, service_level=service_level, terminal_hard=terminal_hard)
    issues = list(accounting["issues"])
    if objective == "cost":
        drift = abs(objective_value - accounting["objective"]) / max(1.0, abs(objective_value))
        stats["objective_drift"] = drift
        if drift > 1e-6:
            issues.append(f"solver objective differs from independent accounting by {drift:.2e}")

    dual_values = {}
    if duals:
        dual_values = _duals(model, ship, act, order, capacity_rows, time_limit)
    return Plan(net.name, scenarios, reveal_week, status,
                objective_value if objective == "cost" else accounting["objective"],
                accounting["expected"], accounting["per_scenario"], solution, dual_values, stats, settings, issues)


def _duals(model, ship, act, order, capacity_rows, time_limit) -> dict:
    """Shadow prices of the LP obtained by fixing lane activations and order flags at the MIP optimum
    and relaxing shipment integrality. MIPs have no duals; this is the standard fix-and-price approach."""
    for var in set(ship.values()):
        var.cat = pulp.LpContinuous
    for variables in (act, order):
        for var in set(variables.values()):
            fixed = round(var.varValue or 0.0)
            var.lowBound = var.upBound = fixed
            var.cat = pulp.LpContinuous
    model.solve(pulp.HiGHS(msg=False, timeLimit=time_limit))
    if model.sol_status != 1:
        return {"status": STATUS.get(model.sol_status, "undefined")}
    result = {"status": "optimal", "lp_objective": float(pulp.value(model.objective)),
              "method": "LP with lane activations fixed at the MIP optimum and shipment integrality relaxed"}
    row = model.get_constraint_by_name
    if row("carbon_cap") is not None:
        result["carbon_usd_per_t"] = max(0.0, -float(row("carbon_cap").pi or 0.0) * 1000)
    if row("service") is not None:
        result["service_usd_per_unit_week"] = max(0.0, -float(row("service").pi or 0.0))
    result["capacity_usd_per_kg"] = sorted(
        ({"scenario": scenario, "lane": lane, "week": week, "usd_per_kg": round(-float(cap.pi), 4)}
         for name, (scenario, lane, week) in capacity_rows.items()
         if (cap := row(name)) is not None and cap.pi is not None and -cap.pi > 1e-6),
        key=lambda item: -item["usd_per_kg"])
    return result


def _finite(value):
    return None if value is None or not np.isfinite(value) else float(value)
