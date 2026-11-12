"""Chip dispatch, carrier consolidation, extra truck trips and charging equipment in one mixed-integer model.

Weekly layer: every order goes by road (space left on the carrier's base trips, extra space bought on them, or an
extra truck trip) or by air. An earlier road dispatch pays holding cost, a later one the backlog penalty.

Hourly layer: one representative week per week type ("block"): the base trips and at most one extra trip, under
normal or congested border crossings. Trucks keep an energy balance and plug in where the timeline allows. The
charging constraints follow the UM charging model: a truck uses at most one connector (C02), power needs an occupied
connector (C03), connectors and site power are limited (C04, C05), energy balance and bounds (C06, C07).

One set of equipment (opened sites, connectors, connection upgrades) serves every week type that is used.

Modes:
    joint       dispatch, trips, equipment and charging decided together;
    logistics   dispatch and trips only, an extra trip's electricity priced at a planning rate (step 1 of the
                sequential plan); pass its result as ``fixed`` to a joint solve for step 2;
    diesel      the same dispatch choices with diesel trucks and no equipment.
"""
from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import pulp

from .accounting import evaluate
from .data import Block, Order, Site, build_blocks, capital_share, sites_from

ROAD_CHANNELS = ("consolidated", "premium", "extra_trip")
STATUS = {1: "optimal", 2: "feasible", 0: "not_solved", -1: "infeasible", -2: "unbounded", -3: "undefined"}


def week_conditions(weeks: int, congested_weeks: Sequence[int]) -> list[str]:
    return ["congested" if week in congested_weeks else "normal" for week in range(1, weeks + 1)]


def dispatch_windows(order: Order, config: dict[str, Any], conditions: Sequence[str]) -> list[tuple[int, int]]:
    """(dispatch week, weeks early (+) or late (-) on arrival) for every road dispatch the order may use."""
    cargo, delay = config["cargo"], int(config["congestion"]["road_delay_weeks"])
    out = []
    for week in range(max(1, order.due_week - int(cargo["release_lead_weeks"])), len(conditions) + 1):
        arrival = week + (delay if conditions[week - 1] == "congested" else 0)
        if arrival - order.due_week > int(cargo["max_late_weeks"]):
            continue
        out.append((week, order.due_week - arrival))
    return out


