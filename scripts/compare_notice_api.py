"""Replay one complete API test run and pair it with the frozen text rules.

All computation is offline. A second run is a repeat of the same cases, never
an additional holdout or a way to increase the independent case count.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from notice_benchmark import api_runner as runner
from notice_benchmark.data import validate_dataset
from notice_benchmark.effects import compare_effect
from notice_benchmark.metrics import paired_cluster_bootstrap, score_predictions
from notice_benchmark.rules import extract_notice
from scripts.score_notice_api import score_run


EVIDENCE_FILES = (
    "estimate.json", "evaluation.json", "evaluation.md", "inputs.jsonl",
    "ledger-anchor.json", "manifest.json", "prompt.txt", "records.jsonl",
    "schema.json", "summary.json",
)


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _pairs(values):
    result = {}
    for key, value in values:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non_finite_json_number")


def _decode(raw):
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_reject_constant)


def _read(path):
    return _decode(Path(path).read_bytes())


def _hash(path):
    return runner.sha256(Path(path).read_bytes())


def _verify_run(dataset_path, run_dir, cases):
    """Use the strict scorer in a private copy; original evidence stays intact."""
    run_dir = Path(run_dir)
    file_hashes = {}
    for name in EVIDENCE_FILES:
        path = run_dir / name
        _require(path.is_file() and not path.is_symlink(), "missing_or_symlink_evidence:" + name)
        file_hashes[name] = _hash(path)
        if path.suffix == ".json":
            _read(path)
        elif path.suffix == ".jsonl":
            for line in path.read_bytes().splitlines():
                _decode(line)
    _require((run_dir / "prompt.txt").read_bytes() == runner.PROMPT.encode(), "prompt_file_mismatch")
    _require((run_dir / "schema.json").read_bytes() == runner.canonical_bytes(runner.SCHEMA) + b"\n", "schema_file_mismatch")
    provenance_path = run_dir / "provenance.json"
    provenance_verified = False
    if provenance_path.exists():
        _require(not provenance_path.is_symlink(), "symlink_provenance")
        provenance = _read(provenance_path)
        _require(provenance.get("files_sha256") == file_hashes, "provenance_file_hash_mismatch")
        provenance_verified = True
    with tempfile.TemporaryDirectory(prefix="notice-api-verify-") as temporary:
        private_run = Path(temporary) / "run"
        private_run.mkdir()
        for name in EVIDENCE_FILES:
            shutil.copyfile(run_dir / name, private_run / name)
        assessment = score_run(dataset_path, private_run)
    _require(assessment == _read(run_dir / "evaluation.json"), "recorded_evaluation_mismatch")
    _require(not assessment["partial_run"] and assessment["counts"]["completed_calls"] == len(cases), "complete_test_run_required")
    manifest = _read(run_dir / "manifest.json")
    identity = manifest["identity"]
    config = identity["configuration"]
    _require(identity["split"] == "test", "test_split_required")
    _require(config["repeats"] == 1 and config["max_calls"] == len(cases), "one_call_per_test_case_required")
    planned = manifest["requests"]
    case_ids = [case["id"] for case in cases]
    _require(len(case_ids) == len(set(case_ids)), "duplicate_dataset_case")
    _require(len(planned) == len(cases) and {item["case_id"] for item in planned} == set(case_ids), "full_paired_case_coverage_required")
    records, last_hash = runner._read_log(run_dir / "records.jsonl")
    results = [row for row in records if row["kind"] == "result"]
    result_ids = [row["case_id"] for row in results]
    _require(len(result_ids) == len(set(result_ids)) == len(cases), "duplicate_or_missing_case_result")
    by_id = {row["case_id"]: row for row in results}
    predictions = {case_id: by_id[case_id]["parsed_output"] for case_id in case_ids}
    scored = score_predictions(cases, predictions)
    effects = {case["id"]: bool(compare_effect(case["reference"], predictions[case["id"]],
        case["model_input"]["context"])["effect_match"]) for case in cases}
    timestamps = [row["time_utc"] for row in records]
    responses = [row["raw_response"] for row in results]
    epoch_bounds = {}
    for key in ("created_at", "completed_at"):
        values = [response[key] for response in responses if response.get(key) is not None]
        epoch_bounds[key] = [min(values), max(values)] if values else None
    usage = {key: sum(row["usage"][key] for row in results)
        for key in ("input_tokens", "output_tokens", "total_tokens")}
    summary = {
        "verification": {"strict_score_run": True, "original_files_unchanged": True,
            "provenance_file_hashes_verified": provenance_verified, "files_sha256": file_hashes},
        "assessment_status": assessment["status"], "transport": assessment["transport"],
        "live_api_evidence": assessment["live_api_evidence"],
        "identity": identity, "ledger_last_sha256": last_hash,
        "counts": assessment["counts"], "metrics": assessment["metrics"],
        "scoring_summary": scored["summary"], "usage": usage,
        "usage_reported_usd": format(sum((Decimal(row["usage_cost_usd"]) for row in results), Decimal(0)), "f"),
        "returned_models": dict(sorted(Counter(response["model"] for response in responses).items())),
        "returned_system_fingerprints": dict(sorted(Counter(str(response["system_fingerprint"])
            for response in responses if response.get("system_fingerprint") is not None).items())),
        "recorded_time_utc_bounds": [min(timestamps), max(timestamps)],
        "raw_response_epoch_bounds": epoch_bounds,
    }
    return summary, scored, effects, predictions


def _paired_intervals(left, right, samples, seed):
    event = paired_cluster_bootstrap(left, right, samples=samples, seed=seed)
    event["cluster_key"] = "event_id"
    family_reports = []
    for report in (left, right):
        grouped = deepcopy(report)
        for case in grouped["per_case"]:
            case["event_id"] = case["template_family_id"]
        family_reports.append(grouped)
    family = paired_cluster_bootstrap(*family_reports, samples=samples, seed=seed)
    family["cluster_key"] = "template_family_id"
    family["number_render_family_clusters"] = family.pop("number_event_clusters")
    family["resampling_unit"] = "whole render family, retaining all its cases and paired calls"
    limitation = "Separate event and render-family cluster sensitivity intervals, not a multiway bootstrap; synthetic families cannot establish real-notice generalization."
    return {"event": event, "render_family": family, "limitation": limitation}


def _paired_summary(cases, api_score, rule_score, api_effects, rule_effects, samples, seed):
    api = {row["case_id"]: row for row in api_score["per_case"]}
    rules = {row["case_id"]: row for row in rule_score["per_case"]}
    per_case = []
    for case in cases:
        case_id = case["id"]
        a, b = api[case_id], rules[case_id]
        per_case.append({"case_id": case_id, "event_id": case["event_id"],
            "template_family_id": case["template_family_id"], "category": case["category"],
            "input_sha256": runner.sha256(runner.canonical_bytes(case["model_input"])),
            "case_sha256": a["case_sha256"], "reference_status": case["reference"]["status"],
            "api_exact": a["all_repeats_correct"], "rules_exact": b["all_repeats_correct"],
            "exact_difference": int(a["all_repeats_correct"]) - int(b["all_repeats_correct"]),
            "api_effect_match": api_effects[case_id], "rules_effect_match": rule_effects[case_id]})
    categories = {}
    for category in sorted({row["category"] for row in per_case}):
        rows = [row for row in per_case if row["category"] == category]
        categories[category] = {"cases": len(rows),
            "api_exact": sum(row["api_exact"] for row in rows),
            "rules_exact": sum(row["rules_exact"] for row in rows),
            "api_only_correct": sum(row["exact_difference"] == 1 for row in rows),
            "rules_only_correct": sum(row["exact_difference"] == -1 for row in rows)}
    return {"difference": api_score["summary"]["mean_case_exact_match_rate"] - rule_score["summary"]["mean_case_exact_match_rate"],
        "both_correct": sum(row["api_exact"] and row["rules_exact"] for row in per_case),
        "api_only_correct": sum(row["exact_difference"] == 1 for row in per_case),
        "rules_only_correct": sum(row["exact_difference"] == -1 for row in per_case),
        "both_incorrect": sum(not row["api_exact"] and not row["rules_exact"] for row in per_case),
        "confidence_intervals": _paired_intervals(api_score, rule_score, samples, seed),
        "by_category": categories, "per_case": per_case}


def compare_runs(dataset_path, freeze_path, run_dir, *, repeat_run=None, samples=10000, seed=20261030):
    """Verify complete, singly sampled test runs and compare each with frozen rules."""
    dataset_path, freeze_path = Path(dataset_path), Path(freeze_path)
    dataset, frozen = _read(dataset_path), _read(freeze_path)
    validate_dataset(dataset)
    _require(frozen.get("schema_version") == "notice-rules-freeze-v1", "unsupported_rules_freeze")
    _require(frozen["rules_sha256"] == _hash(ROOT / "notice_benchmark/rules.py")
        and frozen["dataset_sha256"] == dataset["manifest"]["dataset_sha256"], "frozen_dataset_or_rules_changed")
    cases = dataset["splits"]["test"]
    rules = {case["id"]: extract_notice(**case["model_input"]) for case in cases}
    rule_score = score_predictions(cases, rules)
    rule_effects = {case["id"]: bool(compare_effect(case["reference"], rules[case["id"]],
        case["model_input"]["context"])["effect_match"]) for case in cases}
    primary, api_score, api_effects, api_outputs = _verify_run(dataset_path, run_dir, cases)
    paired = _paired_summary(cases, api_score, rule_score, api_effects, rule_effects, samples, seed)
    report = {"schema_version": "notice-api-paired-comparison-v1", "split": "test",
        "synthetic": True, "independent_real_notices": 0, "api_calls_made_by_comparison": 0,
        "distinct_cases": len(cases), "event_clusters": len({case["event_id"] for case in cases}),
        "render_family_clusters": len({case["template_family_id"] for case in cases}),
        "dataset_file_sha256": _hash(dataset_path), "frozen_identity": frozen,
        "primary": primary, "rules": {"counts": rule_score["counts"], "summary": rule_score["summary"],
            "schedule_effect_match_rate": sum(rule_effects.values()) / len(cases)},
        "paired": paired, "repeat": None, "total_recorded_calls": len(cases),
        "limitations": [
            "The model alias and request configuration are fixed; the backend model snapshot is not pinned or independently identified.",
            "The holdout consists of generated in-domain notices, not independently collected real notices.",
            "A repeat over the same case set measures observed stability and adds no distinct holdout cases.",
        ]}
    if repeat_run is not None:
        _require(Path(run_dir).resolve() != Path(repeat_run).resolve(), "repeat_must_be_a_separate_run")
        repeat, repeat_score, repeat_effects, repeat_outputs = _verify_run(dataset_path, repeat_run, cases)
        _require(primary["ledger_last_sha256"] != repeat["ledger_last_sha256"], "same_ledger_is_not_a_repeat")
        _require(primary["identity"] == repeat["identity"], "repeat_identity_mismatch")
        repeat["paired_with_rules"] = _paired_summary(cases, repeat_score, rule_score,
            repeat_effects, rule_effects, samples, seed)
        repeat["same_case_set"] = True
        repeat["distinct_additional_cases"] = 0
        repeat["identical_parsed_outputs"] = sum(api_outputs[key] == repeat_outputs[key] for key in api_outputs)
        repeat["disagreement_case_ids"] = [key for key in api_outputs if api_outputs[key] != repeat_outputs[key]]
        report["repeat"] = repeat
        report["total_recorded_calls"] += len(cases)
    return report


def _markdown(report):
    total = report["distinct_cases"]
    primary = report["primary"]
    rules = report["rules"]["summary"]
    paired = report["paired"]
    lines = ["# 合成留出集 API 成对比较", "",
        f"同一 {total} 条冻结合成公告；{report['event_clusters']} 个事件；{report['render_family_clusters']} 个渲染族。", "",
        "| 指标 | API 主运行 | 冻结规则 |", "|---|---:|---:|",
        f"| 整条公告精确匹配 | {primary['scoring_summary']['exact_matches']}/{total} | {rules['exact_matches']}/{total} |",
        f"| 排程效果一致 | {primary['metrics']['schedule_effect_accuracy']:.1%} | {report['rules']['schedule_effect_match_rate']:.1%} |", "",
        f"成对差值：{paired['difference'] * 100:.1f} 个百分点；API 独对 {paired['api_only_correct']} 条，规则独对 {paired['rules_only_correct']} 条。", "",
        "| 95% 成对 bootstrap 区间 | 下界（百分点） | 上界（百分点） |", "|---|---:|---:|"]
    for key, label in (("event", "按事件聚类"), ("render_family", "按渲染族聚类")):
        interval = paired["confidence_intervals"][key]
        lines.append(f"| {label} | {interval['interval'][0] * 100:.2f} | {interval['interval'][1] * 100:.2f} |")
    lines += ["", "两个区间分别重采样完整事件或完整渲染族，按被抽中案例数加权；不是多维联合 bootstrap。合成族不能代表真实公告的抽样分布。", "",
        "| 类别 | 案例 | API 正确 | 规则正确 |", "|---|---:|---:|---:|"]
    for category, counts in paired["by_category"].items():
        lines.append(f"| {category} | {counts['cases']} | {counts['api_exact']} | {counts['rules_exact']} |")
    if report["repeat"] is not None:
        repeat = report["repeat"]
        lines += ["", f"复测完成 {repeat['counts']['completed_calls']} 次请求，精确匹配 {repeat['scoring_summary']['exact_matches']}/{total}；{repeat['identical_parsed_outputs']} 条解析输出与主运行一致。",
            f"两次运行共有 {report['total_recorded_calls']} 次调用，仍为 {total} 条不同案例，新增独立案例为 0。"]
    lines += ["", "模型名和请求配置固定，返回模型名仍为别名，未锁定后端快照。输入、原始响应、时间戳及用量按原文件保留。复算不调用 API。"]
    return "\n".join(lines) + "\n"


def write_comparison(report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "comparison.json").write_bytes(runner.canonical_bytes(report) + b"\n")
    (output_dir / "comparison.md").write_text(_markdown(report), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "benchmarks/notices_v1/dataset.json")
    parser.add_argument("--freeze", type=Path, default=ROOT / "benchmarks/notices_v1/rules_freeze.json")
    parser.add_argument("--run", type=Path, default=ROOT / "benchmark_results/api_test")
    parser.add_argument("--repeat-run", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--samples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261030)
    args = parser.parse_args(argv)
    try:
        report = compare_runs(args.dataset, args.freeze, args.run, repeat_run=args.repeat_run,
            samples=args.samples, seed=args.seed)
        write_comparison(report, args.output or args.run)
    except (ValueError, KeyError, TypeError, OSError, ArithmeticError, runner.RunnerError) as error:
        print(json.dumps({"status": "integrity_failure", "error": str(error)}))
        return 2
    print(json.dumps({"status": "verified", "distinct_cases": report["distinct_cases"],
        "total_recorded_calls": report["total_recorded_calls"], "paired_difference": report["paired"]["difference"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
