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
    export = sub.add_parser("export-prompts")
    export.add_argument("--data", type=Path, required=True)
    export.add_argument("--split", choices=("train", "dev", "test"), required=True)
    export.add_argument("--mode", choices=("None", "Chain", "Graph"), required=True)
    export.add_argument("--source", choices=("gold", "own"), required=True)
    export.add_argument("--lang", choices=("zh", "en"), required=True)
    export.add_argument("--answers", type=Path)
    export.add_argument("--out", type=Path, required=True)
    ev = sub.add_parser("evaluate")
    ev.add_argument("--data", type=Path, required=True)
    ev.add_argument("--out", type=Path, required=True)
    ev.add_argument("--answers", type=Path)
    phase = ev.add_mutually_exclusive_group()
    phase.add_argument("--pilot", action="store_true")
    phase.add_argument("--pilot-evidence", type=Path)
    ve = sub.add_parser("verify-eval")
    ve.add_argument("--out", type=Path, required=True)
    from . import llm_eval
    from .llm.data import LlmError

    llm_eval.register(sub)
    args = parser.parse_args()
    if args.command in ("llm-run", "llm-batch", "llm-score", "llm-prompts"):
        try:
            llm_eval.dispatch(args)
        except LlmError as error:
            parser.error(str(error))
        return
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
    elif args.command == "export-prompts":
        from .evaluation import export_prompts, read_answers

        if args.source == "own" and args.answers is None:
            parser.error("--source own requires --answers")
        result = export_prompts(args.data, split=args.split, mode=args.mode, source=args.source,
                                lang=args.lang, out=args.out,
                                submissions=read_answers(args.answers) if args.answers else None)
    elif args.command == "evaluate":
        from .eval_run import evaluate

        pilot = args.pilot_evidence
        if not args.pilot and pilot is None:
            pilot = args.out.with_name(f"{args.out.name}.pilot")
            result = evaluate(args.data, pilot, pilot=True, answers=args.answers)
            print(compact(result), flush=True)
            if result["status"] != "complete":
                raise SystemExit(2)
        result = evaluate(args.data, args.out, pilot=args.pilot, pilot_evidence=pilot, answers=args.answers)
        print(compact(result), flush=True)
        if result["status"] != "complete":
            raise SystemExit(2)
        return
    elif args.command == "verify-eval":
        from .eval_run import verify_eval

        result = verify_eval(args.out)
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

