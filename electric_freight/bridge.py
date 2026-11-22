"""Exchange with the UM charging model (UM-RESEARCH, src/um_charging): same trucks, same week, two solvers.

``um_instance`` writes one week type as a ``capacity-investment-v2`` input of that model. ``cross_check`` solves it
there and here under the same decisions and compares cost and equipment. Each repository still runs on its own: this
module imports the other one only when a path to its checkout is given.

The UM model has no site opening, no demand charge and no shared substation, so the comparison uses a reduced
configuration without them (``comparable_config``). Costs are USD for one week; the UM schema calls its unit
"synthetic_currency".
"""
from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path
from typing import Any

from .data import MY, ROAD, SG, build_blocks, capital_share, sites_from
from .model import solve


def comparable_config(config: dict[str, Any], site_ids: tuple[str, str] = ("MY_DEPOT", "SG_HUB")) -> dict[str, Any]:
    """One week, the two named sites already open, no demand charge, one truck per connector and hour."""
    reduced = copy.deepcopy(config)
    reduced["horizon"]["weeks"] = 1
    reduced["sites"] = {j: reduced["sites"][j] for j in site_ids}
    for spec in reduced["sites"].values():
        spec.update(open_capex_usd=0, demand_usd_per_kw_month=0, substation=None, access_delay_hours=0,
                    share_connector_within_hour=False)
    reduced["substations"] = {}
    return reduced


def um_instance(config: dict[str, Any], block_id: str = "normal:none") -> dict[str, Any]:
    """The week type ``block_id`` of a comparable configuration as an input of the UM charging model."""
    sites = sites_from(config)
    if len(sites) != 2 or {site.side for site in sites.values()} != {MY, SG}:
        raise ValueError("the UM instance needs exactly one site on each side; use comparable_config")
    side_site = {site.side: site.id for site in sites.values()}
    condition = block_id.split(":")[0]
    block = next(b for b in build_blocks(config, sites, [condition]) if b.id == block_id)
    slots = int(config["horizon"]["slots_per_week"])
    share = capital_share(config, int(config["horizon"]["weeks"]))
    truck = config["truck"]
    transit: list[str] = []
    vehicles = []
    for line in block.timelines:
        if not line.trips:
            continue  # a truck that never leaves needs no charging and would only add idle variables
        timeline: list[dict[str, Any]] = []
        charging: list[str | None] = []
        for t in range(slots):
            here = line.location[t]
            if here != ROAD:
                site = side_site[here]
                timeline.append({"from": site, "to": site, "activity": "dwell", "plug_allowed": True})
                charging.append(site)
                continue
            start = t
            while start > 0 and line.location[start - 1] == ROAD:
                start -= 1
            end = t
            while end + 1 < slots and line.location[end + 1] == ROAD:
                end += 1
            # The week is a closed cycle: a leg that ends with the week arrives where the week began.
            origin = side_site[line.location[start - 1]]
            target = side_site[line.location[(end + 1) % slots]]

            def point(index: int, origin: str = origin, target: str = target, start: int = start,
                      end: int = end) -> str:
                if index == start:
                    return origin
                if index == end + 1:
                    return target
                name = f"{origin}>{target}:{index - start}"
                if name not in transit:
                    transit.append(name)
                return name

            timeline.append({"from": point(t), "to": point(t + 1), "activity": "drive", "plug_allowed": False})
            charging.append(None)
        vehicles.append({"id": line.vehicle, "energy_min_kwh": truck["min_energy_kwh"],
                         "energy_max_kwh": truck["battery_usable_kwh"],
                         "initial_energy_kwh": truck["initial_energy_kwh"],
                         "efficiency": truck["charging_efficiency"],
                         "power_limit_kw": {j: site.connector_kw for j, site in sites.items()},
                         "drive_energy_kwh": list(line.drive_kwh), "charging_site": charging, "timeline": timeline})
    return {
        "schema_version": "capacity-investment-v2", "instance_id": f"ms_corridor_{block_id.replace(':', '_')}",
        "description": "Malaysia-Singapore corridor trucks of the electric freight study, one representative week.",
        "provenance": {"observed": [], "derived": ["Leg energy from the archived truck-energy transfer (1.13 kWh/km)."],
                       "assumed": ["Costs are USD for one week; the schema's unit name is kept as required."],
                       "simulated": ["Timelines, sites and equipment costs of electric_freight/config.json."]},
        "units": {"energy": "kWh", "power": "kW", "time": "hour", "price": "synthetic_currency/kWh",
                  "objective": "synthetic_currency"},
        "slot_hours": float(config["horizon"]["slot_hours"]), "slot_count": slots, "representative_weight": 1,
        "cost_basis": "synthetic_cycle_equivalent", "transit_locations": transit,
        "connector_policy": "slot_boundary_switching",
        "sites": [{"id": j, "active": True, "interfaces": 0, "available_power_kw": [site.base_kw] * slots,
                   "price_per_kwh": [site.energy_usd_per_kwh] * slots, "max_new_interfaces": site.max_connectors,
                   "interface_cost": share * site.connector_capex_usd,
                   "upgrade_options": [{"id": u.id, "additional_power_kw": u.kw, "cost": share * u.capex_usd}
                                       for u in site.upgrades]} for j, site in sites.items()],
        "vehicles": vehicles}


