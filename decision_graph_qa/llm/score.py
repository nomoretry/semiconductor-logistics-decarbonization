"""Score frozen model requests using the decision graph's offline evaluators."""

from __future__ import annotations

import gzip
import platform
import statistics
import time
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from rolling_inventory.planning import base_stock

from ..consequence import Consequences, ContinuationFailure, replay_trajectory
from ..dataset import records, trajectories, write
from ..eval_run import _read_attempts
from ..eval_statistics import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    bootstrap_clusters,
    summarize_baselines,
)
from ..evaluation import rule_answers
from ..planner import AuditFailure, Record, SolveFailure, original, scenarios, tolerance
from ..scoring import grade_graph
from .data import (
    TERMINAL,
    LlmError,
    Task,
    canonical,
    digest,
    load_config,
    plan,
    read_jsonl,
    records_for_tasks,
    response_path,
    root_lock,
    verified_manifest,
    verify_file,
)

RATES = ("accuracy", "violation", "truncated", "parse_failure")
OUTCOMES = ("plan_excess", "cost_delta", "fill_rate_delta_pp", "emissions_delta")
PAIRINGS = (("Chain", "None"), ("Graph", "None"), ("Graph", "Chain"))
IDENTITY = ("id", "split", "profile", "seed", "policy", "objective")
USAGE = ("input_tokens", "cached_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens")


def _source(config: Record, source: str, filename: str) -> Path:
    directory, filenames = verified_manifest(config, source)
    return verify_file(directory, filenames, filename)


def _load_graphs(config: Record) -> list[Record]:
    return list(records(_source(config, "dataset", "test.jsonl")))


def _replay(graphs: list[Record], selected: set[str]):
    histories = defaultdict(list)
    for graph in graphs:
        histories[graph["split"], graph["profile"], graph["seed"], graph["policy"]].append(graph)
    for task, policy in trajectories(False):
        history = histories.get((task["split"], task["profile"], task["seed"], policy), ())
        if not any(graph["id"] in selected for graph in history):
            continue
        for graph, env in replay_trajectory(task, policy, history):
            if graph["id"] in selected:
                yield graph, env


def _effects(compare: Consequences, b: object) -> tuple[Record | None, Record | None]:
    try:
        return compare.compare(b), None
    except ContinuationFailure as exc:
        return None, {"type": type(exc).__name__, "message": str(exc), "evidence": exc.evidence}


def score_answers(graph: Record, answers: Record, compare: Consequences, counts: Counter) -> Record:
    """Score only submitted answers and execute only an adjudicated feasible B."""
    try:
        grades = grade_graph(graph, answers, counts) if answers else []
    except AuditFailure:
        raise
    except SolveFailure as exc:
        return {"nodes": {}, "consequence": None, "error": {"type": type(exc).__name__, "message": str(exc)}}
    nodes = {node["id"]: node for node in grades if node["provided"]}
    dispatch = nodes.get("B")
    if dispatch is None or dispatch["violation"]:
        return {"nodes": nodes, "consequence": None, "error": None}
    consequence, error = _effects(compare, answers["B"])
    if consequence is not None and consequence["status"] != "ok":
        raise LlmError(f"{graph['id']}: planned and realized feasibility disagree")
    return {"nodes": nodes, "consequence": consequence, "error": error}


def _question_metrics(response: Record | None, grade: Record | None) -> Record:
    status = response["status"] if response else None
    terminal = status in TERMINAL
    return {
        "accuracy": int(grade["correct"]) if grade is not None else (0 if terminal and status != "ok" else None),
        "violation": int(grade["violation"]) if grade is not None else None,
        "truncated": int(status == "truncated") if terminal else None,
        "parse_failure": int(status == "parse_failure") if terminal else None,
    }


def _outcomes(judgment: Record) -> Record:
    delta = (judgment["consequence"] or {}).get("delta") or {}
    fill = delta.get("fill_rate")
    return {
        "plan_excess": judgment["nodes"].get("B", {}).get("excess"),
        "cost_delta": delta.get("cost"),
        "fill_rate_delta_pp": 100 * fill if fill is not None else None,
        "emissions_delta": delta.get("emissions"),
    }


def _mean(values) -> float | None:
    observed = [value for value in values if value is not None]
    return statistics.mean(observed) if observed else None


