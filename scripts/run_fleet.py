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
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from electric_freight.fleet import horizon_check, load_v2, make_scenario, sequential, solve  # noqa: E402
from electric_freight.fleet_accounting import audit_plan, evaluate_horizon  # noqa: E402

PROTOCOL = ROOT / "benchmarks" / "electric_freight_v2" / "protocol.json"
SUPPLEMENT = PROTOCOL.with_name("protocol_supplement_1.json")
RESULTS = ROOT / "benchmark_results" / "electric_freight_v2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_version() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    dirty = git("status", "--porcelain", "--", "electric_freight", "scripts/run_fleet.py",
                "scripts/check_fleet_presolve.py", "benchmarks/electric_freight_v2")
    return git("rev-parse", "--short", "HEAD") + ("+uncommitted" if dirty else "")


def protocol() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    addition = json.loads(SUPPLEMENT.read_text(encoding="utf-8"))
    data["sensitivity"]["plans"] = addition["sensitivity"]["plans"]
    data["presolve_check"] = addition["presolve_check"]
    return data


def scenario_for(config: dict[str, Any], spec: dict[str, Any], instance: str, name: str = "s") -> Any:
    return make_scenario(config, name, 1.0, overrides=spec.get("overrides"),
                         weekly_plan=spec.get("weekly_plan", "normal"),
                         congested_weeks=spec.get("congested_weeks", ()), instance=instance)


