"""Tables of the model-v2 study from benchmark_results/electric_freight_v2/ (no solving).

    python scripts/summarize_fleet.py            # writes benchmark_results/electric_freight_v2/summary.md

Every number comes from runs.jsonl, stochastic.json and stochastic_de.json as saved; costs are the independent
accounting's totals.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmark_results" / "electric_freight_v2"
PLANS = ("A", "B", "B*", "C")


def rows() -> list[dict[str, Any]]:
    path = RESULTS / "runs.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def money(value: Any) -> str:
    return "—" if value is None else f"{value:,.2f}"


def solver(row: dict[str, Any]) -> str:
    gap = row["stats"].get("mip_gap")
    status = str(row["status"])
    if status not in ("optimal", "feasible"):
        return status
    return status if gap is None else f"{status}, gap {100 * gap:.2f}%"


def equipment(row: dict[str, Any]) -> str:
    plant = (row.get("first_stage") or {}).get("plant")
    if not plant:
        lease = [k for k, v in (row.get("first_stage") or {}).get("lease", {}).items() if v]
        return "diesel" + (f"; lease {', '.join(lease)}" if lease else "")
    parts = [f"{k.replace('|', ' ')}×{v}" for k, v in plant["n"].items() if v]
    parts += [f"upgrade {k.split('|')[0]} {k.split('|')[1]}" for k, v in plant["up"].items() if v]
    parts += [f"{k.split('|')[0]}→{k.split('|')[1]}" for k, v in plant["conn"].items() if v]
    parts += [f"expand {k}" for k, v in plant["exp"].items() if v]
    lease = [k for k, v in row["first_stage"].get("lease", {}).items() if v]
    if lease:
        parts.append("lease " + ", ".join(lease))
    return "; ".join(parts)


def extra_trips(row: dict[str, Any]) -> str:
    weeks = [w for w, t in (row.get("week_types") or {}).items() if not t.endswith("|0")]
    if not weeks:
        return "none"
    out = []
    for typ in sorted({row["week_types"][w] for w in weeks}):
        for trip in row["trips"][typ]:
            if trip["kind"].startswith("extra"):
                day = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[trip["depart"] // 24]
                out.append(f"{typ}: {trip['truck']} {day} {trip['depart'] % 24:02d}:00, dwell {trip['dwell']} h")
    return f"weeks {', '.join(weeks)} ({'; '.join(out)})"


def cost(row: dict[str, Any], key: str | None = None) -> float | None:
    account = row.get("accounting")
    if not account:
        return None
    return float(account["total_cost_usd"] if key is None else account["cost_usd"].get(key, 0.0))


def deterministic(all_rows: list[dict[str, Any]]) -> list[str]:
    out = ["## Plans A, B, B* and C", "",
           "| instance | scenario | plan | cost (USD) | solver | equipment | extra trips | depot peak kW | "
           "demand charge | CO2e kg |", "|---|---|---|---|---|---|---|---|---|---|"]
    table: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in all_rows:
        if row.get("group") == "deterministic":
            table.setdefault((row["instance"], row["scenario"]), {})[row["plan"]] = row
    for (instance, scenario), plans in sorted(table.items()):
        for plan in PLANS:
            if plan not in plans:
                continue
            row = plans[plan]
            peak = (row.get("peak_kw") or {}).get("MY_DEPOT")
            account = row.get("accounting") or {}
            out.append(f"| {instance} | {scenario} | {plan} | {money(cost(row))} | {solver(row)} | {equipment(row)} | "
                       f"{extra_trips(row) if 'week_types' in row else '—'} | "
                       f"{'—' if peak is None else f'{peak:.1f}'} | {money(cost(row, 'demand_charge'))} | "
                       f"{money(account.get('total_emissions_kg'))} |")
    out += ["", "| instance | scenario | B − C | B* − C | C − A (electric minus diesel) | CO2e C vs A |",
            "|---|---|---|---|---|---|"]
    for (instance, scenario), plans in sorted(table.items()):
        values = {p: cost(plans[p]) if p in plans else None for p in PLANS}
        diffs = []
        for a, b in (("B", "C"), ("B*", "C"), ("C", "A")):
            va, vb = values[a], values[b]
            diffs.append("—" if va is None or vb is None else money(va - vb))
        emissions = "—"
        if "A" in plans and "C" in plans and plans["A"].get("accounting") and plans["C"].get("accounting"):
            a, c = plans["A"]["accounting"]["total_emissions_kg"], plans["C"]["accounting"]["total_emissions_kg"]
            emissions = f"{100 * (c - a) / a:+.1f}%"
        out.append(f"| {instance} | {scenario} | {' | '.join(diffs)} | {emissions} |")
    return out


def boundaries(all_rows: list[dict[str, Any]]) -> list[str]:
    out = ["", "## Boundary sweeps (base instance)", "",
           "| sweep | value | plan | cost (USD) | solver | equipment | extra trips |", "|---|---|---|---|---|---|---|"]
    found = sorted((r for r in all_rows if r.get("group") == "boundaries"),
                   key=lambda r: (r["sweep"], -float(r["value"]), PLANS.index(r["plan"])))
    for row in found:
        out.append(f"| {row['sweep']} | {row['value']} | {row['plan']} | {money(cost(row))} | {solver(row)} | "
                   f"{equipment(row)} | {extra_trips(row) if 'week_types' in row else '—'} |")
    return out


def horizon(all_rows: list[dict[str, Any]]) -> list[str]:
    out = ["", "## Representative weeks against one unbroken horizon", "",
           "| plan | equipment | representative (USD) | horizon (USD) | solver | restriction cost (USD) | start |",
           "|---|---|---|---|---|---|---|"]
    for row in (r for r in all_rows if r.get("group") == "horizon"):
        gap = row.get("mip_gap")
        interval = row.get("restriction_interval_usd")
        span = "—" if interval is None else f"{interval[0]:,.2f} to {interval[1]:,.2f}"
        out.append(f"| {row['target']} | {row['equipment']} | {money(row.get('representative_usd'))} | "
                   f"{money(row.get('objective_usd'))} | {row['status']}"
                   f"{'' if gap is None else f', gap {100 * gap:.2f}%'} | {span} | {row.get('start')} |")
    return out


def stochastic() -> list[str]:
    path = RESULTS / "stochastic.json"
    if not path.exists():
        return []
    result = json.loads(path.read_text(encoding="utf-8"))
    out = ["", "## Two-stage plan", "", "| quantity | value (USD) | interval (USD) |", "|---|---|---|"]
    for name in ("WS", "RP", "EEV", "VSS", "EVPI"):
        item = result.get(name) or {}
        value = item.get("value", item.get("expected_usd"))
        interval = item.get("interval")
        out.append(f"| {name} | {money(value)} | "
                   f"{'—' if not interval else f'{interval[0]:,.2f} to {interval[1]:,.2f}'} |")
    out += ["", "| candidate | from scenarios | expected (USD) | " +
            " | ".join(result["scenarios"]) + " |", "|---|---|---|" + "---|" * len(result["scenarios"])]
    for i, cand in enumerate(result["candidates"]):
        per = cand.get("per_scenario", {})
        cells = " | ".join(money(per.get(n)) if isinstance(per.get(n), (int, float)) else str(per.get(n))
                           for n in result["scenarios"])
        out.append(f"| {i} | {', '.join(cand['origin'])} | {money(cand.get('expected_usd'))} | {cells} |")
    de_path = RESULTS / "stochastic_de.json"
    if de_path.exists():
        de = json.loads(de_path.read_text(encoding="utf-8"))
        gap = de["stats"].get("mip_gap")
        out += ["", f"Deterministic equivalent: {de['status']}, {money(de.get('objective_usd'))} USD"
                    f"{'' if gap is None else f', gap {100 * gap:.2f}%'}, dual bound "
                    f"{money(de['stats'].get('dual_bound'))}, {de.get('seconds')} s."]
    return out


def main() -> int:
    all_rows = rows()
    lines = ["# Model v2 results", "", "Generated by `scripts/summarize_fleet.py` from the saved results; costs are "
             "the independent accounting's totals over 16 weeks.", ""]
    lines += deterministic(all_rows) + boundaries(all_rows) + horizon(all_rows) + stochastic()
    text = "\n".join(lines) + "\n"
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "summary.md").write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
