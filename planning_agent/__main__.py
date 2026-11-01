"""Command line for the supply-chain planning copilot.

python -m planning_agent ask "红海中断对 ASML 备件成本有什么影响？"
python -m planning_agent chat
python -m planning_agent demo --output artifacts/planning_agent/demo
python -m planning_agent eval --agent rule --output benchmark_results/planning_agent
python -m planning_agent replay --output benchmark_results/planning_agent
python -m planning_agent flow                       # notice -> parameters -> confirm -> plans -> memo

--agent auto uses the LLM agent when LLM_API_KEY is set, otherwise the offline rule agent.
--agent graph runs the same model, tools and guardrail as a LangGraph state graph (needs the agent extra).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import llm
from .agent import run_llm
from .evaluate import evaluate, rescore
from .rules import run_rules
from .tools import Session

DEMO = (
    "介绍一下 ASML 备件网络有哪些运输线路，各自运力多少？",
    "船公司通知：受红海安全局势影响，第4到12周亚欧航线绕行好望角，海运延误2周，舱位削减30%。"
    "这对我们新加坡备件仓的成本和排放有什么影响？",
    "如果在这种情况下还要求减排 25%，成本代价是多少？瓶颈在哪？",
    "红海中断大概有 25% 的概率发生，要不要提前对冲？",
    "把结论写成备忘录给物流经理。",
)


def _agent(choice: str):
    if choice == "rule" or (choice == "auto" and not llm.configured()):
        return "rule", None
    return ("graph" if choice == "graph" else "llm"), llm.OpenAICompatibleClient()


def _conversation(kind, session, client):
    if kind != "graph":
        return None
    from .graph import PlanningGraph
    return PlanningGraph(session, client)


def _answer(kind, client, question, session, history, conversation=None):
    if kind == "rule":
        return run_rules(question, session)
    if kind == "graph":
        return conversation.ask(question)  # the graph keeps its own checkpointed history
    result = run_llm(question, session, client, history=history)
    history += [{"role": "user", "content": question}, {"role": "assistant", "content": result.answer}]
    return result


def _flow(args) -> int:
    from . import workflow
    notice = args.notice or workflow.DEMO_NOTICE
    if args.mode == "rule":
        proposal = workflow.propose_from_rules(notice, args.network)
    elif args.mode == "replay":
        proposal = workflow.propose_from_recording(args.case)
    else:
        if not llm.configured():
            print("实时模式需要 LLM_API_KEY；本命令不会在没有 key 时调用模型。")
            return 2
        proposal = workflow.propose_from_model(notice, llm.OpenAICompatibleClient(), max_tokens=args.max_tokens,
                                               network=args.network)
    changes = {k: v for k, v in (("carbon_cap_pct", args.carbon_cap), ("hedge_probability_pct", args.probability))
               if v is not None}
    proposal = proposal.with_changes(**changes)
    args.output.mkdir(parents=True, exist_ok=True)
    session = Session(memo_dir=args.output)
    print(f"【{workflow.MODE_LABELS[proposal.mode]}】")
    print(f"公告：{proposal.notice}")
    while True:
        print()
        print("\n".join(workflow.describe(proposal)))
        checked = workflow.preview(proposal, session)
        if checked["error"]:
            print(f"参数不可用：{checked['error']}")
        for item in checked["assumptions"]:
            print(f"默认假设：{item}")
        if args.yes:
            break
        answer = input("按以上参数求解？[y] 确认  [e] 修改第一个扰动  [n] 取消：").strip().lower()
        if answer == "y":
            break
        if answer == "e" and proposal.disruptions:
            proposal = workflow.edit_disruption(proposal, 0, lambda key, now: input(f"  {key} [{now}]："))
            continue
        print("已取消，没有求解。")
        return 1
    outcome = workflow.run(proposal, session, confirmed=True)
    print()
    print("方案对比（确认后实时求解）：")
    for row in workflow.summary_rows(outcome):
        print("  " + "  ".join(f"{k}：{v}" for k, v in row.items()))
    if outcome.hedge and "error" not in outcome.hedge:
        print(f"对冲：VSS {outcome.hedge['VSS_usd']:,} 美元（{outcome.hedge['VSS_pct']}%）")
    print(f"备忘录：{outcome.memo_path}（用时 {outcome.seconds} 秒，工具调用 {len(outcome.tool_calls)} 次）")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="planning_agent", description=__doc__.splitlines()[0])
    parser.add_argument("--agent", choices=("auto", "rule", "llm", "graph"), default="auto")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ask")
    p.add_argument("question")
    p.add_argument("--show-tools", action="store_true")
    sub.add_parser("chat")
    p = sub.add_parser("demo")
    p.add_argument("--output", type=Path, default=Path("artifacts/planning_agent/demo"))
    p = sub.add_parser("eval")
    p.add_argument("--split", choices=("all", "dev", "holdout"), default="all")
    p.add_argument("--output", type=Path, default=Path("benchmark_results/planning_agent"))
    p.add_argument("--ids", help="comma-separated case ids for a pilot run, e.g. D03,D13,H05")
    p.add_argument("--resume", action="store_true", help="skip cases already saved in the output folder")
    p.add_argument("--max-tokens", type=int, help="stop between cases once billable tokens reach this budget")
    p.add_argument("--rescore", action="store_true",
                   help="re-check saved answers with the current guardrail by replaying their tool calls (no API calls)")
    p = sub.add_parser("flow", help="notice -> parameters and assumptions -> confirmation -> plans -> memo")
    p.add_argument("--mode", choices=("rule", "replay", "live"), default="rule",
                   help="rule: offline parser; replay: recorded model output (no call); live: paid model call")
    p.add_argument("--notice", help="carrier notice or disruption text (rule and live modes)")
    p.add_argument("--case", default="D13", help="recorded case for replay mode")
    p.add_argument("--network", choices=("asml", "marvell"))
    p.add_argument("--carbon-cap", type=float, help="emission cap, %% of the uncapped plan")
    p.add_argument("--probability", type=float, help="disruption probability %% for a hedge")
    p.add_argument("--max-tokens", type=int, help="live mode: approved token cap")
    p.add_argument("--yes", action="store_true", help="confirm without asking (scripts)")
    p.add_argument("--output", type=Path, default=Path("artifacts/planning_agent/flow"))
    p = sub.add_parser("replay", help="replay recorded model runs through the LangGraph agent (no API calls)")
    p.add_argument("--source", type=Path, default=Path("benchmark_results/planning_agent"))
    p.add_argument("--output", type=Path)
    p.add_argument("--ids", help="comma-separated case ids")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.command == "flow":
        return _flow(args)
    if args.command == "replay":
        from .graph import replay
        ids = [i.strip() for i in args.ids.split(",") if i.strip()] if args.ids else None
        result = replay(args.source, args.output, ids=ids, progress=lambda line: print(line, flush=True))
        print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
        return 0 if not result["summary"]["mismatches"] else 1
    if args.command == "eval" and args.rescore:
        result = rescore(args.agent if args.agent in ("rule", "graph") else "llm", args.output)
        print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
        return 0
    kind, client = _agent(args.agent)
    if args.command == "eval":
        ids = [i.strip() for i in args.ids.split(",") if i.strip()] if args.ids else None
        result = evaluate(kind, split=args.split, ids=ids, output=args.output, client=client, resume=args.resume,
                          max_tokens=args.max_tokens, progress=lambda line: print(line, flush=True))
        print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
        return 0
    if args.command == "demo":
        args.output.mkdir(parents=True, exist_ok=True)
        session, history = Session(memo_dir=args.output), []
        conversation = _conversation(kind, session, client)
        lines = [f"# Planning agent demo ({kind} agent)", ""]
        for question in DEMO:
            result = _answer(kind, client, question, session, history, conversation)
            tools = ", ".join(f"`{c['name']}({json.dumps(c['arguments'], ensure_ascii=False)})`"
                              for c in result.tool_calls) or "（无）"
            lines += [f"## 问：{question}", "", f"**工具调用**：{tools}", "", result.answer, "",
                      f"*护栏：{'通过' if result.guardrail['ok'] else '未通过 ' + str(result.guardrail['unsupported'])}；"
                      f"{result.seconds} 秒*", ""]
            print(f"> {question}\n{result.answer}\n")
        (args.output / "transcript.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
        print(f"wrote {args.output / 'transcript.md'}")
        return 0
    session, history = Session(), []
    conversation = _conversation(kind, session, client)
    if args.command == "ask":
        result = _answer(kind, client, args.question, session, history, conversation)
        print(result.answer)
        if args.show_tools:
            for call in result.tool_calls:
                print(f"- {call['name']} {json.dumps(call['arguments'], ensure_ascii=False)} ({call['seconds']} s)")
        return 0
    print(f"规划副驾驶（{kind} agent）。输入问题，空行退出。")
    while True:
        try:
            question = input("> ").strip()
        except EOFError:
            break
        if not question:
            break
        print(_answer(kind, client, question, session, history, conversation).answer, "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
