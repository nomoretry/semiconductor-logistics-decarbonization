"""Offline-only corpus, baseline, input-export, and API-artifact commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from notice_benchmark.api_runner import RunnerError

from .api import api_input_dataset, score_api_run
from .data import canonical_bytes, corpus_summary, load_dataset
from .evaluation import evaluate_offline


def _number(value):
    return "unavailable" if value is None else f"{value:.6f}" if isinstance(value, float) else str(value)


def markdown_report(report):
    lines = ["## Real-notice short-excerpt abstention audit", "",
             "Assistant reference decisions remain pending independent human review. "
             "This exploratory audit does not establish transit-update extraction skill.", ""]
    corpus = report.get("corpus")
    if corpus:
        lines += ["| Corpus count | Value |", "|---|---:|"]
        for key in ("number_cases", "number_source_documents", "number_event_groups",
                    "number_correlation_groups", "excluded_source_count"):
            lines.append(f"| {key} | {_number(corpus[key])} |")
        for key, value in corpus["reference_class_balance"].items():
            lines.append(f"| reference_{key} | {value} |")
        lines += ["", "The single exploratory test split is not a held-out evaluation. "
                  "Absent reference classes have unavailable rates.", ""]
    if "methods" in report:
        lines += ["| Offline method | Exact assistant-reference agreement |", "|---|---:|"]
        for method, score in report["methods"].items():
            lines.append(f"| {method} | {_number(score['exact_reference_match_rate'])} |")
        lines += ["", "The always-clarify baseline exposes an all-clarification corpus ceiling. API calls: 0."]
    else:
        lines += [f"Status: {report['status']}. Transport: {report['transport']}.", "",
                  "| API count | Value |", "|---|---:|"]
        for key, value in report["counts"].items():
            lines.append(f"| {key} | {_number(value)} |")
        lines += ["", "| Reference agreement denominator | Rate |", "|---|---:|"]
        for key in ("reference_agreement_completed_outputs", "reference_agreement_all_planned_outputs"):
            score = report[key]
            lines.append(f"| {key} | {_number(None if score is None else score['exact_reference_match_rate'])} |")
        if corpus:
            n = corpus["number_cases"]
            clarify = corpus["reference_class_balance"]["needs_clarification"]
            lines.append(f"| always_clarify_reference_baseline | {_number(clarify / n if n else None)} |")
        lines += ["", "API errors, unknown outcomes, and unattempted calls remain in the counts. "
                  "No completed outputs means unavailable agreement, not zero accuracy."]
        if report["transport"] == "injected_test_transport":
            lines += ["", "Injected transport outputs are mock evidence, not live model performance."]
    return "\n".join(lines) + "\n"


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "offline", "export-api", "score-api"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--dataset", default="benchmarks/real_notices_v1/dataset.json")
        if command in {"validate", "offline"}:
            sub.add_argument("--split", choices=("development", "test"), default="test")
        if command == "offline":
            sub.add_argument("--output", default="artifacts/real_notice/offline")
        elif command == "export-api":
            sub.add_argument("--output", required=True)
        elif command == "score-api":
            sub.add_argument("--input-dataset", required=True)
            sub.add_argument("--run-dir", required=True)
            sub.add_argument("--output", required=True)
        if command in {"offline", "score-api"}:
            sub.add_argument("--github-summary")
    args = parser.parse_args()
    try:
        dataset = load_dataset(args.dataset)
        if args.command == "validate":
            result = corpus_summary(dataset, args.split)
        elif args.command == "export-api":
            projected = api_input_dataset(dataset)
            _write_json(args.output, projected)
            result = {"status": "inputs_exported_no_api_call", "synthetic": False,
                      "case_counts": {key: len(value) for key, value in projected["splits"].items()},
                      "source_corpus_sha256": projected["source_corpus_sha256"]}
        else:
            if args.command == "offline":
                result = evaluate_offline(dataset, args.split)
                output = Path(args.output) / "report.json"
            else:
                result = score_api_run(dataset, args.input_dataset, args.run_dir)
                output = Path(args.output)
            _write_json(output, result)
            markdown = markdown_report(result)
            output.with_suffix(".md").write_text(markdown, encoding="utf-8")
            if args.github_summary:
                with Path(args.github_summary).open("a", encoding="utf-8") as stream:
                    stream.write(markdown)
            result = {key: value for key, value in result.items()
                      if key not in {"methods", "reference_agreement_completed_outputs",
                                     "reference_agreement_all_planned_outputs"}}
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError, RunnerError) as error:
        # Fail closed. Do not echo input/provider text, paths, or credentials.
        code = error.code if isinstance(error, RunnerError) else type(error).__name__
        print(json.dumps({"status": "failed", "error_code": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
