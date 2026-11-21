"""Offline commands for scenario-tree development pilots and M1 first-action stability.

The pilot and stability runners refuse a non-empty output directory. Verification runs no solver.
"""
import argparse
import json
import sys


def _stability_progress(event, detail):
    print(json.dumps(dict(event=event, **detail)), file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['pilot', 'verify', 'tune2', 'pilot2', 'verify2', 'check2',
                                            'stability3', 'verify3', 'consensus4', 'verify4', 'closing', 'verify5'])
    parser.add_argument('--output', default=None)
    parser.add_argument('--max-wall-seconds', type=int,
                        help='shared wall-time budget for consensus4 (default 5400) or closing (default 7200)')
    parser.add_argument('--gate1', action='store_true', help='verify the first timing-gate archives with verify4')
    args = parser.parse_args()
    if args.max_wall_seconds is not None and args.command not in ('consensus4', 'closing'):
        parser.error('--max-wall-seconds requires consensus4')
    if args.gate1 and args.command != 'verify4':
        parser.error('--gate1 requires verify4')
    if args.command in ('closing', 'verify5'):
        from . import closing, closing_replay
        output = args.output or closing.OUTPUT
        if args.command == 'verify5':
            print(json.dumps(closing_replay.verify(output), indent=2))
            return
        limit = 7200 if args.max_wall_seconds is None else args.max_wall_seconds
        execution = closing.run(output, max_wall_seconds=limit, progress=_stability_progress)
        print(json.dumps(execution, indent=2), flush=True)
        if execution['stop_reason'] is not None:
            raise SystemExit(1)
        return
    if args.command in ('consensus4', 'verify4'):
        from . import consensus
        output = args.output or consensus.OUTPUT
        if args.command == 'verify4':
            print(json.dumps(consensus.verify(output, gate1=args.gate1), indent=2))
            return
        limit = consensus.DEFAULT_MAX_WALL_SECONDS if args.max_wall_seconds is None else args.max_wall_seconds
        if limit not in consensus.WALL_BUDGETS:
            parser.error('--max-wall-seconds must be 5400 or 10800')
        execution = consensus.run(output, progress=_stability_progress, max_wall_seconds=limit)
        print(json.dumps(execution, indent=2))
        if execution['stop_reason'] is not None:
            raise SystemExit(1)
        return
    if args.command in ('stability3', 'verify3'):
        from . import stability
        output = args.output or stability.OUTPUT
        if args.command == 'verify3':
            print(json.dumps(stability.verify(output), indent=2))
            return
        summary = stability.run(output, progress=_stability_progress)
        print(json.dumps(summary, indent=2))
        if summary['stop_reason'] is not None:
            raise SystemExit(1)
        return
    if args.command in ('pilot', 'verify'):
        from .experiment import pilot, verify
        call, default = (pilot if args.command == 'pilot' else verify), 'benchmark_results/rolling_tree_pilot'
    else:
        from . import experiment_v2 as v2
        call, default = {'tune2': (v2.tune, v2.TUNING), 'pilot2': (v2.pilot, v2.PILOT),
                         'verify2': (v2.verify, v2.PILOT),
                         'check2': (v2.continuation_check, v2.CHECK)}[args.command]
    print(json.dumps(call(args.output or default), indent=2))


if __name__ == '__main__':
    main()
