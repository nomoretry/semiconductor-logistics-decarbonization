"""Offline command for the exact finite-support mechanism check."""
import argparse
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run', 'verify'])
    parser.add_argument('--output', default='benchmark_results/rolling_recourse_mechanism')
    args = parser.parse_args()
    from .experiment import write, verify
    print(json.dumps((write if args.command == 'run' else verify)(args.output), indent=2))


if __name__ == '__main__':
    main()
