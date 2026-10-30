"""Multi-seed development, explicit test freeze and final evidence replay."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("develop","verify-development","freeze","evaluate","verify-final","smoke-check"))
    p.add_argument("--development",type=Path,default=Path("benchmark_results/query_study_development"))
    p.add_argument("--frozen",type=Path,default=Path("benchmarks/query_final_v1"))
    p.add_argument("--output",type=Path)
    p.add_argument("--freeze-commit")
    p.add_argument("--smoke",action="store_true")
    args=p.parse_args()
    from . import development,final
    if args.action=="develop":
        result=development.run(args.output or Path("artifacts/query_study"),args.smoke)
    elif args.action=="verify-development":result=development.verify(args.development)
    elif args.action=="freeze":result=final.freeze(args.development,args.output or args.frozen)
    elif args.action=="evaluate":
        if args.freeze_commit is None:p.error("--freeze-commit is required")
        result=final.run(args.development,args.frozen,args.output or Path("artifacts/query_final"),args.freeze_commit)
    elif args.action=="verify-final":
        result=final.verify(args.development,args.frozen,args.output or Path("benchmark_results/query_final_v1"))
    else:
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d,f,o=(root/n for n in ("development","freeze","evaluation"))
            development.run(d,True);development.verify(d,False);final.freeze(d,f)
            final.run(d,f,o,"0"*40);result=final.verify(d,f,o)
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":main()
