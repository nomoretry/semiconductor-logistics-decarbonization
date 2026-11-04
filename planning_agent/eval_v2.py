"""Evaluation v2: twenty frozen planner tasks, three independent runs each, scored by fixed rules.

The earlier 24-question evaluation (evaluate.py) has been seen and is kept as it is. This package adds new tasks, a
scorer that looks at extracted parameters and missing information, a run identity per task and repeat, and records of
what the service actually did. Twenty tasks repeated three times are twenty distinct questions, not sixty: intervals
come from a bootstrap over tasks.

    python -m planning_agent eval-v2 gold                         # gold numbers from the engine (no model)
    python -m planning_agent eval-v2 run --agent rule             # rule baseline (no model)
    python -m planning_agent eval-v2 run --agent graph --execute  # paid run with the frozen configuration
    python -m planning_agent eval-v2 analyze                      # statistics from the saved runs (no model)
    python -m planning_agent eval-v2 verify                       # re-score saved runs and check hashes (no model)
"""
from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import json
import os
import platform
import random
import re
import subprocess
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, cast

from .agent import SYSTEM_PROMPT, AgentResult
from .evaluate import REFUSAL, Gold, _has_number
from .llm import OpenAICompatibleClient
from .spending import Limits, LLMError, Meter
from .tools import Session

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks" / "planning_agent_v2"
CASES = BENCHMARK / "cases.json"
CONFIG = BENCHMARK / "run_config.json"
FREEZE = BENCHMARK / "freeze.json"
RESULTS = Path("benchmark_results/planning_agent_v2")
NOTICES = ROOT / "benchmarks" / "real_notices_v1" / "test.jsonl"
FROZEN_FILES = ("benchmarks/planning_agent_v2/cases.json", "benchmarks/planning_agent_v2/run_config.json",
                "planning_agent/eval_v2.py", "planning_agent/agent.py", "planning_agent/graph.py",
                "planning_agent/llm.py", "planning_agent/spending.py", "planning_agent/tools.py",
                "planning_agent/guardrails.py", "planning_agent/rules.py", "planning_agent/evaluate.py",
                "network_planning/config.json")
SOLVER_KINDS = ("scenario", "tool")
FIELD_DEFAULTS = {"extra_lead_weeks": 0.0, "capacity_change_pct": 0.0, "cost_change_pct": 0.0, "distance_factor": 1.0}
FIELD_TOLERANCE = {"start_week": 0.0, "end_week": 0.0, "extra_lead_weeks": 0.0, "capacity_change_pct": 1.0,
                   "cost_change_pct": 1.0, "distance_factor": 0.01}
FLAGGED = re.compile(r"假设|假定|默认|未给|没有给|未说明|未提及|没有提到|没说|不变"
                     r"|assum|default|unchanged|not stated|not specified|not given|no information|held constant"
                     r"|kept at",
                     re.IGNORECASE)
WHAT_IF = re.compile(r"假设|假定|如果|若|示意|情景|assum|hypothetical|illustrat|what-if|what if|if we|if the",
                     re.IGNORECASE)
MISSING_SIGNAL = re.compile(r"[?？]|缺|不足|未给|没有给|没给|没说|未说明|未提供|未提及|无法确定|不能确定|无法判断"
                            r"|需要|请提供|请确认"
                            r"|missing|not specif|not state|does not|doesn't|do not|don't|unknown|insufficient|need"
                            r"|please (?:provide|confirm|share)|cannot determine|can't determine", re.IGNORECASE)
MISSING_FAMILIES = {
    "route": re.compile(r"线路|航线|路线|映射|对应|哪条|服务|service|route|lane|mapping|NL_ocean|string|trade",
                        re.IGNORECASE),
    "calendar": re.compile(r"周次|哪几周|哪些周|第几周|时间窗|日期|何时|什么时候|起止|多久"
                           r"|week|when|date|calendar|timing"
                           r"|window|duration", re.IGNORECASE),
    "amount": re.compile(r"幅度|几周|多少|天数|延误|运力|舱位|delay|how much|how many|magnitude|capacity|lead time"
                         r"|lead-time|transit", re.IGNORECASE),
}
TRANSIENT = ("cannot reach", "unreadable reply", "the response failed", "HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503",
             "HTTP 504")
FATAL = ("HTTP 400", "HTTP 401", "HTTP 403", "HTTP 404", "insufficient_quota", "model_not_found", "ledger")


# ---------------------------------------------------------------------------- cases and gold numbers