def solve(config: dict[str, Any], orders: Sequence[Order], *, mode: str = "joint",
          congested_weeks: Sequence[int] = (), air: dict[str, float] | None = None,
          fixed: dict[str, Any] | None = None, mip_gap: float = 1e-4, time_limit: float = 180.0) -> dict[str, Any]:
    if mode not in ("joint", "logistics", "diesel"):
        raise ValueError("mode must be joint, logistics or diesel")
    started = time.perf_counter()
    weeks = int(config["horizon"]["weeks"])
    slots = int(config["horizon"]["slots_per_week"])
    hours = float(config["horizon"]["slot_hours"])
    carrier, truck = config["carrier"], config["truck"]
    air = air or {"spot_usd_per_kg": 6.875, "kg_co2e_per_kg": 0.198253}
    conditions = week_conditions(weeks, congested_weeks)
    sites = sites_from(config)
    blocks = build_blocks(config, sites, sorted(set(conditions)))
    by_id = {block.id: block for block in blocks}
    model = pulp.LpProblem("electric_freight", pulp.LpMinimize)
    cost: list[Any] = []

    # ---- weekly layer: which week type, and how every order travels
    week_type = {(w, block.id): model.add_variable(f"z_{w}_{block.condition}_{block.option or 'none'}", cat="Binary")
                 for w in range(1, weeks + 1) for block in blocks if block.condition == conditions[w - 1]}
    for w in range(1, weeks + 1):
        model += (pulp.lpSum(v for (week, _), v in week_type.items() if week == w) == 1, f"one_type_{w}")
    ship: dict[tuple[str, int, str], Any] = {}
    by_air: dict[str, Any] = {}
    for i, order in enumerate(orders):
        by_air[order.id] = model.add_variable(f"air_{i}", 0)
        terms = [by_air[order.id]]
        cost.append(air["spot_usd_per_kg"] * order.mass_kg * by_air[order.id])
        for week, early in dispatch_windows(order, config, conditions):
            for channel in ROAD_CHANNELS:
                var = model.add_variable(f"x_{i}_{week}_{channel}", 0)
                ship[order.id, week, channel] = var
                terms.append(var)
                rate = (order.holding_usd_per_unit_week * early if early > 0
                        else order.backlog_usd_per_unit_week * -early)
                if channel == "premium":
                    rate += carrier["premium_usd_per_kg"] * order.mass_kg
                if rate:
                    cost.append(rate * var)
        model += (pulp.lpSum(terms) == order.units, f"serve_{i}")
    mass = {order.id: order.mass_kg for order in orders}
    factor = float(config["congestion"]["consolidation_factor"])
    for w in range(1, weeks + 1):
        scale = factor if conditions[w - 1] == "congested" else 1.0
        for channel, limit in (("consolidated", carrier["weekly_consolidation_kg"] * scale),
                               ("premium", carrier["premium_kg_per_week"] * scale)):
            load = [mass[o] * var for (o, week, ch), var in ship.items() if week == w and ch == channel]
            if load:
                model += (pulp.lpSum(load) <= limit, f"{channel}_{w}")
        load = [mass[o] * var for (o, week, ch), var in ship.items() if week == w and ch == "extra_trip"]
        if load:
            trips = pulp.lpSum(v for (week, block_id), v in week_type.items()
                               if week == w and by_id[block_id].option is not None)
            model += (pulp.lpSum(load) <= carrier["extra_trip_chip_capacity_kg"] * trips, f"extra_trip_{w}")
    surcharge = carrier["congested_trip_surcharge_usd"]
    base_trips = sum(len(trip["depart_hours"]) for trip in carrier["base_trips"])
    for (_, block_id), var in week_type.items():
        block = by_id[block_id]
        extra = surcharge if block.condition == "congested" else 0.0
        if block.option is not None:
            cost.append((carrier["extra_options"][block.option]["trip_cost_usd"] + extra) * var)
    constant = sum(base_trips * (carrier["trip_cost_usd"] + (surcharge if c == "congested" else 0.0))
                   for c in conditions)

    if fixed is not None:  # step 2 of the sequential plan: dispatch and trips are no longer decisions
        for (w, block_id), var in week_type.items():
            var.lowBound = var.upBound = 1.0 if fixed["week_types"][str(w)] == block_id else 0.0
        chosen = {(s["order"], s["week"], s["channel"]): s["units"] for s in fixed["shipments"]}
        for key, var in ship.items():
            var.lowBound = var.upBound = chosen.get(key, 0.0)
        flown = {a["order"]: a["units"] for a in fixed["air"]}
        for order_id, var in by_air.items():
            var.lowBound = var.upBound = flown.get(order_id, 0.0)

    # ---- energy of the trucks
    variables: dict[str, Any] = {"week_type": week_type, "ship": ship, "air": by_air}
    if mode == "diesel":
        diesel = config["diesel"]
        for (_, block_id), var in week_type.items():
            block = by_id[block_id]
            crossing = int(config["corridor"]["crossing_hours"][block.condition])
            litres = 2 * (config["corridor"]["distance_km"] * diesel["litres_per_km"]
                          + diesel["idle_litres_per_hour"] * crossing)
            trips = sum(t.trips for t in block.timelines)
            cost.append(litres * trips * diesel["price_usd_per_litre"] * var)
    elif mode == "logistics":
        for (_, block_id), var in week_type.items():
            block = by_id[block_id]
            kwh = sum(sum(t.drive_kwh) for t in block.timelines if t.extra) / truck["charging_efficiency"]
            cost.append(config["planning_energy_usd_per_kwh"] * kwh * var)
    else:
        variables.update(_charging(model, cost, config, sites, blocks, week_type, weeks, slots, hours))

    model += pulp.lpSum(cost) + constant
    build_seconds = time.perf_counter() - started
    model.solve(pulp.HiGHS(msg=False, timeLimit=time_limit, gapRel=mip_gap))
    status = STATUS.get(model.sol_status, "undefined")
    info = getattr(getattr(model, "solverModel", None), "getInfo", lambda: None)()
    stats = {"variables": len(model.variables()), "constraints": model.numConstraints(),
             "binary_or_integer": sum(v.cat == pulp.LpInteger for v in model.variables()),
             "build_seconds": round(build_seconds, 2),
             "solve_seconds": round(time.perf_counter() - started - build_seconds, 2),
             "mip_gap": getattr(info, "mip_gap", None), "dual_bound": getattr(info, "mip_dual_bound", None)}
    result: dict[str, Any] = {"mode": mode, "status": status, "stats": stats, "congested_weeks": list(congested_weeks),
                              "sequential_step_2": fixed is not None}
    if status not in ("optimal", "feasible"):
        return result
    result["objective_usd"] = float(pulp.value(model.objective))
    result["solution"] = _read(variables, orders, blocks, sites, conditions, slots, mode)
    result["accounting"] = evaluate(config, orders, result["solution"], mode=mode, congested_weeks=congested_weeks,
                                    air=air)
    recomputed = result["accounting"]["objective_usd"]
    drift = abs(result["objective_usd"] - recomputed) / max(1.0, abs(result["objective_usd"]))
    result["objective_drift"] = drift
    if mode != "logistics" and drift > 1e-6:
        result["accounting"]["issues"].append(f"solver objective differs from the recomputation by {drift:.2e}")
    return result


