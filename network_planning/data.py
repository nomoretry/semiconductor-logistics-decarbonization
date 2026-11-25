"""Network data for the multi-SKU, multi-modal planning engine.

Lane geometry, base freight rates and lead times are read from the original
case files (asml/config.json, marvell/config.json) and emission factors from
data_sources/selected_emission_factors.json, so this engine and the original
study share one set of sourced inputs. SKU portfolios, committed demand,
capacities, fixed costs and disruption parameters are synthetic scenario
assumptions declared in network_planning/config.json.

Weeks are 1-based in this module and in every public API.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads(Path(__file__).with_name("config.json").read_text(encoding="utf-8"))
NETWORKS = tuple(CONFIG["networks"])


def emission_factors() -> dict[str, float]:
    """Well-to-wheel kg CO2e per tonne-km by mode (UK DESNZ factors, see data_sources)."""
    data = json.loads((ROOT / "data_sources/selected_emission_factors.json").read_text(encoding="utf-8"))
    combined = data["combined_factors"]
    return {"air": combined["air_without_rf"]["combined"],
            "ocean": combined["container_ship_average"]["combined"],
            "road": data["road_factor_extension"]["combined_kgco2e_per_tonne_km"]}


@dataclass(frozen=True)
class Lane:
    id: str
    origin: str
    mode: str
    lead_weeks: int
    distance_km: float
    freight_usd_per_kg: float
    capacity_kg: float          # weekly capacity (spot capacity for air)
    fixed_usd: float            # booking/handling cost per lane-week used
    ef_kg_per_tkm: float
    reservable_kg: float = 0.0  # air block space that can be reserved before the season

    @property
    def is_air(self) -> bool:
        return self.mode == "air"

    @property
    def kgco2e_per_kg(self) -> float:
        return self.distance_km * self.ef_kg_per_tkm / 1000


@dataclass(frozen=True)
class Sku:
    id: str
    template: str
    origin: str
    mass_kg: float
    value_usd: float
    mean_demand: float
    backlog_usd: float          # penalty per unit-week of backlog
    lanes: tuple[str, ...]


@dataclass(frozen=True)
class Disruption:
    lanes: tuple[str, ...]
    start_week: int
    end_week: int
    extra_lead_weeks: int = 0
    capacity_factor: float = 1.0
    distance_factor: float = 1.0
    cost_factor: float = 1.0    # freight surcharge; for air it applies to the spot price

    def active(self, lane: str, week: int) -> bool:
        return lane in self.lanes and self.start_week <= week <= self.end_week


@dataclass(frozen=True)
class Scenario:
    name: str
    probability: float = 1.0
    disruptions: tuple[Disruption, ...] = ()
    demand_factor: float = 1.0
    demand_weeks: tuple[int, int] | None = None
    description: str = ""

    def _active(self, lane: str, week: int):
        return [d for d in self.disruptions if d.active(lane, week)]

    def lead(self, lane: Lane, week: int) -> int:
        return lane.lead_weeks + sum(d.extra_lead_weeks for d in self._active(lane.id, week))

    def capacity(self, lane: Lane, week: int) -> float:
        return lane.capacity_kg * math.prod(d.capacity_factor for d in self._active(lane.id, week))

    def distance(self, lane: Lane, week: int) -> float:
        return lane.distance_km * math.prod(d.distance_factor for d in self._active(lane.id, week))

    def cost_factor(self, lane: Lane, week: int) -> float:
        return math.prod(d.cost_factor for d in self._active(lane.id, week))

    def with_probability(self, probability: float) -> Scenario:
        return Scenario(self.name, probability, self.disruptions, self.demand_factor,
                        self.demand_weeks, self.description)

    def to_dict(self) -> dict:
        return {"name": self.name, "probability": self.probability, "description": self.description,
                "demand_factor": self.demand_factor, "demand_weeks": self.demand_weeks,
                "disruptions": [d.__dict__ | {"lanes": list(d.lanes)} for d in self.disruptions]}


def scenario_from_spec(name: str, spec: dict, probability: float | None = None) -> Scenario:
    disruptions = tuple(Disruption(tuple(d["lanes"]), int(d["start_week"]), int(d["end_week"]),
                                   int(d.get("extra_lead_weeks", 0)), float(d.get("capacity_factor", 1.0)),
                                   float(d.get("distance_factor", 1.0)), float(d.get("cost_factor", 1.0)))
                        for d in spec.get("disruptions", []))
    weeks = spec.get("demand_weeks")
    return Scenario(name, float(spec.get("probability", 1.0) if probability is None else probability),
                    disruptions, float(spec.get("demand_factor", 1.0)),
                    (int(weeks[0]), int(weeks[1])) if weeks else None, spec.get("description", ""))


@dataclass
class Network:
    name: str
    label: str
    weeks: int
    seed: int
    skus: list[Sku]
    lanes: dict[str, Lane]
    demand: np.ndarray             # (S, T) committed orders in units
    initial_inventory: np.ndarray  # (S,)
    pipeline: np.ndarray           # (S, T) arrivals already in transit; their transport is sunk
    terminal_target: np.ndarray    # (S,) end-of-horizon net stock target
    carry_rate_week: float
    warehouse_usd: float
    warehouse_kg: float
    air_spot_premium: float
    reservation_usd_per_kg_week: float
    terminal_penalty_weeks: float
    scenario_specs: dict
    stochastic_set: tuple[str, ...]

    def scenario(self, name: str, probability: float | None = None) -> Scenario:
        if name not in self.scenario_specs:
            raise ValueError(f"unknown scenario '{name}' for {self.name}; known: {sorted(self.scenario_specs)}")
        return scenario_from_spec(name, self.scenario_specs[name], probability)

    def scenarios(self, names=None, probabilities=None) -> list[Scenario]:
        """Scenario set with probabilities normalised to one (default: the configured stochastic set)."""
        names = list(names or self.stochastic_set)
        result = [self.scenario(n) if probabilities is None else self.scenario(n, p)
                  for n, p in zip(names, probabilities or [None] * len(names), strict=True)]
        total = sum(s.probability for s in result)
        if total <= 0:
            raise ValueError("scenario probabilities must sum to a positive number")
        return [s.with_probability(s.probability / total) for s in result]

    def demand_for(self, scenario: Scenario) -> np.ndarray:
        if scenario.demand_factor == 1.0:
            return self.demand
        start, end = scenario.demand_weeks or (1, self.weeks)
        demand = self.demand.astype(float).copy()
        demand[:, start - 1:end] *= scenario.demand_factor
        return np.rint(demand).astype(int)

    def validate(self, scenario: Scenario) -> None:
        for d in scenario.disruptions:
            unknown = set(d.lanes) - set(self.lanes)
            if unknown:
                raise ValueError(f"unknown lanes {sorted(unknown)}; known: {sorted(self.lanes)}")
            if not 1 <= d.start_week <= d.end_week <= self.weeks:
                raise ValueError(f"disruption weeks must satisfy 1 <= start <= end <= {self.weeks}")
            if not 0 <= d.extra_lead_weeks <= 8:
                raise ValueError("extra_lead_weeks must be between 0 and 8")
            for field, value, low, high, hint in (
                    ("capacity_factor", d.capacity_factor, 0, 3, "capacity_change_pct between -100 and +200"),
                    ("distance_factor", d.distance_factor, 0.5, 3, "distance_factor between 0.5 and 3"),
                    ("cost_factor", d.cost_factor, 0.2, 5, "cost_change_pct between -80 and +400")):
                if not low <= value <= high:
                    raise ValueError(f"{field}={value:g} on {'/'.join(d.lanes)} weeks {d.start_week}-{d.end_week} "
                                     f"is outside {low}-{high}; use {hint}")
        if scenario.demand_weeks and not 1 <= scenario.demand_weeks[0] <= scenario.demand_weeks[1] <= self.weeks:
            raise ValueError(f"demand weeks must lie within 1..{self.weeks}")
        if not 0 <= scenario.demand_factor <= 3:
            raise ValueError("demand_factor must be between 0 and 3")

    def describe(self) -> dict:
        kg = self.demand * np.array([s.mass_kg for s in self.skus])[:, None]
        density = [s.value_usd / s.mass_kg for s in self.skus]
        return {
            "network": self.name, "label": self.label, "weeks": self.weeks, "skus": len(self.skus),
            "seed": self.seed, "demand_units": int(self.demand.sum()), "demand_kg": round(float(kg.sum()), 1),
            "value_density_usd_per_kg": [round(min(density)), round(max(density))],
            "lanes": [{"id": ln.id, "mode": ln.mode, "origin": ln.origin, "lead_weeks": ln.lead_weeks,
                       "distance_km": round(ln.distance_km), "freight_usd_per_kg": ln.freight_usd_per_kg,
                       "weekly_capacity_kg": ln.capacity_kg, "reservable_kg": ln.reservable_kg,
                       "fixed_usd_per_week": ln.fixed_usd, "kgco2e_per_kg": round(ln.kgco2e_per_kg, 3)}
                      for ln in self.lanes.values()],
            "scenarios": {name: {"probability": spec.get("probability", 1.0),
                                 "description": spec.get("description", "")}
                          for name, spec in self.scenario_specs.items()},
            "data_note": "Synthetic SKUs, demand, capacities and disruption factors; sourced distances and emission factors.",
        }


def build_network(name: str = "asml", n_skus: int | None = None, weeks: int | None = None,
                  seed: int | None = None) -> Network:
    if name not in CONFIG["networks"]:
        raise ValueError(f"unknown network '{name}'; known: {list(NETWORKS)}")
    defaults, common, spec = CONFIG["defaults"], CONFIG["common"], CONFIG["networks"][name]
    n_skus = defaults["n_skus"] if n_skus is None else int(n_skus)
    weeks = defaults["weeks"] if weeks is None else int(weeks)
    seed = defaults["seed"] if seed is None else int(seed)
    if not 1 <= n_skus <= 2000 or not 8 <= weeks <= 104:
        raise ValueError("n_skus must be 1-2000 and weeks 8-104")
    case = json.loads((ROOT / name / "config.json").read_text(encoding="utf-8"))
    routes, factors, jitter = case["routes"], emission_factors(), common["sku_jitter"]
    rng = np.random.default_rng(seed)

    skus = []
    for i in range(n_skus):
        k = i % len(case["sku_names"])
        lanes = tuple(r["name"] for j, r in enumerate(routes) if case["eligibility"][j][k])
        origin = next(r["origin"] for r in routes if r["name"] == lanes[0])
        value = round(case["unit_value_usd"][k] * rng.uniform(*jitter["value"]), -1)
        skus.append(Sku(id=f"{case['sku_names'][k]}_{i + 1:03d}", template=case["sku_names"][k], origin=origin,
                        mass_kg=round(case["mass_kg"][k] * rng.uniform(*jitter["mass"]), 2), value_usd=value,
                        mean_demand=round(case["mean_order_units"][k] * rng.uniform(*jitter["demand"]), 2),
                        backlog_usd=round(spec["backlog_rate_per_week"] * value, 2), lanes=lanes))
    # Same generator family as shared/experiments.synthetic_orders: Poisson orders with
    # a zero-order probability, rescaled so the mean matches the SKU's mean demand.
    p0 = case["zero_demand_probability"]
    means = np.array([s.mean_demand for s in skus])
    demand = rng.poisson(means / (1 - p0), size=(weeks, n_skus)).T
    demand[rng.random(demand.shape) < p0] = 0

    lanes = {}
    for r in routes:
        lane_spec = spec["lanes"][r["name"]]
        base_kg = sum(s.mean_demand * s.mass_kg for s in skus if r["name"] in s.lanes)
        lanes[r["name"]] = Lane(r["name"], r["origin"], r["mode"], int(r["lead"]), float(r["distance_km"]),
                                float(r["freight_usd_per_kg"]), round(lane_spec["capacity_ratio"] * base_kg, 1),
                                float(lane_spec["fixed_usd"]), factors[r["mode"]],
                                round(lane_spec.get("reservable_ratio", 0.0) * base_kg, 1))

    carry = common["annual_carry_rate"] / 52
    pipeline = np.zeros((n_skus, weeks))
    for i, s in enumerate(skus):
        # Steady state before week 1: each SKU flowed on its cheapest lane (freight + transit capital).
        nominal = min((lanes[l] for l in s.lanes),
                      key=lambda ln: ln.freight_usd_per_kg * s.mass_kg + s.value_usd * carry * ln.lead_weeks)
        pipeline[i, :min(nominal.lead_weeks, weeks)] = round(s.mean_demand)
    initial = np.ceil(means * common["initial_cover_weeks"])
    return Network(name=name, label=spec["label"], weeks=weeks, seed=seed, skus=skus, lanes=lanes,
                   demand=demand.astype(int), initial_inventory=initial, pipeline=pipeline,
                   terminal_target=initial.copy(), carry_rate_week=carry,
                   warehouse_usd=common["warehouse_usd_per_unit_week"],
                   warehouse_kg=common["warehouse_kgco2e_per_unit_week"],
                   air_spot_premium=common["air_spot_premium"],
                   reservation_usd_per_kg_week=common["air_reservation_usd_per_kg_week"],
                   terminal_penalty_weeks=common["terminal_penalty_weeks"],
                   scenario_specs=spec["scenarios"], stochastic_set=tuple(spec["stochastic_set"]))
