"""Run the sequential evaluation and verify its saved evidence without solving."""
from __future__ import annotations

import gzip
import json
import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from .consequence import replay_trajectory, verify_comparison
from .dataset import (
    check_manifest,
    digest,
    environment,
    graphs,
    read,
    records,
    trajectories,
    write,
)
from .eval_statistics import summarize_ablations, summarize_baselines
from .evaluation import (
    LANGUAGES,
    MODES,
    EvaluationStop,
    check_submissions,
    empty_graph,
    evaluate_graph,
    export_prompts,
    gold_check,
    read_answers,
)
from .graph import compact
from .planner import Record
from .scoring import answer_map

ATTEMPTS = "attempts.jsonl.gz"
ANSWER_FILE = "file_responses.jsonl"
PROMPT_FILES = {f"prompts_test_{mode}_{lang}.jsonl": (mode, lang) for mode in MODES for lang in LANGUAGES}
CORE_FILES = {ATTEMPTS, ANSWER_FILE, "config.json", "completion.json", "environment.json", "summary.json"}
PILOT_COUNT = 66
FORMAL_COUNT = 880
FORMAL_LIMIT = 5400


def _pack(row: Record) -> Record:
    """Store each distinct judged response once and preserve every rendered input length."""
    results: list[Record] = []
    keys: dict[str, int] = {}
    links: Record = {}
    for name, modes in row["baselines"].items():
        links[name] = {}
        for mode, sources in modes.items():
            links[name][mode] = {}
            for source, result in sources.items():
                signature = compact(result["answers"])
                if signature not in keys:
                    keys[signature] = len(results)
                    results.append({key: value for key, value in result.items() if key != "prompt_characters"})
                links[name][mode][source] = {"index": keys[signature], "characters": result["prompt_characters"]}
    return {**row, "baselines": links, "response_artifacts": results}


def _read_attempts(directory: Path, periods: int) -> Iterator[Record]:
    with gzip.open(directory / ATTEMPTS, "rt", encoding="utf-8") as file:
        for line in file:
            row: Record = json.loads(line)
            t = int(row["id"].rsplit("/", 1)[1])
            responses = row.pop("response_artifacts")
            for result in [*responses, *row["ablations"].values()]:
                outcome = result["consequence"]
                if outcome is not None:
                    verify_comparison(outcome, start_period=t, end_period=periods - 1)
                    if "changed" in result:
                        differences = outcome["delta"] or {}
                        drift = any(result[f"{key}_delta"] != differences.get(key)
                                    for key in ("cost", "fill_rate", "emissions"))
                        if drift or result["violation"] != (outcome["status"] == "violation"):
                            raise ValueError(f"{row['id']}: ablation differs from replayed consequence evidence")
                    # Summaries need totals and deltas. The original period rows stay in the raw evidence.
                    for branch in ("reference", "actual"):
                        if outcome[branch] is not None:
                            outcome[branch].pop("periods")
                result.pop("answers", None)
            for modes in row["baselines"].values():
                for sources in modes.values():
                    for source, link in sources.items():
                        sources[source] = responses[link["index"]]
            yield row


def _prompt_stats(directory: Path, filenames: list[str]) -> Record:
    stats: Record = {}
    for name in filenames:
        mode, lang = PROMPT_FILES[name]
        lengths: list[int] = []
        seen: set[tuple[str, str]] = set()
        for record in records(directory / name):
            length = len(record["prompt"])
            key = record["id"], record["node_id"]
            if (length != record["characters"] or (record["mode"], record["lang"], record["source"])
                    != (mode, lang, "gold") or key in seen):
                raise ValueError(f"invalid prompt evidence: {name}, {key}")
            seen.add(key)
            lengths.append(length)
        if len(lengths) != 352 * 31:
            raise ValueError(f"incomplete prompt evidence: {name}")
        stats.setdefault(lang, {})[mode] = {
            "count": len(lengths), "min": min(lengths), "mean": sum(lengths) / len(lengths),
            "p95": float(np.percentile(lengths, 95)), "max": max(lengths),
        }
    return stats