def _row(graph: Record, context: str, responses: dict[str, Record | None], judgment: Record,
         fallback: Record | None) -> Record:
    judgments = judgment["nodes"]
    questions = {question: _question_metrics(response, judgments.get(question))
                 for question, response in responses.items()}
    return {
        **{key: graph[key] for key in IDENTITY}, "context": context,
        "responses": responses, "questions": questions, **judgment, "fallback": fallback,
        "metrics": {metric: _mean(question[metric] for question in questions.values()) for metric in RATES}
        | _outcomes(judgment),
        "fallback_metrics": _outcomes(fallback if fallback is not None else judgment),
    }


def _judge(graphs: list[Record], jobs: dict[str, tuple[list[Task], dict[str, Record]]], contexts: list[str]) -> dict:
    grouped = defaultdict(lambda: defaultdict(dict))
    for arm, (tasks, response_rows) in jobs.items():
        for task in tasks:
            grouped[task.graph][arm].setdefault(task.context, {})[task.question] = response_rows.get(task.custom_id)
    output = {arm: {context: [] for context in contexts} for arm in jobs}
    counts: Counter = Counter()
    seen = set()
    for graph, env in _replay(graphs, set(grouped)):
        seen.add(graph["id"])
        compare = Consequences(env, graph, counts)
        for arm, row in _judge_graph(graph, grouped[graph["id"]], compare, counts):
            output[arm][row["context"]].append(row)
    if seen != set(grouped):
        raise LlmError("frozen trajectory replay missed planned graphs")
    return output


def _judge_graph(graph: Record, by_arm: dict, compare: Consequences, counts: Counter):
    cache: dict[bytes, Record] = {}

    def judge(answers: Record) -> Record:
        signature = canonical(answers)
        if signature not in cache:
            cache[signature] = score_answers(graph, answers, compare, counts)
        return cache[signature]

    for arm, by_context in by_arm.items():
        for context, responses in by_context.items():
            answers = {question: reply["parsed"] for question, reply in responses.items()
                       if reply is not None and reply["status"] == "ok"}
            judgment = judge(answers)
            b = responses.get("B")
            fallback = judge({"B": rule_answers(graph)["B"]}) if b is not None and b["status"] != "ok" else None
            yield arm, {**_row(graph, context, responses, judgment, fallback), "answers": answers}


def _bootstrap(rows: list[Record], metrics: tuple[str, ...], *, field: str = "metrics") -> Record:
    return bootstrap_clusters([{**{key: row[key] for key in ("split", "profile", "seed")}, **row[field]}
                               for row in rows], metrics)


def _difference(left: float | None, right: float | None) -> float | None:
    return left - right if left is not None and right is not None else None


def _question_differences(left: Record, right: Record, metrics: tuple[str, ...],
                          question: str | None = None) -> Record:
    common = left["questions"].keys() & right["questions"].keys()
    if question is not None:
        common &= {question}
    return {metric: _mean(_difference(left["questions"][key][metric], right["questions"][key][metric])
                          for key in sorted(common)) for metric in metrics}


def _paired(left: list[Record], right: list[Record], phase: str) -> Record:
    right_by_id = {row["id"]: row for row in right}
    pairs = [(row, right_by_id[row["id"]]) for row in left if row["id"] in right_by_id]
    evidence = []
    for lrow, rrow in pairs:
        outcome = {metric: _difference(lrow["metrics"][metric], rrow["metrics"][metric]) for metric in OUTCOMES}
        fallback = {metric: _difference(lrow["fallback_metrics"][metric], rrow["fallback_metrics"][metric])
                    for metric in OUTCOMES}
        evidence.append({**{key: lrow[key] for key in ("split", "profile", "seed")},
                         "metrics": _question_differences(lrow, rrow, RATES) | outcome,
                         "fallback_metrics": fallback})
    if phase != "p3":
        return {"primary": _bootstrap(evidence, RATES + OUTCOMES),
                "fallback": _bootstrap(evidence, OUTCOMES, field="fallback_metrics")}
    questions = sorted({key for row in left + right for key in row["questions"]})
    per_question = {question: bootstrap_clusters([
        {**{key: lrow[key] for key in ("split", "profile", "seed")},
         **_question_differences(lrow, rrow, RATES, question)} for lrow, rrow in pairs
    ], RATES) for question in questions}
    return {"primary": _bootstrap(evidence, RATES), "per_question": per_question}


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = 0.95 * (len(ordered) - 1)
    lo = int(index)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (index - lo) * (ordered[hi] - ordered[lo])