def _charging(model: Any, cost: list[Any], config: dict[str, Any], sites: dict[str, Site], blocks: list[Block],
              week_type: dict[tuple[int, str], Any], weeks: int, slots: int, hours: float) -> dict[str, Any]:
    truck = config["truck"]
    eta = float(truck["charging_efficiency"])
    share = capital_share(config, weeks)
    months = weeks / float(config["finance"]["weeks_per_month"])
    opened = {j: model.add_variable(f"open_{j}", cat="Binary") for j in sites}
    connectors = {j: model.add_variable(f"n_{j}", 0, site.max_connectors, cat="Integer") for j, site in sites.items()}
    upgrade = {(j, u.id): model.add_variable(f"up_{j}_{u.id}", cat="Binary") for j, site in sites.items()
               for u in site.upgrades}
    peak = {j: model.add_variable(f"peak_{j}", 0) for j in sites}
    for j, site in sites.items():
        model += (connectors[j] <= site.max_connectors * opened[j], f"open_first_{j}")
        if site.upgrades:
            model += (pulp.lpSum(upgrade[j, u.id] for u in site.upgrades) <= opened[j], f"one_upgrade_{j}")
        cost.append(share * (site.open_capex_usd * opened[j] + site.connector_capex_usd * connectors[j]
                             + pulp.lpSum(u.capex_usd * upgrade[j, u.id] for u in site.upgrades)))
        cost.append(site.demand_usd_per_kw_month * months * peak[j])
    used = {block.id: model.add_variable(f"used_{block.condition}_{block.option or 'none'}", cat="Binary")
            for block in blocks}
    for (w, block_id), var in week_type.items():
        model += (used[block_id] >= var, f"used_{w}_{block_id.replace(':', '_')}")
    for block in blocks:
        if block.option is None and any(b == block.id for (_, b) in week_type):
            used[block.id].lowBound = 1  # the base trips run in every week of this condition
    rule = config["substation_rule"]
    plug: dict[tuple[str, str, str, int], Any] = {}
    power: dict[tuple[str, str, str, int], Any] = {}
    energy: dict[tuple[str, str, int], Any] = {}
    block_cost = {}
    for b, block in enumerate(blocks):
        site_power: dict[tuple[str, int], list[Any]] = {(j, t): [] for j in sites for t in range(slots)}
        site_plugs: dict[tuple[str, int], list[Any]] = {(j, t): [] for j in sites for t in range(slots)}
        for v, line in enumerate(block.timelines):
            for t in range(slots + 1):
                energy[block.id, line.vehicle, t] = model.add_variable(
                    f"e_{b}_{v}_{t}", truck["min_energy_kwh"], truck["battery_usable_kwh"])
            start = energy[block.id, line.vehicle, 0]
            start.lowBound = start.upBound = truck["initial_energy_kwh"]
            model += (energy[block.id, line.vehicle, slots] >= truck["initial_energy_kwh"], f"end_{b}_{v}")
            for t in range(slots):
                here = [j for j, site in sites.items() if line.plug[j][t]]
                charge = []
                for j in here:
                    a = model.add_variable(f"a_{b}_{v}_{j}_{t}", 0, 1,
                                           cat="Continuous" if sites[j].share_within_hour else "Binary")
                    p = model.add_variable(f"p_{b}_{v}_{j}_{t}", 0)
                    plug[block.id, line.vehicle, j, t], power[block.id, line.vehicle, j, t] = a, p
                    model += (p <= sites[j].connector_kw * a, f"c03_{b}_{v}_{j}_{t}")
                    site_power[j, t].append(p)
                    site_plugs[j, t].append(a)
                    charge.append(p)
                if len(here) > 1:
                    model += (pulp.lpSum(plug[block.id, line.vehicle, j, t] for j in here) <= 1, f"c02_{b}_{v}_{t}")
                # An extra truck drives only in a week type that is actually used.
                burn = line.drive_kwh[t] * (used[block.id] if line.extra else 1)
                model += (energy[block.id, line.vehicle, t + 1] == energy[block.id, line.vehicle, t]
                          + eta * hours * pulp.lpSum(charge) - burn, f"c06_{b}_{v}_{t}")
        for j, site in sites.items():
            capacity = site.base_kw * opened[j] + pulp.lpSum(u.kw * upgrade[j, u.id] for u in site.upgrades)
            for t in range(slots):
                if not site_power[j, t]:
                    continue
                total = pulp.lpSum(site_power[j, t])
                model += (pulp.lpSum(site_plugs[j, t]) <= connectors[j], f"c04_{b}_{j}_{t}")
                model += (total <= capacity, f"c05_{b}_{j}_{t}")
                model += (total <= peak[j], f"peak_{b}_{j}_{t}")
                if site.substation and rule == "split":
                    model += (total <= config["substations"][site.substation]["split_kw"][j], f"split_{b}_{j}_{t}")
        if rule == "shared":
            for name, spec in config["substations"].items():
                members = [j for j, site in sites.items() if site.substation == name]
                for t in range(slots):
                    terms = [p for j in members for p in site_power[j, t]]
                    if terms:
                        model += (pulp.lpSum(terms) <= spec["headroom_kw"], f"shared_{b}_{name}_{t}")
        block_cost[block.id] = pulp.lpSum(sites[j].energy_usd_per_kwh * hours * p
                                          for (j, _), terms in site_power.items() for p in terms)
    # A week pays the electricity of its own week type. The bound is loose only for week types not chosen.
    dearest = max(site.energy_usd_per_kwh for site in sites.values())
    for w in range(1, weeks + 1):
        bill = model.add_variable(f"bill_{w}", 0)
        cost.append(bill)
        for (week, block_id), var in week_type.items():
            if week != w:
                continue
            block = next(b for b in blocks if b.id == block_id)
            ceiling = dearest * (sum(sum(t.drive_kwh) for t in block.timelines) + truck["battery_usable_kwh"]
                                 * len(block.timelines)) / eta
            model += (bill >= block_cost[block_id] - ceiling * (1 - var), f"bill_{w}_{block_id.replace(':', '_')}")
    return {"opened": opened, "connectors": connectors, "upgrade": upgrade, "peak": peak, "used": used,
            "plug": plug, "power": power, "energy": energy}