def compact(config: dict[str, Any], sc: Any, result: dict[str, Any], mode: str) -> dict[str, Any]:
    """What a plan decided and what it costs, recomputed by the independent accounting."""
    out: dict[str, Any] = {"status": result["status"], "objective_usd": result.get("objective_usd"),
                           "stats": result["stats"], "step_1": result.get("step_1")}
    if "cargo_fixing" in result:
        out["cargo_fixing"] = result["cargo_fixing"]  # plan B's step 2: step-1 quantities, or week types only
    if "solution" not in result:
        return out
    solution = result["solution"][sc.name]
    account = audit_plan(config, sc, result, mode)
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
    if job["meta"]["group"] == "sensitivity" and "step_1_result" in b and "solution" in b["step_1_result"]:
        rows[-1]["step_1_accounting"] = audit_plan(config, sc, b["step_1_result"], "relaxed")
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
    """Append rows under a lock file, so two groups running at once never interleave their lines."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row) + "\n" for row in rows)
    lock = RESULTS / "runs.jsonl.lock"
    for _ in range(1200):
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            time.sleep(0.5)
    else:
        raise RuntimeError(f"{lock} is held; delete it if no run is writing")
    try:
        with (RESULTS / "runs.jsonl").open("a", encoding="utf-8", newline="\n") as out:
            out.write(text)
    finally:
        os.close(handle)
        lock.unlink()


def run_group(jobs: list[dict[str, Any]], workers: int, version: str, *, only: list[str] | None = None,
              note: str | None = None) -> None:
    """``version`` is the code version when the group started; the workers import the code once, at that time.
    ``only`` runs just these jobs again ("<id>/<plans>", for example deterministic/fleet/border_congestion/BC), even
    when saved; the new rows carry ``note`` and come after the old ones, which stay in the file (the summary reads
    the last row of an id)."""
    done = saved()
    # A job is done when its last plan is saved: A for "A", B for "B", C for "C" and for the chain "BC" (C is
    # written last); a search job names its row in "last".
    if only:
        todo = [j for j in jobs if f"{j['id']}/{j['plans']}" in only]
    else:
        todo = [j for j in jobs if j.get("last", f"{j['id']}/{j['plans'][-1]}") not in done]
    print(f"{len(todo)} of {len(jobs)} jobs to run, code {version}", flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_job, job): job for job in todo}
        for future in as_completed(futures):
            rows = future.result()
            for row in rows:
                row["code_version"] = version
                if note:
                    row["rerun_note"] = note
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


def run_horizon(item: tuple[str, dict[str, Any], str, bool], *,
                highs_options: dict[str, Any] | None = None) -> dict[str, Any]:
    target, row, instance, free = item
    spec = protocol()
    config = load_v2()
    scenario_spec = spec["scenarios"][row["scenario"]] if row.get("scenario") in spec["scenarios"] else {}
    sc = scenario_for(config, scenario_spec, instance)
    plan = {"first_stage": row["first_stage"],
            "solution": {sc.name: {"week_types": row["week_types"],
                                   "types": {typ: {"trips": trips} for typ, trips in row["trips"].items()}}}}
    check = horizon_check(config, sc, plan, free_first_stage=free, mip_gap=spec["solver"]["mip_gap"],
                          time_limit=spec["horizon"]["time_limit"], highs_options=highs_options)
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
        out["accounting"] = evaluate_horizon(config, sc, check, row["week_types"])
        # restriction cost = representative weeks minus unbroken horizon; the interval uses the dual bound
        out["restriction_usd"] = representative - horizon_cost
        out["restriction_interval_usd"] = [representative - horizon_cost,
                                           representative - (bound if bound is not None else horizon_cost)]
    return out


def stochastic_designs(spec: dict[str, Any], workers: int, config: dict[str, Any],
                       scenarios: list[Any]) -> dict[str, Any]:
    from dataclasses import replace

    from electric_freight.stochastic import decompose
    item = spec["stochastic"]
    options = dict(time_limit=spec["solver"]["time_limit"], mip_gap=spec["solver"]["mip_gap"])
    started = time.perf_counter()
    # The deterministic scenario's perfect-information solve starts from the better of plans B and B*.
    alone = replace(next(s for s in scenarios if s.name == item["deterministic"]), probability=1.0)
    b = sequential(config, [alone], **options)
    best = sequential(config, [alone], best_tie_break=True, start=b.get("values"), step1=b.get("step_1_result"),
                      **options)
    starts = [r for r in (b, best) if "values" in r]
    start = min(starts, key=lambda r: r["objective_usd"])["values"] if starts else None
    warmups = {}
    for label, plan, mode in (("step_1", b["step_1_result"], "relaxed"), ("B", b, "joint"), ("B*", best, "joint")):
        warmups[label] = compact(config, alone, plan, mode)
    replay_target = next(t for t in spec["presolve_check"]["targets"] if t.startswith("stochastic/RP/"))
    result = decompose(config, scenarios, deterministic=item["deterministic"], workers=workers, options=options,
                       start=start, replay_scenario=replay_target.split("/")[2])
    result["warmups"] = warmups
    result["seconds"] = round(time.perf_counter() - started, 1)
    return result


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    temp.replace(path)


def checkpoint_directory() -> Path:
    return ROOT / "_local" / "electric_freight_v2" / sha256(SUPPLEMENT)


def run_stochastic(spec: dict[str, Any], workers: int, version: str) -> None:
    from electric_freight.stochastic import deterministic_equivalent, scenario_set
    if all((RESULTS / name).exists() for name in ("stochastic.json", "stochastic_de.json")):
        print("Two-stage results already saved", flush=True)
        return
    item = spec["stochastic"]
    config = load_v2()
    scenarios = scenario_set(config, item["scenarios"], instance=item["instance"])
    checkpoint = checkpoint_directory() / "stochastic.json"
    if checkpoint.exists():
        result = json.loads(checkpoint.read_text(encoding="utf-8"))
    else:
        result = stochastic_designs(spec, workers, config, scenarios)
        result["code_version"] = version
        save_json(checkpoint, result)
    equivalent_start = result.pop("start_for_equivalent", None)
    print(json.dumps({k: result.get(k) for k in ("WS", "RP", "EEV", "VSS", "EVPI")}, default=str)[:2000], flush=True)
    if item.get("deterministic_equivalent"):
        started = time.perf_counter()
        de = deterministic_equivalent(config, scenarios, time_limit=item["deterministic_equivalent"]["time_limit"],
                                      mip_gap=spec["solver"]["mip_gap"], start=equivalent_start)
        de["seconds"] = round(time.perf_counter() - started, 1)
        de["started_from"] = "best evaluated design" if equivalent_start else None
        de["code_version"] = version
        if "RP" in result:
            low, high = result["RP"]["interval"]
            if de["stats"]["dual_bound"] is not None:
                low = max(low, de["stats"]["dual_bound"])
            if de.get("objective_usd") is not None:
                high = min(high, de["objective_usd"])
            result["certified_intervals_usd"] = {"RP": [low, high],
                "EVPI": [max(0.0, low - result["WS"]["value"]), high - result["WS"]["interval"][0]]}
            if result["EEV"]["status"] == "ok":
                lower_eev, upper_eev = result["EEV"]["interval"]
                result["certified_intervals_usd"]["VSS"] = [max(0.0, lower_eev - high), upper_eev - low]
        save_json(RESULTS / "stochastic_de.json", de)
        print(json.dumps({k: de.get(k) for k in ("status", "objective_usd", "stats")}, default=str), flush=True)
    save_json(RESULTS / "stochastic.json", result)


def write_manifest() -> None:
    files = sorted(p for p in RESULTS.iterdir() if p.is_file() and p.suffix in (".json", ".jsonl", ".md"))
    manifest = {"code_version": code_version(), "protocol_sha256": sha256(PROTOCOL),
                "protocol_supplement_1_sha256": sha256(SUPPLEMENT), "paths_relative_to": "..",
                "sha256": {p.name: sha256(p) for p in files}}
    directory = RESULTS / "supplement_1"
    save_json(directory / "manifest.json", manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("group", choices=["deterministic", "tie_break", "search", "boundaries", "horizon",
                                          "stochastic", "sensitivity", "manifest"])
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--only", nargs="+", help="run these jobs again (<id>/<plans>), even when saved")
    parser.add_argument("--note", help="why they run again; stored on the new rows")
    args = parser.parse_args(argv)
    spec = protocol()
    version = code_version()  # once, when the group starts: edits made while it runs do not relabel its rows
    groups = {"deterministic": deterministic_jobs, "tie_break": tie_break_jobs, "search": search_jobs,
              "boundaries": boundary_jobs, "sensitivity": sensitivity_jobs}
    if args.group in groups:
        run_group(groups[args.group](spec), args.workers, version, only=args.only, note=args.note)
    elif args.group == "horizon":
        items = horizon_jobs(spec)
        checkpoint = checkpoint_directory() / "horizon.json"
        finished = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {}
        todo = [i for i in items if f"horizon/{i[0]}/{'free' if i[3] else 'fixed'}" not in finished]
        print(f"{len(todo)} horizon checks to run, code {version}", flush=True)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for row in pool.map(run_horizon, todo):
                row["code_version"] = version
                finished[row["id"]] = row
                save_json(checkpoint, finished)
                print(json.dumps({k: row.get(k) for k in ("id", "status", "restriction_usd")}), flush=True)
        done = saved()
        append([row for key, row in finished.items() if key not in done])
    elif args.group == "stochastic":
        run_stochastic(spec, args.workers, version)
    write_manifest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
