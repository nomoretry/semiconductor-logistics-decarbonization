"""Run and replay a history-only demand-distribution comparison."""
import argparse
import json
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['run', 'verify', 'smoke-check'])
    p.add_argument('--output'); p.add_argument('--smoke', action='store_true')
    args = p.parse_args()
    from .experiment import run, verify, DEFAULT
    if args.action == 'smoke-check':
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp, True); result = verify(tmp)
    elif args.action == 'run':
        result = run(args.output or 'artifacts/distribution-new', args.smoke)
    else:
        result = verify(args.output or DEFAULT)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
