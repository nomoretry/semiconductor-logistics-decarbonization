import argparse
import json
from pathlib import Path
from .evaluate import DATA, load, offline
from .api import run, verify, write


def main():
    p=argparse.ArgumentParser(description="Source-level quantity facts: offline evaluation, bounded manual API and replay.")
    p.add_argument("command",choices=("validate","offline","api","verify"))
    p.add_argument("--dataset",type=Path,default=DATA)
    p.add_argument("--output",type=Path,default=Path("artifacts/notice_facts"))
    p.add_argument("--split",choices=("development","exploratory"),default="exploratory")
    p.add_argument("--execute",action="store_true")
    p.add_argument("--max-usd")
    p.add_argument("--github-summary",type=Path)
    args=p.parse_args()
    if args.command=="validate":
        d=load(args.dataset);result={"validated":True,"cases":{s:len(v) for s,v in d["splits"].items()}}
    elif args.command=="offline":
        result=offline(args.dataset);write(args.output/"offline.json",result)
    elif args.command=="api":
        result=run(args.output,dataset_path=args.dataset,split=args.split,execute=args.execute,max_usd=args.max_usd)
    else:
        result=verify(args.output,dataset_path=args.dataset,split=args.split);write(args.output/"assessment.json",result)
    if args.github_summary:
        with args.github_summary.open("a") as f:
            f.write("## Real quantity extraction\n\nAssistant reference agreement; human review pending. This does not validate internal-route updates.\n\n```json\n"+json.dumps(result,indent=2)+"\n```\n")
    print(json.dumps(result,sort_keys=True))
    return 2 if args.command=="api" and args.execute and not result["complete"] else 0


if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as e:
        # Never display arbitrary error text from transports/credentials.
        print(json.dumps({"status":"failed","error_type":type(e).__name__}));raise SystemExit(2)
