"""Run the model-v2 study: plans A, B, B* and C by instance and scenario, plan B under other solver seeds, a
fix-and-optimize search from saved plans, the boundary sweeps, the unbroken-horizon check of the representative
weeks, and the two-stage stochastic plan.

    python scripts/run_fleet.py deterministic --workers 3
    python scripts/run_fleet.py tie_break --workers 3
    python scripts/run_fleet.py search --workers 2
    python scripts/run_fleet.py boundaries --workers 3
    python scripts/run_fleet.py horizon --workers 3
    python scripts/run_fleet.py stochastic --workers 3
    python scripts/run_fleet.py sensitivity --workers 3

A base-instance solve needs about 0.6 GB of memory; three workers fit a machine with 3 GB free.

Results go to benchmark_results/electric_freight_v2/. Every group can be resumed: a job whose id is already saved is
skipped. No model is called. Everything is solved locally with HiGHS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from electric_freight.fleet import horizon_check, load_v2, make_scenario, sequential, solve  # noqa: E402
from electric_freight.fleet_accounting import evaluate  # noqa: E402

PROTOCOL = ROOT / "benchmarks" / "electric_freight_v2" / "protocol.json"
RESULTS = ROOT / "benchmark_results" / "electric_freight_v2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_version() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    dirty = git("status", "--porcelain", "--", "electric_freight", "scripts/run_fleet.py",
                "benchmarks/electric_freight_v2")
    return git("rev-parse", "--short", "HEAD") + ("+uncommitted" if dirty else "")


def protocol() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    return data


def scenario_for(config: dict[str, Any], spec: dict[str, Any], instance: str, name: str = "s") -> Any:
    return make_scenario(config, name, 1.0, overrides=spec.get("overrides"),
                         weekly_plan=spec.get("weekly_plan", "normal"),
                         congested_weeks=spec.get("congested_weeks", ()), instance=instance)


def compact(config: dict[str, Any], sc: Any, result: dict[str, Any], mode: str) -> dict[str, Any]:
    """What a plan decided and what it costs, recomputed by the independent accounting."""
    out: dict[str, Any] = {"status": result["status"], "objective_usd": result.get("objective_usd"),
                           "stats": result["stats"], "step_1": result.get("step_1")}
    if "solution" not in result:
        return out
    solution = result["solution"][sc.name]
    account = evaluate(config, sc, result["first_stage"], solution, mode=mode)
    out.update(first_stage=result["first_stage"], week_types=solution["week_types"],
               trips={typ: ops["trips"] for typ, ops in solution["types"].items()},
               peak_kw=solution["peak_kw"], accounting=account,
               delivered=_delivered(solution, sc))
    return out


def _delivered(solution: dict[str, Any], sc: Any) -> dict[str, float]:
    mass = {o.id: o.mass_kg for o in sc.orders}
    out: dict[str, float] = {}
    for item in solution["shipments"]:
        out[item["channel"]] = out.get(item["channel"], 0.0) + item["units"] * mass[item["order"]]
    out["air"] = sum(a["units"] * mass[a["order"]] for a in solution["air"])
    return {k: round(v, 3) for k, v in out.items()}


def run_job(job: dict[str, Any]) -> list[dict[str, Any]]:
    """One setting: plan A, plan C alone, plan B alone with a solver seed, or the chain B -> B* -> C (C starts from
    the better of B and B*)."""
    spec = protocol()
    config = load_v2(job.get("config_overrides"))
    sc = scenario_for(config, job["scenario"], job["instance"])
    options = dict(time_limit=spec["solver"]["time_limit"], mip_gap=spec["solver"]["mip_gap"])
    started = time.perf_counter()
    if job["plans"] == "search":
        return [run_search(job, config, sc, spec)]
    if job["plans"] == "B":
        b = sequential(config, [sc], random_seed=job["seed"], **options)
        return [{"id": f"{job['id']}/B", **job["meta"], "plan": "B", "seed": job["seed"],
                 **compact(config, sc, b, "joint"), "seconds": round(time.perf_counter() - started, 1)}]
    if job["plans"] in ("A", "C"):
        mode = "diesel" if job["plans"] == "A" else "joint"
        result = solve(config, [sc], mode=mode, **options)
        return [{"id": f"{job['id']}/{job['plans']}", **job["meta"], "plan": job["plans"],
                 **compact(config, sc, result, mode), "seconds": round(time.perf_counter() - started, 1)}]
    rows = []
    b = sequential(config, [sc], **options)
    rows.append({"id": f"{job['id']}/B", **job["meta"], "plan": "B", **compact(config, sc, b, "joint")})
    best = sequential(config, [sc], best_tie_break=True, start=b.get("values"), step1=b.get("step_1_result"),
                      **options)
    rows.append({"id": f"{job['id']}/B*", **job["meta"], "plan": "B*", **compact(config, sc, best, "joint")})
    starts = [r for r in (b, best) if "values" in r]
    start = min(starts, key=lambda r: r["objective_usd"])["values"] if starts else None
    c = solve(config, [sc], mode="joint", start=start, **options)
    rows.append({"id": f"{job['id']}/C", **job["meta"], "plan": "C", **compact(config, sc, c, "joint"),
                 "started_from": None if start is None else min(starts, key=lambda r: r["objective_usd"])["mode"]})
    for row in rows:
        row["seconds"] = round(time.perf_counter() - started, 1)
    return rows


def deterministic_jobs(spec: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = []
    for instance in spec["instances"]:
        for name, scenario in spec["scenarios"].items():
            meta = {"group": "deterministic", "instance": instance, "scenario": name}
            for plans in ("A", "BC"):
                jobs.append({"id": f"deterministic/{instance}/{name}", "instance": instance, "scenario": scenario,
                             "plans": plans, "meta": meta})
    return jobs


def run_search(job: dict[str, Any], config: dict[str, Any], sc: Any, spec: dict[str, Any]) -> dict[str, Any]:
    """The fix-and-optimize search from a saved plan; B* keeps the transport cap of its own step 1."""
    from electric_freight.search import default_parts, improve
    item, row = spec["search"], job["row"]
    started = time.perf_counter()
    cap = None
    if row["plan"] == "B*":
        cap = row["step_1"]["objective_usd"] * (1 + 1e-7) + 1e-3  # as in fleet.sequential
    parts = default_parts(config, row["instance"], window_hours=item["parts"]["window_hours"],
                          step_hours=item["parts"]["step_hours"])
    result = improve(config, [sc], {sc.name: row["trips"]}, parts=parts, transport_cap=cap,
                     sub_time_limit=item["sub_time_limit"], mip_gap=spec["solver"]["mip_gap"], rounds=item["rounds"],
                     log=lambda _: None)
    return {"id": job["last"], **job["meta"], "plan": row["plan"], "started_from": job["target"],
            "full_solve": {"objective_usd": row["objective_usd"], "dual_bound": row["stats"]["dual_bound"]},
            **compact(config, sc, result, "joint"), "search": result.get("search"),
            "seconds": round(time.perf_counter() - started, 1)}


def search_jobs(spec: dict[str, Any]) -> list[dict[str, Any]]:
    done = saved()
    jobs = []
    for target in spec["search"]["targets"]:
        row = done.get(target)
        if row is None or "trips" not in row:
            print(f"skip {target}: no saved plan", flush=True)
            continue
        meta = {"group": "search", "instance": row["instance"], "scenario": row["scenario"]}
        jobs.append({"id": target, "last": f"search/{row['instance']}/{row['scenario']}/{row['plan']}",
                     "instance": row["instance"], "scenario": spec["scenarios"][row["scenario"]], "plans": "search",
                     "target": target, "row": row, "meta": meta})
    return jobs


def tie_break_jobs(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Plan B again with other solver seeds: step 1 has many equally cheap schedules and keeps whichever the search
    meets first, so B's charging cost depends on that choice."""
    item = spec["tie_break"]
    jobs = []
    for instance, name in item["targets"]:
        for seed in item["seeds"]:
            meta = {"group": "tie_break", "instance": instance, "scenario": name}
            jobs.append({"id": f"tie_break/{instance}/{name}/seed{seed}", "instance": instance,
                         "scenario": spec["scenarios"][name], "plans": "B", "seed": seed, "meta": meta})
    return jobs


