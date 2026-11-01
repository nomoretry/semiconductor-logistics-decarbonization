"""Offline command for the scenario-tree development pilot.

`pilot` runs MILPs within the configured budget and refuses a non-empty output directory.
`verify` runs no solver.
"""
import argparse
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['pilot', 'verify'])
    parser.add_argument('--output', default='benchmark_results/rolling_tree_pilot')
    args = parser.parse_args()
    from .experiment import pilot, verify
    print(json.dumps((pilot if args.command == 'pilot' else verify)(args.output), indent=2))


if __name__ == '__main__':
    main()
