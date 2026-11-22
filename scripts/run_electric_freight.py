"""Run the electric freight study: plans A, B and C under each scenario, the substation rules and the sweeps.

    python scripts/run_electric_freight.py --workers 6            # writes benchmark_results/electric_freight_v1
    python scripts/run_electric_freight.py --workers 6 --check    # recompute and compare with the saved summary

No model is called. Everything is solved locally with HiGHS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from electric_freight.data import export_orders, load_config, orders_from  # noqa: E402
from electric_freight.model import aggregate_absorption, solve, solve_sequential  # noqa: E402

PROTOCOL = ROOT / "benchmarks" / "electric_freight_v1" / "config.json"
RESULTS = ROOT / "benchmark_results" / "electric_freight_v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_version() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    dirty = git("status", "--porcelain", "--", "electric_freight", "network_planning",
                "scripts/run_electric_freight.py", "benchmarks/electric_freight_v1")
    return git("rev-parse", "--short", "HEAD") + ("+uncommitted" if dirty else "")


def exported() -> dict[str, Any]:
    spec = json.loads(PROTOCOL.read_text(encoding="utf-8"))["orders"]
    return export_orders(spec["scenario"], lane=spec["lane"], network=spec["network"])


def run_one(job: dict[str, Any]) -> dict[str, Any]:
    """One plan in one setting. Jobs are independent so they can be solved side by side."""
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    cargo = exported()
    orders = [] if job["plan"] == "C_no_chips" else orders_from(cargo)
    air = {**cargo["air_fallback"], "road_old_kg_co2e_per_kg": cargo["lane"]["kg_co2e_per_kg_old_basis"]}
    config = load_config(job["overrides"])
    options: dict[str, Any] = dict(congested_weeks=job["congested_weeks"], air=air,
                                   mip_gap=protocol["solver"]["mip_gap"], time_limit=protocol["solver"]["time_limit"])
    plan = job["plan"]
    if plan == "A_diesel":
        result = solve(config, orders, mode="diesel", **options)
    elif plan == "B_sequential":
        result = solve_sequential(config, orders, **options)
    elif plan == "C_fixed_normal_equipment":
        result = solve(config, orders, mode="joint", fixed_equipment=job["equipment"], **options)
    else:
        result = solve(config, orders, mode="joint", **options)
    solution = result.get("solution") or {}
    blocks = {key: value for key, value in (solution.get("blocks") or {}).items() if value["used"]}
    if solution:
        solution = {**solution, "blocks": blocks}
    return {"id": job["id"], "group": job["group"], "setting": job["setting"], "plan": plan,
            "overrides": job["overrides"], "congested_weeks": job["congested_weeks"], "status": result["status"],
            "stats": result["stats"], "objective_usd": result.get("objective_usd"),
            "objective_drift": result.get("objective_drift"), "step_1": result.get("step_1"),
            "accounting": result.get("accounting"), "solution": solution}


def jobs(protocol: dict[str, Any], normal_equipment: dict[str, Any] | None) -> list[dict[str, Any]]:
    out = []

    def add(group: str, setting: str, plan: str, overrides: dict[str, Any], congested: list[int],
            **extra: Any) -> None:
        out.append({"id": f"{group}/{setting}/{plan}", "group": group, "setting": setting, "plan": plan,
                    "overrides": overrides, "congested_weeks": congested, **extra})

    for name, spec in protocol["scenarios"].items():
        for plan in ("A_diesel", "B_sequential", "C_joint", "C_no_chips"):
            add("scenario", name, plan, spec["overrides"], spec["congested_weeks"])
        if normal_equipment is not None and name != "normal":
            add("scenario", name, "C_fixed_normal_equipment", spec["overrides"], spec["congested_weeks"],
                equipment=normal_equipment)
    rules = protocol["substation_rules"]
    base = protocol["scenarios"][rules["scenario"]]
    for rule in rules["rules"]:
        for plan in ("B_sequential", "C_joint"):
            add("substation_rule", rule, plan, {**base["overrides"], "substation_rule": rule}, base["congested_weeks"])
    sweeps = protocol["sweeps"]
    for air_on in sweeps["consolidation_kg"]["air_enabled"]:
        for kg in sweeps["consolidation_kg"]["values"]:
            for plan in sweeps["consolidation_kg"]["plans"]:
                add("sweep_consolidation", f"air={air_on}/kg={kg}", plan,
                    {"carrier.weekly_consolidation_kg": kg, "air_fallback.enabled": air_on}, [])
    for multiplier in sweeps["holding_multiplier"]["values"]:
        for plan in sweeps["holding_multiplier"]["plans"]:
            add("sweep_holding", f"multiplier={multiplier}", plan,
                {**sweeps["holding_multiplier"]["base_overrides"], "cargo.holding_multiplier": multiplier}, [])
    for kw in sweeps["sg_headroom_kw"]["values"]:
        for plan in sweeps["sg_headroom_kw"]["plans"]:
            add("sweep_headroom", f"kw={kw}", plan,
                {**sweeps["sg_headroom_kw"]["base_overrides"], "substations.SG_SUB.headroom_kw": kw}, [])
    return out


def row(result: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"id": result["id"], "status": result["status"],
                           "solve_seconds": result["stats"]["solve_seconds"], "mip_gap": result["stats"]["mip_gap"]}
    account = result.get("accounting")
    if not account:
        return out
    weeks_with_extra = {w: block.split(":")[1] for w, block in result["solution"]["week_types"].items()
                        if not block.endswith(":none")}
    equipment = account.get("equipment") or {}
    out.update(total_cost_usd=account["total_cost_usd"], cost_usd=account["cost_usd"],
               emissions_kg=account["total_emissions_kg_co2e"], emissions_by_source=account["emissions_kg_co2e"],
               delivered_kg=account["delivered_kg"], extra_trip_weeks=weeks_with_extra,
               equipment={j: f"{e['connectors']}c" + (f"+{e['upgrade']}" if e["upgrade"] else "")
                          for j, e in equipment.items() if e["opened"]},
               peak_kw=account["peak_kw"], energy_kwh=account["energy_kwh"], issues=account["issues"])
    return out


def run(workers: int) -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    cargo = exported()
    bridge = [aggregate_absorption(cargo["weekly_kg"], protocol["aggregate_bridge"]["capacity_kg"], e, late)
              for e, late in protocol["aggregate_bridge"]["cases"]]
    normal = protocol["scenarios"]["normal"]
    first = run_one({"id": "scenario/normal/C_joint", "group": "scenario", "setting": "normal", "plan": "C_joint",
                     "overrides": normal["overrides"], "congested_weeks": normal["congested_weeks"]})
    equipment = (first["accounting"] or {}).get("equipment")
    todo = [job for job in jobs(protocol, equipment) if job["id"] != first["id"]]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = [first, *pool.map(run_one, todo)]
    return {"cargo": cargo, "bridge": bridge, "results": results}


def summary(run_output: dict[str, Any]) -> dict[str, Any]:
    cargo = run_output["cargo"]
    return {"protocol_sha256": sha256(PROTOCOL),
            "cargo": {k: cargo[k] for k in ("source", "weekly_kg", "total_kg", "peak_weekly_kg", "eligible_skus")},
            "air_available_kg": cargo["air_fallback"]["available_kg"],
            "bridge": run_output["bridge"], "rows": [row(r) for r in run_output["results"]]}


def comparable(rows: list[dict[str, Any]]) -> str:
    """Rows without timing, which differs from run to run."""
    return json.dumps([{k: v for k, v in r.items() if k != "solve_seconds"} for r in rows], sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--check", action="store_true", help="recompute and compare with the saved summary")
    args = parser.parse_args(argv)
    output = run(args.workers)
    result = summary(output)
    if args.check:
        saved = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
        same = comparable(saved["rows"]) == comparable(result["rows"]) and saved["bridge"] == result["bridge"]
        print("saved summary reproduces" if same else "saved summary differs from this run")
        return 0 if same else 1
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "orders.json").write_text(json.dumps(output["cargo"], indent=2) + "\n", encoding="utf-8",
                                         newline="\n")
    (RESULTS / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in output["results"]), encoding="utf-8",
                                        newline="\n")
    (RESULTS / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    files = sorted(p for p in RESULTS.iterdir() if p.name != "manifest.json")
    manifest = {"code_version": code_version(), "command": "python scripts/run_electric_freight.py --workers 6",
                "sha256": {p.name: sha256(p) for p in files}}
    (RESULTS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    for item in result["rows"]:
        if item["id"].startswith("scenario/"):
            print(json.dumps({k: item.get(k) for k in ("id", "status", "total_cost_usd", "extra_trip_weeks",
                                                        "equipment", "emissions_kg")}), flush=True)
    print(f"wrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