def boundary_jobs(spec: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = []
    for sweep, item in spec["boundaries"].items():
        for value in item["values"]:
            overrides = {**item.get("base_overrides", {}), item["key"]: value}
            scenario = {"overrides": overrides}
            meta = {"group": "boundaries", "sweep": sweep, "value": value, "instance": item["instance"]}
            jobs.append({"id": f"boundaries/{sweep}/{value}", "instance": item["instance"], "scenario": scenario,
                         "plans": "BC", "meta": meta})
    return jobs


def scaled_capex(config: dict[str, Any], factor: float) -> dict[str, Any]:
    """Overrides that multiply every equipment price by ``factor``."""
    over: dict[str, Any] = {}
    for j, site in config["sites"].items():
        over[f"sites.{j}.open_capex_usd"] = site["open_capex_usd"] * factor
        for q, tier in site["tiers"].items():
            over[f"sites.{j}.tiers.{q}.capex_usd"] = tier["capex_usd"] * factor
        over[f"sites.{j}.upgrades"] = [{**u, "capex_usd": u["capex_usd"] * factor} for u in site["upgrades"]]
        over[f"sites.{j}.connections"] = {sub: v * factor for sub, v in site["connections"].items()}
    for name, sub in config["substations"].items():
        over[f"substations.{name}.expansions"] = [{**x, "capex_usd": x["capex_usd"] * factor}
                                                 for x in sub["expansions"]]
    return over


def sensitivity_jobs(spec: dict[str, Any]) -> list[dict[str, Any]]:
    item = spec["sensitivity"]
    base = load_v2()
    jobs = []
    for case, values in item["cases"].items():
        overrides = dict(values)
        factor = overrides.pop("capex_scale", None)
        if factor is not None:
            overrides.update(scaled_capex(base, float(factor)))
        meta = {"group": "sensitivity", "case": case, "instance": item["instance"], "scenario": item["scenario"]}
        for plan in item["plans"]:
            jobs.append({"id": f"sensitivity/{case}", "instance": item["instance"],
                         "scenario": spec["scenarios"][item["scenario"]], "plans": plan,
                         "config_overrides": overrides, "meta": meta})
    return jobs


def saved() -> dict[str, dict[str, Any]]:
    path = RESULTS / "runs.jsonl"
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    return {row["id"]: row for row in (json.loads(line) for line in lines if line)}


def append(rows: list[dict[str, Any]]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    with (RESULTS / "runs.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def run_group(jobs: list[dict[str, Any]], workers: int, version: str) -> None:
    """``version`` is the code version when the group started; the workers import the code once, at that time."""
    done = saved()
    # A job is done when its last plan is saved: A for "A", B for "B", C for "C" and for the chain "BC" (C is
    # written last); a search job names its row in "last".
    todo = [j for j in jobs if j.get("last", f"{j['id']}/{j['plans'][-1]}") not in done]
    print(f"{len(todo)} of {len(jobs)} jobs to run, code {version}", flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_job, job): job for job in todo}
        for future in as_completed(futures):
            rows = future.result()
            for row in rows:
                row["code_version"] = version
            append(rows)
            for row in rows:
                print(json.dumps({k: row.get(k) for k in ("id", "status", "objective_usd")}), flush=True)


def horizon_jobs(spec: dict[str, Any]) -> list[tuple[str, dict[str, Any], str, bool]]:
    """Every target plan twice: equipment fixed (operations only) and equipment free."""
    done = saved()
    out = []
    for target in spec["horizon_check"]:
        row = done.get(target)
        if row is None or "first_stage" not in row:
            print(f"skip {target}: no saved plan", flush=True)
            continue
        for free in (False, True):
            if f"horizon/{target}/{'free' if free else 'fixed'}" not in done:
                out.append((target, row, row["instance"], free))
    return out


def run_horizon(item: tuple[str, dict[str, Any], str, bool]) -> dict[str, Any]:
    target, row, instance, free = item
    spec = protocol()
    config = load_v2()
    scenario_spec = spec["scenarios"][row["scenario"]] if row.get("scenario") in spec["scenarios"] else {}
    sc = scenario_for(config, scenario_spec, instance)
    plan = {"first_stage": row["first_stage"],
            "solution": {sc.name: {"week_types": row["week_types"],
                                   "types": {typ: {"trips": trips} for typ, trips in row["trips"].items()}}}}
    check = horizon_check(config, sc, plan, free_first_stage=free, mip_gap=spec["solver"]["mip_gap"],
                          time_limit=spec["horizon"]["time_limit"])
    account = row["accounting"]["cost_usd"]
    keys = ["trips", "waiting", "energy", "demand_charge"] + (["equipment", "lease"] if free else [])
    representative = sum(float(account.get(k, 0.0)) for k in keys)
    horizon_cost = check.get("objective_usd")
    bound = check.get("dual_bound")
    out = {"id": f"horizon/{target}/{'free' if free else 'fixed'}", "group": "horizon", "target": target,
           "equipment": "free" if free else "fixed", "status": check["status"],
           "representative_usd": representative,
           **{k: v for k, v in check.items() if k not in ("operations", "status")}}
    if horizon_cost is not None:
        # restriction cost = representative weeks minus unbroken horizon; the interval uses the dual bound
        out["restriction_usd"] = representative - horizon_cost
        out["restriction_interval_usd"] = [representative - horizon_cost,
                                           representative - (bound if bound is not None else horizon_cost)]
    return out


def run_stochastic(spec: dict[str, Any], workers: int, version: str) -> None:
    from dataclasses import replace

    from electric_freight.stochastic import decompose, deterministic_equivalent, scenario_set
    item = spec["stochastic"]
    config = load_v2()
    scenarios = scenario_set(config, item["scenarios"], instance=item["instance"])
    options = dict(time_limit=spec["solver"]["time_limit"], mip_gap=spec["solver"]["mip_gap"])
    started = time.perf_counter()
    # The deterministic scenario's perfect-information solve starts from the better of plans B and B*.
    alone = replace(next(s for s in scenarios if s.name == item["deterministic"]), probability=1.0)
    b = sequential(config, [alone], **options)
    best = sequential(config, [alone], best_tie_break=True, start=b.get("values"), step1=b.get("step_1_result"),
                      **options)
    starts = [r for r in (b, best) if "values" in r]
    start = min(starts, key=lambda r: r["objective_usd"])["values"] if starts else None
    result = decompose(config, scenarios, deterministic=item["deterministic"], workers=workers, options=options,
                       start=start)
    result["seconds"] = round(time.perf_counter() - started, 1)
    result["code_version"] = version
    equivalent_start = result.pop("start_for_equivalent", None)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stochastic.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: result.get(k) for k in ("WS", "RP", "EEV", "VSS", "EVPI")}, default=str)[:2000], flush=True)
    if item.get("deterministic_equivalent"):
        started = time.perf_counter()
        de = deterministic_equivalent(config, scenarios, time_limit=item["deterministic_equivalent"]["time_limit"],
                                      mip_gap=spec["solver"]["mip_gap"], start=equivalent_start)
        de["seconds"] = round(time.perf_counter() - started, 1)
        de["started_from"] = "RP candidate" if equivalent_start else None
        de["code_version"] = version
        (RESULTS / "stochastic_de.json").write_text(json.dumps(de, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({k: de.get(k) for k in ("status", "objective_usd", "stats")}, default=str), flush=True)


def write_manifest() -> None:
    files = sorted(p for p in RESULTS.iterdir() if p.is_file() and p.name != "manifest.json")
    manifest = {"code_version": code_version(), "protocol_sha256": sha256(PROTOCOL),
                "sha256": {p.name: sha256(p) for p in files}}
    (RESULTS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("group", choices=["deterministic", "tie_break", "search", "boundaries", "horizon",
                                          "stochastic", "sensitivity", "manifest"])
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    spec = protocol()
    version = code_version()  # once, when the group starts: edits made while it runs do not relabel its rows
    if args.group == "deterministic":
        run_group(deterministic_jobs(spec), args.workers, version)
    elif args.group == "tie_break":
        run_group(tie_break_jobs(spec), args.workers, version)
    elif args.group == "search":
        run_group(search_jobs(spec), args.workers, version)
    elif args.group == "boundaries":
        run_group(boundary_jobs(spec), args.workers, version)
    elif args.group == "sensitivity":
        run_group(sensitivity_jobs(spec), args.workers, version)
    elif args.group == "horizon":
        items = horizon_jobs(spec)
        print(f"{len(items)} horizon checks to run, code {version}", flush=True)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for row in pool.map(run_horizon, items):
                row["code_version"] = version
                append([row])
                print(json.dumps({k: row.get(k) for k in ("id", "status", "restriction_usd")}), flush=True)
    elif args.group == "stochastic":
        run_stochastic(spec, args.workers, version)
    write_manifest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
