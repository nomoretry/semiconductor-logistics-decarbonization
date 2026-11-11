"""Run the scope-confirmation study: what knowing a notice's scope before week 1 is worth.

    python scripts/run_scope_value.py            # writes benchmark_results/scope_value_v1
    python scripts/run_scope_value.py --check    # recompute and compare with the saved results

No model is called. Everything is solved locally with HiGHS.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network_planning.data import build_network  # noqa: E402
from network_planning.misread import misread_case, scope_value, with_lane_capacity  # noqa: E402
from scripts.run_scope_misread import code_version, scenario, sha256  # noqa: E402

CONFIG = ROOT / "benchmarks" / "scope_value_v1" / "config.json"
RESULTS = ROOT / "benchmark_results" / "scope_value_v1"


def summary_rows(case: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    head = {"capacity_ratio": case["capacity_ratio"], "capacity_kg": case["capacity_kg"]}
    for value in case["value"]:
        if value["status"] != "ok":
            rows.append({**head, "reveal_week": value["reveal_week"], "status": value["status"]})
            continue
        for prior in value["priors"]:
            rows.append({**head, "reveal_week": value["reveal_week"], "probability_broad": prior["probability_broad"],
                         "regret_assumed_narrow_but_broad_usd": value["assumed_narrow_but_broad"]["regret_usd"],
                         "regret_assumed_broad_but_narrow_usd": value["assumed_broad_but_narrow"]["regret_usd"],
                         "service_assumed_narrow_but_broad":
                             value["assumed_narrow_but_broad"]["outcome"]["service_level"],
                         "value_of_confirming_usd": prior.get("value_of_confirming_usd", prior["hedge_status"]),
                         "value_over_assuming_narrow_usd": prior["value_over_assuming_narrow_usd"],
                         "value_over_assuming_broad_usd": prior["value_over_assuming_broad_usd"]})
    return rows


def under_row(case: dict[str, Any]) -> dict[str, Any]:
    record = case["under_reading"]
    row: dict[str, Any] = {"capacity_ratio": case["capacity_ratio"], "status": record["status"]}
    if record["status"] != "ok":
        return row
    row.update(plans_differ=record["plans_differ"]["shipment_variables_differing"],
               no_replanning_feasible=record["no_replanning"]["feasible"],
               no_replanning_violated=record["no_replanning"]["violated"][:3],
               no_replanning_regret_usd=record["no_replanning"]["regret_usd"])
    for item in record["commitments"]:
        week = item["reveal_week"]
        row[f"reveal_{week}"] = item.get("regret_usd", item["status"])
        if "outcome" in item:
            row[f"reveal_{week}_service"] = item["outcome"]["service_level"]
        if "violated" in item:
            row[f"reveal_{week}_violated"] = item["violated"][:3]
    return row


def run() -> list[dict[str, Any]]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    spec, varied, solver = config["network"], config["varied"], config["solver"]
    net = build_network(spec["name"], spec["n_skus"], spec["weeks"], spec["seed"])
    narrow = scenario("narrow_scope", config["narrow_lanes"], config["disruption"])
    broad = scenario("broad_scope", config["broad_lanes"], config["disruption"])
    lane = varied["lane"]
    base_kg = net.lanes[lane].capacity_kg / varied["capacity_ratio_original"]
    cases = []
    for ratio in varied["capacity_ratios"]:
        capacity = net.lanes[lane].capacity_kg if ratio == varied["capacity_ratio_original"] else round(
            ratio * base_kg, 1)
        changed = with_lane_capacity(net, lane, capacity)
        under = misread_case(changed, broad, narrow, config["under_reading"]["reveal_weeks"],
                             mip_gap=solver["mip_gap"], time_limit=solver["time_limit"],
                             tie_break_weight=config["tie_break_weight"], tolerance_usd=config["tolerance_usd"])
        value = [scope_value(changed, narrow, broad, config["probabilities_broad"], reveal,
                             mip_gap=solver["mip_gap"], time_limit=solver["time_limit"])
                 for reveal in config["reveal_weeks"]]
        cases.append({"capacity_ratio": ratio, "lane": lane, "capacity_kg": capacity, "under_reading": under,
                      "value": value})
        print(json.dumps(under_row(cases[-1])), flush=True)
        for row in summary_rows(cases[-1]):
            if row.get("probability_broad") in (0.5, None):
                print(json.dumps(row), flush=True)
    return cases


def summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {"config_sha256": sha256(CONFIG), "under_reading": [under_row(case) for case in cases],
            "value": [row for case in cases for row in summary_rows(case)]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="recompute and compare with the saved summary")
    args = parser.parse_args(argv)
    cases = run()
    if args.check:
        saved = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
        same = json.dumps(saved, sort_keys=True) == json.dumps(summary(cases), sort_keys=True)
        print("saved summary reproduces" if same else "saved summary differs from this run")
        return 0 if same else 1
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "cases.jsonl").write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases),
                                         encoding="utf-8", newline="\n")
    (RESULTS / "summary.json").write_text(json.dumps(summary(cases), indent=2) + "\n", encoding="utf-8",
                                          newline="\n")
    files = sorted(p for p in RESULTS.iterdir() if p.name != "manifest.json")
    manifest = {"code_version": code_version(), "command": "python scripts/run_scope_value.py",
                "sha256": {p.name: sha256(p) for p in files}}
    (RESULTS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
