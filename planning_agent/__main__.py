"""Command line for the supply-chain planning copilot.

python -m planning_agent ask "红海中断对 ASML 备件成本有什么影响？"
python -m planning_agent chat
python -m planning_agent demo --output artifacts/planning_agent/demo
python -m planning_agent eval --agent rule --output benchmark_results/planning_agent

--agent auto uses the LLM agent when LLM_API_KEY is set, otherwise the offline rule agent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import llm
from .agent import run_llm
from .evaluate import evaluate
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
    return "llm", llm.OpenAICompatibleClient()


def _answer(kind, client, question, session, history):
    if kind == "rule":
        return run_rules(question, session)
    result = run_llm(question, session, client, history=history)
    history += [{"role": "user", "content": question}, {"role": "assistant", "content": result.answer}]
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="planning_agent", description=__doc__.splitlines()[0])
    parser.add_argument("--agent", choices=("auto", "rule", "llm"), default="auto")
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
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    kind, client = _agent(args.agent)
    if args.command == "eval":
        result = evaluate(kind, split=args.split, output=args.output, client=client)
        print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
        return 0
    if args.command == "demo":
        args.output.mkdir(parents=True, exist_ok=True)
        session, history = Session(memo_dir=args.output), []
        lines = [f"# Planning agent demo ({kind} agent)", ""]
        for question in DEMO:
            result = _answer(kind, client, question, session, history)
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
    if args.command == "ask":
        result = _answer(kind, client, args.question, session, history)
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
        print(_answer(kind, client, question, session, history).answer, "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
