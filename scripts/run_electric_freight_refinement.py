"""Post-hoc refinement of the electric freight study (thresholds and the day-slot-only case).

    python scripts/run_electric_freight_refinement.py --workers 6
    python scripts/run_electric_freight_refinement.py --workers 6 --check

Uses the same solver settings and order export as scripts/run_electric_freight.py. Exploratory.
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

from scripts.run_electric_freight import RESULTS, comparable, row, run_one, sha256  # noqa: E402

REFINEMENT = ROOT / "benchmarks" / "electric_freight_v1" / "refinement.json"


def jobs() -> list[dict[str, Any]]:
    spec = json.loads(REFINEMENT.read_text(encoding="utf-8"))
    out = []
    for group, item in spec["groups"].items():
        for value in item["values"]:
            for plan in item["plans"]:
                overrides = {**spec["base_overrides"], **item.get("extra_overrides", {}), item["key"]: value}
                out.append({"id": f"{group}/{item['key']}={value}/{plan}", "group": group, "setting": str(value),
                            "plan": plan, "overrides": overrides, "congested_weeks": []})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run_one, jobs()))
    summary = {"refinement_sha256": sha256(REFINEMENT), "rows": [row(r) for r in results]}
    path = RESULTS / "refinement_summary.json"
    if args.check:
        saved = json.loads(path.read_text(encoding="utf-8"))
        same = comparable(saved["rows"]) == comparable(summary["rows"])
        print("saved refinement reproduces" if same else "saved refinement differs from this run")
        return 0 if same else 1
    (RESULTS / "refinement_runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in results), encoding="utf-8",
                                                   newline="\n")
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
