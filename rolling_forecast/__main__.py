"""Compare history-only forecasts and replay paired rolling decisions offline."""
import argparse
import json
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['run','verify','smoke-check'])
    parser.add_argument('--output'); parser.add_argument('--smoke',action='store_true')
    args = parser.parse_args()
    from .experiment import DEFAULT, run, verify
    if args.action=='smoke-check':
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp,True); result = verify(tmp)
    elif args.action=='run':
        result = run(args.output or 'artifacts/rolling_forecast',args.smoke)
    else:
        result = verify(args.output or DEFAULT)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
