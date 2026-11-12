"""Recompute a plan from its decisions alone: deliveries, truck energy, connectors, site power, cost and emissions.

Nothing here reads a solver objective or a solver constraint. Every limit is checked again on the reported values,
and any violation is listed. Costs follow one basis for all modes:

- system cost: what the carrier's trucks, energy and equipment cost, plus what the shipper pays for holding,
  backlog, displaced cargo and air. The base road rate is a payment between the two and is reported, not added;
- emissions: electricity bought at each site, diesel burnt, and air freight. The mass-distance figure the weekly
  plan used for road is reported for reference and not added.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from .data import Order, build_blocks, capital_share, sites_from

TOLERANCE = 1e-5


def evaluate(config: dict[str, Any], orders: Sequence[Order], solution: dict[str, Any], *, mode: str,
             congested_weeks: Sequence[int] = (), air: dict[str, float] | None = None) -> dict[str, Any]:
    from .model import dispatch_windows, week_conditions  # the two rules that define the task, not the model

    air = air or {"spot_usd_per_kg": 6.875, "kg_co2e_per_kg": 0.198253}
    weeks = int(config["horizon"]["weeks"])
    slots = int(config["horizon"]["slots_per_week"])
    hours = float(config["horizon"]["slot_hours"])
    carrier, truck, corridor = config["carrier"], config["truck"], config["corridor"]
    conditions = week_conditions(weeks, congested_weeks)
    sites = sites_from(config)
    blocks = {block.id: block for block in build_blocks(config, sites, sorted(set(conditions)))}
    issues: list[str] = []
    cost = dict.fromkeys(("base_trips", "extra_trips", "energy", "demand_charge", "equipment", "displaced_cargo",
                          "holding", "backlog", "air_freight"), 0.0)

    # ---- deliveries
    by_order = {order.id: order for order in orders}
    windows = {order.id: dict(dispatch_windows(order, config, conditions)) for order in orders}
    served: defaultdict[str, float] = defaultdict(float)
    load: defaultdict[tuple[int, str], float] = defaultdict(float)
    kg = dict.fromkeys(("consolidated", "premium", "extra_trip", "air", "early", "late", "on_time"), 0.0)
    for item in solution["shipments"]:
        order = by_order[item["order"]]
        week, channel, units = int(item["week"]), item["channel"], float(item["units"])
        if week not in windows[order.id]:
            issues.append(f"{order.id}: dispatch in week {week} is outside its release and lateness window")
            continue
        early = windows[order.id][week]
        served[order.id] += units
        load[week, channel] += units * order.mass_kg
        kg[channel] += units * order.mass_kg
        kg["early" if early > 0 else "late" if early < 0 else "on_time"] += units * order.mass_kg
        cost["holding"] += order.holding_usd_per_unit_week * max(early, 0) * units
        cost["backlog"] += order.backlog_usd_per_unit_week * max(-early, 0) * units
        if channel == "premium":
            cost["displaced_cargo"] += carrier["premium_usd_per_kg"] * order.mass_kg * units
    for item in solution["air"]:
        order = by_order[item["order"]]
        served[order.id] += float(item["units"])
        kg["air"] += float(item["units"]) * order.mass_kg
        cost["air_freight"] += air["spot_usd_per_kg"] * order.mass_kg * float(item["units"])
    for order in orders:
        if abs(served[order.id] - order.units) > TOLERANCE * max(1.0, order.units):
            issues.append(f"{order.id}: {served[order.id]:.4f} of {order.units:.4f} units delivered")
    chosen = {int(w): blocks[block_id] for w, block_id in solution["week_types"].items()}
    extra_trips: defaultdict[str, int] = defaultdict(int)
    base_trips = sum(len(trip["depart_hours"]) for trip in carrier["base_trips"])
    factor = float(config["congestion"]["consolidation_factor"])
    for week in range(1, weeks + 1):
        block = chosen.get(week)
        if block is None or block.condition != conditions[week - 1]:
            issues.append(f"week {week}: no week type of the right crossing condition")
            continue
        congested = block.condition == "congested"
        scale = factor if congested else 1.0
        surcharge = carrier["congested_trip_surcharge_usd"] if congested else 0.0
        cost["base_trips"] += base_trips * (carrier["trip_cost_usd"] + surcharge)
        if block.option is not None:
            extra_trips[block.option] += 1
            cost["extra_trips"] += carrier["extra_options"][block.option]["trip_cost_usd"] + surcharge
        limits = {"consolidated": carrier["weekly_consolidation_kg"] * scale,
                  "premium": carrier["premium_kg_per_week"] * scale,
                  "extra_trip": carrier["extra_trip_chip_capacity_kg"] if block.option is not None else 0.0}
        for channel, limit in limits.items():
            if load[week, channel] > limit + TOLERANCE * max(1.0, limit):
                issues.append(f"week {week}: {load[week, channel]:.2f} kg on '{channel}' exceeds {limit:.2f} kg")

    # ---- energy and equipment
    energy_kwh: defaultdict[str, float] = defaultdict(float)
    peak: dict[str, float] = dict.fromkeys(sites, 0.0)
    litres = 0.0
    truck_km = sum(2 * corridor["distance_km"] * sum(t.trips for t in block.timelines) for block in chosen.values())
    equipment: dict[str, Any] = {}
    if mode == "diesel":
        diesel = config["diesel"]
        for block in chosen.values():
            crossing = int(corridor["crossing_hours"][block.condition])
            per_trip = 2 * (corridor["distance_km"] * diesel["litres_per_km"]
                            + diesel["idle_litres_per_hour"] * crossing)
            litres += per_trip * sum(t.trips for t in block.timelines)
        cost["energy"] = litres * diesel["price_usd_per_litre"]
    elif mode == "logistics":
        for block in chosen.values():
            kwh = sum(sum(t.drive_kwh) for t in block.timelines if t.extra) / truck["charging_efficiency"]
            cost["energy"] += config["planning_energy_usd_per_kwh"] * kwh
    else:
        equipment = solution["equipment"]
        share = capital_share(config, weeks)
        capacity = {}
        for j, site in sites.items():
            item = equipment[j]
            if item["connectors"] > site.max_connectors * item["opened"]:
                issues.append(f"{j}: connectors without an opened site or above the site's limit")
            chosen_upgrade = next((u for u in site.upgrades if u.id == item["upgrade"]), None)
            if item["upgrade"] is not None and (chosen_upgrade is None or not item["opened"]):
                issues.append(f"{j}: unknown upgrade or upgrade of an unopened site")
            capacity[j] = site.base_kw * item["opened"] + (chosen_upgrade.kw if chosen_upgrade else 0.0)
            cost["equipment"] += share * (site.open_capex_usd * item["opened"]
                                          + site.connector_capex_usd * item["connectors"]
                                          + (chosen_upgrade.capex_usd if chosen_upgrade else 0.0))
        used = {block.id for block in chosen.values()}
        block_bill: dict[str, float] = {}
        block_kwh: dict[str, dict[str, float]] = {}
        for block_id in used:
            block, values = blocks[block_id], solution["blocks"][block_id]["vehicles"]
            site_power = {j: [0.0] * slots for j in sites}
            site_plugs = {j: [0.0] * slots for j in sites}
            for line in block.timelines:
                record = values[line.vehicle]
                level = truck["initial_energy_kwh"]
                if abs(record["energy_kwh"][0] - level) > TOLERANCE:
                    issues.append(f"{block_id}/{line.vehicle}: does not start at the stated energy")
                for t in range(slots):
                    plugged = 0.0
                    for j, site in sites.items():
                        a, p = record["plug"][j][t], record["power_kw"][j][t]
                        if a > TOLERANCE and not line.plug[j][t]:
                            issues.append(f"{block_id}/{line.vehicle}: plugged in at {j} in hour {t} while not there")
                        whole = site.share_within_hour or abs(a - round(a)) <= TOLERANCE
                        in_range = -TOLERANCE <= a <= 1 + TOLERANCE and -TOLERANCE <= p <= site.connector_kw * a + 1e-4
                        if not (whole and in_range):
                            issues.append(f"{block_id}/{line.vehicle}: power without a connector at {j} in hour {t}")
                        plugged += a
                        site_power[j][t] += p
                        site_plugs[j][t] += a
                        level += truck["charging_efficiency"] * hours * p
                    if plugged > 1 + TOLERANCE:
                        issues.append(f"{block_id}/{line.vehicle}: two connectors in hour {t}")
                    level -= line.drive_kwh[t]
                    if not truck["min_energy_kwh"] - 1e-4 <= level <= truck["battery_usable_kwh"] + 1e-4:
                        issues.append(f"{block_id}/{line.vehicle}: energy {level:.2f} kWh out of bounds after hour {t}")
                    if abs(level - record["energy_kwh"][t + 1]) > 1e-4:
                        issues.append(f"{block_id}/{line.vehicle}: reported energy differs after hour {t}")
                if level < truck["initial_energy_kwh"] - 1e-4:
                    issues.append(f"{block_id}/{line.vehicle}: ends the week below its starting energy")
            for j, site in sites.items():
                for t in range(slots):
                    if site_plugs[j][t] > equipment[j]["connectors"] + TOLERANCE:
                        issues.append(f"{block_id}/{j}: more trucks than connectors in hour {t}")
                    if site_power[j][t] > capacity[j] + 1e-4:
                        issues.append(f"{block_id}/{j}: {site_power[j][t]:.1f} kW above the connection in hour {t}")
                    if (site.substation and config["substation_rule"] == "split"
                            and site_power[j][t] > config["substations"][site.substation]["split_kw"][j] + 1e-4):
                        issues.append(f"{block_id}/{j}: above its share of {site.substation} in hour {t}")
                peak[j] = max(peak[j], max(site_power[j]))
            if config["substation_rule"] == "shared":
                for name, spec in config["substations"].items():
                    members = [j for j, site in sites.items() if site.substation == name]
                    for t in range(slots):
                        if sum(site_power[j][t] for j in members) > spec["headroom_kw"] + 1e-4:
                            issues.append(f"{block_id}/{name}: above the shared headroom in hour {t}")
            block_kwh[block_id] = {j: hours * sum(site_power[j]) for j in sites}
            block_bill[block_id] = sum(sites[j].energy_usd_per_kwh * block_kwh[block_id][j] for j in sites)
        for block in chosen.values():
            cost["energy"] += block_bill[block.id]
            for j in sites:
                energy_kwh[j] += block_kwh[block.id][j]
        months = weeks / float(config["finance"]["weeks_per_month"])
        cost["demand_charge"] = sum(sites[j].demand_usd_per_kw_month * months * peak[j] for j in sites)

    emissions = {"electricity": sum(sites[j].grid_kg_co2e_per_kwh * kwh for j, kwh in energy_kwh.items()),
                 "diesel": litres * config["diesel"]["kg_co2e_per_litre"],
                 "air_freight": air["kg_co2e_per_kg"] * kg["air"]}
    road_kg = kg["consolidated"] + kg["premium"] + kg["extra_trip"]
    reference = {"base_rate_payment_usd": carrier["base_rate_usd_per_kg"] * (kg["consolidated"] + kg["premium"]),
                 "note": "A payment from shipper to carrier for space on the base trips; not part of system cost."}
    if "road_old_kg_co2e_per_kg" in air:
        reference["road_emissions_old_basis_kg"] = air["road_old_kg_co2e_per_kg"] * road_kg
    total = sum(cost.values())
    return {"objective_usd": total, "cost_usd": {key: round(value, 2) for key, value in cost.items()},
            "total_cost_usd": round(total, 2),
            "emissions_kg_co2e": {key: round(value, 1) for key, value in emissions.items()},
            "total_emissions_kg_co2e": round(sum(emissions.values()), 1),
            "delivered_kg": {key: round(value, 2) for key, value in kg.items()},
            "extra_trips": dict(extra_trips), "truck_km": truck_km, "diesel_litres": round(litres, 1),
            "energy_kwh": {j: round(value, 1) for j, value in energy_kwh.items()},
            "peak_kw": {j: round(value, 1) for j, value in peak.items()} if mode == "joint" else {},
            "equipment": equipment, "reference_not_added": reference, "issues": issues}
