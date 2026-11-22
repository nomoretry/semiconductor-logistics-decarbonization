"""Inputs of the electric freight study: orders taken from the weekly plan, trucks, trips and charging sites."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(__file__).with_name("config.json")
ROAD, MY, SG = "ROAD", "MY", "SG"


def load_config(overrides: dict[str, Any] | None = None, path: Path = CONFIG_PATH) -> dict[str, Any]:
    """The documented configuration, with dotted-path overrides such as {"carrier.weekly_consolidation_kg": 200}."""
    config: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return apply_overrides(config, overrides)


def apply_overrides(config: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    """A copy of ``config`` with dotted-path overrides; an unknown path is an error, not a new key."""
    config = copy.deepcopy(config)
    for path, value in (overrides or {}).items():
        node = config
        *parents, last = path.split(".")
        for key in parents:
            if key not in node:
                raise KeyError(f"unknown configuration path '{path}'")
            node = node[key]
        if last not in node:
            raise KeyError(f"unknown configuration path '{path}'")
        node[last] = copy.deepcopy(value)
    return config


@dataclass(frozen=True)
class Order:
    """One dispatch of the weekly plan on the road lane: the cargo this study has to move."""
    id: str
    sku: str
    due_week: int            # the week the weekly plan dispatched it (1-based)
    units: float
    mass_kg: float           # per unit
    value_usd: float         # per unit
    holding_usd_per_unit_week: float
    backlog_usd_per_unit_week: float

    @property
    def kg(self) -> float:
        return self.units * self.mass_kg


def export_orders(scenario: str = "normal", *, lane: str = "MY_road", network: str = "marvell",
                  mip_gap: float = 1e-7, time_limit: float = 120.0) -> dict[str, Any]:
    """Solve the weekly plan and list what it sends on one lane, traceable to SKU and week, in kilograms."""
    from network_planning.data import build_network
    from network_planning.model import solve

    net = build_network(network)
    plan = solve(net, [net.scenario(scenario, 1.0)], mip_gap=mip_gap, time_limit=time_limit)
    if not plan.feasible:
        raise ValueError(f"the weekly plan for '{scenario}' is {plan.status}")
    orders = []
    for (_, s, lane_id, t), units in sorted(plan.solution["ship"].items(), key=lambda item: (item[0][3], item[0][1])):
        if lane_id != lane or units <= 1e-9:
            continue
        sku = net.skus[s]
        orders.append({"id": f"{sku.id}-w{t + 1:02d}", "sku": sku.id, "origin": sku.origin, "due_week": t + 1,
                       "units": round(units, 6), "mass_kg": sku.mass_kg, "kg": round(units * sku.mass_kg, 6),
                       "value_usd": sku.value_usd,
                       "holding_usd_per_unit_week": round(sku.value_usd * net.carry_rate_week + net.warehouse_usd, 6),
                       "backlog_usd_per_unit_week": sku.backlog_usd})
    weekly = [round(sum(o["kg"] for o in orders if o["due_week"] == week), 3) for week in range(1, net.weeks + 1)]
    road, air = net.lanes[lane], net.lanes["MY_air"]
    scenario_obj = plan.scenarios[0]
    spot_used = [plan.solution["air_spot"].get((0, air.id, t), 0.0) for t in range(net.weeks)]
    air_left = [round(max(0.0, scenario_obj.capacity(air, t + 1) - spot_used[t]), 3) for t in range(net.weeks)]
    eligible = sorted({sku.id for sku in net.skus if lane in sku.lanes})
    return {
        "source": {"network": network, "scenario": scenario, "lane": lane, "weeks": net.weeks, "seed": net.seed,
                   "plan_cost_usd": round(plan.objective_usd, 2), "plan_status": plan.status,
                   "note": "Orders are the weekly plan's dispatches on this lane; units are continuous as there."},
        "units": {"mass": "kg", "value": "USD per unit", "holding": "USD per unit-week",
                  "week": "1-based dispatch week"},
        "weekly_kg": weekly, "total_kg": round(sum(weekly), 3), "peak_weekly_kg": max(weekly),
        "lane": {"capacity_kg_per_week": road.capacity_kg, "freight_usd_per_kg": road.freight_usd_per_kg,
                 "distance_km": road.distance_km, "lead_weeks": road.lead_weeks,
                 "kg_co2e_per_kg_old_basis": round(road.kgco2e_per_kg, 6)},
        "air_fallback": {"lane": air.id, "spot_usd_per_kg": round(air.freight_usd_per_kg * net.air_spot_premium, 6),
                         "kg_co2e_per_kg": round(air.kgco2e_per_kg, 6), "available_kg": air_left,
                         "note": "Spot space on the air lane each week minus what the weekly plan already uses."},
        "eligible_skus": eligible,
        "orders": orders,
    }


def orders_from(exported: dict[str, Any]) -> list[Order]:
    return [Order(o["id"], o["sku"], int(o["due_week"]), float(o["units"]), float(o["mass_kg"]), float(o["value_usd"]),
                  float(o["holding_usd_per_unit_week"]), float(o["backlog_usd_per_unit_week"]))
            for o in exported["orders"]]


@dataclass(frozen=True)
class Upgrade:
    id: str
    kw: float
    capex_usd: float


@dataclass(frozen=True)
class Site:
    id: str
    side: str
    open_capex_usd: float
    connector_capex_usd: float
    max_connectors: int
    connector_kw: float
    base_kw: float
    upgrades: tuple[Upgrade, ...]
    energy_usd_per_kwh: float
    demand_usd_per_kw_month: float
    grid_kg_co2e_per_kwh: float
    substation: str | None
    access_delay_hours: int
    share_within_hour: bool = False   # connector time may be divided between trucks within one slot


def sites_from(config: dict[str, Any]) -> dict[str, Site]:
    return {site_id: Site(site_id, spec["side"], float(spec["open_capex_usd"]), float(spec["connector_capex_usd"]),
                          int(spec["max_connectors"]), float(spec["connector_kw"]), float(spec["base_kw"]),
                          tuple(Upgrade(u["id"], float(u["kw"]), float(u["capex_usd"])) for u in spec["upgrades"]),
                          float(spec["energy_usd_per_kwh"]), float(spec["demand_usd_per_kw_month"]),
                          float(spec["grid_kg_co2e_per_kwh"]), spec["substation"], int(spec["access_delay_hours"]),
                          bool(spec.get("share_connector_within_hour", False)))
            for site_id, spec in config["sites"].items()}


@dataclass
class Timeline:
    """One truck over one representative week: where it is, what it burns, and where it may plug in."""
    vehicle: str
    extra: bool
    location: list[str]                       # MY, SG or ROAD for every slot
    drive_kwh: list[float]
    plug: dict[str, list[bool]] = field(default_factory=dict)   # site id -> slot may be used
    trips: int = 0
    crossing_hours: int = 0                   # waiting at the border, both directions, over the week


@dataclass
class Block:
    """A week type: the base trips, plus at most one extra trip, under normal or congested crossings."""
    id: str
    condition: str
    option: str | None
    timelines: list[Timeline]


def _timeline(vehicle: str, extra: bool, departures: list[int], condition: str, config: dict[str, Any],
              sites: dict[str, Site]) -> Timeline:
    corridor, truck = config["corridor"], config["truck"]
    slots = int(config["horizon"]["slots_per_week"])
    crossing = int(corridor["crossing_hours"][condition])
    leg_slots = int(corridor["drive_hours"]) + crossing
    dwell = int(corridor["destination_dwell_hours"])
    leg_kwh = corridor["distance_km"] * truck["drive_kwh_per_km"] + truck["auxiliary_kw_waiting"] * crossing
    location, drive = [MY] * slots, [0.0] * slots
    arrivals = []
    for depart in departures:
        end = depart + 2 * leg_slots + dwell
        if depart < 0 or end > slots:
            raise ValueError(f"{vehicle}: a trip leaving at hour {depart} does not end within the week")
        for t in (*range(depart, depart + leg_slots), *range(depart + leg_slots + dwell, end)):
            if location[t] != MY:
                raise ValueError(f"{vehicle}: overlapping trips")
            location[t], drive[t] = ROAD, leg_kwh / leg_slots
        for t in range(depart + leg_slots, depart + leg_slots + dwell):
            location[t] = SG
        arrivals.append(depart + leg_slots)
    plug = {}
    for site in sites.values():
        allowed = [location[t] == site.side for t in range(slots)]
        for arrival in arrivals:  # some sites can be reached only after unloading
            for t in range(arrival, arrival + site.access_delay_hours):
                if site.side == SG:
                    allowed[t] = False
        plug[site.id] = allowed
    return Timeline(vehicle, extra, location, drive, plug, len(departures), 2 * crossing * len(departures))


def build_blocks(config: dict[str, Any], sites: dict[str, Site], conditions: list[str]) -> list[Block]:
    carrier = config["carrier"]
    blocks = []
    for condition in conditions:
        base = [_timeline(trip["vehicle"], False, list(trip["depart_hours"]), condition, config, sites)
                for trip in carrier["base_trips"]]
        blocks.append(Block(f"{condition}:none", condition, None,
                            [*copy.deepcopy(base), _timeline(carrier["extra_vehicle"], True, [], condition, config,
                                                             sites)]))
        for option, spec in carrier["extra_options"].items():
            extra = _timeline(carrier["extra_vehicle"], True, [int(spec["depart_hour"])], condition, config, sites)
            blocks.append(Block(f"{condition}:{option}", condition, option, [*copy.deepcopy(base), extra]))
    return blocks


def capital_share(config: dict[str, Any], weeks: int) -> float:
    """Share of an upfront cost charged to the modelled weeks: capital recovery factor x weeks / weeks per year."""
    finance = config["finance"]
    rate, years = float(finance["discount_rate"]), int(finance["lifetime_years"])
    crf = rate * (1 + rate) ** years / ((1 + rate) ** years - 1) if rate > 0 else 1 / years
    return crf * weeks / float(finance["weeks_per_year"])
