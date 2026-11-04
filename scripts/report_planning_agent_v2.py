"""Audit the saved 20-task evaluation and write its tables, sensitivity analysis and exploratory check.

Everything is computed from the saved raw runs; no model is called and no plan is solved. The official scores are
never changed here: `sensitivity.json` is a post-hoc reading, labelled as such, of what the frozen scorer's known defects mean.

    python -m planning_agent eval-v2 analyze
    python scripts/report_planning_agent_v2.py
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from planning_agent import eval_v2

RESULTS = Path("benchmark_results/planning_agent_v2")
LABELS = ("task_success", "tool_selection", "tool_call_ok", "params_exact", "param_field_accuracy", "states_missing",
          "invented_parameter", "gold_numbers_found", "numeric_faithfulness", "assumption_flagged",
          "cites_notice_quantity")
NAMES = {
    "zh": {"task_success": "任务完成率", "tool_selection": "工具选择正确率", "tool_call_ok": "工具调用成功率",
           "params_exact": "参数完全正确率", "param_field_accuracy": "参数字段正确率", "states_missing": "说明缺失信息",
           "invented_parameter": "编造或未标注的参数（越低越好）", "gold_numbers_found": "引擎数字出现率",
           "numeric_faithfulness": "数字审查通过率", "assumption_flagged": "写明假设",
           "cites_notice_quantity": "引用公告数量"},
    "en": {"task_success": "Task completion", "tool_selection": "Correct tool selection",
           "tool_call_ok": "Tool calls that succeed", "params_exact": "All parameters correct",
           "param_field_accuracy": "Correct parameter fields", "states_missing": "States what is missing",
           "invented_parameter": "Invented or unlabelled parameters (lower is better)",
           "gold_numbers_found": "Engine numbers present", "numeric_faithfulness": "Numeric review passed",
           "assumption_flagged": "States its assumption", "cites_notice_quantity": "Cites the notice's quantity"},
}
HEAD = {"zh": ("指标", "题数", "模型 Sol max", "规则", "模型 − 规则（百分点）"),
        "en": ("Metric", "Tasks", "Model Sol max", "Rules", "Model − rules (points)")}


def share(entry: dict[str, Any]) -> str:
    if entry["estimate"] is None:
        return "—"
    low, high = entry["ci95"]
    return f"{100 * entry['estimate']:.1f}% [{100 * low:.1f}, {100 * high:.1f}]"


def points(entry: dict[str, Any]) -> str:
    if entry["estimate"] is None:
        return "—"
    low, high = entry["ci95"]
    return f"{100 * entry['estimate']:+.1f} [{100 * low:+.1f}, {100 * high:+.1f}]"


def metric_rows(table: dict[str, Any], language: str) -> list[str]:
    head = HEAD[language]
    rows = [f"| {head[0]} | {head[1]} | {head[2]} | {head[3]} | {head[4]} |", "|---|---:|---:|---:|---:|"]
    for key in LABELS:
        entry = table[key]
        if entry["model"]["estimate"] is None and entry["rule"]["estimate"] is None:
            continue
        rows.append(f"| {NAMES[language][key]} | {entry['model']['tasks']} | {share(entry['model'])} | "
                    f"{share(entry['rule'])} | {points(entry['model_minus_rule'])} |")
    return rows


def per_case_rows(report: dict[str, Any], language: str) -> list[str]:
    head = (("题", "类型", "模型三次", "规则", "模型失败标签", "请求数", "费用（美元）", "秒")
            if language == "zh" else
            ("Task", "Kind", "Model, 3 runs", "Rules", "Model failure labels", "Requests", "Cost (USD)", "Seconds"))
    rows = ["| " + " | ".join(head) + " |", "|---|---|---|---|---|---:|---:|---:|"]
    mark = {True: "✓", False: "✗"}
    for row in report["per_case"]:
        labels = sorted({x for run in row["model_labels"] for x in run})
        rows.append(f"| {row['case']} | {row['kind']} | {' '.join(mark[x] for x in row['model_successes'])} | "
                    f"{mark[row['rule_successes'][0]] if row['rule_successes'] else '—'} | "
                    f"{', '.join(labels) or '—'} | "
                    f"{'/'.join(str(x) for x in row['model_requests'])} | "
                    f"{'/'.join(f'{x:.3f}' for x in row['model_cost_usd'])} | "
                    f"{'/'.join(f'{x:.0f}' for x in row['model_seconds'])} |")
    return rows


def write_tables(report: dict[str, Any], output: Path) -> Path:
    parts = []
    for language in ("zh", "en"):
        parts.append(f"<!-- {language}: overall -->")
        parts += metric_rows(report["overall"], language)
        for group in ("A", "B", "C"):
            parts += ["", f"<!-- {language}: group {group} -->"]
            parts += metric_rows(report["groups"][group], language)
        parts += ["", f"<!-- {language}: per task -->"]
        parts += per_case_rows(report, language)
        parts.append("")
    path = output / "tables.md"
    path.write_text("\n".join(parts), encoding="utf-8", newline="\n")
    return path


def audit(results: Path, model_folder: str) -> dict[str, Any]:
    """What the raw records say about completeness, configuration, identity and leaks."""
    model_dir = results / model_folder
    rows = eval_v2.read_jsonl(model_dir / "runs.jsonl")
    attempts = eval_v2.read_jsonl(model_dir / "attempts.jsonl")
    rules = eval_v2.read_jsonl(results / "rule" / "runs.jsonl")
    sessions = eval_v2.read_jsonl(model_dir / "sessions.jsonl")
    freeze = json.loads(eval_v2.FREEZE.read_text(encoding="utf-8"))["sha256"]
    keys = Counter((r["case_id"], r["repeat"]) for r in rows)
    expected = {(c["id"], r) for c in eval_v2.load_cases() for r in (1, 2, 3)}
    answered = [q for r in rows for q in r["requests"] if "failure" not in q]
    first_scored = min(r["started_at"] for r in rows)
    before = [s["started_at"] for s in sessions if s["started_at"] <= first_scored]
    producing = [s for s in sessions if s["started_at"] >= max(before)]  # the starts that produced scored runs
    seconds, costs = sorted(r["seconds"] for r in rows), sorted(r["cost_usd_at_list_price"] for r in rows)
    text = "\n".join(p.read_text(encoding="utf-8") for p in model_dir.rglob("*") if p.is_file())
    leaks = {word: word in text for word in ("Bearer ", "Authorization", "27788", "C:\\\\Users", "D:\\\\coding",
                                             "dusanhanz")}
    return {
        "runs_saved": len(rows), "runs_expected": len(expected),
        "missing_runs": sorted(f"{c} r{r}" for c, r in expected - set(keys)),
        "duplicate_runs": sorted(f"{c} r{r}" for (c, r), n in keys.items() if n > 1),
        "distinct_run_ids": len({r["run_id"] for r in rows}),
        "attempt_numbers": dict(Counter(r["attempt"] for r in rows)),
        "attempts_not_scored": [{"case": a["case_id"], "error": str(a["error"])[:90],
                                 "requests": [q.get("failure", "answered") for q in a["requests"]]} for a in attempts],
        "call_kinds": dict(Counter(r["call_kind"] for r in rows)),
        "effective_per_request": {key: dict(Counter(str(q.get(key)) for q in answered))
                                  for key in ("endpoint", "model", "reasoning_effort", "reasoning_mode", "service_tier",
                                              "status")},
        "first_scored_run": first_scored, "last_scored_run": max(r["started_at"] for r in rows),
        "sessions": [{"started_at": s["started_at"], "commit": s["code"]["commit"][:7],
                      "modified_paths": s["code"]["modified_paths"], "frozen_match": s["frozen_sha256"] == freeze,
                      "config_model": s["config"].get("model"), "effort": s["config"].get("reasoning_effort")}
                     for s in sessions],
        "scoring_sessions": {"commits": sorted({s["code"]["commit"][:7] for s in producing}),
                             "no_uncommitted_changes": all(not s["code"]["modified_paths"] for s in producing),
                             "all_match_freeze": all(s["frozen_sha256"] == freeze for s in producing)},
        "run_statistics": {"median_seconds": round(statistics.median(seconds), 2),
                           "p90_seconds": seconds[int(0.9 * len(seconds))], "max_seconds": seconds[-1],
                           "median_cost_usd": round(statistics.median(costs), 4),
                           "p90_cost_usd": costs[int(0.9 * len(costs))], "max_cost_usd": costs[-1],
                           "tool_seconds_total": round(sum(c["seconds"] for r in rows for c in r["tool_calls"]), 1),
                           "rule_seconds_total": round(sum(r["seconds"] for r in rules), 1)},
        "runs_with_errors": [f"{r['case_id']} r{r['repeat']}: {r['error']}" for r in rows if r["error"]],
        "tool_calls": {"total": sum(len(r["tool_calls"]) for r in rows),
                       "failed": [f"{r['case_id']} r{r['repeat']} {c['name']}: {str(c['result'].get('error'))[:70]}"
                                  for r in rows for c in r["tool_calls"] if not c["ok"]],
                       "by_tool": dict(Counter(c["name"] for r in rows for c in r["tool_calls"]))},
        "rule_runs": len(rules), "rule_runs_identical_across_repeats": all(
            len({json.dumps(r["score"], sort_keys=True) for r in rules if r["case_id"] == c}) == 1
            for c in {r["case_id"] for r in rules}),
        "text_scan_hits": {k: v for k, v in leaks.items() if v},
        "model_requests_with_all_optional_arguments": argument_pattern(rows),
    }


def argument_pattern(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Evidence that optional tool fields were always filled, as strict schema normalisation requires."""
    solve = [c["arguments"] for r in rows for c in r["tool_calls"] if c["name"] == "solve_plan"]
    disruptions = [d for r in rows for c in r["tool_calls"] if c["name"] == "create_scenario"
                   for d in c["arguments"].get("disruptions") or []]
    return {"solve_plan_calls": len(solve),
            "with_carbon_cap_service_price_and_label": sum(
                all(k in a for k in ("carbon_cap_pct", "carbon_price_usd_per_t", "service_level_pct", "label"))
                for a in solve),
            "disruptions": len(disruptions),
            "with_both_mode_and_lanes": sum(bool(d.get("mode")) and bool(d.get("lanes")) for d in disruptions)}


