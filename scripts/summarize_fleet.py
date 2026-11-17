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
                out.append(f"{typ.split('|')[0]} week: {trip['truck']} {day} {trip['depart'] % 24:02d}:00, "
                           f"dwell {trip['dwell']} h")
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
            kit = equipment(row) if row.get("first_stage") else "—"
            out.append(f"| {instance} | {scenario} | {plan} | {money(cost(row))} | {solver(row)} | {kit} | "
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


def closed_form(all_rows: list[dict[str, Any]]) -> list[str]:
    """What follows from the saved plans without solving again: none of these values changes a decision."""
    sys.path.insert(0, str(ROOT))
    from electric_freight.data import capital_share
    from electric_freight.fleet import load_v2, trucks_of
    config = load_v2()
    weeks = int(config["horizon"]["weeks"])
    retail = float(config["diesel"]["price_usd_per_litre"])
    premium = float(config["vehicle_capital"]["electric_premium_usd_per_truck"]) * capital_share(config, weeks)
    germany = 0.363  # kg CO2e per kWh, Germany 2024 (UBA); a counterfactual factor, not a German case
    out = ["", "## Closed form from the saved plans A and C (no solving)", "",
           f"Diesel prices: {retail} USD/L retail (RM 3.35), 0.478 USD/L fleet card (RM 2.15), 1.00 USD/L. "
           f"Electric truck premium: {config['vehicle_capital']['electric_premium_usd_per_truck']:,} USD per truck, "
           f"{premium:,.2f} USD per truck over {weeks} weeks (capital recovery), never added to the plans' cost. "
           "Emission factors applied to the plan's own kWh: the base case, the depot at Germany's 2024 factor "
           f"({germany}), and zero-carbon electricity.", "",
           "| instance | scenario | C solver | C − A at 0.478 / 0.744 / 1.00 USD/L | diesel break-even (USD/L) | "
           "C − A with premium | CO2e A / C (t) | C with depot at 0.363 / zero-carbon (t) | "
           "carbon break-even, decisions fixed (USD/t) |", "|---|---|---|---|---|---|---|---|---|"]
    table: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in all_rows:
        if row.get("group") == "deterministic" and row.get("accounting"):
            table.setdefault((row["instance"], row["scenario"]), {})[row["plan"]] = row
    for (instance, scenario), plans in sorted(table.items()):
        if "A" not in plans or "C" not in plans:
            continue
        a, c = plans["A"]["accounting"], plans["C"]["accounting"]
        litres = a["cost_usd"].get("diesel", 0.0) / retail
        gaps = [c["total_cost_usd"] - (a["total_cost_usd"] + litres * (price - retail))
                for price in (0.478, retail, 1.0)]
        breakeven = retail + gaps[1] / litres if litres else float("nan")
        own, _ = trucks_of(config, instance)
        leased = [k for k, v in plans["C"]["first_stage"].get("lease", {}).items() if v]
        with_premium = gaps[1] + premium * (len(own) + len(leased))
        air = c["emissions_kg"].get("air_freight", 0.0)
        kwh = c["energy_kwh"]
        factor = {j: germany if site["side"] == "MY" else site["grid_kg_co2e_per_kwh"]
                  for j, site in config["sites"].items()}
        depot_de = sum(v * factor[j] for j, v in kwh.items()) + air
        zero = air
        saved_kg = a["total_emissions_kg"] - c["total_emissions_kg"]
        carbon = gaps[1] / saved_kg * 1000 if saved_kg > 0 else float("nan")
        out.append(f"| {instance} | {scenario} | {solver(plans['C'])} | {' / '.join(f'{g:,.0f}' for g in gaps)} | "
                   f"{breakeven:.3f} | "
                   f"{with_premium:,.0f} | {a['total_emissions_kg'] / 1000:.1f} / "
                   f"{c['total_emissions_kg'] / 1000:.1f} | "
                   f"{depot_de / 1000:.1f} / {zero / 1000:.1f} | {carbon:,.0f} |")
    return out


def tie_break(all_rows: list[dict[str, Any]]) -> list[str]:
    """Plan B under solver seeds 0 (the deterministic group) to 5, against B* and C of the same setting."""
    found = [r for r in all_rows if r.get("group") == "tie_break"]
    if not found:
        return []
    reference = {(r["instance"], r["scenario"], r["plan"]): r for r in all_rows if r.get("group") == "deterministic"}
    out = ["", "## Plan B under other solver seeds", "",
           "Step 1 keeps whichever of its equally cheap schedules the search meets first; seed 0 is the "
           "deterministic group's B.", "",
           "| instance | scenario | seed | step-1 cost | B cost | B − B* | equipment | depot peak kW |",
           "|---|---|---|---|---|---|---|---|"]
    settings = sorted({(r["instance"], r["scenario"]) for r in found})
    for instance, scenario in settings:
        seeded = sorted((r for r in found if (r["instance"], r["scenario"]) == (instance, scenario)),
                        key=lambda r: r["seed"])
        mine = [reference.get((instance, scenario, "B")), *seeded]
        best = reference.get((instance, scenario, "B*"))
        best_cost = cost(best) if best else None
        for row in mine:
            if row is None:
                continue
            seed = row.get("seed", 0)
            step1 = (row.get("step_1") or {}).get("objective_usd")
            value = cost(row)
            diff = None if value is None or best_cost is None else value - best_cost
            peak = (row.get("peak_kw") or {}).get("MY_DEPOT")
            out.append(f"| {instance} | {scenario} | {seed} | {money(step1)} | {money(value)} | {money(diff)} | "
                       f"{equipment(row) if row.get('first_stage') else solver(row)} | "
                       f"{'—' if peak is None else f'{peak:.1f}'} |")
    return out


def search(all_rows: list[dict[str, Any]]) -> list[str]:
    """The fix-and-optimize search from saved plans B* and C (same parts, rounds and limits for both)."""
    found = [r for r in all_rows if r.get("group") == "search"]
    if not found:
        return []
    out = ["", "## Fix-and-optimize search from the saved plans", "",
           "Each step fixes the trips outside one truck or one 48-hour window of departures and solves the rest "
           "again from the current plan; B* keeps its step-1 transport cap. The bound is the full solve's.", "",
           "| instance | scenario | plan | full solve (USD) | after search (USD) | change | full-solve bound | "
           "steps that gained | equipment | extra trips | depot peak kW | seconds |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    by_setting: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in sorted(found, key=lambda r: (r["instance"], r["scenario"], PLANS.index(r["plan"]))):
        by_setting.setdefault((row["instance"], row["scenario"]), {})[row["plan"]] = row
        full = row["full_solve"]["objective_usd"]
        after = cost(row)
        change = None if after is None or full is None else after - full
        steps = [h for h in (row.get("search") or {}).get("history", []) if (h.get("gain_usd") or 0) > 1e-6]
        gained = "; ".join(f"r{h['round']} {h['free']} −{h['gain_usd']:,.0f}" for h in steps) or "none"
        peak = (row.get("peak_kw") or {}).get("MY_DEPOT")
        out.append(f"| {row['instance']} | {row['scenario']} | {row['plan']} | {money(full)} | {money(after)} | "
                   f"{money(change)} | {money(row['full_solve']['dual_bound'])} | {gained} | "
                   f"{equipment(row) if row.get('first_stage') else solver(row)} | "
                   f"{extra_trips(row) if 'week_types' in row else '—'} | "
                   f"{'—' if peak is None else f'{peak:.1f}'} | {(row.get('search') or {}).get('seconds')} |")
    out += ["", "| instance | scenario | B* after search − C after search |", "|---|---|---|"]
    for (instance, scenario), plans in sorted(by_setting.items()):
        if "B*" in plans and "C" in plans and cost(plans["B*"]) is not None and cost(plans["C"]) is not None:
            out.append(f"| {instance} | {scenario} | {money(cost(plans['B*']) - cost(plans['C']))} |")  # type: ignore[operator]
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
    lines += (deterministic(all_rows) + closed_form(all_rows) + tie_break(all_rows) + search(all_rows)
              + boundaries(all_rows) + horizon(all_rows) + stochastic())
    text = "\n".join(lines) + "\n"
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "summary.md").write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
