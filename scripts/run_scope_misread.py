"""Run the scope-misreading study: plan under the wrong scope of a notice, live through the right one.

    python scripts/run_scope_misread.py                 # writes benchmark_results/scope_misread_v1
    python scripts/run_scope_misread.py --check         # recompute and compare with the saved results
    python scripts/run_scope_misread.py --refinement    # finer grid chosen after the first results (exploratory)

No model is called. Everything is solved locally with HiGHS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network_planning.data import Scenario, build_network, scenario_from_spec  # noqa: E402
from network_planning.misread import misread_case, with_lane_capacity  # noqa: E402

CONFIG = ROOT / "benchmarks" / "scope_misread_v1" / "config.json"
RESULTS = ROOT / "benchmark_results" / "scope_misread_v1"
RETEST = ROOT / "benchmark_results" / "planning_agent_v2_1" / "a04_retest" / "runs.jsonl"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_version() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    dirty = git("status", "--porcelain", "--", "network_planning", "scripts/run_scope_misread.py",
                "benchmarks/scope_misread_v1")
    return git("rev-parse", "--short", "HEAD") + ("+uncommitted" if dirty else "")


def scenario(name: str, lanes: list[str], disruption: dict[str, Any]) -> Scenario:
    spec = {"disruptions": [{"lanes": lanes, "start_week": disruption["start_week"],
                             "end_week": disruption["end_week"],
                             "capacity_factor": 1 + disruption["capacity_change_pct"] / 100,
                             "cost_factor": 1 + disruption["cost_change_pct"] / 100}]}
    return scenario_from_spec(name, spec, 1.0)


def reproduction() -> dict[str, Any]:
    """The saved A04 arguments through the tool layer, under the old and the fixed lane contract."""
    from planning_agent.tools import Session
    row = json.loads(RETEST.read_text(encoding="utf-8").splitlines()[0])
    call = next(c for c in row["tool_calls"] if c["name"] == "create_scenario")
    out: dict[str, Any] = {"source_run": row["run_id"], "arguments": call["arguments"]["disruptions"]}
    for label, additive in (("fixed_contract", False), ("old_contract", True)):
        session = Session(additive_mode_lanes=additive)
        made = session.call("create_scenario", {**call["arguments"], "name": "a04"})
        plan = session.call("solve_plan", {"network": "marvell", "scenario": "a04"})
        base = session.call("solve_plan", {"network": "marvell"})
        out[label] = {"lanes": [d["lanes"] for d in made["definition"]["disruptions"]],
                      "total_cost_usd": plan["total_cost_usd"], "emissions_t": float(plan["emissions_t"]),
                      "service_level_pct": plan["service_level_pct"],
                      "normal_cost_usd": base["total_cost_usd"], "normal_emissions_t": float(base["emissions_t"])}
    return out


def summary_row(case: dict[str, Any]) -> dict[str, Any]:
    if case["status"] != "ok":
        return {"capacity_ratio": case["capacity_ratio"], "status": case["status"]}
    row: dict[str, Any] = {
        "capacity_ratio": case["capacity_ratio"], "capacity_kg": case["capacity_kg"],
        "best_cost_usd": case["best_plan"]["total_cost_usd"],
        "best_service_level": case["best_plan"]["service_level"],
        "my_air_kg_weeks_7_9_best": round(sum(case["flows_best_plan_kg"]["MY_air"][6:9]), 1),
        "my_air_kg_weeks_7_9_believed": round(sum(case["flows_believed_plan_kg"]["MY_air"][6:9]), 1),
        "plans_differ": case["plans_differ"]["shipment_variables_differing"],
        "optimum_difference_usd": case["optimum_difference_usd"],
        "no_replanning_regret_usd": case["no_replanning"]["regret_usd"],
        "no_replanning_feasible": case["no_replanning"]["feasible"]}
    for item in case["commitments"]:
        week = item["reveal_week"]
        row[f"regret_reveal_{week}_usd"] = item.get("regret_usd", item["status"])
        if "favourable_tie_break" in item:
            row[f"regret_reveal_{week}_tie_break_usd"] = item["favourable_tie_break"]["regret_usd"]
    return row


def run(config_path: Path = CONFIG, reproduce: bool = True) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    spec = config["network"]
    net = build_network(spec["name"], spec["n_skus"], spec["weeks"], spec["seed"])
    actual = scenario("actual_scope", config["actual_lanes"], config["disruption"])
    believed = scenario("believed_scope", config["believed_lanes"], config["disruption"])
    lane, varied = config["varied"]["lane"], config["varied"]
    base_kg = net.lanes[lane].capacity_kg / varied["capacity_ratio_original"]
    cases = []
    for ratio in varied["capacity_ratios"]:
        capacity = net.lanes[lane].capacity_kg if ratio == varied["capacity_ratio_original"] else round(
            ratio * base_kg, 1)
        record = misread_case(with_lane_capacity(net, lane, capacity), actual, believed, config["reveal_weeks"],
                              mip_gap=config["solver"]["mip_gap"], time_limit=config["solver"]["time_limit"],
                              tie_break_weight=config["tie_break_weight"], tolerance_usd=config["tolerance_usd"])
        cases.append({"capacity_ratio": ratio, "lane": lane, "capacity_kg": capacity, **record})
        print(json.dumps(summary_row(cases[-1])), flush=True)
    return {"reproduction": reproduction() if reproduce else None, "cases": cases}


def write(results: dict[str, Any], config_path: Path = CONFIG, prefix: str = "") -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{prefix}cases.jsonl").write_text(
        "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in results["cases"]), encoding="utf-8",
        newline="\n")
    if results["reproduction"] is not None:
        (RESULTS / "reproduction.json").write_text(json.dumps(results["reproduction"], indent=2) + "\n",
                                                   encoding="utf-8", newline="\n")
    summary = {"config": config_path.relative_to(ROOT).as_posix(), "config_sha256": sha256(config_path),
               "rows": [summary_row(case) for case in results["cases"]]}
    (RESULTS / f"{prefix}summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8",
                                                   newline="\n")
    files = sorted(p for p in RESULTS.iterdir() if p.name != "manifest.json")
    manifest = {"code_version": code_version(),
                "commands": ["python scripts/run_scope_misread.py", "python scripts/run_scope_misread.py --refinement"],
                "sha256": {p.name: sha256(p) for p in files}}
    (RESULTS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="recompute and compare with the saved summary")
    parser.add_argument("--refinement", action="store_true",
                        help="the finer grid in refinement.json, chosen after the first results (exploratory)")
    args = parser.parse_args(argv)
    config_path = CONFIG.with_name("refinement.json") if args.refinement else CONFIG
    prefix = "refinement_" if args.refinement else ""
    results = run(config_path, reproduce=not args.refinement)
    if args.check:
        saved = json.loads((RESULTS / f"{prefix}summary.json").read_text(encoding="utf-8"))["rows"]
        now = [summary_row(case) for case in results["cases"]]
        same = json.dumps(saved, sort_keys=True) == json.dumps(now, sort_keys=True)
        print("saved summary reproduces" if same else "saved summary differs from this run")
        return 0 if same else 1
    write(results, config_path, prefix)
    print(f"wrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