def sensitivity(rows: list[dict[str, Any]], rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Post-hoc readings of the frozen scorer's known defects. The official scores stay as they are."""
    def apostrophe(row: dict[str, Any]) -> bool:
        """B06: the refusal list has "can't" with a straight apostrophe; the model wrote a typographic one."""
        return bool(row["kind"] == "refuse" and not row["tool_calls"] and not row["error"] and row["guardrail"]["ok"]
                    and "can’t" in (row["answer"] or "").lower())

    def notice_scope(row: dict[str, Any]) -> bool:
        """C03: the notice is about another trade. Saying so, asking and inventing nothing is the right reading."""
        return bool(row["case_id"] == "C03" and row["score"]["states_missing"] is False
                    and not row["score"]["executed_scenario"] and row["guardrail"]["ok"] and not row["error"])

    readings = {"official": lambda r: r["score"]["success"],
                "with_B06_apostrophe_read_correctly": lambda r: r["score"]["success"] or apostrophe(r),
                "and_with_C03_read_by_hand": lambda r: r["score"]["success"] or apostrophe(r) or notice_scope(r)}
    out: dict[str, Any] = {"note": "Post-hoc. Not a replacement for the pre-specified scores; the corrections were "
                                   "chosen after seeing the failures."}
    for name, value in readings.items():
        per_task = eval_v2.by_case(rows, value)
        out[name] = {"runs_succeeded": sum(bool(value(r)) for r in rows), "runs": len(rows),
                     **eval_v2.bootstrap(per_task),
                     "minus_rule": eval_v2.bootstrap(per_task, eval_v2.by_case(rules, eval_v2.METRICS["task_success"]))}
    return out


def notice_workflow(results: Path) -> dict[str, Any]:
    """Exploratory: the fixed, model-free notice workflow on the tasks whose text gives no executable parameters."""
    from planning_agent import workflow
    rows = []
    for case in eval_v2.load_cases():
        if case["kind"] in ("notice", "clarify"):
            proposal = workflow.propose_from_notices(case["question"])
            rows.append({"case": case["id"], "disruptions": proposal.disruptions, "preset": proposal.preset,
                         "missing_listed": proposal.missing, "references": [r["id"] for r in proposal.references]})
    return {"note": "Exploratory and outside the pre-specified comparison: workflow.propose_from_notices, no model.",
            "tasks": len(rows), "proposed_no_parameters": sum(not (r["disruptions"] or r["preset"]) for r in rows),
            "listed_missing_information": sum(bool(r["missing_listed"]) for r in rows), "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, default=RESULTS)
    args = parser.parse_args()
    config = json.loads(eval_v2.CONFIG.read_text(encoding="utf-8"))
    output = args.results / "analysis"
    report = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    rows = eval_v2.read_jsonl(args.results / config["result_folder"] / "runs.jsonl")
    rules = eval_v2.read_jsonl(args.results / "rule" / "runs.jsonl")
    for name, value in (("audit", audit(args.results, config["result_folder"])),
                        ("sensitivity", sensitivity(rows, rules)),
                        ("notice_workflow_exploratory", notice_workflow(args.results))):
        (output / f"{name}.json").write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                             newline="\n")
        print(f"wrote {output / (name + '.json')}")
    print(f"wrote {write_tables(report, output)}")


if __name__ == "__main__":
    main()