def _read(variables: dict[str, Any], orders: Sequence[Order], blocks: list[Block], sites: dict[str, Site],
          conditions: Sequence[str], slots: int, mode: str) -> dict[str, Any]:
    def value(var: Any) -> float:
        return 0.0 if var.varValue is None else float(var.varValue)

    chosen = {w: block_id for (w, block_id), var in variables["week_type"].items() if value(var) > 0.5}
    solution: dict[str, Any] = {
        "week_types": {str(w): chosen[w] for w in sorted(chosen)},
        "shipments": [{"order": o, "week": w, "channel": ch, "units": value(var)}
                      for (o, w, ch), var in variables["ship"].items() if value(var) > 1e-9],
        "air": [{"order": o, "units": value(var)} for o, var in variables["air"].items() if value(var) > 1e-9]}
    if mode != "joint":
        return solution
    solution["equipment"] = {
        j: {"opened": round(value(variables["opened"][j])), "connectors": round(value(variables["connectors"][j])),
            "upgrade": next((u.id for u in site.upgrades if value(variables["upgrade"][j, u.id]) > 0.5), None)}
        for j, site in sites.items()}
    solution["blocks"] = {}
    for block in blocks:
        vehicles = {}
        for line in block.timelines:
            vehicles[line.vehicle] = {
                "energy_kwh": [value(variables["energy"][block.id, line.vehicle, t]) for t in range(slots + 1)],
                "plug": {j: [value(variables["plug"][block.id, line.vehicle, j, t])
                             if (block.id, line.vehicle, j, t) in variables["plug"] else 0.0 for t in range(slots)]
                         for j in sites},
                "power_kw": {j: [value(variables["power"][block.id, line.vehicle, j, t])
                                 if (block.id, line.vehicle, j, t) in variables["power"] else 0.0
                                 for t in range(slots)] for j in sites}}
        solution["blocks"][block.id] = {"used": value(variables["used"][block.id]) > 0.5, "vehicles": vehicles}
    return solution


def solve_sequential(config: dict[str, Any], orders: Sequence[Order], **options: Any) -> dict[str, Any]:
    """Plan dispatch and trips first without charging equipment, then fit equipment and charging to that plan."""
    first = solve(config, orders, mode="logistics", **options)
    if "solution" not in first:
        return {"mode": "sequential", "status": first["status"], "step_1": first}
    second = solve(config, orders, mode="joint", fixed=first["solution"], **options)
    return {**second, "mode": "sequential", "step_1": {"status": first["status"], "stats": first["stats"],
                                                       "objective_usd": first["objective_usd"]}}
