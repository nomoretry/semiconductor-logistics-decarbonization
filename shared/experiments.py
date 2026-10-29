"""Company-inspired logistics experiments; all business parameters are explicit.

This first-stage experiment plans a fully committed order book and announced
disruptions. It is NOT a stochastic rolling-horizon controller or a company
operational forecast. No language-model API is called by this replay code.
"""
from __future__ import annotations

import copy
import csv
import gzip
import hashlib
import json
import math
import platform
import time
import zipfile
from pathlib import Path

import numpy as np
import scipy

from .optimization import solve_plan

ROOT = Path(__file__).resolve().parents[1]
EF = {"air": 0.66646, "ocean": 0.01977, "road": 0.12715}
SEEDS = tuple(range(100, 110))
CASES = ("normal", "ocean_delay", "capacity_restriction")
BUDGETS = (("carbon_minus10", .90), ("carbon_minus25", .75), ("carbon_minus50", .50))


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def config(project):
    return json.loads((ROOT / project / "config.json").read_text())


def compile_notice(base, extraction):
    """Allowlisted parameter updates only; never execute LLM-generated code."""
    if set(extraction) != {"status", "changes"}:
        raise ValueError("Unexpected extraction fields")
    if extraction["status"] != "ready":
        raise ValueError("Critical information missing: clarification required")
    out = copy.deepcopy(base)
    routes = [r["name"] for r in out["routes"]]
    origins = list(dict.fromkeys(out["route_origin"]))
    T, J = out["horizon"], len(routes)
    out.setdefault("lead_schedule", np.tile([r["lead"] for r in out["routes"]], (T, 1)).tolist())
    out.setdefault("distance_schedule", np.tile([r["distance_km"] for r in out["routes"]], (T, 1)).tolist())
    out.setdefault("freight_schedule", np.tile([r["freight_usd_per_kg"] for r in out["routes"]], (T, 1)).tolist())
    out.setdefault("capacity_schedule", np.tile([r["capacity"] for r in out["routes"]], (T, 1)).tolist())
    out.setdefault("origin_schedule", np.tile(out["origin_capacity"], (T, 1)).tolist())
    for change in extraction["changes"]:
        op, value = change["op"], change["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or value < 0:
            raise ValueError("Invalid numeric value")
        if op == "carbon_reduction_fraction":
            if set(change) != {"op", "value"} or not 0 <= value < 1:
                raise ValueError("Invalid carbon-reduction fraction")
            out["requested_carbon_reduction"] = value
            continue
        entity_key = "origin" if op == "multiply_origin_capacity" else "route"
        if set(change) != {"op", entity_key, "start_week", "end_week", "value"}:
            raise ValueError("Invalid operation fields")
        start, end = change["start_week"], change["end_week"]
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= T:
            raise ValueError("Weeks must be one-based inclusive integers within horizon")
        if entity_key == "origin":
            if change["origin"] not in origins:
                raise ValueError("Unknown origin")
            j = origins.index(change["origin"])
            for t in range(start - 1, end):
                out["origin_schedule"][t][j] *= value
            continue
        if change["route"] not in routes:
            raise ValueError("Unknown route")
        j = routes.index(change["route"])
        for t in range(start - 1, end):
            if op == "add_lead":
                if int(value) != value:
                    raise ValueError("Lead increment must be integer weeks")
                out["lead_schedule"][t][j] += int(value)
            elif op == "set_distance":
                out["distance_schedule"][t][j] = value
            elif op == "set_capacity":
                out["capacity_schedule"][t][j] = value
            elif op == "multiply_freight":
                out["freight_schedule"][t][j] *= value
            else:
                raise ValueError("Operation is not allowlisted")
    return out


def case_config(project, case, labels=None):
    base = config(project)
    if case == "normal":
        return base
    labels = labels or json.loads((ROOT / "llm/reference_labels.json").read_text())
    ids = {"asml": {"ocean_delay": "A01", "capacity_restriction": "A02"},
           "marvell": {"ocean_delay": "M01", "capacity_restriction": "M02"}}
    return compile_notice(base, labels[ids[project][case]])


def synthetic_orders(c, seed):
    """Known committed orders generated synthetically, not predicted company sales."""
    rng = np.random.default_rng(seed)
    mean = np.asarray(c["mean_order_units"], dtype=float)
    p0 = c["zero_demand_probability"]
    orders = rng.poisson(mean / (1 - p0), size=(c["horizon"], len(mean)))
    orders[rng.random(orders.shape) < p0] = 0
    # Fixed disclosed large-order stress, matched across all policies.
    orders[8:10] = np.rint(orders[8:10] * 1.5).astype(int)
    return orders


def planning_inputs(c, orders, *, initial=None, ef=None):
    T, K = orders.shape
    routes, J = c["routes"], len(c["routes"])
    if c["period"] not in ("week", "month"):
        raise ValueError("period must be week or month")
    lead_values = np.asarray(c.get("lead_schedule", np.tile([r["lead"] for r in routes], (T, 1))), dtype=float)
    if not np.all(np.isfinite(lead_values)) or np.any(lead_values < 1) or not np.all(lead_values == np.floor(lead_values)):
        raise ValueError("lead times must be finite positive integers in the chosen period")
    lead = lead_values.astype(int)
    distance = np.asarray(c.get("distance_schedule", np.tile([r["distance_km"] for r in routes], (T, 1))), dtype=float)
    price = np.asarray(c.get("freight_schedule", np.tile([r["freight_usd_per_kg"] for r in routes], (T, 1))), dtype=float)
    mass = np.asarray(c["mass_kg"])
    periods_year = 52 if c["period"] == "week" else 12
    capital = np.asarray(c["unit_value_usd"]) * c["annual_carry_rate"] / periods_year
    freight = price[:, :, None] * mass[None, None, :]
    transit = lead[:, :, None] * capital[None, None, :]
    factors = ef or EF
    # kg / 1000 -> tonnes. Aviation factor already incorporates its 8% uplift.
    emissions = distance[:, :, None] * mass[None, None, :] / 1000 * np.array(
        [factors[r["mode"]] for r in routes])[None, :, None]
    if initial is None:
        buffer = np.asarray(c["mean_order_units"]) * (max(r["lead"] for r in routes) + 1)
        initial = np.maximum(np.ceil(buffer), orders[0]).astype(int)
    args = dict(demand=orders, initial_inventory=initial,
        pipeline_arrivals=np.zeros((T, K)), lead_times=lead,
        unit_costs=freight + transit, unit_emissions=emissions,
        holding_cost=capital + c["warehouse_usd_per_unit_period"],
        backlog_cost=np.full(K, 1e6),
        route_capacity=np.asarray(c.get("capacity_schedule", np.tile([r["capacity"] for r in routes], (T, 1))), dtype=float),
        warehouse_emissions=np.full(K, c["warehouse_kgco2e_per_unit_period"]),
        terminal_inventory=initial, integer=True, time_limit=2., mip_rel_gap=1e-4,
        backlog_limit=0, eligibility=np.asarray(c["eligibility"], dtype=bool),
        route_origin=c["route_origin"],
        origin_capacity=np.asarray(c.get("origin_schedule", np.tile(c["origin_capacity"], (T, 1))), dtype=float))
    return args, {"freight": freight, "transit": transit, "mass": mass}


def solve_policy(c, orders, policy, *, carbon_cap=None, initial=None, ef=None):
    args, parts = planning_inputs(c, orders, initial=initial, ef=ef)
    if policy in ("fast_only", "slow_only"):
        fast = np.array([r["mode"] == "air" for r in c["routes"]])
        keep = fast if policy == "fast_only" else ~fast
        args["eligibility"] = args["eligibility"] & keep[:, None]
    args["carbon_cap"] = carbon_cap
    result = solve_plan(**args)
    if not result["success"]:
        return result, args
    q, inv = result["orders"], result["inventory"]
    freight, transit = float((q * parts["freight"]).sum()), float((q * parts["transit"]).sum())
    np.testing.assert_allclose(result["total_cost"], freight + transit + result["holding_cost"], atol=1e-4)
    transported_mass = (q * parts["mass"]).sum(axis=(0, 2))
    denominator = float(transported_mass.sum())
    fast_mass = sum(float(transported_mass[j]) for j, r in enumerate(c["routes"]) if r["mode"] == "air")
    result.update(freight_cost=freight, transit_capital_cost=transit,
        inventory_unit_periods=float(inv.sum()), mean_total_inventory=float(inv.sum(axis=1).mean()),
        order_std=float(q.sum(axis=1).std(axis=0).mean()),
        air_mass_share=fast_mass / denominator if denominator else None,
        fill_rate=1.0, terminal_inventory_coverage=float(np.min(inv[-1] / np.maximum(args["terminal_inventory"], 1))),
        route_units=q.sum(axis=(0, 2)).tolist())
    return result, args


def metric_row(project, demand_set, case, seed, policy, result, cap=None):
    row = dict(project=project, demand_set=demand_set, case=case, seed=seed, policy=policy,
               feasible=bool(result["success"]), optimal=bool(result["optimal"]),
               status=result["status"], mip_gap=result["mip_gap"], carbon_cap=cap,
               solve_seconds=result["solve_seconds"])
    keys = ("total_cost", "total_emissions", "freight_cost", "transit_capital_cost", "holding_cost",
            "transport_emissions", "warehouse_emissions", "mean_total_inventory", "order_std",
            "air_mass_share", "fill_rate", "terminal_inventory_coverage")
    for key in keys:
        row[key] = result.get(key) if result["success"] else None
    return row


def external_carparts_groups():
    """Real MONTHLY demand, retained as months; no relabeling months as weeks."""
    archive = ROOT / "data_sources/raw/car_parts_dataset_with_missing_values.zip"
    complete = []
    with zipfile.ZipFile(archive) as z:
        text = z.read(z.namelist()[0]).decode("cp1252")
    for line in text.splitlines():
        if not line or line.startswith(("#", "@")):
            continue
        fields = line.split(":")
        values = fields[-1].split(",")
        if "?" in values:
            continue
        values = np.asarray([float(x) for x in values])
        # Select using ONLY the history, not whether the final 12 months are busy.
        if len(values) == 51 and values[:39].sum() >= 6:
            complete.append((fields[0], values))
    rng = np.random.default_rng(4100)
    chosen = rng.choice(len(complete), size=40, replace=False)
    for group in range(10):
        records = [complete[i] for i in chosen[group * 4:group * 4 + 4]]
        yield 4100 + group, [x[0] for x in records], np.column_stack([x[1][-12:] for x in records]).astype(int), np.array([x[1][:39].mean() for x in records])


def run_grid(projects=("asml", "marvell"), seeds=SEEDS, include_analogue=True):
    started, rows, plan_records, instances = time.perf_counter(), [], [], []
    for project in projects:
        for case in CASES:
            c = case_config(project, case)
            for seed in seeds:
                orders = synthetic_orders(c, seed)
                instance = dict(project=project, demand_set="synthetic_weekly", case=case, seed=seed,
                                config=c, orders=orders.tolist())
                instances.append(instance)
                base, _ = solve_policy(c, orders, "cost_only")
                jobs = [("cost_only", None, base)]
                for policy in ("fast_only", "slow_only"):
                    sol, _ = solve_policy(c, orders, policy)
                    jobs.append((policy, None, sol))
                if base["success"]:
                    for policy, fraction in BUDGETS:
                        cap = fraction * base["total_emissions"]
                        sol, _ = solve_policy(c, orders, policy, carbon_cap=cap)
                        jobs.append((policy, cap, sol))
                for policy, cap, sol in jobs:
                    rows.append(metric_row(project, "synthetic_weekly", case, seed, policy, sol, cap))
                    if sol["success"]:
                        plan_records.append(dict(project=project, demand_set="synthetic_weekly", case=case,
                            seed=seed, policy=policy, orders=sol["orders"].tolist(),
                            inventory=sol["inventory"].tolist(), backlog=sol["backlog"].tolist()))
            print(f"{project} {case}: completed {len(seeds)} matched order books", flush=True)
    if include_analogue and "asml" in projects:
        for seed, series_ids, orders, training_mean in external_carparts_groups():
            c = config("asml")
            c.update(period="month", horizon=12, mean_order_units=training_mean.tolist(),
                     warehouse_usd_per_unit_period=.4 * 52 / 12,
                     warehouse_kgco2e_per_unit_period=.04 * 52 / 12)
            for route in c["routes"]:
                route["lead"] = math.ceil(route["lead"] * 12 / 52)
            instances.append(dict(project="asml", demand_set="real_carparts_monthly", case="normal",
                seed=seed, config=c, series_ids=series_ids, orders=orders.tolist(),
                note="Real automotive demand with illustrative semiconductor-inspired shipping costs; not semiconductor calibration"))
            base, _ = solve_policy(c, orders, "cost_only")
            jobs = [("cost_only", None, base)]
            for policy in ("fast_only", "slow_only"):
                sol, _ = solve_policy(c, orders, policy)
                jobs.append((policy, None, sol))
            if base["success"]:
                cap = .75 * base["total_emissions"]
                sol, _ = solve_policy(c, orders, "carbon_minus25", carbon_cap=cap)
                jobs.append(("carbon_minus25", cap, sol))
            for policy, cap, sol in jobs:
                rows.append(metric_row("asml", "real_carparts_monthly", "normal", seed, policy, sol, cap))
                if sol["success"]:
                    plan_records.append(dict(project="asml", demand_set="real_carparts_monthly", case="normal",
                        seed=seed, series_ids=series_ids, policy=policy, orders=sol["orders"].tolist(),
                        inventory=sol["inventory"].tolist(), backlog=sol["backlog"].tolist()))
    write_json(ROOT / "reports/episodes.json", rows)
    write_json(ROOT / "reports/instances.json", instances)
    with gzip.open(ROOT / "reports/plans.json.gz", "wt") as f:
        json.dump(plan_records, f, allow_nan=False)
    with (ROOT / "reports/episodes.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(rows)
    write_json(ROOT / "reports/summary.json", summary)
    write_json(ROOT / "reports/run_manifest.json", dict(
        experiment="committed orders + announced disruptions, integer planning",
        date="2026-10-30", python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
        synthetic_seeds=list(seeds), cases=list(CASES), total_solves=len(rows),
        status_counts={str(status):sum(r["status"] == status for r in rows) for status in sorted({r["status"] for r in rows})},
        service="zero end-period backlog every period; final inventory >= same initial inventory",
        risk_excluded="cargo damage; manufacturing, wafer yields, product embodied carbon",
        business_data="synthetic scenario assumptions, not proprietary company data",
        budget_reference="10/25/50% below SAME instance cost-only logistics emissions",
        air_kgco2e_per_tonne_km=.66646, ocean_kgco2e_per_tonne_km=.01977,
        road_kgco2e_per_tonne_km=.12715,
        source_sha256={str(p.relative_to(ROOT)):sha256(p) for p in sorted(ROOT.rglob("*.py")) if "__pycache__" not in p.parts},
        input_sha256={str(p.relative_to(ROOT)):sha256(p) for p in [*[ROOT/project/"config.json" for project in projects],ROOT/"data_sources/raw/car_parts_dataset_with_missing_values.zip",ROOT/"data_sources/raw/ghg_factors_2026_flat_revised.xlsx"]},
        seconds=time.perf_counter() - started,
        llm="Separate saved in-session extraction pilot; no external API inference in numerical grid"))
    return rows, summary


def summarize(rows):
    groups = sorted({(r["project"],r["demand_set"],r["case"],r["policy"]) for r in rows})
    result=[]
    for group in groups:
        all_rows=[r for r in rows if (r["project"],r["demand_set"],r["case"],r["policy"])==group]
        good=[r for r in all_rows if r["feasible"]]
        out=dict(zip(("project","demand_set","case","policy"),group))
        out.update(n=len(all_rows),feasible_n=len(good),optimal_n=sum(r["optimal"] for r in good))
        for key in ("total_cost","total_emissions","freight_cost","transit_capital_cost","holding_cost","mean_total_inventory","air_mass_share","fill_rate"):
            out[key]=float(np.mean([r[key] for r in good])) if good else None
        result.append(out)
    return result