def _compute(responses: list[Record], *, dispatch: bool) -> Record:
    seconds = [reply["seconds"] for reply in responses if reply["seconds"] is not None]
    charges = [Decimal(reply["charged_usd"]) for reply in responses if reply["charged_usd"] is not None]
    known = [Decimal(reply["actual_usd"]) for reply in responses if reply["actual_usd"] is not None]
    attempts = sum(reply["attempts"] for reply in responses)
    costed_attempts = sum(reply["attempts"] for reply in responses if reply["charged_usd"] is not None)
    charged = sum(charges, Decimal(0))
    return {
        "responses": len(responses), "attempts": attempts, "costed_attempts": costed_attempts,
        "known_usage_responses": len(known), "charged_responses": len(charges), "timed_responses": len(seconds),
        "total_charged_usd": float(charged), "total_reported_usage_usd": float(sum(known)),
        "total_above_reported_usage_usd": float(charged - sum(known)),
        "mean_usd_per_call": float(charged / costed_attempts) if costed_attempts else None,
        "mean_usd_per_b_decision": float(charged / len(charges)) if charges and dispatch else None,
        "mean_seconds": _mean(seconds), "p95_seconds": _p95(seconds),
        "mean_tokens": {key: _mean(reply["usage"][key] for reply in responses if reply["usage"] is not None)
                        for key in USAGE},
    }


def _responses(rows: list[Record]) -> list[Record]:
    return [reply for row in rows for reply in row["responses"].values() if reply is not None]


def _journal_costs(tasks: list[Task], events: list[Record], *, dispatch: bool) -> Record:
    keys = {(task.phase, task.custom_id, task.request_hash) for task in tasks}
    if dispatch:
        keys.update(("pilot", task.custom_id, task.request_hash) for task in tasks if task.phase == "main")
    pending: dict[str, Decimal] = {}
    settled = 0
    keys_charged = set()
    total = known = Decimal(0)
    for event in events:
        key = event.get("phase"), event.get("task_key"), event.get("request_hash")
        if key not in keys:
            continue
        attempt = event["attempt_id"]
        if event["event"] == "reserve":
            pending[attempt] = Decimal(event["reserved_usd"])
        elif event["event"] == "settle":
            pending.pop(attempt, None)
            settled += 1
            keys_charged.add(key[1])
            total += Decimal(event["charged_usd"])
            if event.get("actual_usd") is not None:
                known += Decimal(event["actual_usd"])
    return {
        "settled_attempts": settled, "open_reservations": len(pending), "decisions_with_settlements": len(keys_charged),
        "settled_usd": float(total), "settled_usage_usd": float(known), "open_reserved_usd": float(sum(pending.values())),
        "mean_settled_usd_per_call": float(total / settled) if settled else None,
        "mean_settled_usd_per_b_decision": float(total / len(keys_charged)) if keys_charged and dispatch else None,
    }


def _context(rows: list[Record], phase: str) -> Record:
    statuses = Counter(reply["status"] if reply is not None else "unattempted"
                       for row in rows for reply in row["responses"].values())
    responses = _responses(rows)
    result = {"statuses": dict(statuses), "scoring_errors": sum(row["error"] is not None for row in rows),
              "primary": _bootstrap(rows, RATES if phase == "p3" else RATES + OUTCOMES),
              "compute": _compute(responses, dispatch=phase != "p3")}
    if phase == "p3":
        questions = sorted({key for row in rows for key in row["questions"]})
        result["per_question"] = {question: bootstrap_clusters([
            {**{key: row[key] for key in ("split", "profile", "seed")}, **row["questions"][question]}
            for row in rows if question in row["questions"]
        ], RATES) for question in questions}
    else:
        result.update(fallback=_bootstrap(rows, OUTCOMES, field="fallback_metrics"),
                      fallback_count=sum(row["fallback"] is not None for row in rows),
                      fallback_errors=sum(row["fallback"] is not None and row["fallback"]["error"] is not None
                                          for row in rows),
                      violations=sum(row["metrics"]["violation"] == 1 for row in rows),
                      without_consequence=sum(row["consequence"] is None for row in rows))
    return result


