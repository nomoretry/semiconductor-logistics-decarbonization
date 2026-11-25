"""Evaluate planning agents on planner questions with engine-computed gold numbers.

A case succeeds when the agent called every expected tool with the expected
key arguments, its answer contains every gold number (within rounding) and
the numeric guardrail found no untraceable numbers. Refusal and clarification
cases succeed when the agent declines or asks back without solving anything.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .guardrails import numbers_in
from .tools import Session

CASES = Path(__file__).with_name("eval_cases.json")
REFUSAL = ("超出", "范围", "无法", "不能", "outside", "can't", "cannot", "unable", "only help", "not able")


def load_cases(split: str = "all", ids=None) -> list[dict]:
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    return [c for c in cases if (split == "all" or c["split"] == split) and (ids is None or c["id"] in ids)]


class Gold:
    """Gold numbers from direct tool calls on a separate session with the same solver settings."""

    def __init__(self, settings: dict):
        self.session = Session(**settings)
        self.custom = 0

    def value(self, fact: dict) -> float:
        s, kind = self.session, fact["kind"]
        if kind == "lane":
            lanes = s.call("describe_network", {"network": fact["network"]})["lanes"]
            return next(lane[fact["field"]] for lane in lanes if lane["id"] == fact["lane"])
        if kind == "frontier":
            return s.call("carbon_frontier", {"network": fact["network"]})[fact["field"]]
        if kind == "hedge":
            args = {"network": fact["network"]}
            if "scenarios" in fact:
                args.update(scenarios=fact["scenarios"], probabilities=fact["probabilities"])
            return s.call("hedge_disruption_risk", args)[fact["field"]]
        scenario = fact.get("scenario", "normal")
        if fact.get("custom"):
            self.custom += 1
            scenario = f"gold_custom_{self.custom}"
            created = s.call("create_scenario", {"network": fact["network"], "name": scenario, **fact["custom"]})
            if "error" in created:
                raise ValueError(created["error"])
        target = {"network": fact["network"], "scenario": scenario}
        if fact.get("carbon_cap_pct"):
            target["carbon_cap_pct"] = fact["carbon_cap_pct"]
        plan = s.call("solve_plan", target)
        if kind == "shadow":
            return plan["carbon_shadow_price_usd_per_t"]
        base = s.call("solve_plan", {"network": fact["network"]})
        row = s.call("compare_plans", {"plan_ids": [base["plan_id"], plan["plan_id"]]})["rows"][1]
        return row[fact["metric"]]


def _has_number(answer: str, gold: float) -> bool:
    tolerance = max(0.02 * abs(gold), 0.1 if abs(gold) < 100 else 1.0)
    return any(abs(abs(value) - abs(gold)) <= tolerance for _, value, _ in numbers_in(answer))


def _args_match(case: dict, calls: list) -> tuple[int, int]:
    created = {c["arguments"].get("name") for c in calls if c["name"] == "create_scenario" and c["ok"]}
    met = total = 0
    for tool, expected in case.get("expect_args", {}).items():
        total += 1
        for call in calls:
            if call["name"] != tool:
                continue
            ok = True
            for key, value in expected.items():
                got = call["arguments"].get(key)
                if key == "scenario" and got in created:
                    continue  # an equivalent custom scenario is judged by the gold numbers instead
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    ok &= got is not None and abs(float(got) - value) <= 0.5
                else:
                    ok &= got == value
            if ok:
                met += 1
                break
    return met, total


def score(case: dict, result, gold: Gold) -> dict:
    names = result.tool_names()
    answer = result.answer
    row = {"id": case["id"], "split": case["split"], "question": case["question"], "tools": names,
           "steps": len(names), "seconds": result.seconds, "faithful": result.guardrail["ok"],
           "unsupported_numbers": result.guardrail["unsupported"], "error": result.error}
    if case.get("expect_refusal") or case.get("expect_clarification"):
        if case.get("expect_refusal"):
            ok = not names and any(word in answer.lower() for word in REFUSAL)
        else:
            ok = ("?" in answer or "？" in answer) and "solve_plan" not in names
        row.update(success=ok, tool_recall=1.0 if ok else 0.0, tool_precision=None, args_met=None,
                   facts_found=None, facts_total=0)
        return row
    expected = set(case["expect_tools"])
    called = set(names)
    recall = len(expected & called) / len(expected) if expected else 1.0
    precision = len(expected & called) / len(called) if called else 0.0
    met, total = _args_match(case, result.tool_calls)
    found, gold_values = 0, []
    for fact in case.get("facts", []):
        value = gold.value(fact)
        gold_values.append(value)
        found += _has_number(answer, value)
    row.update(tool_recall=round(recall, 3), tool_precision=round(precision, 3), args_met=f"{met}/{total}",
               facts_found=found, facts_total=len(case.get("facts", [])), gold=gold_values,
               success=recall == 1.0 and met == total and found == len(case.get("facts", []))
               and result.guardrail["ok"] and not result.error)
    return row


def summarise(rows: list[dict]) -> dict:
    def mean(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 4) if values else None
    facts_total = sum(r["facts_total"] for r in rows)
    return {"cases": len(rows), "success_rate": mean([float(r["success"]) for r in rows]),
            "tool_recall": mean([r["tool_recall"] for r in rows]),
            "tool_precision": mean([r["tool_precision"] for r in rows]),
            "fact_accuracy": round(sum(r["facts_found"] or 0 for r in rows) / facts_total, 4) if facts_total else None,
            "faithfulness": mean([float(r["faithful"]) for r in rows]),
            "mean_tool_calls": mean([r["steps"] for r in rows]), "mean_seconds": mean([r["seconds"] for r in rows])}


USAGE_KEYS = ("prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens", "calls")


def _tokens(usage: dict | None) -> int:
    """Billable tokens; providers count reasoning tokens inside completion tokens."""
    usage = usage or {}
    return usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)


def evaluate(agent: str, *, split: str = "all", ids=None, output: Path | None = None, settings: dict | None = None,
             client=None, resume: bool = False, max_tokens: int | None = None, progress=None) -> dict:
    """Run the cases, saving each row as soon as it is scored.

    resume skips cases already in <agent>_cases.jsonl, so an interrupted paid run is never repeated;
    max_tokens stops between cases once the recorded usage reaches the budget.
    """
    from .agent import run_llm
    from .rules import run_rules
    settings = settings or {}
    output = Path(output) if output else None
    path = output / f"{agent}_cases.jsonl" if output else None
    rows = []
    if path and resume and path.exists():
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if path:
        output.mkdir(parents=True, exist_ok=True)
        if not resume:
            path.write_text("", encoding="utf-8")
    done = {r["id"] for r in rows}
    todo = [c for c in load_cases(split, ids) if c["id"] not in done]
    gold, stopped = Gold(settings), None
    for n, case in enumerate(todo, 1):
        spent = sum(_tokens(r.get("usage")) for r in rows)
        if max_tokens and spent >= max_tokens:
            stopped = {"reason": f"token budget {max_tokens:,} reached after {spent:,} tokens",
                       "remaining": [c["id"] for c in todo[n - 1:]]}
            break
        before = dict(getattr(client, "usage", None) or {})
        session = Session(**settings)
        if agent == "rule":
            result = run_rules(case["question"], session)
        elif agent == "graph":
            from .graph import run_graph
            result = run_graph(case["question"], session, client)
        else:
            result = run_llm(case["question"], session, client)
        row = score(case, result, gold)
        after = dict(getattr(client, "usage", None) or {})
        row.update(answer=result.answer, model=getattr(client, "model", None),
                   tool_calls=[{"name": c["name"], "arguments": c["arguments"], "ok": c["ok"],
                                **({} if c["ok"] else {"error": str(c["result"].get("error", ""))[:300]})}
                               for c in result.tool_calls],
                   usage={k: after.get(k, 0) - before.get(k, 0) for k in USAGE_KEYS} if after else {})
        rows.append(row)
        if path:
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        if progress:
            progress(f"[{n}/{len(todo)}] {case['id']} {'OK  ' if row['success'] else 'FAIL'} "
                     f"tools={len(row['tools'])} tokens={_tokens(row['usage']):,} {row['seconds']}s")
    order = {c["id"]: i for i, c in enumerate(load_cases())}
    rows.sort(key=lambda r: order.get(r["id"], len(order)))
    summary = {"agent": agent, "model": getattr(client, "model", None),
               "api_style": getattr(client, "api_style", None),
               "reasoning_effort": getattr(client, "reasoning_effort", None),
               "usage": {k: sum((r.get("usage") or {}).get(k, 0) for r in rows) for k in USAGE_KEYS},
               "stopped_early": stopped,
               "splits": {name: summarise([r for r in rows if r["split"] == name])
                          for name in sorted({r["split"] for r in rows})},
               "overall": summarise(rows)}
    if output:
        _write(output, agent, summary, rows)
    return {"summary": summary, "rows": rows}


GUARDRAIL_NOTE = "\n\n> 自动审查提示："


def rescore(agent: str, output: Path, settings: dict | None = None) -> dict:
    """Re-check saved answers with the current guardrail without calling any model.

    Each case's recorded tool calls are replayed on a fresh session to rebuild the tool results the model
    saw (the engine is deterministic; a replayed call whose success differs from the recording is counted
    as a mismatch), the note the guardrail appended at run time is removed, and success is recomputed.
    Results go to <agent>_rescored_*; the original files are left untouched.
    """
    from .guardrails import check_answer
    output, settings = Path(output), settings or {}
    rows = [json.loads(line) for line in (output / f"{agent}_cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    cases = {c["id"]: c for c in load_cases()}
    rescored, mismatches = [], 0
    for row in rows:
        if "tool_calls" not in row:
            raise ValueError(f"{row['id']} has no recorded tool calls; rerun it with the current evaluation")
        session = Session(**settings)
        results = []
        for call in row["tool_calls"]:
            results.append(session.call(call["name"], call["arguments"]))
            mismatches += session.calls[-1]["ok"] != call["ok"]
        answer = row["answer"].split(GUARDRAIL_NOTE)[0]
        check = check_answer(answer, results, row["question"])
        new = dict(row, answer=answer, faithful=check["ok"], unsupported_numbers=check["unsupported"], rescored=True)
        case = cases[row["id"]]
        if not (case.get("expect_refusal") or case.get("expect_clarification")):
            met, total = (int(x) for x in row["args_met"].split("/"))
            new["facts_found"] = sum(_has_number(answer, g) for g in row.get("gold") or [])
            new["success"] = (row["tool_recall"] == 1.0 and met == total and new["facts_found"] == row["facts_total"]
                              and check["ok"] and not row.get("error"))
        rescored.append(new)
    summary = json.loads((output / f"{agent}_summary.json").read_text(encoding="utf-8"))
    summary.update(rescored_with="current guardrail; tool results rebuilt by replaying the recorded calls",
                   replay_mismatches=mismatches,
                   splits={name: summarise([r for r in rescored if r["split"] == name])
                           for name in sorted({r["split"] for r in rescored})},
                   overall=summarise(rescored))
    _write(output, f"{agent}_rescored", summary, rescored)
    return {"summary": summary, "rows": rescored}


def _write(output: Path, agent: str, summary: dict, rows: list[dict]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{agent}_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8",
                                                newline="\n")
    with (output / f"{agent}_cases.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    with (output / f"{agent}_cases.csv").open("w", newline="", encoding="utf-8") as handle:
        keys = ["id", "split", "success", "tool_recall", "tool_precision", "args_met", "facts_found", "facts_total",
                "faithful", "steps", "seconds", "tools", "question"]
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
