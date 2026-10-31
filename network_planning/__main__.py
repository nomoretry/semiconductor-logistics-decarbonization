"""Command line for the network planning engine.

python -m network_planning describe --network asml
python -m network_planning solve --network asml --scenario red_sea --carbon-cap-pct 75
python -m network_planning frontier --network marvell
python -m network_planning stochastic --network asml --reveal-week 3
python -m network_planning scale --quick
python -m network_planning report --output benchmark_results/network_planning
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import carbon_frontier, explain_plan, plan_row, scale_benchmark, stochastic_value
from .data import NETWORKS, build_network
from .model import solve
from .report import QUICK_SCALE, run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="network_planning", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def network_args(p):
        p.add_argument("--network", choices=NETWORKS, default="asml")
        p.add_argument("--skus", type=int, default=None)
        p.add_argument("--weeks", type=int, default=None)
        p.add_argument("--seed", type=int, default=None)

    network_args(sub.add_parser("describe", help="network, lanes and scenarios"))
    p = sub.add_parser("solve", help="solve one deterministic plan")
    network_args(p)
    p.add_argument("--scenario", default="normal")
    p.add_argument("--carbon-cap-pct", type=float, help="cap as %% of the uncapped plan's emissions")
    p.add_argument("--carbon-price", type=float, default=0.0, help="USD per tonne CO2e")
    p.add_argument("--service-level", type=float)
    p.add_argument("--integer", action="store_true", help="integer shipment units")
    p.add_argument("--explain", action="store_true")
    p = sub.add_parser("frontier", help="cost-emissions frontier and marginal abatement cost")
    network_args(p)
    p.add_argument("--scenario", default="normal")
    p = sub.add_parser("stochastic", help="two-stage plan, VSS and EVPI")
    network_args(p)
    p.add_argument("--reveal-week", type=int, default=3)
    p = sub.add_parser("scale", help="model size and solve time")
    p.add_argument("--quick", action="store_true")
    p = sub.add_parser("report", help="run every analysis and write the evidence bundle")
    p.add_argument("--output", type=Path, default=Path("benchmark_results/network_planning"))
    p.add_argument("--quick", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "report":
        run(args.output, quick=args.quick)
        print(f"wrote {args.output / 'report.md'}")
        return 0
    if args.command == "scale":
        _print(scale_benchmark("asml", QUICK_SCALE) if args.quick else scale_benchmark("asml"))
        return 0
    net = build_network(args.network, args.skus, args.weeks, args.seed)
    if args.command == "describe":
        _print(net.describe())
    elif args.command == "solve":
        sc = net.scenario(args.scenario, 1.0)
        cap = None
        if args.carbon_cap_pct is not None:
            reference = solve(net, [sc], service_level=args.service_level)
            cap = args.carbon_cap_pct / 100 * reference.kpis["emissions_t"] * 1000
        plan = solve(net, [sc], carbon_cap_kg=cap, carbon_price=args.carbon_price, service_level=args.service_level,
                     integer_shipments=args.integer, duals=args.explain)
        out = {"plan": plan_row(plan, scenario=args.scenario), "issues": plan.issues}
        if plan.feasible:
            out["cost_breakdown_usd"] = {k: round(v, 2) for k, v in plan.kpis["cost_breakdown_usd"].items()}
            if args.explain:
                out["explanation"] = explain_plan(net, plan)
        _print(out)
    elif args.command == "frontier":
        _print(carbon_frontier(net, args.scenario))
    elif args.command == "stochastic":
        result = stochastic_value(net, reveal_week=args.reveal_week)
        result.pop("plans", None)
        _print(result)
    return 0


def _print(value) -> None:
    sys.stdout.write(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
