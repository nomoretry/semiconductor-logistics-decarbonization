"""Model v2: which truck runs which trip and when, how it charges, and what charging equipment and grid connection to
build, in one mixed-integer program; deterministic or two-stage stochastic.

Time. A week has 168 hourly slots; slot 0 is Monday 00:00. A truck leaving at slot t drives slots t .. t+D-1 and is
at the other end from slot t+D. Cargo is planned by week: every order leaves in some week by some channel, and every
week takes one week type (crossing condition and number of extra trips). Every week type in use gets one
representative week of truck operations. All trucks stand at the depot at every Monday 00:00, each with a state of
charge that is the same at every week boundary of a scenario; that makes all weeks of one type the same problem, so
one representative week serves them exactly. ``horizon_check`` re-solves the operations over an unbroken horizon
without that restriction.

Trucks follow a time-space network: wait at the depot, drive to the destination, stay there between the minimum and
the maximum dwell, drive back. Background trips of other customers must leave within their windows; every other
departure is an extra trip that carries chips. Staying longer than the minimum dwell costs driver and truck time.

Charging. A truck charges where it stands from connectors of a chosen power tier, within the site's connection and
its substation's headroom. Connector time may be shared between trucks within an hour.

First stage (before a scenario is known, shared by all scenarios): open sites, connectors per power tier, site
connection upgrades, which substation each opened site is wired to, substation expansions, and leasing a truck for
the season. Everything else is second stage, decided per scenario.

Modes:
    joint     everything together (plan C);
    relaxed   step 1 of the sequential plan: no equipment; a truck may charge wherever it stands at the planning
              power, energy at the planning price;
    diesel    the same trips with diesel trucks (plan A).
``fixed_schedule`` (step 2 of the sequential plan) freezes cargo, week types, the lease and every departure;
``fixed_first_stage`` freezes the first stage; ``transport_cap`` bounds the step-1 cost (the best a sequential
process can do when it breaks ties among equally cheap schedules in favour of charging).
"""
from __future__ import annotations

import copy
import time
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any

import pulp

from .data import Order, apply_overrides, capital_share, export_orders, load_config, orders_from
from .model import ROAD_CHANNELS, STATUS, dispatch_windows

CONFIG_V2 = Path(__file__).with_name("config_v2.json")
FIRST_STAGE_KEYS = ("sites", "fleet", "finance", "horizon")


