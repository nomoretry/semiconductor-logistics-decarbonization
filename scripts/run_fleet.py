"""Run the model-v2 study: plans A, B, B* and C by instance and scenario, the boundary sweeps, the unbroken-horizon
check of the representative weeks, and the two-stage stochastic plan.

    python scripts/run_fleet.py deterministic --workers 6
    python scripts/run_fleet.py boundaries --workers 6
    python scripts/run_fleet.py horizon --workers 3
    python scripts/run_fleet.py stochastic --workers 6

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
    """One setting: plan A, or the chain B -> B* -> C (C starts from the better of B and B*)."""
    spec = protocol()
    config = load_v2(job.get("config_overrides"))
    sc = scenario_for(config, job["scenario"], job["instance"])
    options = dict(time_limit=spec["solver"]["time_limit"], mip_gap=spec["solver"]["mip_gap"])
    started = time.perf_counter()
    if job["plans"] == "A":
        result = solve(config, [sc], mode="diesel", **options)
        return [{"id": f"{job['id']}/A", **job["meta"], "plan": "A",
                 **compact(config, sc, result, "diesel"), "seconds": round(time.perf_counter() - started, 1)}]
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


def run_group(jobs: list[dict[str, Any]], workers: int) -> None:
    done = saved()
    todo = [j for j in jobs if not any(k.startswith(j["id"] + "/") for k in done)]
    print(f"{len(todo)} of {len(jobs)} jobs to run", flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_job, job): job for job in todo}
        for future in as_completed(futures):
            rows = future.result()
            for row in rows:
                row["code_version"] = code_version()
            append(rows)
            for row in rows:
                print(json.dumps({k: row.get(k) for k in ("id", "status", "objective_usd")}), flush=True)


def horizon_jobs(spec: dict[str, Any]) -> list[tuple[str, dict[str, Any], str]]:
    done = saved()
    out = []
    for target in spec["horizon_check"]:
        row = done.get(target)
        if row is None or "first_stage" not in row:
            print(f"skip {target}: no saved plan", flush=True)
            continue
        out.append((target, row, row["instance"]))
    return out


def run_horizon(item: tuple[str, dict[str, Any], str]) -> dict[str, Any]:
    target, row, instance = item
    spec = protocol()
    config = load_v2()
    scenario_spec = spec["scenarios"][row["scenario"]] if row.get("scenario") in spec["scenarios"] else {}
    sc = scenario_for(config, scenario_spec, instance)
    plan = {"first_stage": row["first_stage"], "solution": {sc.name: {"week_types": row["week_types"]}}}
    check = horizon_check(config, sc, plan, mip_gap=spec["solver"]["mip_gap"],
                          time_limit=spec["horizon"]["time_limit"])
    account = row["accounting"]["cost_usd"]
    representative = sum(account.get(k, 0.0) for k in ("trips", "waiting", "energy", "demand_charge"))
    return {"id": f"horizon/{target}", "group": "horizon", "target": target, "status": check["status"],
            "representative_operating_usd": representative, **{k: v for k, v in check.items() if k != "operations"},
            "difference_usd": None if "operating_cost_usd" not in check
            else check["operating_cost_usd"] - representative}


def run_stochastic(spec: dict[str, Any], workers: int) -> None:
    from electric_freight.stochastic import decompose, deterministic_equivalent, scenario_set
    item = spec["stochastic"]
    config = load_v2()
    scenarios = scenario_set(config, item["scenarios"], instance=item["instance"])
    options = dict(time_limit=spec["solver"]["time_limit"], mip_gap=spec["solver"]["mip_gap"])
    started = time.perf_counter()
    result = decompose(config, scenarios, deterministic=item["deterministic"], workers=workers, options=options)
    result["seconds"] = round(time.perf_counter() - started, 1)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stochastic.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: result.get(k) for k in ("WS", "RP", "EEV", "VSS", "EVPI")}, default=str)[:2000], flush=True)
    if item.get("deterministic_equivalent"):
        started = time.perf_counter()
        de = deterministic_equivalent(config, scenarios, time_limit=item["deterministic_equivalent"]["time_limit"],
                                      mip_gap=spec["solver"]["mip_gap"])
        de["seconds"] = round(time.perf_counter() - started, 1)
        (RESULTS / "stochastic_de.json").write_text(json.dumps(de, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({k: de.get(k) for k in ("status", "objective_usd", "stats")}, default=str), flush=True)


def write_manifest() -> None:
    files = sorted(p for p in RESULTS.iterdir() if p.is_file() and p.name != "manifest.json")
    manifest = {"code_version": code_version(), "protocol_sha256": sha256(PROTOCOL),
                "sha256": {p.name: sha256(p) for p in files}}
    (RESULTS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("group", choices=["deterministic", "boundaries", "horizon", "stochastic", "manifest"])
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    spec = protocol()
    if args.group == "deterministic":
        run_group(deterministic_jobs(spec), args.workers)
    elif args.group == "boundaries":
        run_group(boundary_jobs(spec), args.workers)
    elif args.group == "horizon":
        items = horizon_jobs(spec)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for row in pool.map(run_horizon, items):
                row["code_version"] = code_version()
                append([row])
                print(json.dumps({k: row.get(k) for k in ("id", "status", "difference_usd")}), flush=True)
    elif args.group == "stochastic":
        run_stochastic(spec, args.workers)
    write_manifest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