def cross_check(config: dict[str, Any], um_checkout: Path, block_id: str = "normal:none",
                time_limit: float = 300.0) -> dict[str, Any]:
    """Solve one week with both models and compare. ``um_checkout`` is a checkout of UM-RESEARCH."""
    source = Path(um_checkout) / "src"
    if not (source / "um_charging" / "model.py").exists():
        raise FileNotFoundError(f"no um_charging package under {source}")
    sys.path.insert(0, str(source))
    try:
        um_model = importlib.import_module("um_charging.model")
        um_validation = importlib.import_module("um_charging.validation")
    finally:
        sys.path.remove(str(source))
    reduced = comparable_config(config)
    option = block_id.split(":")[1]
    extras = reduced["carrier"]["extra_options"]
    reduced["carrier"]["extra_options"] = {} if option == "none" else {option: extras[option]}
    instance = um_instance(reduced, block_id)
    theirs = um_model.solve(instance, time_limit=time_limit)
    check = um_validation.check_solution(instance, theirs) if theirs["has_solution"] else {"passed": None}
    fixed = {"week_types": {"1": block_id}, "shipments": [], "air": []}
    congested = [1] if block_id.startswith("congested") else []
    ours = solve(reduced, [], mode="joint", fixed=fixed, congested_weeks=congested, mip_gap=0.0,
                 time_limit=time_limit)
    carrier = reduced["carrier"]
    trips = sum(len(trip["depart_hours"]) for trip in carrier["base_trips"]) * carrier["trip_cost_usd"]
    if option != "none":
        trips += carrier["extra_options"][option]["trip_cost_usd"]
    if block_id.startswith("congested"):
        count = sum(len(trip["depart_hours"]) for trip in carrier["base_trips"]) + (option != "none")
        trips += carrier["congested_trip_surcharge_usd"] * count
    ours_cost = ours.get("objective_usd")
    site_ids = [site["id"] for site in instance["sites"]]
    result: dict[str, Any] = {
        "block": block_id, "um_status": theirs["status"], "um_objective": theirs["objective"],
        "um_validation_passed": check["passed"], "ours_status": ours["status"],
        "ours_charging_objective": None if ours_cost is None else ours_cost - trips,
        "um_new_connectors": dict(zip(site_ids, theirs["solution"]["new_interfaces"], strict=True))
        if theirs["has_solution"] else None,
        "ours_connectors": {j: item["connectors"] for j, item in ours["solution"]["equipment"].items()}
        if "solution" in ours else None,
        "ours_issues": ours.get("accounting", {}).get("issues")}
    if theirs["objective"] is not None and ours_cost is not None:
        result["difference"] = (ours_cost - trips) - theirs["objective"]
    return result