def _derive(directory: Path) -> Record:
    config = read(directory / "config.json")
    completion = read(directory / "completion.json")
    items = list(_read_attempts(directory, config["periods"]))
    ids = [row["id"] for row in items]
    expected_ids = config["graph_ids"]
    if len(set(ids)) != len(ids) or ids != expected_ids[:len(ids)]:
        raise ValueError("evaluation attempt order or IDs differ")
    if completion["status"] != "failed" and ids != expected_ids:
        raise ValueError("evaluation attempts are incomplete")
    if completion["status"] != "failed":
        for row in items:
            gold_check(row, row["baselines"]["gold"]["None"]["gold"], expected=31)
    count = len(items)
    solves: Counter[str] = Counter()
    for row in items:
        solves.update(row["solves"])
    p95 = float(np.percentile([row["seconds"] for row in items], 95)) if count else None
    estimate = None if p95 is None else p95 * FORMAL_COUNT + 60
    if config["phase"] == "pilot" and completion["status"] != "failed":
        status = "over_budget" if estimate is not None and estimate > FORMAL_LIMIT else "complete"
        if completion["status"] != status:
            raise ValueError("pilot gate contradicts recorded timing")
    return {**completion, "phase": config["phase"], "attempted": count,
            "paths": len({(row["split"], row["profile"], row["seed"]) for row in items}),
            "trajectories": len({row["id"].rsplit("/", 1)[0] for row in items}), "solves": dict(solves),
            "failed_calls": sum(row["failed_calls"] for row in items),
            "cache_hits": sum(row["cache_hits"] for row in items), "p95_seconds": p95,
            "estimated_formal_seconds": estimate if config["phase"] == "pilot" else None,
            "prompt_lengths": _prompt_stats(directory, config["prompt_files"]),
            "baselines": summarize_baselines(items), "ablations": summarize_ablations(items)}


def _files(directory: Path) -> set[str]:
    config = read(directory / "config.json")
    prompts = set(config["prompt_files"])
    allowed = config["phase"] == "formal" and read(directory / "completion.json")["status"] == "complete"
    if prompts != (set(PROMPT_FILES) if allowed else set()):
        raise ValueError("unexpected prompt file set")
    return CORE_FILES | prompts


def write_summary(directory: Path) -> Record:
    result = _derive(directory)
    write(directory / "summary.json", result)
    write(directory / "manifest.json", {"algorithm": "SHA256", "files": {
        name: digest(directory / name) for name in sorted(_files(directory))}})
    return result


def verify_eval(directory: Path) -> Record:
    manifest = read(directory / "manifest.json")
    files = manifest["files"]
    if (manifest["algorithm"] != "SHA256" or any(Path(name).name != name for name in files)
            or set(files) != {file.name for file in directory.iterdir()} - {"manifest.json"}):
        raise ValueError("evaluation manifest file set")
    for name, expected in files.items():
        if digest(directory / name) != expected:
            raise ValueError(f"SHA256 mismatch: {name}")
    if set(files) != _files(directory):
        raise ValueError("unexpected evaluation artifact files")
    actual = _derive(directory)
    if actual != read(directory / "summary.json"):
        raise ValueError("recomputed evaluation summary differs")
    return {"phase": actual["phase"], "status": actual["status"], "verified": actual["attempted"],
            "sha256_files": len(files), "solver_calls": 0}


def _runtime() -> Record:
    info = environment()
    protocol = Path(__file__).parents[1] / "docs" / "decision_graph_qa_eval_protocol.md"
    info["sha256_eval_protocol"] = digest(protocol)
    return info


def _pilot_gate(pilot: Path, manifest: str, answer_digest: str | None, runtime: Record) -> str:
    actual = verify_eval(pilot)
    config = read(pilot / "config.json")
    summary = read(pilot / "summary.json")
    if (actual["phase"] != "pilot" or actual["status"] != "complete" or actual["verified"] != PILOT_COUNT
            or summary["paths"] != 3 or summary["trajectories"] != 6
            or (config["input_manifest_sha256"], config["external_answers_sha256"]) != (manifest, answer_digest)
            or read(pilot / "environment.json") != runtime):
        raise EvaluationStop("pilot evidence does not clear the registered formal gate")
    return digest(pilot / "manifest.json")


