"""Offline commands for the scenario-tree development pilots (v1: pilot, verify; v2: tune2, pilot2, verify2).

`pilot` runs MILPs within the configured budget and refuses a non-empty output directory.
`verify` runs no solver.
"""
import argparse
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['pilot', 'verify', 'tune2', 'pilot2', 'verify2', 'check2'])
    parser.add_argument('--output', default=None)
    args = parser.parse_args()
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