def load_cases(ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Cases with the notice text filled in; the excerpts stay in the frozen notice dataset."""
    data = json.loads(CASES.read_text(encoding="utf-8"))
    notices = {row["id"]: row for row in (json.loads(line) for line in NOTICES.read_text(encoding="utf-8").splitlines()
                                          if line.strip())}
    wanted = set(ids) if ids else None
    cases = []
    for case in data["cases"]:
        if wanted is not None and case["id"] not in wanted:
            continue
        case = dict(case)
        if case["kind"] == "notice":
            notice = notices[case["notice_id"]]
            case["question"] = data["notice_question"][case["language"]].format(text=notice["model_input"]["text"])
            case["quantities"] = notice["annotation"]["broad_reference"]["quantities"]
            case["reference_status"] = notice["annotation"]["status"]
        cases.append(case)
    return cases


def facts_of(case: dict[str, Any]) -> list[dict[str, Any]]:
    if case["kind"] == "scenario":
        custom: dict[str, Any] = {"disruptions": case["disruptions"]}
        if "demand_change_pct" in case:
            custom.update(demand_change_pct=case["demand_change_pct"], demand_weeks=case["demand_weeks"])
        return [{"kind": "change", "metric": metric, "network": case["network"], "custom": custom}
                for metric in case["metrics"]]
    return cast(list[dict[str, Any]], case.get("facts", []))


class GoldV2(Gold):
    def value(self, fact: dict[str, Any]) -> float:
        if fact["kind"] == "frontier_point":
            result = self.session.call("carbon_frontier", {"network": fact["network"], "levels_pct": fact["levels"]})
            point = next(p for p in result["points"] if p["emission_cap_pct"] == fact["level"])
            return cast(float, point[fact["field"]])
        return super().value(fact)


def gold_numbers(cases: Sequence[dict[str, Any]], progress: Any = None) -> dict[str, list[float]]:
    """Engine numbers for each task, computed without any agent."""
    gold = GoldV2({})
    table = {}
    for case in cases:
        table[case["id"]] = [float(gold.value(fact)) for fact in facts_of(case)]
        if progress:
            progress(f"{case['id']}: {table[case['id']]}")
    return table


# ---------------------------------------------------------------------------- scoring

@cache
def lane_modes(network: str) -> dict[str, str]:
    if network not in ("asml", "marvell"):
        return {}
    return {lane_id: lane.mode for lane_id, lane in Session().network(network).lanes.items()}


def expand(disruptions: Iterable[Any], network: str) -> list[dict[str, Any]]:
    """One item per lane, with every field explicit, in the way create_scenario reads its arguments."""
    items = []
    for raw in disruptions or []:
        if not isinstance(raw, dict):
            continue
        lanes = list(raw.get("lanes") or [])
        mode = raw.get("mode")
        if mode:
            lanes += [lane for lane, m in lane_modes(network).items() if m == mode and lane not in lanes]
        for lane in lanes:
            item = {"lane": lane, "start_week": raw.get("start_week"), "end_week": raw.get("end_week")}
            for key, default in FIELD_DEFAULTS.items():
                value = raw.get(key)
                item[key] = default if value is None else value
            items.append(item)
    return items


def _field_ok(field: str, got: Any, want: Any) -> bool:
    try:
        return abs(float(got) - float(want)) <= FIELD_TOLERANCE[field] + 1e-9
    except (TypeError, ValueError):
        return False


def compare_parameters(case: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Field-level comparison of one create_scenario call with the reference parameters."""
    network = case["network"]
    want = expand(case.get("disruptions", []), network)
    got = expand(arguments.get("disruptions") or [], network) if arguments.get("network") == network else []
    unused = list(got)
    correct = total = 0
    invented = False
    for item in want:
        total += len(FIELD_TOLERANCE)
        candidates = [g for g in unused if g["lane"] == item["lane"]]
        best, best_score = None, -1
        for candidate in candidates:
            hits = sum(_field_ok(f, candidate[f], item[f]) for f in FIELD_TOLERANCE)
            if hits > best_score:
                best, best_score = candidate, hits
        if best is None:
            continue
        unused.remove(best)
        correct += best_score
        for field, default in FIELD_DEFAULTS.items():
            given_default = abs(float(item[field]) - default) < 1e-9
            if given_default and not _field_ok(field, best[field], item[field]):
                invented = True  # a value the notice does not state
    if unused:
        invented = True
    demand_ok = True
    if "demand_change_pct" in case:
        total += 2
        change, weeks = arguments.get("demand_change_pct"), arguments.get("demand_weeks")
        hit_change = change is not None and abs(float(change) - case["demand_change_pct"]) <= 0.5
        hit_weeks = weeks == case["demand_weeks"]
        correct += int(hit_change) + int(hit_weeks)
        demand_ok = hit_change and hit_weeks
    elif arguments.get("demand_change_pct"):
        invented, demand_ok = True, False
    exact = correct == total and not unused and demand_ok
    return {"correct": correct, "total": total, "exact": exact, "invented": invented}


def scenario_executed(calls: Sequence[dict[str, Any]]) -> bool:
    """Did the agent build or solve anything other than the normal plan?"""
    for call in calls:
        if not call["ok"]:
            continue
        if call["name"] in ("create_scenario", "hedge_disruption_risk"):
            return True
        if call["name"] in ("solve_plan", "carbon_frontier") and call["arguments"].get("scenario") not in (
                None, "normal"):
            return True
    return False


def _args_met(case: dict[str, Any], calls: Sequence[dict[str, Any]]) -> bool:
    for tool, expected in case.get("expect_args", {}).items():
        if not any(c["name"] == tool and c["ok"] and _call_matches(expected, c["arguments"]) for c in calls):
            return False
    return True


def _call_matches(expected: dict[str, Any], arguments: dict[str, Any]) -> bool:
    for key, want in expected.items():
        got = arguments.get(key)
        if key == "probabilities" and isinstance(got, list) and len(got) == len(want):
            total = sum(float(x) for x in got) or 1.0
            if any(abs(float(a) / total - float(b) / sum(want)) > 0.005 for a, b in zip(got, want, strict=True)):
                return False
        elif key == "levels_pct":
            if sorted(float(x) for x in got or []) != sorted(float(x) for x in want):
                return False
        elif got != want:
            return False
    return True


def _notice_numbers(case: dict[str, Any]) -> list[float]:
    numbers = []
    for quantity in case.get("quantities", []):
        numbers += [quantity[k] for k in ("value", "minimum", "maximum") if quantity.get(k) is not None]
    return [float(n) for n in numbers]


def score_run(case: dict[str, Any], run: dict[str, Any], gold: Sequence[float]) -> dict[str, Any]:
    """Deterministic score of one saved run. Every rule here was fixed before any agent ran on these tasks."""
    calls, answer, kind = run["tool_calls"], run["answer"] or "", case["kind"]
    names = [c["name"] for c in calls]
    ok_names = {c["name"] for c in calls if c["ok"]}
    error, faithful = run.get("error"), bool(run["guardrail"]["ok"])
    score: dict[str, Any] = {"tool_calls": len(calls), "tool_calls_ok": sum(c["ok"] for c in calls),
                             "faithful": faithful, "error": bool(error), "tool_selection": None, "params_exact": None,
                             "param_fields_correct": None, "param_fields_total": None, "invented_parameter": None,
                             "facts_found": 0, "facts_total": len(gold), "assumption_flagged": None,
                             "states_missing": None, "executed_scenario": scenario_executed(calls),
                             "cites_notice_quantity": None}
    labels: list[str] = []
    if error:
        text = str(error)
        if "limit" in text and "not sent" in text:
            labels.append("budget_limit")
        elif "cannot reach" in text or "timed out" in text:
            labels.append("timeout")
        elif "output stopped at the cap" in text:
            labels.append("output_cap")
        elif text == "max_steps":
            labels.append("max_steps")
        else:
            labels.append("api_error")
    if kind in SOLVER_KINDS:
        selected = set(case["expect_tools"]) <= ok_names and _args_met(case, calls)
        score["tool_selection"] = selected
        asked_back = not (ok_names - {"describe_network"}) and bool(re.search(r"[?？]", answer))
        if asked_back and not error:
            labels.append("unnecessary_clarification")
        elif not selected and not error:
            labels.append("tool_selection_error")
        score["facts_found"] = sum(_has_number(answer, value) for value in gold)
        params_ok = True
        if kind == "scenario":
            created = [compare_parameters(case, c["arguments"]) for c in calls
                       if c["name"] == "create_scenario" and c["ok"]]
            best = max(created, key=lambda c: (c["exact"], c["correct"]), default=None)
            total = len(expand(case["disruptions"], case["network"])) * len(FIELD_TOLERANCE)
            total += 2 if "demand_change_pct" in case else 0
            params_ok = bool(best and best["exact"])
            score.update(params_exact=params_ok, param_fields_correct=best["correct"] if best else 0,
                         param_fields_total=total, invented_parameter=bool(best and best["invented"]))
            if created and not params_ok:
                labels.append("param_error")
            if case.get("must_flag_assumption"):
                score["assumption_flagged"] = bool(FLAGGED.search(answer))
                if not score["assumption_flagged"]:
                    labels.append("assumption_not_flagged")
        if score["facts_found"] < len(gold) and "unnecessary_clarification" not in labels and not error:
            labels.append("gold_number_missing")
        success = selected and params_ok and score["facts_found"] == len(gold) and faithful and not error
        success = success and score["assumption_flagged"] is not False
    elif kind == "refuse":
        refused = not names and any(word in answer.lower() for word in REFUSAL)
        if not refused and not error:
            labels.append("refusal_failed")
        score["tool_selection"] = not names
        success = refused and faithful and not error
    else:  # clarify and notice: nothing in the text makes the task executable
        families = [name for name, pattern in MISSING_FAMILIES.items() if pattern.search(answer)]
        states = bool(MISSING_SIGNAL.search(answer)) and len(families) >= 2
        score["states_missing"] = states
        score["missing_families"] = families
        labelled = bool(WHAT_IF.search(answer))
        honest = states and (not score["executed_scenario"] or labelled)
        score["invented_parameter"] = score["executed_scenario"] and not honest
        if score["executed_scenario"] and not honest and not error:
            labels.append("wrong_assumption")
        elif not states and not error:
            labels.append("missing_info_not_stated")
        numbers = _notice_numbers(case)
        if numbers:
            score["cites_notice_quantity"] = all(_has_number(answer, n) for n in numbers)
        success = honest and faithful and not error
    if not faithful:
        labels.append("unsupported_number")
    score["success"] = bool(success)
    score["labels"] = labels
    return score


def signature(case: dict[str, Any], run: dict[str, Any]) -> str:
    """What a repeat is compared on: which tools worked and which parameters and plans were used, not the wording."""
    parameters = []
    for call in run["tool_calls"]:
        if call["ok"] and call["name"] in ("create_scenario", "hedge_disruption_risk", "carbon_frontier"):
            args = dict(call["arguments"])
            args.pop("name", None)
            args.pop("description", None)
            if args.get("disruptions"):
                args["disruptions"] = sorted(expand(args["disruptions"], args.get("network", "")),
                                             key=lambda d: (d["lane"], str(d["start_week"])))
            parameters.append(args)
        elif call["ok"] and call["name"] == "solve_plan" and call["arguments"].get("scenario") in (
                "red_sea", "air_crunch", "typhoon", "border_congestion", "demand_surge"):
            parameters.append({"preset": call["arguments"]["scenario"],
                               "cap": call["arguments"].get("carbon_cap_pct")})
    return json.dumps({"tools": sorted({c["name"] for c in run["tool_calls"] if c["ok"]}), "parameters": parameters},
                      sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------------------- running

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_hashes() -> dict[str, str]:
    return {name: sha256(ROOT / name) for name in FROZEN_FILES}


def tool_schema_hash() -> str:
    return hashlib.sha256(json.dumps(Session().schemas(), sort_keys=True).encode("utf-8")).hexdigest()


def code_version() -> dict[str, Any]:
    def git(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
        return done.stdout.strip()
    paths = ["planning_agent", "network_planning", "benchmarks/planning_agent_v2"]
    return {"commit": git("rev-parse", "HEAD"),
            "modified_paths": git("status", "--porcelain", "--", *paths).splitlines()}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def effective_config(requests: Sequence[dict[str, Any]]) -> dict[str, list[Any]]:
    answered = [r for r in requests if "failure" not in r]

    def distinct(key: str) -> list[Any]:
        return sorted({r.get(key) for r in answered}, key=str)
    return {"endpoints": distinct("endpoint"), "models": distinct("model"),
            "reasoning_efforts": distinct("reasoning_effort"), "reasoning_modes": distinct("reasoning_mode"),
            "service_tiers": distinct("service_tier")}


def config_mismatch(effective: dict[str, list[Any]], config: dict[str, Any]) -> str | None:
    """What the service reports must be what the protocol fixed; a field it does not report is left as not reported."""
    wanted = {"reasoning_efforts": config["reasoning_effort"], "reasoning_modes": config["reasoning_mode"],
              "service_tiers": config["service_tier"]}
    for key in ("models", *wanted):
        wrong = [v for v in effective[key] if v is not None
                 and not (str(v).startswith(config["model"]) if key == "models" else v == wanted[key])]
        if wrong:
            return f"{key}: {wrong}"
    if any(e != "responses" for e in effective["endpoints"]):
        return f"endpoints: {effective['endpoints']}"
    return None


def request_cost(request: dict[str, Any], prices: dict[str, float]) -> float:
    """Cost of one answered request at the listed prices; the service's invoice is the record of what was charged."""
    total_input = request.get("input_tokens") or 0
    cached = request.get("cached_tokens") or 0
    written = request.get("cache_write_tokens") or 0
    plain = max(total_input - cached - written, 0)
    return (plain * prices["input"] + cached * prices["cached_input"] + written * prices["cache_write"]
            + (request.get("output_tokens") or 0) * prices["output"]) / 1_000_000


def run_case(case: dict[str, Any], agent: str, repeat: int, attempt: int, client: Any, config: dict[str, Any],
             memo_root: Path) -> dict[str, Any]:
    from .graph import run_graph
    from .rules import run_rules
    run_id = f"{case['id']}-r{repeat}-{uuid.uuid4().hex[:8]}"
    session = Session(memo_dir=memo_root / run_id, **config["session"])  # no state carries over between runs
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    result: AgentResult = (run_rules(case["question"], session) if agent == "rule"
                           else run_graph(case["question"], session, client, max_steps=config["max_steps"]))
    requests = list(getattr(client, "request_log", []))
    return {"run_id": run_id, "case_id": case["id"], "group": case["group"], "kind": case["kind"], "repeat": repeat,
            "attempt": attempt, "agent": agent, "started_at": started_at, "seconds": result.seconds,
            "question": case["question"], "answer": result.answer, "error": result.error, "steps": result.steps,
            "tool_calls": [{"name": c["name"], "arguments": c["arguments"], "ok": c["ok"], "seconds": c["seconds"],
                            "result": c["result"]} for c in result.tool_calls],
            "guardrail": result.guardrail, "requests": requests, "effective": effective_config(requests),
            "usage": getattr(client, "usage", {}), "call_kind": getattr(client, "call_kind", "none")}


def run_evaluation(agent: str, output: Path, *, repeats: int | None = None, ids: Iterable[str] | None = None,
                   api_key: str | None = None, base_url: str | None = None, execute: bool = False,
                   progress: Any = print) -> dict[str, Any]:
    """Run every task and repeat not yet saved. Saved rows are final; an interrupted run continues where it stopped."""
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    cases = load_cases(ids)
    gold_path = output.parent / "gold.json"
    gold = json.loads(gold_path.read_text(encoding="utf-8")) if gold_path.exists() else None
    if gold is None:
        raise SystemExit(f"{gold_path} is missing: run `eval-v2 gold` first")
    meter = None
    make_client: Callable[[], OpenAICompatibleClient] | None = None
    limits = Limits(config["max_requests"], config["max_total_tokens"], config["max_output_tokens"],
                    config["max_input_tokens"], config["max_usd"], config["meter_prices"]["input"],
                    config["meter_prices"]["output"])
    if agent != "rule":
        if not execute:
            raise SystemExit("a model run needs --execute; nothing was sent")
        output.mkdir(parents=True, exist_ok=True)
        meter = Meter(limits, output / "ledger.jsonl")
        os.environ.update(LLM_API_STYLE=config["api_style"], LLM_REASONING_EFFORT=config["reasoning_effort"],
                          LLM_REASONING_MODE=config["reasoning_mode"], LLM_SERVICE_TIER=config["service_tier"])

        def new_client(meters: list[Meter] = [meter]) -> OpenAICompatibleClient:  # noqa: B006
            return OpenAICompatibleClient(api_key=api_key, base_url=base_url, model=config["model"],
                                          timeout=config["timeout_seconds"], retries=config["client_retries"],
                                          meters=meters)
        make_client = new_client  # a new client per run: no reasoning items carry over
        if make_client().call_kind == "real":
            version = code_version()
            if version["modified_paths"]:
                raise SystemExit(f"refusing a paid run with uncommitted changes: {version['modified_paths']}")
            frozen = json.loads(FREEZE.read_text(encoding="utf-8"))["sha256"]
            if frozen != frozen_hashes():
                raise SystemExit("refusing a paid run: frozen files differ from freeze.json")
    output.mkdir(parents=True, exist_ok=True)
    runs_path, attempts_path = output / "runs.jsonl", output / "attempts.jsonl"
    done = {(r["case_id"], r["repeat"]) for r in read_jsonl(runs_path)}
    manifest = {"agent": agent, "started_at": datetime.now(UTC).isoformat(timespec="seconds"), "code": code_version(),
                "config": config if agent != "rule" else {"session": config["session"]},
                "platform": platform.platform(), "python": platform.python_version(),
                "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
                "tool_schema_sha256": tool_schema_hash(), "frozen_sha256": frozen_hashes()}
    append_jsonl(output / "sessions.jsonl", manifest)
    repeats = repeats or config["repeats"]
    todo = [(c, r) for c in cases for r in range(1, repeats + 1) if (c["id"], r) not in done]
    spent = sum(request_cost(q, config["prices"]) for r in [*read_jsonl(attempts_path), *read_jsonl(runs_path)]
                for q in r["requests"] if "failure" not in q)
    stopped = None
    for n, (case, repeat) in enumerate(todo, 1):
        for attempt in range(1, config["run_attempts"] + 1):
            client = make_client() if make_client else None
            row = run_case(case, agent, repeat, attempt, client, config, output / "memos")
            cost = sum(request_cost(q, config["prices"]) for q in row["requests"] if "failure" not in q)
            spent += cost
            text = str(row["error"] or "")
            transient = any(t in text for t in TRANSIENT) and "insufficient_quota" not in text
            if transient and attempt < config["run_attempts"]:
                append_jsonl(attempts_path, row)
                progress(f"[{n}/{len(todo)}] {case['id']} r{repeat} attempt {attempt} failed ({text[:80]}); again")
                continue
            break
        stop_reason = None
        if client is not None and client.budget_stop:
            stop_reason = f"budget: {client.budget_stop}"
        elif any(f in text for f in FATAL):
            stop_reason = f"service: {text[:300]}"
        elif client is not None:
            mismatch = config_mismatch(row["effective"], config)
            if mismatch:
                stop_reason = f"effective configuration differs from the protocol: {mismatch}"
        if stop_reason:
            append_jsonl(attempts_path, row)  # counted in cost, not scored
            stopped = {"reason": stop_reason, "at": f"{case['id']} r{repeat}", "completed": n - 1,
                       "remaining": len(todo) - n + 1}
            break
        row["score"] = score_run(case, row, gold[case["id"]])
        row["cost_usd_at_list_price"] = round(cost, 6)
        append_jsonl(runs_path, row)
        progress(f"[{n}/{len(todo)}] {case['id']} r{repeat} {'OK  ' if row['score']['success'] else 'FAIL'} "
                 f"{','.join(row['score']['labels']) or '-'} requests={len(row['requests'])} ${cost:.3f} "
                 f"total=${spent:.2f} {row['seconds']}s")
    report = {"finished_at": datetime.now(UTC).isoformat(timespec="seconds"), "stopped": stopped,
              "runs_saved": len(read_jsonl(runs_path)), "cost_usd_at_list_price": round(spent, 4),
              "meter": meter.snapshot() if meter else None}
    (output / "last_run.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                          newline="\n")
    return report


# ---------------------------------------------------------------------------- statistics

def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def by_case(rows: Sequence[dict[str, Any]], value: Any) -> dict[str, float]:
    """Mean of a per-run value within each task; runs where the value does not apply are left out."""
    groups: dict[str, list[float]] = {}
    for row in rows:
        v = value(row)
        if v is not None:
            groups.setdefault(row["case_id"], []).append(float(v))
    return {case: sum(values) / len(values) for case, values in groups.items()}


def bootstrap(per_case: dict[str, float], other: dict[str, float] | None = None, *, rounds: int = 10_000,
              seed: int = 20261104) -> dict[str, Any]:
    """Percentile interval from resampling tasks, so that repeats of one task are not treated as independent."""
    keys = sorted(per_case if other is None else set(per_case) & set(other))
    if not keys:
        return {"estimate": None, "ci95": None, "tasks": 0}
    values = [per_case[k] - (other[k] if other else 0.0) for k in keys]
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(rounds))
    return {"estimate": round(sum(values) / len(values), 4),
            "ci95": [round(means[int(0.025 * rounds)], 4), round(means[int(0.975 * rounds) - 1], 4)],
            "tasks": len(keys), "unit": "task"}


METRICS = {
    "task_success": lambda r: r["score"]["success"],
    "tool_selection": lambda r: r["score"]["tool_selection"],
    "tool_call_ok": lambda r: (r["score"]["tool_calls_ok"] / r["score"]["tool_calls"])
    if r["score"]["tool_calls"] else None,
    "params_exact": lambda r: r["score"]["params_exact"],
    "param_field_accuracy": lambda r: (r["score"]["param_fields_correct"] / r["score"]["param_fields_total"])
    if r["score"]["param_fields_total"] else None,
    "states_missing": lambda r: r["score"]["states_missing"],
    "invented_parameter": lambda r: r["score"]["invented_parameter"],
    "gold_numbers_found": lambda r: (r["score"]["facts_found"] / r["score"]["facts_total"])
    if r["score"]["facts_total"] else None,
    "numeric_faithfulness": lambda r: r["score"]["faithful"],
    "assumption_flagged": lambda r: r["score"]["assumption_flagged"],
    "cites_notice_quantity": lambda r: r["score"]["cites_notice_quantity"],
}


def metric_table(rows: Sequence[dict[str, Any]], other: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    table = {}
    for name, value in METRICS.items():
        mine = by_case(rows, value)
        entry = bootstrap(mine)
        if other:
            theirs = by_case(other, value)
            entry = {"model": entry, "rule": bootstrap(theirs), "model_minus_rule": bootstrap(mine, theirs)}
        table[name] = entry
    return table


def resources(rows: Sequence[dict[str, Any]], attempts: Sequence[dict[str, Any]], prices: dict[str, float],
              meter: dict[str, Any] | None) -> dict[str, Any]:
    everything = [*rows, *attempts]
    answered = [q for r in everything for q in r["requests"] if "failure" not in q]
    failed = [q for r in everything for q in r["requests"] if "failure" in q]
    seconds = sorted(r["seconds"] for r in rows)
    cost_per_run = sorted(r.get("cost_usd_at_list_price", 0.0) for r in rows)

    def quantile(values: Sequence[float], q: float) -> float | None:
        return values[min(int(q * len(values)), len(values) - 1)] if values else None
    return {"runs_scored": len(rows), "attempts_not_scored": len(attempts), "requests_answered": len(answered),
            "requests_failed": len(failed), "failure_types": dict(Counter(q["failure"] for q in failed)),
            "input_tokens": sum(q.get("input_tokens") or 0 for q in answered),
            "cached_input_tokens": sum(q.get("cached_tokens") or 0 for q in answered),
            "cache_write_tokens": sum(q.get("cache_write_tokens") or 0 for q in answered),
            "output_tokens": sum(q.get("output_tokens") or 0 for q in answered),
            "reasoning_tokens": sum(q.get("reasoning_tokens") or 0 for q in answered),
            "cost_usd_at_list_price": round(sum(request_cost(q, prices) for q in answered), 4),
            "cost_per_run_usd": {"median": quantile(cost_per_run, 0.5), "p90": quantile(cost_per_run, 0.9),
                                 "max": cost_per_run[-1] if cost_per_run else None},
            "seconds_per_run": {"median": quantile(seconds, 0.5), "p90": quantile(seconds, 0.9),
                                "max": seconds[-1] if seconds else None, "total": round(sum(seconds), 1)},
            "request_seconds_total": round(sum(q.get("seconds") or 0 for q in [*answered, *failed]), 1),
            "effective": effective_config(answered), "meter": meter}


def stability(rows: Sequence[dict[str, Any]], cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["case_id"], []).append(row)
    per_case = {}
    for case_id, runs in groups.items():
        runs = sorted(runs, key=lambda r: r["repeat"])
        signatures = [signature(cases[case_id], r) for r in runs]
        per_case[case_id] = {"successes": [bool(r["score"]["success"]) for r in runs],
                             "same_outcome": len({r["score"]["success"] for r in runs}) == 1,
                             "distinct_signatures": len(set(signatures))}
    return {"tasks": len(per_case),
            "tasks_with_same_outcome_every_run": sum(v["same_outcome"] for v in per_case.values()),
            "tasks_with_identical_tools_and_parameters": sum(v["distinct_signatures"] == 1 for v in per_case.values()),
            "per_case": per_case}


def analyze(rule_dir: Path, model_dir: Path, output: Path) -> dict[str, Any]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in load_cases()}
    rule, model = read_jsonl(rule_dir / "runs.jsonl"), read_jsonl(model_dir / "runs.jsonl")
    attempts = read_jsonl(model_dir / "attempts.jsonl")
    ledger = Meter(Limits(config["max_requests"], config["max_total_tokens"], config["max_output_tokens"],
                          config["max_input_tokens"], config["max_usd"], config["meter_prices"]["input"],
                          config["meter_prices"]["output"]), model_dir / "ledger.jsonl").snapshot()
    groups = {}
    for name in ("A", "B", "C"):
        groups[name] = metric_table([r for r in model if r["group"] == name], [r for r in rule if r["group"] == name])
    per_case = []
    for case_id in cases:
        mine = sorted((r for r in model if r["case_id"] == case_id), key=lambda r: r["repeat"])
        base = sorted((r for r in rule if r["case_id"] == case_id), key=lambda r: r["repeat"])
        per_case.append({
            "case": case_id, "group": cases[case_id]["group"], "kind": cases[case_id]["kind"],
            "model_successes": [bool(r["score"]["success"]) for r in mine],
            "model_labels": [r["score"]["labels"] for r in mine],
            "rule_successes": [bool(r["score"]["success"]) for r in base],
            "rule_labels": base[0]["score"]["labels"] if base else [],
            "model_seconds": [r["seconds"] for r in mine],
            "model_cost_usd": [r.get("cost_usd_at_list_price") for r in mine],
            "model_requests": [len(r["requests"]) for r in mine]})
    wins = {"model_better": 0, "rule_better": 0, "tied": 0}
    for row in per_case:
        a = _mean([float(x) for x in row["model_successes"]]) or 0.0
        b = _mean([float(x) for x in row["rule_successes"]]) or 0.0
        wins["model_better" if a > b else "rule_better" if b > a else "tied"] += 1
    labels = {"model": Counter(x for r in model for x in r["score"]["labels"]),
              "rule": Counter(x for r in rule for x in r["score"]["labels"])}
    report = {"method": "Means are over tasks after averaging repeats within each task; intervals are percentile "
                        "bootstraps over tasks (10,000 resamples), so repeats of a task are not treated as "
                        "independent.",
              "authorship": "Tasks written by the project author; not an independent evaluation.",
              "tasks": len(cases), "runs": {"model": len(model), "rule": len(rule)},
              "overall": metric_table(model, rule), "groups": groups,
              "task_level_comparison": wins, "failure_labels": {k: dict(v) for k, v in labels.items()},
              "stability": {"model": stability(model, cases), "rule": stability(rule, cases)},
              "resources": {"model": resources(model, attempts, config["prices"], ledger)},
              "per_case": per_case}
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                         newline="\n")
    with (output / "per_case.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["case", "group", "kind", "model_r1", "model_r2", "model_r3", "rule", "model_failures",
                         "rule_failures", "model_seconds", "model_cost_usd"])
        for row in per_case:
            runs = [*row["model_successes"], None, None, None][:3]
            writer.writerow([row["case"], row["group"], row["kind"], *runs,
                             row["rule_successes"][0] if row["rule_successes"] else None,
                             "|".join(",".join(x) or "-" for x in row["model_labels"]), ",".join(row["rule_labels"]),
                             "|".join(str(x) for x in row["model_seconds"]),
                             "|".join(str(x) for x in row["model_cost_usd"])])
    return report


def verify(output: Path = RESULTS) -> list[str]:
    """Re-score every saved run with the current scorer and check the recorded file hashes. No model, no solver."""
    problems = []
    cases = {c["id"]: c for c in load_cases()}
    gold = json.loads((output / "gold.json").read_text(encoding="utf-8"))
    for folder in sorted(p for p in output.iterdir() if p.is_dir()):
        for row in read_jsonl(folder / "runs.jsonl"):
            if score_run(cases[row["case_id"]], row, gold[row["case_id"]]) != row["score"]:
                problems.append(f"{folder.name}/{row['run_id']}: score differs")
    manifest = output / "manifest.json"
    if manifest.exists():
        for name, digest in json.loads(manifest.read_text(encoding="utf-8"))["sha256"].items():
            path = output / name
            if not path.exists() or sha256(path) != digest:
                problems.append(f"{name}: hash differs")
    return problems


def write_manifest(output: Path = RESULTS) -> Path:
    files = sorted(p for p in output.rglob("*") if p.is_file() and p.name != "manifest.json")
    path = output / "manifest.json"
    hashes = {p.relative_to(output).as_posix(): sha256(p) for p in files}
    path.write_text(json.dumps({"sha256": hashes}, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


# ---------------------------------------------------------------------------- command line

def add_arguments(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("freeze", help="record hashes of the tasks, configuration, scorer and agent code")
    p = actions.add_parser("gold", help="compute gold numbers with the engine (no agent, no model)")
    p.add_argument("--output", type=Path, default=RESULTS)
    p = actions.add_parser("run", help="run the tasks; a model run needs --execute")
    p.add_argument("--agent", choices=("rule", "graph"), required=True)
    p.add_argument("--output", type=Path)
    p.add_argument("--repeats", type=int)
    p.add_argument("--ids", help="comma-separated task ids")
    p.add_argument("--execute", action="store_true", help="really send requests, within the frozen limits")
    p.add_argument("--prompt-key", action="store_true", help="ask for the key with hidden input instead of LLM_API_KEY")
    p.add_argument("--base-url", help="another OpenAI-compatible endpoint, e.g. a local test server")
    p = actions.add_parser("analyze", help="statistics from saved runs (no model)")
    p.add_argument("--output", type=Path, default=RESULTS)
    p = actions.add_parser("verify", help="re-score saved runs and check hashes (no model)")
    p.add_argument("--output", type=Path, default=RESULTS)
    p = actions.add_parser("manifest", help="record hashes of the saved results")
    p.add_argument("--output", type=Path, default=RESULTS)


def command(args: argparse.Namespace) -> int:
    if args.action == "freeze":
        prompt = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
        FREEZE.write_text(json.dumps({"sha256": frozen_hashes(), "tool_schema_sha256": tool_schema_hash(),
                                      "system_prompt_sha256": prompt}, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {FREEZE}")
        return 0
    if args.action == "gold":
        table = gold_numbers(load_cases(), print)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "gold.json").write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8", newline="\n")
        return 0
    if args.action == "run":
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        output = args.output or RESULTS / ("rule" if args.agent == "rule" else config["result_folder"])
        ids = [i.strip() for i in args.ids.split(",") if i.strip()] if args.ids else None
        key = getpass.getpass("LLM_API_KEY (input stays hidden): ").strip() if args.prompt_key else None
        try:
            report = run_evaluation(args.agent, output, repeats=args.repeats, ids=ids, api_key=key,
                                    base_url=args.base_url, execute=args.execute)
        except LLMError as error:
            print(f"not started: {error}")
            return 2
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if report["stopped"] else 0
    if args.action == "analyze":
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        report = analyze(args.output / "rule", args.output / config["result_folder"], args.output / "analysis")
        keys = ("tasks", "runs", "task_level_comparison", "failure_labels")
        print(json.dumps({k: report[k] for k in keys}, indent=2))
        return 0
    if args.action == "manifest":
        print(f"wrote {write_manifest(args.output)}")
        return 0
    problems = verify(args.output)
    print("\n".join(problems) if problems else "saved scores and hashes reproduce")
    return 1 if problems else 0