def _baseline_summaries(config: Record, graph_ids: set[str], periods: int) -> Record:
    attempts = _source(config, "evaluation", "attempts.jsonl.gz")
    rows = []
    for row in _read_attempts(attempts.parent, periods):
        if row["id"] in graph_ids:
            baselines = {name: {"None": {"gold": row["baselines"][name]["None"]["gold"]}}
                         for name in ("gold", "rule")}
            rows.append({"objective": row["objective"], "baselines": baselines})
    if len(rows) != len(graph_ids):
        raise LlmError("DQ-2 evidence does not cover the registered graph scope")
    result = {name: modes["None"]["gold"] for name, modes in summarize_baselines(rows).items()}
    for entry in result.values():
        fill = entry["B"]["metrics"].pop("fill_rate_delta")
        if fill["mean"] is not None:
            fill["mean"] *= 100
        entry["B"]["metrics"]["fill_rate_delta_pp"] = fill
    return result


def _timings(config: Record, graphs: list[Record], arm: str) -> Record:
    pilot_ids = {task.graph for task in plan(config, "pilot", arm)}
    counts: Counter = Counter()
    cases = []
    for graph in graphs:
        if graph["id"] not in pilot_ids:
            continue
        obs = graph["observation"]
        started = time.perf_counter()
        schedule, value = original(obs, scenarios(obs), counts, "reference")
        reference_seconds = time.perf_counter() - started
        if not schedule or abs(value - graph["objective"]) > tolerance(graph["objective"]):
            raise LlmError(f"{graph['id']}: reference timing objective differs from frozen value")
        started = time.perf_counter()
        base_stock(obs, 1.0)
        cases.append({"id": graph["id"], "reference_seconds": reference_seconds,
                      "rule_seconds": time.perf_counter() - started})
    return {"machine": platform.platform(), "python": platform.python_version(), "cases": cases,
            "reference_median_seconds": statistics.median(case["reference_seconds"] for case in cases),
            "rule_median_seconds": statistics.median(case["rule_seconds"] for case in cases)}


def _arm_comparison(evidence: dict) -> Record:
    comparisons = {}
    for context in evidence["S"]:
        right = {row["id"]: row for row in evidence["S"][context] if row["responses"]["B"] is not None}
        left = {row["id"]: row for row in evidence["A"][context] if row["responses"]["B"] is not None}
        shared = sorted(left.keys() & right.keys())
        if shared:
            pairs = {"A": [left[key] for key in shared], "S": [right[key] for key in shared]}
            comparisons[context] = {"difference": _paired(pairs["A"], pairs["S"], "main"),
                                    "compute": {arm: _compute(_responses(rows), dispatch=True)
                                                for arm, rows in pairs.items()}}
    return comparisons


def _number(value: float | None) -> str:
    return "—" if value is None else f"{value:.6g}"


def _metric_table(metrics: Record) -> list[str]:
    return [f"| {metric} | {result['n']} | {_number(result['mean'])} | {_number(result['lower'])} | "
            f"{_number(result['upper'])} |" for metric, result in metrics.items()]