def load_v2(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    return load_config(overrides, path=CONFIG_V2)


class StartedHiGHS(pulp.HiGHS):  # type: ignore[misc]
    """PuLP's HiGHS interface, handing the solver a starting solution (variable name -> value) when one is given.
    HiGHS checks it and keeps it as the first incumbent only if it is feasible."""

    def __init__(self, start: dict[str, float] | None = None, **options: Any) -> None:
        super().__init__(**options)
        self.start = start

    def callSolver(self, lp: Any) -> None:
        if self.start:
            import highspy
            columns = lp.variables()
            values = [0.0] * len(columns)
            for var in columns:
                values[var.index] = float(self.start.get(var.name, 0.0))
            solution = highspy.HighsSolution()
            solution.col_value = values
            solution.value_valid = True
            lp.solverModel.setSolution(solution)
        lp.solverModel.run()


# ----------------------------------------------------------------------------------------------- inputs

@dataclass
class Scenario:
    """Second-stage data of one possible season."""
    name: str
    probability: float
    config: dict[str, Any]
    orders: list[Order]
    air: dict[str, Any]
    conditions: list[str]
    instance: str


@lru_cache(maxsize=8)
def _exported(weekly_plan: str) -> dict[str, Any]:
    return export_orders(weekly_plan)


def make_scenario(config: dict[str, Any], name: str = "normal", probability: float = 1.0, *,
                  overrides: dict[str, Any] | None = None, weekly_plan: str = "normal",
                  congested_weeks: Sequence[int] = (), instance: str = "base", with_chips: bool = True) -> Scenario:
    """``overrides`` change second-stage parameters only; first-stage ones must be equal in every scenario."""
    for path in overrides or {}:
        if path.split(".")[0] in FIRST_STAGE_KEYS and not path.endswith(("energy_usd_per_kwh",
                                                                         "unavailable_hours_of_day",
                                                                         "demand_usd_per_kw_month",
                                                                         "grid_kg_co2e_per_kwh")):
            raise ValueError(f"'{path}' is a first-stage parameter and cannot change between scenarios")
    scenario_config = apply_overrides(config, overrides)
    cargo = _exported(weekly_plan)
    weeks = int(scenario_config["horizon"]["weeks"])
    air = {**cargo["air_fallback"], "road_old_kg_co2e_per_kg": cargo["lane"]["kg_co2e_per_kg_old_basis"]}
    if not scenario_config["air_fallback"]["enabled"]:
        air["available_kg"] = [0.0] * weeks
    conditions = ["congested" if w in congested_weeks else "normal" for w in range(1, weeks + 1)]
    return Scenario(name, probability, scenario_config, orders_from(cargo) if with_chips else [], air, conditions,
                    instance)


def leg(config: dict[str, Any], condition: str) -> tuple[int, float]:
    """Hours and kWh of one leg in either direction."""
    corridor, truck = config["corridor"], config["truck"]
    crossing = int(corridor["crossing_hours"][condition])
    return (int(corridor["drive_hours"]) + crossing,
            corridor["distance_km"] * truck["drive_kwh_per_km"] + truck["auxiliary_kw_waiting"] * crossing)


def departure_cost(config: dict[str, Any], slot: int, condition: str) -> float:
    trips = config["trips"]
    hour, day = slot % 24, (slot // 24) % 7
    start, end = trips["night_hours"]
    cost = float(trips["trip_cost_usd"])
    if hour >= start or hour < end:
        cost += trips["night_premium_usd"]
    if day == 6:
        cost += trips["sunday_premium_usd"]
    if condition == "congested":
        cost += trips["congested_surcharge_usd"]
    return cost


def diesel_litres(config: dict[str, Any], condition: str) -> float:
    """One round trip."""
    diesel, corridor = config["diesel"], config["corridor"]
    crossing = int(corridor["crossing_hours"][condition])
    return float(2 * (corridor["distance_km"] * diesel["litres_per_km"] + diesel["idle_litres_per_hour"] * crossing))


def trucks_of(config: dict[str, Any], instance: str) -> tuple[list[str], list[str]]:
    spec = config["background"]["instances"][instance]
    own = list(config["fleet"]["own"])[: int(spec["own_trucks"])]
    if len(own) < int(spec["own_trucks"]):
        own += [f"T{i + 1}" for i in range(len(own), int(spec["own_trucks"]))]
    return own, list(config["fleet"]["lease"])


# ----------------------------------------------------------------------------------------------- truck operations

@dataclass
class Horizon:
    """A stretch of truck operations: one representative week (template) or an unbroken run of weeks."""
    tag: str
    slots: int
    conditions: list[str]            # per week covered
    windows: list[list[int]]         # allowed departure slots of each background trip
    extra: list[Any]                 # extra departures required in each week (int or expression)
    week_starts: list[int]


def _week_of(horizon: Horizon, slot: int) -> int:
    return min(slot // 168, len(horizon.conditions) - 1)


def operations(m: Any, cfg: dict[str, Any], horizon: Horizon, own: list[str], leasable: list[str], *,
               mode: str, used: Any, boundary: dict[str, Any], lease: dict[str, Any], plant: dict[str, Any] | None,
               at_depot_at_ends: bool = True, symmetric: bool = False) -> dict[str, Any]:
    """Variables and constraints of truck movements, energy and charging over one horizon.

    Returns the transport cost, energy cost, site power expressions and the variables. ``plant`` carries the first-stage
    variables (``None`` in relaxed and diesel modes)."""
    tag, T = horizon.tag, horizon.slots
    corridor, truck = cfg["corridor"], cfg["truck"]
    h_min, h_max = int(corridor["sg_min_dwell_hours"]), int(corridor["sg_max_dwell_hours"])
    turnaround = int(corridor["my_min_turnaround_hours"])
    eta = float(truck["charging_efficiency"])
    trucks = own + leasable
    wage = corridor["waiting_usd_per_hour"]
    carbon = float(cfg["carbon"]["price_usd_per_t"]) / 1000  # USD per kg CO2e

    def condition(t: int) -> str:
        return horizon.conditions[_week_of(horizon, t)]

    # Round-trip patterns: truck k leaves the depot at s, stays h hours at the destination, comes back.
    patterns: list[dict[str, Any]] = []

    def add(kind: tuple[str, int], k: str, s: int) -> None:
        out_d, out_e = leg(cfg, condition(s))
        for h in range(h_min, h_max + 1):
            back = s + out_d + h
            if back >= T:
                return
            back_d, back_e = leg(cfg, condition(back))
            if back + back_d > T - 1:  # the truck must stand at the depot in the last slot
                return
            patterns.append({"kind": kind, "truck": k, "s": s, "h": h, "arrive": s + out_d, "back": back,
                             "home": back + back_d, "out_e": out_e / out_d, "back_e": back_e / back_d,
                             "cost": departure_cost(cfg, s % 168, condition(s)) + wage * (h - h_min)})

    for k in trucks:
        for b, window in enumerate(horizon.windows):
            for s in window:
                if 0 <= s < T:
                    add(("task", b), k, s)
        for w, start in enumerate(horizon.week_starts):
            end = horizon.week_starts[w + 1] if w + 1 < len(horizon.week_starts) else T
            for s in range(start, end):
                add(("extra", w), k, s)
    x = {i: m.add_variable(f"x_{tag}_{i}", cat="Binary") for i in range(len(patterns))}
    busy: dict[tuple[str, int], list[Any]] = {}       # trip plus loading time after it: no other departure
    away: dict[tuple[str, int], list[Any]] = {}       # not at the depot
    there: dict[tuple[str, int], list[Any]] = {}      # at the destination
    drive: dict[tuple[str, int], list[Any]] = {}      # kWh used in the slot
    for i, pat in enumerate(patterns):
        k, var = pat["truck"], x[i]
        for t in range(pat["s"], min(T, pat["home"] + turnaround)):
            busy.setdefault((k, t), []).append(var)
        for t in range(pat["s"], pat["home"]):
            away.setdefault((k, t), []).append(var)
        for t in range(pat["arrive"], pat["back"]):
            there.setdefault((k, t), []).append(var)
        for t in range(pat["s"], pat["arrive"]):
            drive.setdefault((k, t), []).append(pat["out_e"] * var)
        for t in range(pat["back"], pat["home"]):
            drive.setdefault((k, t), []).append(pat["back_e"] * var)
    for (k, t), terms in busy.items():
        if len(terms) > 1:
            m += (pulp.lpSum(terms) <= 1, f"busy_{tag}_{k}_{t}")
    for b in range(len(horizon.windows)):
        mine = [x[i] for i, pat in enumerate(patterns) if pat["kind"] == ("task", b)]
        if not mine:
            raise ValueError(f"background trip {b} of {tag} cannot leave and return within the horizon")
        m += (pulp.lpSum(mine) == used, f"task_{tag}_{b}")
    if symmetric and len(own) > 1:
        # Own trucks are identical and start every week alike, so the first one may take the first trip.
        first = [x[i] for i, pat in enumerate(patterns) if pat["kind"] == ("task", 0) and pat["truck"] == own[0]]
        m += (pulp.lpSum(first) == used, f"first_{tag}")
    for w in range(len(horizon.week_starts)):
        mine = [x[i] for i, pat in enumerate(patterns) if pat["kind"] == ("extra", w)]
        m += (pulp.lpSum(mine) == horizon.extra[w], f"extra_{tag}_{w}")
    for k in leasable:
        mine = [x[i] for i, pat in enumerate(patterns) if pat["truck"] == k]
        m += (pulp.lpSum(mine) <= (len(horizon.windows) + 2 * len(horizon.week_starts)) * lease[k], f"lease_{tag}_{k}")
    at_my = {(k, t): 1 - pulp.lpSum(away.get((k, t), [])) for k in trucks for t in range(T)}
    at_sg = {(k, t): pulp.lpSum(there.get((k, t), [])) for k in trucks for t in range(T)}
    out: dict[str, Any] = {"tag": tag, "x": x, "patterns": patterns, "at_my": at_my, "at_sg": at_sg,
                           "trucks": trucks, "slots": T,
                           "transport_cost": pulp.lpSum(pat["cost"] * x[i] for i, pat in enumerate(patterns)),
                           "site_power": {}, "energy_cost": 0, "energy": {}, "power": {}, "occupancy": {}}
    if mode == "diesel":
        fuel = cfg["diesel"]["price_usd_per_litre"] + carbon * cfg["diesel"]["kg_co2e_per_litre"]
        out["energy_cost"] = pulp.lpSum(diesel_litres(cfg, condition(pat["s"])) * fuel * x[i]
                                        for i, pat in enumerate(patterns))
        return out
    duration = {0: leg(cfg, condition(0))}

    def driving(k: str, t: int) -> Any:
        return pulp.lpSum(drive.get((k, t), []))

    energy = {(k, t): m.add_variable(f"e_{tag}_{k}_{t}", truck["min_energy_kwh"], truck["battery_usable_kwh"])
              for k in trucks for t in range(T + 1)}
    for k in trucks:
        m += (energy[k, 0] == boundary[k], f"start_{tag}_{k}")
        m += (energy[k, T] >= boundary[k], f"end_{tag}_{k}")
    power: dict[tuple[str, str, int], Any] = {}
    occupancy: dict[tuple[str, str, str, int], Any] = {}
    site_power: dict[tuple[str, int], list[Any]] = {}
    by_truck: dict[tuple[str, int], list[Any]] = {}          # charging power of a truck in a slot
    plugs_side: dict[tuple[str, str, int], list[Any]] = {}   # connector time of a truck on one side in a slot
    energy_cost = []
    if mode == "relaxed":
        plan = cfg["planning"]
        for k in trucks:
            for t in range(T):
                for side, at in (("MY", at_my), ("SG", at_sg)):
                    p = m.add_variable(f"p_{tag}_{k}_{side}_{t}", 0)
                    power[k, side, t] = p
                    by_truck.setdefault((k, t), []).append(p)
                    m += (p <= plan["charge_kw"] * at[k, t], f"plan_{tag}_{k}_{side}_{t}")
                    energy_cost.append(plan["energy_usd_per_kwh"] * p)
    else:
        assert plant is not None
        for j, site in cfg["sites"].items():
            closed = {h % 24 for h in site["unavailable_hours_of_day"]}
            delay = int(site["access_delay_hours"])
            for k in trucks:
                for t in range(T):
                    if t % 24 in closed or (site["side"] == "SG" and t < duration[0][0] + delay):
                        continue
                    p = m.add_variable(f"p_{tag}_{k}_{j}_{t}", 0)
                    power[k, j, t] = p
                    tiers, plugs = [], []
                    for q, tier in site["tiers"].items():
                        o = m.add_variable(f"o_{tag}_{k}_{j}_{q}_{t}", 0, 1)
                        occupancy[k, j, q, t] = o
                        tiers.append(tier["kw"] * o)
                        plugs.append(o)
                    m += (p <= pulp.lpSum(tiers), f"rating_{tag}_{k}_{j}_{t}")
                    for h in range(1, delay + 1):  # this site can be used only after the first hours there
                        m += (pulp.lpSum(plugs) <= at_sg[k, t - h], f"access_{tag}_{k}_{j}_{t}_{h}")
                    plugs_side.setdefault((k, site["side"], t), []).extend(plugs)
                    site_power.setdefault((j, t), []).append(p)
                    by_truck.setdefault((k, t), []).append(p)
                    energy_cost.append((site["energy_usd_per_kwh"] + carbon * site["grid_kg_co2e_per_kwh"]) * p)
        for (k, side, t), plugs in plugs_side.items():
            at = at_my if side == "MY" else at_sg
            m += (pulp.lpSum(plugs) <= at[k, t], f"plug_{tag}_{k}_{side}_{t}")
        for (k, t), charging in by_truck.items():
            if len(charging) > 1:
                m += (pulp.lpSum(charging) <= truck["vehicle_max_charge_kw"], f"vmax_{tag}_{k}_{t}")
        for j, site in cfg["sites"].items():
            for q in site["tiers"]:
                for t in range(T):
                    plugs = [occupancy[k, j, q, t] for k in trucks if (k, j, q, t) in occupancy]
                    if plugs:
                        m += (pulp.lpSum(plugs) <= plant["n"][j, q], f"conn_{tag}_{j}_{q}_{t}")
            for t in range(T):
                if (j, t) in site_power:
                    m += (pulp.lpSum(site_power[j, t]) <= plant["capacity"][j], f"cap_{tag}_{j}_{t}")
        grid(m, cfg, plant, site_power, tag, T)
    for k in trucks:
        for t in range(T):
            m += (energy[k, t + 1] == energy[k, t] + eta * pulp.lpSum(by_truck.get((k, t), []))
                  - driving(k, t), f"soc_{tag}_{k}_{t}")
    out.update(energy_cost=pulp.lpSum(energy_cost), energy=energy, power=power, occupancy=occupancy,
               site_power={key: pulp.lpSum(v) for key, v in site_power.items()})
    return out


def grid(m: Any, cfg: dict[str, Any], plant: dict[str, Any], site_power: dict[tuple[str, int], list[Any]], tag: str,
         T: int) -> None:
    """Each site draws through the substation it is wired to; each substation stays within its headroom."""
    load: dict[tuple[str, int], list[Any]] = {}
    for j, site in cfg["sites"].items():
        options = list(site["connections"])
        for t in range(T):
            if (j, t) not in site_power:
                continue
            if len(options) == 1:
                load.setdefault((options[0], t), []).append(pulp.lpSum(site_power[j, t]))
                continue
            flows = []
            ceiling = site["base_kw"] + sum(u["kw"] for u in site["upgrades"])
            for s in options:
                f = m.add_variable(f"f_{tag}_{j}_{s}_{t}", 0)
                m += (f <= ceiling * plant["conn"][j, s], f"wire_{tag}_{j}_{s}_{t}")
                flows.append(f)
                load.setdefault((s, t), []).append(f)
            m += (pulp.lpSum(flows) == pulp.lpSum(site_power[j, t]), f"split_{tag}_{j}_{t}")
    for (s, t), terms in load.items():
        sub = cfg["substations"][s]
        m += (pulp.lpSum(terms) <= sub["headroom_kw"] + pulp.lpSum(x["kw"] * plant["exp"][s, x["id"]]
                                                                   for x in sub["expansions"]),
              f"sub_{tag}_{s}_{t}")


# ----------------------------------------------------------------------------------------------- first stage

def first_stage(m: Any, cfg: dict[str, Any], leasable: list[str], fixed: dict[str, Any] | None,
                with_plant: bool) -> tuple[dict[str, Any] | None, dict[str, Any], Any]:
    weeks = int(cfg["horizon"]["weeks"])
    lease = {k: m.add_variable(f"lease_{k}", cat="Binary") for k in leasable}
    cost = [cfg["fleet"]["lease"][k]["usd_per_week"] * weeks * lease[k] for k in leasable]
    if fixed is not None:
        for k in leasable:
            lease[k].lowBound = lease[k].upBound = float(fixed["lease"].get(k, 0))
    if not with_plant:
        return None, lease, pulp.lpSum(cost)
    share = capital_share(cfg, weeks)
    plant: dict[str, Any] = {"open": {}, "n": {}, "up": {}, "conn": {}, "exp": {}, "capacity": {}}
    for j, site in cfg["sites"].items():
        opened = plant["open"][j] = m.add_variable(f"open_{j}", cat="Binary")
        counts = []
        for q, tier in site["tiers"].items():
            n = plant["n"][j, q] = m.add_variable(f"n_{j}_{q}", 0, site["max_connectors"], cat="Integer")
            counts.append(n)
            cost.append(share * tier["capex_usd"] * n)
        m += (pulp.lpSum(counts) <= site["max_connectors"] * opened, f"open_first_{j}")
        ups = []
        for u in site["upgrades"]:
            up = plant["up"][j, u["id"]] = m.add_variable(f"up_{j}_{u['id']}", cat="Binary")
            ups.append(up)
            cost.append(share * u["capex_usd"] * up)
        if ups:
            m += (pulp.lpSum(ups) <= opened, f"one_upgrade_{j}")
        wires = []
        for s, capex in site["connections"].items():
            c = plant["conn"][j, s] = m.add_variable(f"conn_{j}_{s}", cat="Binary")
            wires.append(c)
            cost.append(share * capex * c)
        m += (pulp.lpSum(wires) == opened, f"wired_{j}")
        cost.append(share * site["open_capex_usd"] * opened)
        plant["capacity"][j] = site["base_kw"] * opened + pulp.lpSum(
            u["kw"] * plant["up"][j, u["id"]] for u in site["upgrades"])
    for s, sub in cfg["substations"].items():
        for x in sub["expansions"]:
            plant["exp"][s, x["id"]] = m.add_variable(f"exp_{s}_{x['id']}", cat="Binary")
            cost.append(share * x["capex_usd"] * plant["exp"][s, x["id"]])
    if fixed is not None and "plant" in fixed:
        values = fixed["plant"]
        for key, group in (("open", plant["open"]), ("n", plant["n"]), ("up", plant["up"]),
                           ("conn", plant["conn"]), ("exp", plant["exp"])):
            for name, var in group.items():
                label = name if isinstance(name, str) else "|".join(name)
                var.lowBound = var.upBound = float(values[key].get(label, 0))
    return plant, lease, pulp.lpSum(cost)


def needed_sides(config: dict[str, Any], scenarios: Sequence[Scenario]) -> list[str]:
    """Sides of the corridor where every feasible plan charges.

    The depot always: a truck comes home below full and must be full again at the next week boundary. The
    destination when a round trip needs more than the battery holds: the truck arrives with at most battery - E and
    must leave with at least E + reserve."""
    truck = config["truck"]
    need = {"MY"}
    for sc in scenarios:
        for c in set(sc.conditions):
            if 2 * leg(sc.config, c)[1] + truck["min_energy_kwh"] > truck["battery_usable_kwh"]:
                need.add("SG")
    return sorted(need)


def side_cuts(m: Any, config: dict[str, Any], plant: dict[str, Any], scenarios: Sequence[Scenario]) -> None:
    """Valid inequalities: every scenario runs background trips, so each side in ``needed_sides`` has an open site
    with at least one connector. They remove no feasible plan; they stop the linear relaxation from opening sites and
    buying connectors in fractions, which left most of the equipment cost out of the dual bound."""
    for side in needed_sides(config, scenarios):
        sites = [j for j, s in config["sites"].items() if s["side"] == side]
        m += (pulp.lpSum(plant["open"][j] for j in sites) >= 1, f"side_open_{side}")
        m += (pulp.lpSum(n for (j, _), n in plant["n"].items() if j in sites) >= 1, f"side_plug_{side}")


# ----------------------------------------------------------------------------------------------- the whole model

def week_bounds(cfg: dict[str, Any], mode: str, condition: str, departures: int,
                trucks: int) -> tuple[float, float, float, float]:
    """Lower and upper bounds on one week's transport and energy cost with ``departures`` round trips.

    Transport: every round trip pays at least the plain trip cost, at most the dearest trip and the longest wait.
    Energy: a round trip needs 2E kWh at the battery. When 2E plus the reserve exceeds the battery, at least
    2E + reserve - battery of it must be charged at the destination (the truck arrives with at most battery - E and
    must leave with at least E + reserve); the rest at the cheapest price of either side. The upper bound adds a
    full battery per truck at the dearest price."""
    corridor, truck = cfg["corridor"], cfg["truck"]
    carbon = float(cfg["carbon"]["price_usd_per_t"]) / 1000  # USD per kg CO2e, part of every energy price
    cheapest = min(departure_cost(cfg, t, condition) for t in range(168))
    dearest = max(departure_cost(cfg, t, condition) for t in range(168))
    wait = (corridor["sg_max_dwell_hours"] - corridor["sg_min_dwell_hours"]) * corridor["waiting_usd_per_hour"]
    low_t, high_t = departures * cheapest, departures * (dearest + wait) + 1
    if mode == "diesel":
        fuel = departures * diesel_litres(cfg, condition) * (cfg["diesel"]["price_usd_per_litre"]
                                                             + carbon * cfg["diesel"]["kg_co2e_per_litre"])
        return low_t, high_t, fuel, fuel + 1
    eta = float(truck["charging_efficiency"])
    energy = 2 * leg(cfg, condition)[1]
    if mode == "relaxed":
        price = cfg["planning"]["energy_usd_per_kwh"]
        refill = trucks * (truck["battery_usable_kwh"] - truck["min_energy_kwh"])
        return low_t, high_t, price * departures * energy / eta, price * (departures * energy + refill) / eta + 1
    sides: dict[str, list[float]] = {}
    for site in cfg["sites"].values():
        sides.setdefault(site["side"], []).append(site["energy_usd_per_kwh"] + carbon * site["grid_kg_co2e_per_kwh"])
    at_destination = max(0.0, energy + truck["min_energy_kwh"] - truck["battery_usable_kwh"])
    low_e = departures * (at_destination * min(sides["SG"]) + (energy - at_destination) * min(min(v) for v in
                                                                                               sides.values())) / eta
    refill = trucks * (truck["battery_usable_kwh"] - truck["min_energy_kwh"])
    high_e = max(max(v) for v in sides.values()) * (departures * energy + refill) / eta + 1
    return low_t, high_t, low_e, high_e


def week_types(scenario: Scenario) -> list[tuple[str, int]]:
    cap = int(scenario.config["trips"]["max_extra_per_week"])
    return [(c, n) for c in sorted(set(scenario.conditions)) for n in range(cap + 1)]


def windows_of(cfg: dict[str, Any], instance: str, offset: int = 0) -> list[list[int]]:
    spec = cfg["background"]["instances"][instance]
    return [list(range(offset + d - spec["window_before"], offset + d + spec["window_after"] + 1))
            for d in spec["departures"]]


def solve(config: dict[str, Any], scenarios: Sequence[Scenario], *, mode: str = "joint",
          fixed_first_stage: dict[str, Any] | None = None, fixed_schedule: dict[str, Any] | None = None,
          transport_cap: float | None = None, mip_gap: float = 1e-4, time_limit: float = 600.0,
          threads: int | None = None, start: dict[str, float] | None = None,
          random_seed: int | None = None, neighbourhood: dict[str, Any] | None = None) -> dict[str, Any]:
    """``random_seed`` changes only the solver's search order (HiGHS option), so ties among equally good plans may be
    broken differently; the model is unchanged.

    ``neighbourhood`` is one fix-and-optimize step: every trip outside its free parts is fixed to a given schedule,
    while cargo, the first stage and charging stay free. The schedule is ``"trips"`` ({scenario: {week type:
    [trip, ...]}}, as read back; a week type it does not list stays free) or ``"values"`` (variable values of an
    earlier solution). ``"free"`` lists parts ``{"trucks": [...], "window": [first, last]}``; a missing key means all
    trucks or the whole week, and a trip stays free when its truck and departure hour fall in any part."""
    if mode not in ("joint", "relaxed", "diesel"):
        raise ValueError("mode must be joint, relaxed or diesel")
    if abs(sum(s.probability for s in scenarios) - 1) > 1e-9:
        raise ValueError("scenario probabilities must sum to one")
    instances = {s.instance for s in scenarios}
    if len(instances) != 1:
        raise ValueError("all scenarios must use the same background instance")
    started = time.perf_counter()
    m = pulp.LpProblem("fleet", pulp.LpMinimize)
    own, leasable = trucks_of(config, scenarios[0].instance)
    fixed = fixed_first_stage or (fixed_schedule["first_stage"] if fixed_schedule else None)
    if fixed is not None and "plant" not in fixed and mode == "joint" and fixed_first_stage is None:
        fixed = {"lease": fixed["lease"]}
    plant, lease, first_cost = first_stage(m, config, leasable, fixed, with_plant=(mode == "joint"))
    if plant is not None:
        side_cuts(m, config, plant, scenarios)
    expected: list[Any] = []
    transport_terms: list[Any] = []
    per: dict[str, Any] = {}
    for sc in scenarios:
        per[sc.name] = _scenario(m, sc, own, leasable, mode, plant, lease, fixed_schedule)
        expected.append(sc.probability * per[sc.name]["cost"])
        transport_terms.append(sc.probability * per[sc.name]["transport"])
    if neighbourhood is not None:
        _freeze_trips(per, neighbourhood)
    if transport_cap is not None:
        m += (first_cost if mode != "joint" else pulp.lpSum(
            config["fleet"]["lease"][k]["usd_per_week"] * int(config["horizon"]["weeks"]) * lease[k]
            for k in leasable)) + pulp.lpSum(transport_terms) <= transport_cap, "transport_cap"
    m += first_cost + pulp.lpSum(expected)
    build = time.perf_counter() - started
    m.solve(StartedHiGHS(start, msg=False, timeLimit=time_limit, gapRel=mip_gap, mip_heuristic_effort=0.3,
                         **({"threads": threads} if threads else {}),
                         **({"random_seed": int(random_seed)} if random_seed is not None else {})))
    status = STATUS.get(m.sol_status, "undefined")
    info = getattr(getattr(m, "solverModel", None), "getInfo", lambda: None)()
    stats = {"variables": len(m.variables()), "integers": sum(v.cat == pulp.LpInteger for v in m.variables()),
             "constraints": m.numConstraints(), "build_seconds": round(build, 2),
             "solve_seconds": round(time.perf_counter() - started - build, 2),
             "mip_gap": getattr(info, "mip_gap", None), "dual_bound": getattr(info, "mip_dual_bound", None)}
    result: dict[str, Any] = {"mode": mode, "status": status, "stats": stats,
                              "scenarios": [s.name for s in scenarios]}
    if status not in ("optimal", "feasible"):
        return result
    result["objective_usd"] = float(pulp.value(m.objective))
    result["first_stage"] = _read_first_stage(plant, lease)
    result["first_stage_cost_usd"] = float(pulp.value(first_cost))
    result["solution"] = {sc.name: _read_scenario(per[sc.name], sc) for sc in scenarios}
    result["transport_usd"] = float(pulp.value(pulp.lpSum(transport_terms)))
    result["values"] = {v.name: float(v.varValue) for v in m.variables() if v.varValue}
    return result


def _scenario(m: Any, sc: Scenario, own: list[str], leasable: list[str], mode: str, plant: dict[str, Any] | None,
              lease: dict[str, Any], fixed_schedule: dict[str, Any] | None) -> dict[str, Any]:
    cfg, name = sc.config, sc.name
    weeks = len(sc.conditions)
    trucks = own + leasable
    if cfg["truck"]["week_boundary"] == "full":
        boundary: dict[str, Any] = {k: cfg["truck"]["battery_usable_kwh"] for k in trucks}
    else:
        boundary = {k: m.add_variable(f"s_{name}_{k}", cfg["truck"]["min_energy_kwh"],
                                      cfg["truck"]["battery_usable_kwh"]) for k in trucks}
        for a, b in pairwise(own):  # identical own trucks: order their boundary energy to break symmetry
            m += (boundary[a] >= boundary[b], f"sym_{name}_{a}_{b}")
    types = week_types(sc)
    cargo = _cargo(m, sc, types, fixed_schedule)
    used = {(c, n): m.add_variable(f"u_{name}_{c}_{n}", cat="Binary") for c, n in types}
    for (w, c, n), z in cargo["z"].items():
        m += (used[c, n] >= z, f"used_{name}_{w}_{c}_{n}")
    for c, n in types:
        if n == 0 and fixed_schedule is None:
            # The week without extra trips of every condition is always scheduled, whether or not a week takes it.
            # This removes no optimum: an extra-trip week's schedule without its extra trip, charging less after it,
            # is such a week within the same equipment, connectors and peak. It stops the linear relaxation from
            # running a fraction of the background trips (and so charging less, with a lower peak) by splitting weeks
            # between types. Its cost is billed only for the weeks that take it.
            used[c, n].lowBound = 1
            continue
        # Otherwise a week type no week takes has no trips, so it cannot claim chargers or peak power.
        m += (used[c, n] <= pulp.lpSum(z for (_, cc, nn), z in cargo["z"].items() if (cc, nn) == (c, n)),
              f"unused_{name}_{c}_{n}")
    ops = {}
    for c, n in types:
        horizon = Horizon(f"{name}_{c}_{n}", 168, [c], windows_of(cfg, sc.instance), [n * used[c, n]], [0])
        ops[c, n] = operations(m, cfg, horizon, own, leasable, mode=mode, used=used[c, n], boundary=boundary,
                               lease=lease, plant=plant, symmetric=cfg["truck"]["week_boundary"] == "full")
        if fixed_schedule is not None:
            _fix_schedule(ops[c, n], fixed_schedule["solution"][name]["types"].get(f"{c}|{n}"), used[c, n])
    # Each week pays the transport and energy of its own week type.
    # Each week pays its own week type's transport and energy. Upper bounds make the switch exact; lower bounds,
    # valid for every feasible schedule of a type, keep the linear relaxation from dropping these costs.
    tasks = len(windows_of(cfg, sc.instance))
    bounds = {(c, n): week_bounds(cfg, mode, c, tasks + n, len(trucks)) for c, n in types}
    bills_t, bills_e = [], []
    for w in range(1, weeks + 1):
        bt = m.add_variable(f"bt_{name}_{w}", 0)
        be = m.add_variable(f"be_{name}_{w}", 0)
        bills_t.append(bt)
        bills_e.append(be)
        mine = [(c, n, z) for (ww, c, n), z in cargo["z"].items() if ww == w]
        # When another type is chosen the bill is already at least that type's lower bound, so each big-M term
        # only has to reach down to the lowest lower bound among this week's types.
        floor_t = min(bounds[c, n][0] for c, n, _ in mine)
        floor_e = min(bounds[c, n][2] for c, n, _ in mine)
        for c, n, z in mine:
            _, high_t, _, high_e = bounds[c, n]
            m += (bt >= ops[c, n]["transport_cost"] - (high_t - floor_t) * (1 - z), f"bt_{name}_{w}_{c}_{n}")
            m += (be >= ops[c, n]["energy_cost"] - (high_e - floor_e) * (1 - z), f"be_{name}_{w}_{c}_{n}")
        m += (bt >= pulp.lpSum(bounds[c, n][0] * z for c, n, z in mine), f"bt_low_{name}_{w}")
        m += (be >= pulp.lpSum(bounds[c, n][2] * z for c, n, z in mine), f"be_low_{name}_{w}")
    demand = 0
    peaks = {}
    if mode == "joint":
        months = weeks / float(cfg["finance"]["weeks_per_month"])
        for j in cfg["sites"]:
            peaks[j] = m.add_variable(f"peak_{name}_{j}", 0)
            for op in ops.values():
                for (jj, t), expr in op["site_power"].items():
                    if jj == j:
                        m += (expr <= peaks[j], f"peak_{op['tag']}_{t}_{j}")
        demand = pulp.lpSum(cfg["sites"][j]["demand_usd_per_kw_month"] * months * peaks[j] for j in peaks)
    plan_price = cfg["planning"]["energy_usd_per_kwh"] / cfg["truck"]["charging_efficiency"]
    plan_energy = pulp.lpSum(plan_price * (tasks + n) * 2 * leg(cfg, c)[1] * z for (_, c, n), z in cargo["z"].items())
    transport = pulp.lpSum(bills_t) + cargo["cost"] + plan_energy
    return {"cost": pulp.lpSum(bills_t) + pulp.lpSum(bills_e) + cargo["cost"] + demand, "transport": transport,
            "ops": ops, "cargo": cargo, "used": used, "boundary": boundary, "peaks": peaks, "types": types,
            "bills_t": bills_t, "bills_e": bills_e, "demand": demand}


def _cargo(m: Any, sc: Scenario, types: list[tuple[str, int]], fixed: dict[str, Any] | None) -> dict[str, Any]:
    """Which week every order leaves and by which channel, and the week type of every week."""
    cfg, name = sc.config, sc.name
    carrier = cfg["carrier"]
    weeks = len(sc.conditions)
    holding = float(cfg["cargo"].get("holding_multiplier", 1.0))
    z = {(w, c, n): m.add_variable(f"z_{name}_{w}_{c}_{n}", cat="Binary")
         for w in range(1, weeks + 1) for c, n in types if c == sc.conditions[w - 1]}
    for w in range(1, weeks + 1):
        m += (pulp.lpSum(v for (ww, _, _), v in z.items() if ww == w) == 1, f"type_{name}_{w}")
    ship: dict[tuple[str, int, str], Any] = {}
    by_air: dict[str, Any] = {}
    cost = []
    for i, order in enumerate(sc.orders):
        by_air[order.id] = m.add_variable(f"air_{name}_{i}", 0)
        carbon = float(cfg["carbon"]["price_usd_per_t"]) / 1000
        cost.append((sc.air["spot_usd_per_kg"] + carbon * sc.air["kg_co2e_per_kg"]) * order.mass_kg
                    * by_air[order.id])
        terms = [by_air[order.id]]
        for week, early in dispatch_windows(order, cfg, sc.conditions):
            for channel in ROAD_CHANNELS:
                var = ship[order.id, week, channel] = m.add_variable(f"x_{name}_{i}_{week}_{channel}", 0)
                terms.append(var)
                rate = (holding * order.holding_usd_per_unit_week * early if early > 0
                        else order.backlog_usd_per_unit_week * -early)
                if channel == "premium":
                    rate += carrier["premium_usd_per_kg"] * order.mass_kg
                if rate:
                    cost.append(rate * var)
        m += (pulp.lpSum(terms) == order.units, f"serve_{name}_{i}")
    mass = {o.id: o.mass_kg for o in sc.orders}
    factor = float(cfg["congestion"]["consolidation_factor"])
    for w in range(1, weeks + 1):
        flown = [o.mass_kg * by_air[o.id] for o in sc.orders if o.due_week == w]
        if flown:
            m += (pulp.lpSum(flown) <= sc.air["available_kg"][w - 1], f"air_{name}_{w}")
        scale = factor if sc.conditions[w - 1] == "congested" else 1.0
        for channel, limit in (("consolidated", carrier["weekly_consolidation_kg"] * scale),
                               ("premium", carrier["premium_kg_per_week"] * scale)):
            load = [mass[o] * v for (o, ww, ch), v in ship.items() if ww == w and ch == channel]
            if load:
                m += (pulp.lpSum(load) <= limit, f"{channel}_{name}_{w}")
        load = [mass[o] * v for (o, ww, ch), v in ship.items() if ww == w and ch == "extra_trip"]
        if load:
            trips = pulp.lpSum(n * v for (ww, _, n), v in z.items() if ww == w)
            m += (pulp.lpSum(load) <= carrier["extra_trip_chip_capacity_kg"] * trips, f"extra_{name}_{w}")
    if fixed is not None:
        chosen = fixed["solution"][name]
        for (w, c, n), v in z.items():
            v.lowBound = v.upBound = float(chosen["week_types"][str(w)] == f"{c}|{n}")
        # Quantities are kept within a tolerance band, not at the solver's exact output: a plan that met a capacity
        # row within the solver's tolerance can exceed it by a few 1e-7 once every quantity is fixed, and presolve
        # then declares the fixed plan infeasible (it did in fleet/border_congestion).
        tol = 1e-6
        flows = {(s["order"], s["week"], s["channel"]): s["units"] for s in chosen["shipments"]}
        for key, v in ship.items():
            value = flows.get(key, 0.0)
            v.lowBound, v.upBound = max(0.0, value - tol), value + tol
        flown_units = {a["order"]: a["units"] for a in chosen["air"]}
        for oid, v in by_air.items():
            value = flown_units.get(oid, 0.0)
            v.lowBound, v.upBound = max(0.0, value - tol), value + tol
    return {"z": z, "ship": ship, "air": by_air, "cost": pulp.lpSum(cost)}


def _fix_schedule(op: dict[str, Any], schedule: dict[str, Any] | None, used: Any) -> None:
    """Step 2 of the sequential plan: the trips of step 1, unchanged."""
    if schedule is None:
        used.lowBound = used.upBound = 0
        return
    chosen = {(t["kind"], t["truck"], t["depart"], t["dwell"]) for t in schedule["trips"]}
    for i, pat in enumerate(op["patterns"]):
        key = (f"{pat['kind'][0]}{pat['kind'][1]}", pat["truck"], pat["s"], pat["h"])
        op["x"][i].lowBound = op["x"][i].upBound = float(key in chosen)


def _inside(pat: dict[str, Any], part: dict[str, Any]) -> bool:
    trucks, window = part.get("trucks"), part.get("window")
    return (trucks is None or pat["truck"] in trucks) and (window is None or window[0] <= pat["s"] < window[1])


def _freeze_trips(per: dict[str, Any], hood: dict[str, Any]) -> int:
    """Fix the trips outside the neighbourhood's free parts (see ``solve``); returns how many were fixed."""
    values: dict[str, float] = hood.get("values") or {}
    saved: dict[str, Any] | None = hood.get("trips")
    parts: list[dict[str, Any]] = hood.get("free") or []
    fixed = 0
    for name, s in per.items():
        for (c, n), op in s["ops"].items():
            chosen = None
            if saved is not None:
                listed = saved.get(name, {}).get(f"{c}|{n}")
                if listed is None:
                    continue  # a week type the saved plan does not use stays free
                chosen = {(t["kind"], t["truck"], int(t["depart"]), int(t["dwell"])) for t in listed}
            for i, pat in enumerate(op["patterns"]):
                if any(_inside(pat, part) for part in parts):
                    continue
                var = op["x"][i]
                if chosen is not None:
                    value = float((f"{pat['kind'][0]}{pat['kind'][1]}", pat["truck"], pat["s"], pat["h"]) in chosen)
                else:
                    value = float(round(values.get(var.name, 0.0)))
                var.lowBound = var.upBound = value
                fixed += 1
    return fixed


# ----------------------------------------------------------------------------------------------- reading results

def _value(var: Any) -> float:
    if isinstance(var, (int, float)):
        return float(var)
    return 0.0 if var is None or var.varValue is None else float(var.varValue)


def _read_first_stage(plant: dict[str, Any] | None, lease: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"lease": {k: round(_value(v)) for k, v in lease.items()}}
    if plant is None:
        return out
    out["plant"] = {key: {(name if isinstance(name, str) else "|".join(name)): round(_value(v))
                          for name, v in plant[key].items()} for key in ("open", "n", "up", "conn", "exp")}
    return out


def _read_scenario(s: dict[str, Any], sc: Scenario) -> dict[str, Any]:
    cargo = s["cargo"]
    week_type = {w: f"{c}|{n}" for (w, c, n), v in cargo["z"].items() if _value(v) > 0.5}
    out: dict[str, Any] = {
        "week_types": {str(w): week_type[w] for w in sorted(week_type)},
        "shipments": [{"order": o, "week": w, "channel": ch, "units": _value(v)}
                      for (o, w, ch), v in cargo["ship"].items() if _value(v) > 1e-9],
        "air": [{"order": o, "units": _value(v)} for o, v in cargo["air"].items() if _value(v) > 1e-9],
        "boundary_kwh": {k: _value(v) for k, v in s["boundary"].items()},
        "peak_kw": {j: _value(v) for j, v in s["peaks"].items()},
        "types": {}}
    taken = set(week_type.values())
    for (c, n), op in s["ops"].items():
        if f"{c}|{n}" not in taken:  # scheduled but taken by no week (see _scenario)
            continue
        out["types"][f"{c}|{n}"] = read_operations(op)
    return out


def read_operations(op: dict[str, Any]) -> dict[str, Any]:
    trucks, slots = op["trucks"], op["slots"]
    chosen = [pat for i, pat in enumerate(op["patterns"]) if _value(op["x"][i]) > 0.5]
    record: dict[str, Any] = {
        "trips": [{"kind": f"{pat['kind'][0]}{pat['kind'][1]}", "truck": pat["truck"], "depart": pat["s"],
                   "dwell": pat["h"], "arrive": pat["arrive"], "back": pat["back"], "home": pat["home"]}
                  for pat in sorted(chosen, key=lambda q: (q["truck"], q["s"]))],
        "slots": slots, "energy_kwh": {}, "power_kw": {}, "occupancy": {}}
    if op["energy"]:
        record["energy_kwh"] = {k: [round(_value(op["energy"][k, t]), 6) for t in range(slots + 1)] for k in trucks}
    for (k, j, t), v in op["power"].items():
        if _value(v) > 1e-7:
            record["power_kw"].setdefault(k, {}).setdefault(j, {})[str(t)] = _value(v)
    for (k, j, q, t), v in op["occupancy"].items():
        if _value(v) > 1e-7:
            record["occupancy"].setdefault(k, {}).setdefault(j, {}).setdefault(q, {})[str(t)] = _value(v)
    return record


# ----------------------------------------------------------------------------------------------- plans A, B, B*, C

def sequential(config: dict[str, Any], scenarios: Sequence[Scenario], *, best_tie_break: bool = False,
               step1: dict[str, Any] | None = None, **options: Any) -> dict[str, Any]:
    """Plan B: transport and truck schedules first (charging assumed available everywhere), then equipment and
    charging for that schedule. ``best_tie_break`` gives B*: among schedules as cheap as step 1, the one that is best
    for charging. ``step1`` reuses a step-1 result already solved for the same scenarios."""
    if step1 is None:
        step1 = solve(config, scenarios, mode="relaxed", **{k: v for k, v in options.items() if k != "start"})
    if "solution" not in step1:
        return {"mode": "sequential", "status": step1["status"], "step_1": step1}
    if best_tie_break:
        cap = step1["objective_usd"] * (1 + 1e-7) + 1e-3
        step2 = solve(config, scenarios, mode="joint", transport_cap=cap, **options)
        label = "sequential_best"
    else:
        step2 = solve(config, scenarios, mode="joint", fixed_schedule=step1, **options)
        label = "sequential"
    return {**step2, "mode": label, "step_1": {k: step1[k] for k in ("status", "stats", "objective_usd")},
            "step_1_result": step1}


def copy_config(config: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(config)


# ----------------------------------------------------------------------------------------------- representative weeks

def horizon_check(config: dict[str, Any], sc: Scenario, plan: dict[str, Any], *, free_first_stage: bool = False,
                  mip_gap: float = 1e-3, time_limit: float = 900.0) -> dict[str, Any]:
    """Re-solve the truck operations of a plan over one unbroken horizon of all weeks.

    Cargo and the number of extra trips in every week are those of ``plan``; so are the equipment and the lease unless
    ``free_first_stage``, which also lets the horizon choose them (and adds their cost to the objective). Unlike the
    representative weeks, trucks need not stand at the depot or be full at Monday 00:00, and a trip may run across a
    week boundary. The plan's own weeks laid end to end are a feasible solution of this problem: when the plan carries
    its trips, they are fixed first, the remaining (continuous) variables are solved, and that solution starts the
    free solve. The cost of the representative-week restriction is the plan's cost minus the horizon's cost; it is at
    least zero up to the solver's gap."""
    weeks = len(sc.conditions)
    m = pulp.LpProblem("horizon", pulp.LpMinimize)
    own, leasable = trucks_of(config, sc.instance)
    plant, lease, first_cost = first_stage(m, config, leasable, None if free_first_stage else plan["first_stage"],
                                           with_plant=True)
    assert plant is not None
    side_cuts(m, config, plant, [sc])
    types = plan["solution"][sc.name]["week_types"]
    extra = [int(types[str(w)].split("|")[1]) for w in range(1, weeks + 1)]
    tasks = len(windows_of(sc.config, sc.instance))
    windows = [window for w in range(weeks) for window in windows_of(sc.config, sc.instance, offset=168 * w)]
    horizon = Horizon(f"{sc.name}_horizon", 168 * weeks, list(sc.conditions), windows, extra,
                      [168 * w for w in range(weeks)])
    full = sc.config["truck"]["battery_usable_kwh"]
    op = operations(m, sc.config, horizon, own, leasable, mode="joint", used=1,
                    boundary={k: full for k in own + leasable}, lease=lease, plant=plant, symmetric=True)
    months = weeks / float(sc.config["finance"]["weeks_per_month"])
    demand = []
    for j, site in sc.config["sites"].items():
        peak = m.add_variable(f"peak_{j}", 0)
        for (jj, t), expr in op["site_power"].items():
            if jj == j:
                m += (expr <= peak, f"peak_{j}_{t}")
        demand.append(site["demand_usd_per_kw_month"] * months * peak)
    operating = op["transport_cost"] + op["energy_cost"] + pulp.lpSum(demand)
    m += operating + (first_cost if free_first_stage else 0)
    started = time.perf_counter()
    start, start_note = _concatenated_start(m, op, plan, sc, tasks, plant, lease, free_first_stage)
    m.solve(StartedHiGHS(start, msg=False, timeLimit=time_limit, gapRel=mip_gap, mip_heuristic_effort=0.3))
    info = getattr(getattr(m, "solverModel", None), "getInfo", lambda: None)()
    status = STATUS.get(m.sol_status, "undefined")
    out: dict[str, Any] = {"status": status, "solve_seconds": round(time.perf_counter() - started, 2),
                           "free_first_stage": free_first_stage, "start": start_note,
                           "integers": sum(v.cat == pulp.LpInteger for v in m.variables()),
                           "mip_gap": getattr(info, "mip_gap", None),
                           "dual_bound": getattr(info, "mip_dual_bound", None)}
    if status in ("optimal", "feasible"):
        out["objective_usd"] = float(pulp.value(m.objective))
        out["operating_cost_usd"] = float(pulp.value(operating))
        out["first_stage"] = _read_first_stage(plant, lease)
        out["first_stage_cost_usd"] = float(pulp.value(first_cost))
        out["operations"] = read_operations(op)
    return out


def _concatenated_start(m: Any, op: dict[str, Any], plan: dict[str, Any], sc: Scenario, tasks: int,
                        plant: dict[str, Any], lease: dict[str, Any],
                        free_first_stage: bool) -> tuple[dict[str, float] | None, str]:
    """The plan's representative weeks laid end to end, as a full starting solution of the horizon model."""
    scenario_plan = plan["solution"][sc.name]
    if "types" not in scenario_plan:
        return None, "none: the plan carries no trips"
    chosen = set()
    for w in range(1, len(sc.conditions) + 1):
        for trip in scenario_plan["types"][scenario_plan["week_types"][str(w)]]["trips"]:
            kind = trip["kind"]
            label = (f"task{(w - 1) * tasks + int(kind[4:])}" if kind.startswith("task") else f"extra{w - 1}")
            chosen.add((label, trip["truck"], trip["depart"] + 168 * (w - 1), trip["dwell"]))
    found = set()
    saved: list[tuple[Any, Any, Any]] = []
    for i, pat in enumerate(op["patterns"]):
        k = (f"{pat['kind'][0]}{pat['kind'][1]}", pat["truck"], pat["s"], pat["h"])
        var = op["x"][i]
        saved.append((var, var.lowBound, var.upBound))
        var.lowBound = var.upBound = float(k in chosen)
        if k in chosen:
            found.add(k)
    if free_first_stage:  # the start keeps the plan's equipment and lease
        fixed = plan["first_stage"]
        for k_name, var in lease.items():
            saved.append((var, var.lowBound, var.upBound))
            var.lowBound = var.upBound = float(fixed["lease"].get(k_name, 0))
        for group in ("open", "n", "up", "conn", "exp"):
            for name, var in plant[group].items():
                label = name if isinstance(name, str) else "|".join(name)
                saved.append((var, var.lowBound, var.upBound))
                var.lowBound = var.upBound = float(fixed["plant"][group].get(label, 0))
    note = f"{len(found)} of {len(chosen)} trips mapped"
    values = None
    if found == chosen:
        m.solve(pulp.HiGHS(msg=False, timeLimit=600))
        if STATUS.get(m.sol_status, "undefined") in ("optimal", "feasible"):
            values = {v.name: float(v.varValue) for v in m.variables() if v.varValue}
            note += "; plan's weeks feasible, used as the start"
        else:
            note += "; plan's weeks not feasible in the horizon model"
    for var, low, up in saved:
        var.lowBound, var.upBound = low, up
    return values, note