def evaluate(data: Path, out: Path, *, pilot: bool, pilot_evidence: Path | None = None,
             answers: Path | None = None) -> Record:
    started = time.perf_counter()
    check_manifest(data)
    manifest = digest(data / "manifest.json")
    answer_digest = digest(answers) if answers is not None else None
    runtime = _runtime()
    if not pilot and pilot_evidence is None:
        raise ValueError("formal evaluation requires qualifying pilot evidence")
    pilot_sha = _pilot_gate(pilot_evidence, manifest, answer_digest, runtime) if pilot_evidence is not None else None

    groups: dict[str, list[Record]] = defaultdict(list)
    for graph in graphs(data):
        groups[graph["id"].rsplit("/", 1)[0]].append(graph)
    tasks = list(trajectories(False))
    if pilot:
        first_paths: dict[str, str] = {}
        for task, _ in tasks:
            first_paths.setdefault(task["split"], task["id"])
        tasks = [(task, policy) for task, policy in tasks if task["id"] == first_paths[task["split"]]]
    selected = [graph for task, policy in tasks for graph in groups[f"{task['id']}/{policy}"]]
    if len(selected) != (PILOT_COUNT if pilot else FORMAL_COUNT):
        raise EvaluationStop("unexpected evaluation graph count")
    submissions = read_answers(answers) if answers is not None else {}
    check_submissions((item for group in groups.values() for item in group), submissions)
    out.mkdir(parents=True, exist_ok=False)
    with (out / ANSWER_FILE).open("x", encoding="utf-8", newline="\n") as output:
        for graph in selected:
            gid = graph["id"]
            reply = answer_map(graph) if answers is None else submissions.get(gid, {})
            output.write(compact({"id": gid, "answers": reply}) + "\n")
    submissions = read_answers(out / ANSWER_FILE)
    config = {"phase": "pilot" if pilot else "formal", "periods": tasks[0][0]["public"]["periods"],
              "graph_ids": [graph["id"] for graph in selected], "input_manifest_sha256": manifest,
              "external_answers_sha256": answer_digest, "pilot_manifest_sha256": pilot_sha, "prompt_files": []}
    write(out / "environment.json", runtime)

    timings: list[float] = []
    calls = failures = 0
    stop = ""
    try:
        with gzip.open(out / ATTEMPTS, "xt", encoding="utf-8", newline="\n", compresslevel=3) as raw:
            for task, policy in tasks:
                sequence = replay_trajectory(task, policy, groups[f"{task['id']}/{policy}"])
                t0 = time.perf_counter()
                for graph, env in sequence:
                    counts: Counter[str] = Counter()
                    row = {**empty_graph(graph), "baselines": {}, "ablations": {}, "errors": [],
                           "failed_calls": 0, "cache_hits": 0}
                    try:
                        evaluate_graph(graph, env, submissions[graph["id"]], row, counts, calls, failures)
                    finally:
                        row.update(seconds=time.perf_counter() - t0, solves=dict(counts))
                        timings.append(row["seconds"])
                        calls += counts.total()
                        failures += row["failed_calls"]
                        raw.write(compact(_pack(row)) + "\n")
                        raw.flush()
                    if len(timings) % 11 == 0 or row["failed_calls"]:
                        print(compact({"attempted": len(timings), "failed_calls": failures, "solver_calls": calls,
                                       "elapsed_seconds": time.perf_counter() - started}), flush=True)
                    t0 = time.perf_counter()
    except (EvaluationStop, ValueError) as exc:
        stop = str(exc)

    status = "failed" if stop else "complete"
    if not stop and pilot and float(np.percentile(timings, 95)) * FORMAL_COUNT + 60 > FORMAL_LIMIT:
        status, stop = "over_budget", "estimated formal wall time exceeds 5400 seconds"
    if status == "complete" and not pilot:
        for name, (mode, lang) in PROMPT_FILES.items():
            export_prompts(data, split="test", mode=mode, source="gold", lang=lang, out=out / name)
        config["prompt_files"] = sorted(PROMPT_FILES)
    write(out / "config.json", config)
    write(out / "completion.json", {"status": status, "stop_reason": stop,
                                    "wall_seconds": time.perf_counter() - started})
    summary = write_summary(out)
    return {key: summary[key] for key in ("status", "stop_reason", "phase", "attempted", "solves", "failed_calls",
                                          "cache_hits", "wall_seconds", "p95_seconds", "estimated_formal_seconds")}
