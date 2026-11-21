"""Command-line entry points for the frozen decision graph experiment."""
from __future__ import annotations

import argparse
from pathlib import Path

from .dataset import build, graphs
from .graph import compact
from .replay import recheck, score, verify
from .scoring import answer_map


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    kind = b.add_mutually_exclusive_group(required=True)
    kind.add_argument("--pilot", type=Path, metavar="DIR")
    kind.add_argument("--pilot-evidence", type=Path, metavar="DIR")
    b.add_argument("--out", type=Path)
    for name in ("verify", "recheck", "score", "fixtures"):
        command = sub.add_parser(name)
        command.add_argument("--data", type=Path, required=True)
        if name == "recheck":
            command.add_argument("--sample", type=float, default=0.1)
        if name == "score":
            command.add_argument("--answers", type=Path, required=True)
            command.add_argument("--details", type=Path)
        if name == "fixtures":
            command.add_argument("--out", type=Path, required=True)
            command.add_argument("--perturb", action="store_true")
    args = parser.parse_args()
    if args.command == "build":
        if (args.pilot is None) != (args.out is not None):
            parser.error("use --pilot DIR or --pilot-evidence DIR --out DATA")
        result = build(args.pilot or args.out, pilot=args.pilot is not None,
                       pilot_evidence=args.pilot_evidence)
    elif args.command == "verify":
        result = verify(args.data)
    elif args.command == "recheck":
        result = recheck(args.data, args.sample)
    elif args.command == "score":
        result = score(args.data, args.answers, args.details)
    else:
        with args.out.open("x", encoding="utf-8", newline="\n") as file:
            for g in graphs(args.data):
                file.write(compact({"id": g["id"], "answers": answer_map(g, args.perturb)}) + "\n")
        return
    print(compact(result), flush=True)
    if args.command == "build" and result["status"] != "complete":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