def _report(result: Record) -> str:
    lines = ["# 决策图模型评测 / Decision graph model evaluation", "",
             "本文先中文、后英文。Chinese precedes English.", ""]
    for chinese in (True, False):
        lines += ["## 中文" if chinese else "## English", "",
                  (f"`{result['phase']}` · `{result['arm']}` · `{result['size']}` · `{result['interpretation']}` · "
                   f"`{result['status']}`"), "",
                  ("终态请求 / 计划请求" if chinese else "Terminal requests / planned requests") + " · "
                  f"{result['terminal_requests']} / {result['expected_requests']}", "",
                  ("正确率、违约率、截断率和解析失败率以比例计。即时满足率差以百分点计。"
                   "实际成本、排放和计划超额沿用合成环境单位。"
                   if chinese else "Accuracy, violation, truncation and parse failure are proportions. Immediate "
                   "fulfillment differences are in percentage points. Realized cost, emissions and planned "
                   "excess use the synthetic environment's units."), ""]
        header = ["| 指标 | 样本数 | 均值 | 95% 下界 | 95% 上界 |" if chinese else
                  "| Metric | n | Mean | 95% lower | 95% upper |", "|---|---:|---:|---:|---:|"]
        panels = {}
        for context, block in result["contexts"].items():
            panels[context] = block["primary"]
            if "fallback" in block:
                panels[f"{context} · {'规则兜底' if chinese else 'rule fallback'}"] = block["fallback"]
            panels.update({f"{context} · {key}": value for key, value in block.get("per_question", {}).items()})
        for label, block in result["paired"].items():
            panels[label] = block["primary"]
            if "fallback" in block:
                panels[f"{label} · {'规则兜底' if chinese else 'rule fallback'}"] = block["fallback"]
            panels.update({f"{label} · {key}": value for key, value in block.get("per_question", {}).items()})
        for context, block in result["A_minus_S"].items():
            panels[f"A − S · {context}"] = block["difference"]["primary"]
        for label, panel in panels.items():
            lines += [f"### {label}", "", *header, *_metric_table(panel["metrics"]), ""]
        lines += ["### 计算代价" if chinese else "### Computational cost", "",
                  ("| 上下文 | 美元/调用 | 美元/B 决定 | 平均秒 | p95 秒 | 输入 token | 输出 token | 推理 token |"
                   if chinese else "| Context | USD/call | USD/B decision | Mean s | p95 s | Input tokens | "
                   "Output tokens | Reasoning tokens |"), "|---|---:|---:|---:|---:|---:|---:|---:|"]
        compute_panels = {key: block["compute"] for key, block in result["contexts"].items()}
        compute_panels.update({f"{arm} · {context} (A/S)": table for context, block in result["A_minus_S"].items()
                               for arm, table in block["compute"].items()})
        for label, block in compute_panels.items():
            values = [_number(block[key]) for key in ("mean_usd_per_call", "mean_usd_per_b_decision",
                                                     "mean_seconds", "p95_seconds")]
            values += [_number(block["mean_tokens"][key]) for key in ("input_tokens", "output_tokens", "reasoning_tokens")]
            lines.append(f"| {label} | " + " | ".join(values) + " |")
        bill = result["cumulative_selected_task_ledger"]
        lines += ["", ("累计账本按相同请求哈希纳入历次已结算调用。"
                       if chinese else "The cumulative ledger includes settled attempts with matching request hashes."),
                  "", ("| 结算调用 | 结算美元 | 预留美元 | 结算美元/调用 | 结算美元/B 决定 |" if chinese else
                       "| Settled calls | Settled USD | Reserved USD | Settled USD/call | Settled USD/B decision |"),
                  "|---:|---:|---:|---:|---:|",
                  (f"| {bill['settled_attempts']} | {_number(bill['settled_usd'])} | "
                   f"{_number(bill['open_reserved_usd'])} | {_number(bill['mean_settled_usd_per_call'])} | "
                   f"{_number(bill['mean_settled_usd_per_b_decision'])} |")]
        timing = result["reference_timing"]
        lines += ["", (f"{len(timing['cases'])} 张试点图的参考规划器与规则动作耗时中位数（秒）依次为 "
                       if chinese else f"Median local time (seconds) on {len(timing['cases'])} pilot graphs, "
                       "reference planner then rule action, was ")
                  + f"{_number(timing['reference_median_seconds'])} / "
                  f"{_number(timing['rule_median_seconds'])}.", "",
                  "### 同范围 DQ-2 基线" if chinese else "### DQ-2 baselines over the same graph scope", "",
                  ("| 答题方 | B 正确率 | B 违约率 | P3 正确率 | 计划超额 | 实际成本差 | 即时满足率差（百分点） | 排放差 |"
                   if chinese else "| Responder | B accuracy | B violation | P3 accuracy | Planned excess | "
                   "Cost delta | Immediate fulfillment delta (pp) | Emissions delta |"),
                  "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for name, base in result["dq2_baselines"].items():
            values = [base["stages"]["B"]["accuracy"], base["B"]["violation_rate"], base["stages"]["P3"]["accuracy"]]
            values += [base["B"]["metrics"][metric]["mean"] for metric in OUTCOMES]
            lines.append(f"| `{name}` | " + " | ".join(_number(value) for value in values) + " |")
        lines.append("")
        snapshots = result["model_snapshots"]
        if snapshots:
            lines += ["### 返回模型" if chinese else "### Returned models", ""]
            for arm, counts in snapshots.items():
                description = ", ".join(f"`{model}` ({n})" for model, n in counts.items()) or "—"
                lines.append(f"- {arm} · {description}")
                if len(counts) > 1:
                    lines.append("  此配置记录到多个返回模型。" if chinese else
                                 "  Responses for this configuration report multiple models.")
            lines.append("")
    return "\n".join(lines)


def score(root: Path, phase: str, arm: str, size: str = "full") -> Record:
    config = load_config()
    if (config["seeds"]["bootstrap"], config["bootstrap_replicates"]) != (BOOTSTRAP_SEED, BOOTSTRAP_REPLICATES):
        raise LlmError("bootstrap configuration differs from the frozen evaluator")
    tasks = plan(config, phase, arm, size)
    contexts = config["scope"]["contexts"]
    with root_lock(root):
        jobs = {arm: (tasks, records_for_tasks(root, tasks))}
        events = list(read_jsonl(root / "ledger.jsonl"))
        usage_checks = [row for row in read_jsonl(root / "batches" / "usage_checks.jsonl")
                        if (row["phase"], row["arm"]) == (phase, arm)]
        other_arm = {"S": "A", "A": "S"}[arm]
        if phase in ("pilot", "main") and response_path(root, phase, other_arm).is_file():
            other = plan(config, phase, other_arm, size)
            jobs[other_arm] = (other, records_for_tasks(root, other))
    graphs = _load_graphs(config)
    evidence = _judge(graphs, jobs, contexts)
    selected = evidence[arm]
    all_rows = [row for context in contexts for row in selected[context]]
    responses = _responses(all_rows)
    terminal = sum(row["status"] in TERMINAL for row in responses)
    grading_errors = sum(row["error"] is not None or (row["fallback"] or {}).get("error") is not None
                         for row in all_rows)
    result = {
        "phase": phase, "arm": arm, "size": size,
        "interpretation": {"pilot": "operational", "main": "formal", "p3": "descriptive"}[phase],
        "status": "complete" if terminal == len(tasks) and not grading_errors else "partial",
        "expected_requests": len(tasks), "terminal_requests": terminal, "offline_errors": grading_errors,
        "pilot_reused_requests": sum(phase == "main" and row["phase"] == "pilot" for row in responses),
        "contexts": {context: _context(selected[context], phase) for context in contexts},
        "paired": {f"{left} − {right}": _paired(selected[left], selected[right], phase) for left, right in PAIRINGS},
        "compute": _compute(responses, dispatch=phase != "p3"),
        "cumulative_selected_task_ledger": _journal_costs(tasks, events, dispatch=phase != "p3"),
        "batch_usage_checks": usage_checks,
        "compute_by_transport": {transport: _compute([row for row in responses if row["transport"] == transport],
                                                     dispatch=phase != "p3")
                                 for transport in sorted({row["transport"] for row in responses})},
        "A_minus_S": _arm_comparison(evidence) if len(jobs) == 2 else {},
        "reference_timing": _timings(config, graphs, arm),
        "dq2_baselines": _baseline_summaries(config, {task.graph for task in tasks},
                                             graphs[0]["observation"]["public"]["periods"]),
        "model_snapshots": {name: dict(Counter(row["model"] for row in _responses(
            [item for by_context in evidence[name].values() for item in by_context]) if row["model"])) for name in jobs},
    }
    with root_lock(root):
        _write_artifacts(response_path(root, phase, arm).parent, phase, arm, selected, result, all_rows)
    return result


def _write_artifacts(destination: Path, phase: str, arm: str, selected: dict, result: Record,
                     all_rows: list[Record]) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    tag = f"{phase}_{arm}"
    paths = []
    for context, rows in selected.items():
        path = destination / f"answers_{tag}_{context}.jsonl"
        path.write_bytes(b"".join(canonical({"id": row["id"], "answers": row["answers"]}) + b"\n"
                                  for row in rows))
        paths.append(path)
    details = destination / f"scores_{tag}.jsonl.gz"
    with details.open("wb") as stream, gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as archive:
        for row in all_rows:
            archive.write(canonical(row) + b"\n")
    summary = destination / f"summary_{tag}.json"
    markdown = summary.with_suffix(".md")
    write(summary, result)
    markdown.write_text(_report(result), encoding="utf-8")
    manifest = destination / f"manifest_{tag}.json"
    write(manifest, {"algorithm": "SHA256", "files": {path.name: digest(path)
                                                    for path in [*paths, details, summary, markdown]}})
