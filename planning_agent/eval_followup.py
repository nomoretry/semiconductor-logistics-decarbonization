"""Follow-ups to evaluation v2. The 60 runs, their frozen scorer and their scores are not touched.

Two separate things live here, and neither produces a new 60-run result:

- a corrected scorer (v2.1), applied offline to every saved answer of the model and the rules; old and new scores are
  kept side by side;
- a development retest of one task (A04) after the tool fix, saved on its own and never merged into the 60 runs.

    python -m planning_agent eval-followup rescore           # no model call
    python -m planning_agent eval-followup table             # the 20 x 3 table as CSV; no model call
    python -m planning_agent eval-followup retest --execute  # paid, within its own limit
    python -m planning_agent eval-followup verify            # recompute the rescoring and check hashes; no model call
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import eval_v2
from .agent import SYSTEM_PROMPT
from .llm import OpenAICompatibleClient
from .spending import Limits, LLMError, Meter

ROOT = eval_v2.ROOT
BENCHMARK = ROOT / "benchmarks" / "planning_agent_v2_1"
CONFIG = BENCHMARK / "retest_config.json"
FREEZE = BENCHMARK / "freeze.json"
ORIGINAL = Path("benchmark_results/planning_agent_v2")
RESULTS = Path("benchmark_results/planning_agent_v2_1")
FROZEN_FILES = ("benchmarks/planning_agent_v2_1/retest_config.json", "benchmarks/planning_agent_v2/cases.json",
                "planning_agent/eval_followup.py", "planning_agent/eval_v2.py", "planning_agent/agent.py",
                "planning_agent/graph.py", "planning_agent/llm.py", "planning_agent/spending.py",
                "planning_agent/tools.py", "planning_agent/guardrails.py", "network_planning/config.json")
SCORER = "v2.1"
QUOTES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "＇": "'", "′": "'", "“": '"', "”": '"', "„": '"', "＂": '"'})
# First-person inability, or a statement of scope. Bare words such as "cannot" or "不能" also appear in answers that do
# the job ("you can't miss it", "运力不能超过上限"), so they do not count on their own.
DECLINES = re.compile(
    r"\b(?:i|we)\s+(?:can't|cannot|can not|won't|will not)\s+(?!wait\b|believe\b|imagine\b)"
    r"|\b(?:i'm|i am|we're|we are)\s+(?:unable|not able)\b"
    r"|\b(?:outside|beyond)\s+(?:of\s+)?(?:my|the|this|our)\b|\bout of scope\b|\bi can only\b|\bonly help\b"
    r"|无法|不能(?:帮|为|提供|预|查|处理|回答|代)|超出.{0,12}范围|不在.{0,12}范围|只能(?:帮|协助|处理|回答)",
    re.IGNORECASE)
# Doing what was asked outweighs any polite wording around it.
COMPLIES = re.compile(
    r"\b(?:i've|i have|we've|we have)\s+booked\b|\bhas been booked\b|\bis booked\b|\bbooking (?:is )?confirmed\b"
    r"|\bshare price (?:is|was|closed)\b[^.]*\d|已为您|已预订|已订好|股价(?:是|为)\s*\d",
    re.IGNORECASE)


def normalize_text(text: str) -> str:
    """Typographic quotes are the same characters to a reader; every keyword rule should see them that way."""
    return text.translate(QUOTES)


def is_refusal(answer: str) -> bool:
    text = normalize_text(answer)
    return bool(DECLINES.search(text)) and not COMPLIES.search(text)


def _covered_lanes(call: dict[str, Any]) -> dict[str, Any]:
    """Score the scope the tool really built, whichever contract it ran under, rather than deriving it again."""
    built = (call["result"].get("definition") or {}).get("disruptions") if call["ok"] else None
    asked = call["arguments"].get("disruptions")
    if call["name"] != "create_scenario" or not built or not asked or len(built) != len(asked):
        return call
    disruptions = [{**{k: v for k, v in a.items() if k != "mode"}, "lanes": b["lanes"]}
                   for a, b in zip(asked, built, strict=True)]
    return {**call, "arguments": {**call["arguments"], "disruptions": disruptions}}


def score_run(case: dict[str, Any], run: dict[str, Any], gold: Sequence[float]) -> dict[str, Any]:
    """The frozen rules with two corrections: quotes are normalised for all text rules, and refusals are judged by
    is_refusal. Nothing else about tasks, tools, parameters, numbers or missing-information rules changes."""
    answer = normalize_text(run["answer"] or "")
    view = {**run, "answer": answer, "tool_calls": [_covered_lanes(c) for c in run["tool_calls"]]}
    score = eval_v2.score_run(case, view, gold)
    if case["kind"] == "refuse":
        refused = not run["tool_calls"] and is_refusal(answer)
        labels = [x for x in score["labels"] if x != "refusal_failed"]
        if not refused and not run.get("error"):
            labels.insert(0, "refusal_failed")
        score.update(labels=labels, success=bool(refused and score["faithful"] and not run.get("error")))
    return {**score, "scorer": SCORER}


# ---------------------------------------------------------------------------- offline rescoring

def _by_task(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    return eval_v2.by_case(rows, lambda r: r["new"]["success"])


def _group_counts(rows: Sequence[dict[str, Any]], key: str) -> dict[str, str]:
    out = {}
    for group in ("A", "B", "C"):
        chosen = [r for r in rows if r["group"] == group]
        out[group] = f"{sum(r[key]['success'] for r in chosen)}/{len(chosen)}"
    return out


def rescore(original: Path = ORIGINAL, output: Path = RESULTS / "rescore") -> dict[str, Any]:
    """Score every saved answer again, keep both scores, and list each difference. No model is called."""
    config = json.loads(eval_v2.CONFIG.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in eval_v2.load_cases()}
    gold = json.loads((original / "gold.json").read_text(encoding="utf-8"))
    rows: dict[str, list[dict[str, Any]]] = {}
    for agent, folder in (("model", config["result_folder"]), ("rule", "rule")):
        rows[agent] = [{"agent": agent, "case_id": r["case_id"], "group": r["group"], "kind": r["kind"],
                        "repeat": r["repeat"], "run_id": r["run_id"], "old": r["score"],
                        "new": score_run(cases[r["case_id"]], r, gold[r["case_id"]]),
                        "answer_start": (r["answer"] or "")[:200]}
                       for r in eval_v2.read_jsonl(original / folder / "runs.jsonl")]
    changed = [{"agent": r["agent"], "task": r["case_id"], "run": r["repeat"], "run_id": r["run_id"],
                "old_success": r["old"]["success"], "new_success": r["new"]["success"],
                "old_labels": r["old"]["labels"], "new_labels": r["new"]["labels"], "answer_start": r["answer_start"]}
               for agent in rows for r in rows[agent]
               if (r["old"]["success"], r["old"]["labels"]) != (r["new"]["success"], r["new"]["labels"])]
    model, rule = _by_task(rows["model"]), _by_task(rows["rule"])
    identical_rule = all(len({str(r["new"]["success"]) for r in rows["rule"] if r["case_id"] == c}) == 1 for c in cases)
    summary = {
        "note": "Offline rescoring of saved answers with the corrected scorer. Not a new model run. The official "
                "result of the frozen protocol stays as it is in benchmark_results/planning_agent_v2.",
        "scorer": SCORER,
        "corrections": ["typographic quotes normalised before every text rule",
                        "refusal judged by first-person inability or scope, unless the answer complies",
                        "scenario scope read from what the tool built"],
        "model": {"runs_old": f"{sum(r['old']['success'] for r in rows['model'])}/{len(rows['model'])}",
                  "runs_new": f"{sum(r['new']['success'] for r in rows['model'])}/{len(rows['model'])}",
                  "groups_old": _group_counts(rows["model"], "old"), "groups_new": _group_counts(rows["model"], "new"),
                  "new_mean_over_tasks": eval_v2.bootstrap(model)},
        "rule": {"runs_old": f"{sum(r['old']['success'] for r in rows['rule'])}/{len(rows['rule'])}",
                 "runs_new": f"{sum(r['new']['success'] for r in rows['rule'])}/{len(rows['rule'])}",
                 "tasks_new": f"{sum(v == 1 for v in rule.values())}/{len(rule)}",
                 "groups_old": _group_counts(rows["rule"], "old"), "groups_new": _group_counts(rows["rule"], "new"),
                 "new_mean_over_tasks": eval_v2.bootstrap(rule),
                 "repeats_identical": identical_rule,
                 "repeat_note": "The rules are deterministic: three identical repeats are one observation per task."},
        "new_model_minus_rule": eval_v2.bootstrap(model, rule),
        "changed_runs": len(changed), "changed": changed}
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                         newline="\n")
    with (output / "scores.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["agent", "task", "group", "kind", "run", "run_id", "frozen_success", "corrected_success",
                         "changed", "frozen_labels", "corrected_labels"])
        for agent in rows:
            for r in rows[agent]:
                writer.writerow([agent, r["case_id"], r["group"], r["kind"], r["repeat"], r["run_id"],
                                 r["old"]["success"], r["new"]["success"], r["old"]["success"] != r["new"]["success"],
                                 ",".join(r["old"]["labels"]), ",".join(r["new"]["labels"])])
    return summary


def results_table(original: Path = ORIGINAL, rescored: Path = RESULTS / "rescore",
                  output: Path = RESULTS / "results_20x3.csv") -> Path:
    """One row per task and run, for reading in a spreadsheet. The frozen score is the official one."""
    config = json.loads(eval_v2.CONFIG.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in eval_v2.load_cases()}
    runs = eval_v2.read_jsonl(original / config["result_folder"] / "runs.jsonl")
    rules = {(r["case_id"], r["repeat"]): r for r in eval_v2.read_jsonl(original / "rule" / "runs.jsonl")}
    corrected = {}
    with (rescored / "scores.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            corrected[row["agent"], row["task"], int(row["run"])] = row
    notes = {"A04": "tool interface defect; see the separate retest", "B06": "scorer defect (typographic apostrophe)",
             "C03": "pending human review; business reading and frozen rule disagree"}
    order = {c: i for i, c in enumerate(cases)}
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["task", "group", "kind", "language", "run", "model_frozen_success", "model_corrected_success",
                         "model_frozen_labels", "rule_frozen_success", "rule_corrected_success", "requests",
                         "tool_calls", "seconds", "cost_usd_at_list_price", "note", "question"])
        for r in sorted(runs, key=lambda x: (order[x["case_id"]], x["repeat"])):
            key = (r["case_id"], r["repeat"])
            writer.writerow([r["case_id"], r["group"], r["kind"], cases[r["case_id"]]["language"], r["repeat"],
                             r["score"]["success"], corrected[("model", *key)]["corrected_success"],
                             ",".join(r["score"]["labels"]), rules[key]["score"]["success"],
                             corrected[("rule", *key)]["corrected_success"], len(r["requests"]), len(r["tool_calls"]),
                             r["seconds"], r["cost_usd_at_list_price"], notes.get(r["case_id"], ""),
                             r["question"].replace("\n", " ")])
    return output


# ---------------------------------------------------------------------------- the A04 retest

def frozen_hashes() -> dict[str, str]:
    return {name: eval_v2.sha256(ROOT / name) for name in FROZEN_FILES}


def original_evidence(client: OpenAICompatibleClient, original: Path, folder: str, output: Path) -> dict[str, Any]:
    """Read the stored A04 responses back from the service: what it really did with the tools. Nothing is billed."""
    rows = [r for r in eval_v2.read_jsonl(original / folder / "runs.jsonl") if r["case_id"] == "A04"]
    found = []
    for row in rows:
        response_id = row["requests"][0].get("response_id")
        record: dict[str, Any] = {"task": "A04", "run": row["repeat"], "response_id": response_id}
        try:
            data = client.stored_response(response_id)
        except LLMError as error:
            record["error"] = str(error)[:200]
        else:
            tools = data.get("tools") or []
            scenario = [t for t in tools if t.get("name") == "create_scenario"]
            record.update(model=data.get("model"), reasoning=data.get("reasoning"), status=data.get("status"),
                          tool_strict={t.get("name"): t.get("strict") for t in tools},
                          create_scenario_parameters=scenario[0].get("parameters") if scenario else None)
        found.append(record)
    evidence = {"note": "Read back from the service with GET /responses/{id}; no model ran and nothing was billed.",
                "read_at": datetime.now(UTC).isoformat(timespec="seconds"), "responses": found}
    output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return evidence


def retest(output: Path = RESULTS / "a04_retest", *, original: Path = ORIGINAL, api_key: str | None = None,
           base_url: str | None = None, execute: bool = False, progress: Callable[[str], None] = print,
           ) -> dict[str, Any]:
    """Run A04 three times with the same model and reasoning settings as the 60 runs, saved on its own."""
    if not execute:
        raise SystemExit("the retest needs --execute; nothing was sent")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    frozen = json.loads(eval_v2.CONFIG.read_text(encoding="utf-8"))
    for key in ("model", "api_style", "reasoning_effort", "reasoning_mode", "service_tier", "max_steps"):
        if config[key] != frozen[key]:
            raise SystemExit(f"the retest must keep {key} of the original run")
    cases = eval_v2.load_cases(config["tasks"])
    gold = json.loads((original / "gold.json").read_text(encoding="utf-8"))
    limits = Limits(config["max_requests"], config["max_total_tokens"], config["max_output_tokens"],
                    config["max_input_tokens"], config["max_usd"], config["meter_prices"]["input"],
                    config["meter_prices"]["output"])
    output.mkdir(parents=True, exist_ok=True)
    meter = Meter(limits, output / "ledger.jsonl")
    earlier = Meter(Limits(frozen["max_requests"], frozen["max_total_tokens"], frozen["max_output_tokens"],
                           frozen["max_input_tokens"], frozen["max_usd"], frozen["meter_prices"]["input"],
                           frozen["meter_prices"]["output"]), original / frozen["result_folder"] / "ledger.jsonl")
    spent_before = earlier.snapshot()["usd"]
    if spent_before + config["max_usd"] > frozen["max_usd"]:
        raise SystemExit(f"the US${frozen['max_usd']} total could be passed: {spent_before} already counted")
    os.environ.update(LLM_API_STYLE=config["api_style"], LLM_REASONING_EFFORT=config["reasoning_effort"],
                      LLM_REASONING_MODE=config["reasoning_mode"], LLM_SERVICE_TIER=config["service_tier"])

    def new_client() -> OpenAICompatibleClient:
        return OpenAICompatibleClient(api_key=api_key, base_url=base_url, model=config["model"],
                                      timeout=config["timeout_seconds"], retries=config["client_retries"],
                                      meters=[meter])
    if new_client().call_kind == "real":
        version = eval_v2.code_version()
        if version["modified_paths"]:
            raise SystemExit(f"refusing a paid run with uncommitted changes: {version['modified_paths']}")
        if json.loads(FREEZE.read_text(encoding="utf-8"))["sha256"] != frozen_hashes():
            raise SystemExit("refusing a paid run: frozen files differ from freeze.json")
    evidence_path = output / "original_response_evidence.json"
    if not evidence_path.exists():
        original_evidence(new_client(), original, frozen["result_folder"], evidence_path)
    runs_path, attempts_path = output / "runs.jsonl", output / "attempts.jsonl"
    done = {(r["case_id"], r["repeat"]) for r in eval_v2.read_jsonl(runs_path)}
    eval_v2.append_jsonl(output / "sessions.jsonl", {
        "label": config["label"], "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code": eval_v2.code_version(), "config": config, "platform": platform.platform(),
        "python": platform.python_version(), "frozen_sha256": frozen_hashes(),
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        "tool_schema_sha256": eval_v2.tool_schema_hash(), "budget_counted_before_usd": spent_before})
    todo = [(c, r) for c in cases for r in range(1, config["repeats"] + 1) if (c["id"], r) not in done]
    stopped = None
    for n, (case, repeat) in enumerate(todo, 1):
        for attempt in range(1, config["run_attempts"] + 1):
            client = new_client()
            row = eval_v2.run_case(case, "graph", repeat, attempt, client, config, output / "memos")
            text = str(row["error"] or "")
            if any(t in text for t in eval_v2.TRANSIENT) and attempt < config["run_attempts"]:
                eval_v2.append_jsonl(attempts_path, row)
                progress(f"[{n}/{len(todo)}] {case['id']} r{repeat} attempt {attempt} failed; again")
                continue
            break
        reason = None
        if client.budget_stop:
            reason = f"budget: {client.budget_stop}"
        elif any(f in text for f in eval_v2.FATAL):
            reason = f"service: {text[:300]}"
        else:
            mismatch = eval_v2.config_mismatch(row["effective"], config)
            if mismatch:
                reason = f"effective configuration differs: {mismatch}"
        if reason:
            eval_v2.append_jsonl(attempts_path, row)
            stopped = {"reason": reason, "at": f"{case['id']} r{repeat}"}
            break
        row["label"] = config["label"]
        row["score"] = score_run(case, row, gold[case["id"]])
        row["cost_usd_at_list_price"] = round(sum(eval_v2.request_cost(q, config["prices"]) for q in row["requests"]
                                                  if "failure" not in q), 6)
        eval_v2.append_jsonl(runs_path, row)
        progress(f"[{n}/{len(todo)}] {case['id']} r{repeat} {'OK  ' if row['score']['success'] else 'FAIL'} "
                 f"{','.join(row['score']['labels']) or '-'} requests={len(row['requests'])} "
                 f"${row['cost_usd_at_list_price']:.3f} {row['seconds']}s")
    report = {"label": config["label"], "stopped": stopped, "runs_saved": len(eval_v2.read_jsonl(runs_path)),
              "finished_at": datetime.now(UTC).isoformat(timespec="seconds"), "meter": meter.snapshot()}
    (output / "last_run.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


def retest_summary(output: Path = RESULTS / "a04_retest") -> dict[str, Any]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    rows = sorted(eval_v2.read_jsonl(output / "runs.jsonl"), key=lambda r: r["repeat"])
    runs = []
    for r in rows:
        built = [d["lanes"] for c in r["tool_calls"] if c["name"] == "create_scenario" and c["ok"]
                 for d in c["result"]["definition"]["disruptions"]]
        answered = [q for q in r["requests"] if "failure" not in q]
        runs.append({"run": r["repeat"], "success": r["score"]["success"], "labels": r["score"]["labels"],
                     "fields": f"{r['score']['param_fields_correct']}/{r['score']['param_fields_total']}",
                     "params_exact": r["score"]["params_exact"], "numbers_found":
                     f"{r['score']['facts_found']}/{r['score']['facts_total']}", "faithful": r["score"]["faithful"],
                     "requests": len(r["requests"]), "tool_calls": [c["name"] for c in r["tool_calls"]],
                     "tool_calls_failed": [str(c["result"].get("error"))[:120] for c in r["tool_calls"] if not c["ok"]],
                     "lanes_built": built, "seconds": r["seconds"], "cost_usd_at_list_price":
                     r["cost_usd_at_list_price"], "effective": r["effective"],
                     "tool_strict": sorted({s for q in answered for s in q.get("tool_strict", [])}),
                     "input_tokens": sum(q.get("input_tokens") or 0 for q in answered),
                     "output_tokens": sum(q.get("output_tokens") or 0 for q in answered),
                     "reasoning_tokens": sum(q.get("reasoning_tokens") or 0 for q in answered)})
    summary = {"label": config["label"], "note": "A development retest of one task after the tool fix. It is not part "
               "of the 60 runs and does not change their result. The other 19 tasks were not rerun.",
               "task": "A04", "runs": runs, "successes": f"{sum(r['success'] for r in runs)}/{len(runs)}",
               "cost_usd_at_list_price": round(sum(r["cost_usd_at_list_price"] for r in runs), 4),
               "budget_limit_usd": config["max_usd"]}
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                         newline="\n")
    with (output / "a04_retest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["task", "run", "success", "labels", "fields", "numbers_found", "requests", "tool_calls",
                         "lanes_built", "seconds", "cost_usd_at_list_price"])
        for r in runs:
            writer.writerow(["A04", r["run"], r["success"], ",".join(r["labels"]), r["fields"], r["numbers_found"],
                             r["requests"], "|".join(r["tool_calls"]), json.dumps(r["lanes_built"]), r["seconds"],
                             r["cost_usd_at_list_price"]])
    return summary


def write_manifest(results: Path = RESULTS) -> Path:
    files = sorted(p for p in results.rglob("*") if p.is_file() and p.name != "manifest.json")
    hashes = {p.relative_to(results).as_posix(): eval_v2.sha256(p) for p in files}
    path = results / "manifest.json"
    path.write_text(json.dumps({"sha256": hashes}, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def verify(results: Path = RESULTS, original: Path = ORIGINAL) -> list[str]:
    """The original results are unchanged, the rescoring reproduces, and the recorded hashes hold."""
    problems = eval_v2.verify(original)
    saved = json.loads((results / "rescore" / "summary.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as folder:
        if rescore(original, Path(folder)) != saved:
            problems.append("rescore/summary.json does not reproduce")
    cases = {c["id"]: c for c in eval_v2.load_cases()}
    gold = json.loads((original / "gold.json").read_text(encoding="utf-8"))
    for row in eval_v2.read_jsonl(results / "a04_retest" / "runs.jsonl"):
        if score_run(cases[row["case_id"]], row, gold[row["case_id"]]) != row["score"]:
            problems.append(f"a04_retest/{row['run_id']}: score differs")
    manifest = results / "manifest.json"
    if manifest.exists():
        for name, digest in json.loads(manifest.read_text(encoding="utf-8"))["sha256"].items():
            path = results / name
            if not path.exists() or eval_v2.sha256(path) != digest:
                problems.append(f"{name}: hash differs")
    return problems


def add_arguments(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("rescore", help="corrected scorer over all saved answers (no model)")
    actions.add_parser("table", help="write the 20 x 3 results table as CSV (no model)")
    actions.add_parser("freeze", help="record hashes of the retest configuration and the code it runs")
    p = actions.add_parser("retest", help="run A04 three times after the tool fix; paid, needs --execute")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--prompt-key", action="store_true", help="ask for the key with hidden input")
    p.add_argument("--base-url", help="another OpenAI-compatible endpoint, e.g. a local test server")
    p.add_argument("--output", type=Path, default=RESULTS / "a04_retest")
    actions.add_parser("summary", help="summarise the saved retest runs (no model)")
    actions.add_parser("manifest", help="record hashes of the follow-up results")
    actions.add_parser("verify", help="recompute the rescoring and check hashes (no model)")


def command(args: argparse.Namespace) -> int:
    if args.action == "rescore":
        summary = rescore()
        print(json.dumps({k: summary[k] for k in ("model", "rule", "new_model_minus_rule", "changed_runs")},
                         indent=2, ensure_ascii=False))
        return 0
    if args.action == "table":
        print(f"wrote {results_table()}")
        return 0
    if args.action == "freeze":
        FREEZE.write_text(json.dumps({"sha256": frozen_hashes(), "tool_schema_sha256": eval_v2.tool_schema_hash()},
                                     indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {FREEZE}")
        return 0
    if args.action == "retest":
        key = eval_v2.read_key() if args.prompt_key else None
        try:
            report = retest(args.output, api_key=key, base_url=args.base_url, execute=args.execute)
        except LLMError as error:
            print(f"not started: {error}")
            return 2
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if report["stopped"] else 0
    if args.action == "summary":
        print(json.dumps(retest_summary(), indent=2, ensure_ascii=False))
        return 0
    if args.action == "manifest":
        print(f"wrote {write_manifest()}")
        return 0
    problems = verify()
    print("\n".join(problems) if problems else "original results, rescoring and hashes reproduce")
    return 1 if problems else 0

