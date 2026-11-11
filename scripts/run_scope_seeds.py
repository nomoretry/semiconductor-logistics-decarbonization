"""Repeat the scope-misreading study on other synthetic portfolios (demand seeds), in both directions.

    python scripts/run_scope_seeds.py --workers 6            # writes benchmark_results/scope_seeds_v1
    python scripts/run_scope_seeds.py --workers 6 --check    # recompute and compare with the saved results

No model is called. Everything is solved locally with HiGHS.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network_planning.data import build_network  # noqa: E402
from network_planning.misread import misread_case, with_lane_capacity  # noqa: E402
from scripts.run_scope_misread import code_version, scenario, sha256  # noqa: E402

CONFIG = ROOT / "benchmarks" / "scope_seeds_v1" / "config.json"
RESULTS = ROOT / "benchmark_results" / "scope_seeds_v1"


def one_case(job: tuple[int, float]) -> dict[str, Any]:
    seed, ratio = job
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    spec, varied, solver = config["network"], config["varied"], config["solver"]
    net = build_network(spec["name"], spec["n_skus"], spec["weeks"], seed)
    narrow = scenario("narrow_scope", config["narrow_lanes"], config["disruption"])
    broad = scenario("broad_scope", config["broad_lanes"], config["disruption"])
    lane = varied["lane"]
    base_kg = net.lanes[lane].capacity_kg / varied["capacity_ratio_original"]
    capacity = net.lanes[lane].capacity_kg if ratio == varied["capacity_ratio_original"] else round(
        ratio * base_kg, 1)
    changed = with_lane_capacity(net, lane, capacity)
    options: dict[str, Any] = dict(mip_gap=solver["mip_gap"], time_limit=solver["time_limit"],
                                   tie_break_weight=config["tie_break_weight"],
                                   tolerance_usd=config["tolerance_usd"])
    return {"seed": seed, "capacity_ratio": ratio, "lane": lane, "capacity_kg": capacity,
            "mean_weekly_kg_on_lane_origin": round(base_kg, 1),
            "planned_broad_but_narrow": misread_case(changed, narrow, broad, config["reveal_weeks"], **options),
            "planned_narrow_but_broad": misread_case(changed, broad, narrow, config["reveal_weeks"], **options)}


def row(case: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"seed": case["seed"], "capacity_ratio": case["capacity_ratio"]}
    for direction in ("planned_broad_but_narrow", "planned_narrow_but_broad"):
        record = case[direction]
        if record["status"] != "ok":
            out[direction] = {"status": record["status"]}
            continue
        item: dict[str, Any] = {
            "lane_weeks_differing": len(record["plans_differ"]["lane_weeks_differing"]),
            "shipment_variables_differing": record["plans_differ"]["shipment_variables_differing"],
            "optimum_difference_usd": record["optimum_difference_usd"],
            "never_replanned": (record["no_replanning"]["regret_usd"] if record["no_replanning"]["feasible"]
                                else "infeasible")}
        for commitment in record["commitments"]:
            week = commitment["reveal_week"]
            item[f"reveal_{week}"] = commitment.get("regret_usd", commitment["status"])
            if "outcome" in commitment:
                item[f"reveal_{week}_shortfall_units"] = commitment["outcome"]["terminal_shortfall_units"]
                item[f"reveal_{week}_backlog_unit_weeks"] = commitment["outcome"]["backlog_unit_weeks"]
            if "favourable_tie_break" in commitment:
                item[f"reveal_{week}_tie_break"] = commitment["favourable_tie_break"]["regret_usd"]
        out[direction] = item
    return out


def per_seed(rows: list[dict[str, Any]], tolerance: float) -> list[dict[str, Any]]:
    """For each seed: the largest road-space multiple at which a misreading has a consequence, and how large."""
    def consequence(value: Any) -> bool:
        return value == "infeasible" or (isinstance(value, (int, float)) and value > tolerance)

    out = []
    for seed in sorted({r["seed"] for r in rows}):
        mine = [r for r in rows if r["seed"] == seed]
        summary: dict[str, Any] = {"seed": seed}
        original = next(r for r in mine if r["capacity_ratio"] == max(x["capacity_ratio"] for x in mine))
        summary["original_network_same_lane_week_loads"] = all(
            original[d].get("lane_weeks_differing") == 0
            for d in ("planned_broad_but_narrow", "planned_narrow_but_broad"))
        for direction in ("planned_broad_but_narrow", "planned_narrow_but_broad"):
            for key in ("reveal_7", "reveal_10", "never_replanned"):
                hit = [r["capacity_ratio"] for r in mine if consequence(r[direction].get(key))]
                values = [r[direction][key] for r in mine if isinstance(r[direction].get(key), (int, float))]
                summary[f"{direction}.{key}"] = {
                    "largest_ratio_with_consequence": max(hit) if hit else None,
                    "largest_regret_usd": max(values) if values else None,
                    "infeasible_at": [r["capacity_ratio"] for r in mine if r[direction].get(key) == "infeasible"]}
        out.append(summary)
    return out


def run(workers: int = 1) -> list[dict[str, Any]]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    jobs = [(seed, ratio) for seed in config["seeds"] for ratio in config["varied"]["capacity_ratios"]]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(one_case, jobs))
    return [one_case(job) for job in jobs]


def summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    rows = [row(case) for case in cases]
    return {"config_sha256": sha256(CONFIG), "per_seed": per_seed(rows, config["tolerance_usd"]), "rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="recompute and compare with the saved summary")
    parser.add_argument("--workers", type=int, default=1, help="cases solved side by side (same results)")
    args = parser.parse_args(argv)
    cases = run(args.workers)
    result = summary(cases)
    if args.check:
        saved = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
        same = json.dumps(saved, sort_keys=True) == json.dumps(result, sort_keys=True)
        print("saved summary reproduces" if same else "saved summary differs from this run")
        return 0 if same else 1
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "cases.jsonl").write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases),
                                         encoding="utf-8", newline="\n")
    (RESULTS / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    files = sorted(p for p in RESULTS.iterdir() if p.name != "manifest.json")
    manifest = {"code_version": code_version(), "command": "python scripts/run_scope_seeds.py --workers 6",
                "sha256": {p.name: sha256(p) for p in files}}
    (RESULTS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    for item in result["per_seed"]:
        print(json.dumps(item), flush=True)
    print(f"wrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
