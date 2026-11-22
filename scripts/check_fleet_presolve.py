"""Replay the four pre-registered HiGHS comparisons from saved study results."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import types
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from electric_freight.fleet import load_v2, solve  # noqa: E402
from electric_freight.stochastic import scenario_set  # noqa: E402
from scripts.run_fleet import RESULTS, code_version, compact, protocol, run_horizon, saved, scenario_for  # noqa: E402


def eligible(row: dict[str, Any]) -> bool:
    gap = row.get("stats", row).get("mip_gap")
    return row.get("objective_usd") is not None and (row["status"] == "optimal" or (gap is not None and gap <= 0.001))


def deterministic_replay(spec: dict[str, Any], rows: dict[str, Any], target: str) -> dict[str, Any]:
    # The archived B solves preceded the change to how step-1 cargo quantities are fixed.
    # Rebuild their inputs with exactly their recorded source revision.
    row = rows[target]
    revision = row["code_version"]
    source = subprocess.run(["git", "show", f"{revision}:electric_freight/fleet.py"], cwd=ROOT, capture_output=True,
                            check=True, encoding="utf-8").stdout
    archived = types.ModuleType("electric_freight.archived_fleet")
    archived.__file__ = str(ROOT / "electric_freight" / "fleet.py")
    sys.modules[archived.__name__] = archived
    exec(compile(source, f"{revision}:electric_freight/fleet.py", "exec"), archived.__dict__)
    cfg = load_v2()
    sc = scenario_for(cfg, spec["scenarios"][row["scenario"]], row["instance"])
    options = spec["solver"]
    parent = target.rsplit("/", 1)[0]
    b = archived.sequential(cfg, [sc], **options)

    def matches(plan: dict[str, Any], label: str) -> bool:
        actual = compact(cfg, sc, plan, "joint")
        previous = rows[f"{parent}/{label}"]
        return (all(actual.get(k) == previous.get(k) for k in ("first_stage", "week_types", "trips", "accounting"))
                and abs(actual["objective_usd"] - previous["objective_usd"]) <= 1e-5)

    if not matches(b, "B"):
        return {"comparison_status": "archived B starting plan could not be reproduced"}
    full_options = {**options, "highs_options": {"presolve": "off"}}
    if row["plan"] == "B*":
        cap = b["step_1"]["objective_usd"] * (1 + 1e-7) + 1e-3
        result = solve(cfg, [sc], transport_cap=cap, start=b["values"], **full_options)
    else:
        best = archived.sequential(cfg, [sc], best_tie_break=True, step1=b["step_1_result"], start=b["values"],
                                   **options)
        if not matches(best, "B*"):
            return {"comparison_status": "archived B* starting plan could not be reproduced"}
        start = min((b, best), key=lambda r: r["objective_usd"])
        if start["mode"] != row["started_from"]:
            return {"comparison_status": "archived starting plan selection differs"}
        result = solve(cfg, [sc], start=start["values"], **full_options)
    return {**compact(cfg, sc, result, "joint"), "input": f"reconstructed from {revision}; checked against saved "
            "decisions and accounting; the historical full vector was not archived"}


def run() -> None:
    spec, rows = protocol(), saved()
    path = RESULTS / "presolve_check.json"
    records = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    for label in spec["presolve_check"]["targets"]:
        if label in records:
            continue
        target = label
        if label == "horizon":
            ordered = [f"horizon/{t}/{v}" for t in spec["horizon_check"] for v in ("fixed", "free")]
            target = next((t for t in ordered if t in rows and eligible(rows[t])), "")
        if label.startswith("stochastic/"):
            data = json.loads((RESULTS / "stochastic.json").read_text(encoding="utf-8"))
            name = label.split("/")[2]
            old = data["table"][data["RP"]["candidate"]][name] if "RP" in data else {}
        else:
            old = rows.get(target, {})
        result: dict[str, Any] = {"target": target, "code_version": code_version()}
        started = time.perf_counter()
        if not eligible(old):
            result.update(comparison_status="no eligible saved result", original=old)
        else:
            if label == "horizon":
                source = rows[old["target"]]
                after = run_horizon((old["target"], source, source["instance"], old["equipment"] == "free"),
                                    highs_options={"presolve": "off"})
                if after["start_sha256"] != old["start_sha256"]:
                    after["comparison_status"] = "starting vectors differ"
            elif label.startswith("stochastic/"):
                cfg = load_v2()
                item = spec["stochastic"]
                sc = next(s for s in scenario_set(cfg, item["scenarios"], item["instance"]) if s.name == name)
                alone = replace(sc, probability=1.0)
                plan = solve(cfg, [alone], **data["presolve_input"], **spec["solver"],
                             highs_options={"presolve": "off"})
                after = compact(cfg, alone, plan, "joint")
            else:
                after = deterministic_replay(spec, rows, target)
            result.update(original={k: old.get(k) for k in ("status", "objective_usd")},
                          original_bound=old.get("stats", old).get("dual_bound"), presolve_off=after,
                          comparison_status=after.get("comparison_status", "compared"))
        result["seconds"] = round(time.perf_counter() - started, 2)
        records[label] = result
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8", newline="\n")
        temp.replace(path)
        print(target or label, result["comparison_status"], flush=True)


if __name__ == "__main__":
    run()
