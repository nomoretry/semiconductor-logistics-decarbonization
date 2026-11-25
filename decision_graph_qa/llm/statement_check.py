"""Offline acceptance of the v2 statements, and the score ceilings that closed protocol v1."""
from __future__ import annotations

import itertools
import json
import platform
import statistics
import time
from collections import Counter
from pathlib import Path

import numpy as np

from ..dataset import records
from ..planner import INF, Model, Record, Row, scenarios, tolerance, window
from ..scoring import answer_map, constrained, grade_graph
from .data import (
    LlmError,
    canonical,
    digest,
    load_config,
    prompts_by_graph,
    read_jsonl,
    verified_manifest,
    verify_file,
)
from .reader import (
    MEAN_FORECAST,
    MISREADINGS,
    StatementError,
    answers,
    exact_cost,
    optimize,
    parse,
)
from .rules import ANSWERED, RULES
from .statement import MODES, STAGES, prompt_file, verify, write_gzip

__all__ = ["EVIDENCE", "MEAN_FORECAST", "check", "load_graphs", "replay", "summarize"]

EVIDENCE = "statement_check.jsonl.gz"
SUMMARY = "statement_check.json"
CEILING_DRAWS = 200
CEILING_SEEDS = (20261125, 7)


Prompts = dict[str, dict[tuple[str, str], str]]


def load_graphs(config: Record) -> list[Record]:
    directory, files = verified_manifest(config, "dataset")
    return list(records(verify_file(directory, files, "test.jsonl")))


def load_prompts(directory: Path) -> Prompts:
    return {mode: {(row["id"], row["node_id"]): row["prompt"] for row in read_jsonl(directory / prompt_file(mode))}
            for mode in MODES}


def without_additions(text: str) -> str:
    """Drop the rules, the scenarios and the line before the answered questions from a v2 prompt."""
    if not text.startswith(f"{RULES}\n\n"):
        raise LlmError("Prompt does not start with the planning rules")
    blocks = text[len(RULES) + 2:].split("\n\n")
    rest = blocks[3:] if blocks[2] == ANSWERED else blocks[2:]
    return "\n\n".join([blocks[0], *rest])


class Grader:
    """Grade first dispatches of one graph with the frozen DQ-1 rules."""

    def __init__(self, graph: Record, counts: Counter[str]) -> None:
        self.graph, self.counts = graph, counts
        self.model = Model(graph["observation"], scenarios(graph["observation"]), counts)
        self.reference = answer_map(graph)
        self.cache: dict[str, Record] = {}

    def __call__(self, action: list[list[int]]) -> Record:
        key = json.dumps(action)
        if key not in self.cache:
            feasible, value = constrained(self.model, "B", action, graph_id=self.graph["id"],
                                          reference_plan=self.reference["M"],
                                          reference_objective=self.graph["objective"])
            excess = None if value is None else value - self.graph["objective"]
            self.cache[key] = {"action": action, "violation": not feasible, "excess": excess,
                               "correct": excess is not None and excess <= tolerance(self.graph["objective"])}
        return self.cache[key]


def text_only(graph: Record, prompts: Prompts, grade: Grader) -> tuple[Record, Record]:
    """Solve the graph once from its 21 prompts and grade the seven questions and the whole plan."""
    asked = [node["id"] for node in graph["nodes"] if node["stage"] in STAGES]
    problems = [parse(prompts[mode][graph["id"], question]) for mode in MODES for question in asked]
    if any(problem != problems[0] for problem in problems):
        raise LlmError(f"{graph['id']}: prompts of one graph state different problems")
    problem = problems[0]
    started = time.perf_counter()
    plan, value = optimize(problem)
    seconds = time.perf_counter() - started
    reply = answers(problem, plan)
    graded = {row["id"]: row for row in grade_graph(graph, reply, grade.counts) if row["provided"]}
    if set(graded) != {*asked, "M"}:
        raise LlmError(f"{graph['id']}: unexpected question set")
    result = {"text_objective": value, "exact_cost": float(exact_cost(problem, plan)), "answers": reply,
              "correct": {key: row["correct"] for key, row in sorted(graded.items())},
              "violation": {key: row["violation"] for key, row in sorted(graded.items())},
              "prompts": len(problems), "seconds": seconds}
    return result, {name: grade(optimize(problem, reading)[0][0]) for name, reading in MISREADINGS.items()}


def ceilings(graph: Record, grade: Grader) -> Record:
    """Best dispatches with the rules known but the reference scenarios hidden, as in the v1 prompts."""
    obs, gold = graph["observation"], grade.reference
    h = window(obs)
    result: Record = {}
    for seed in CEILING_SEEDS:
        shape = (CEILING_DRAWS, h, len(obs["public"]["mass"]))
        model = Model(obs, np.random.default_rng(seed).poisson(obs["forecast"][:h], size=shape), grade.counts)
        rows: list[Row] = [(model.flags[i], 1, INF) if gold[f"P3.ship.{i}"] else (model.flags[i], 0, 0)
                           for i in range(model.n)]
        rows += [(model.loads[j], gold[f"P3.load.{j}"], gold[f"P3.load.{j}"]) for j in range(model.r)]
        rows.append((model.emission, gold["P3.emission"], gold["P3.emission"]))
        for label, extra in (("own draws", ()), ("own draws + P3 answers", tuple(rows))):
            plan = model.optimize("ceiling", extra)
            if plan is None:
                raise LlmError(f"{graph['id']}: no plan for the ceiling")
            result[f"{label}, seed {seed}"] = grade(plan[0])
    return result


def assembly(graph: Record, grade: Grader) -> Record:
    """Grade every dispatch that agrees with the P3 reference answers."""
    p, gold = graph["observation"]["public"], grade.reference
    skus, routes = range(len(p["mass"])), range(len(p["lead"]))
    columns = []
    for j in routes:
        load = gold[f"P3.load.{j}"]
        columns.append([units for units in itertools.product(*(range(load // p["mass"][i] + 1) for i in skus))
                        if sum(p["mass"][i] * units[i] for i in skus) == load])
    graded = []
    for choice in itertools.product(*columns):
        action = [[choice[j][i] for j in routes] for i in skus]
        if all(any(action[i]) == gold[f"P3.ship.{i}"] for i in skus):
            graded.append(grade(action))
    if not graded or any(row["violation"] for row in graded):
        raise LlmError(f"{graph['id']}: P3 reference answers do not lead to feasible dispatches")
    return {"candidates": len(graded), "correct": sum(row["correct"] for row in graded),
            "mean_excess": statistics.mean(row["excess"] for row in graded)}


def _graded(rows: list[Record], objectives: list[float]) -> Record:
    relative = [100 * row["excess"] / objective for row, objective in zip(rows, objectives, strict=True)
                if row["excess"] is not None and objective]
    return {"graphs": len(rows), "correct": sum(row["correct"] for row in rows),
            "correct_rate": sum(row["correct"] for row in rows) / len(rows),
            "violations": sum(row["violation"] for row in rows),
            "relative_excess_pct_mean": statistics.mean(relative),
            "relative_excess_pct_median": statistics.median(relative), "relative_excess_n": len(relative)}


def summarize(evidence: list[Record]) -> Record:
    objectives = [row["objective"] for row in evidence]
    text = [row["text_only"] for row in evidence]
    questions = sorted({key for row in text for key in row["correct"]})
    share = [row["assembly"]["correct"] / row["assembly"]["candidates"] for row in evidence]
    excess = [100 * row["assembly"]["mean_excess"] / row["objective"] for row in evidence if row["objective"]]
    differences = [abs(row["text_objective"] - value) for row, value in zip(text, objectives, strict=True)]
    return {
        "graphs": len(evidence),
        "prompts": {"parsed": sum(row["prompts"] for row in text),
                    "v1_text_kept": sum(row["v1_text_kept"] for row in evidence),
                    "v1_prompts_rejected": sum(row["v1_prompts_rejected"] for row in evidence)},
        "text_only_program": {
            "objective_equal": sum(gap <= tolerance(value) for gap, value in zip(differences, objectives, strict=True)),
            "exact_cost_equal": sum(abs(row["exact_cost"] - value) <= tolerance(value)
                                    for row, value in zip(text, objectives, strict=True)),
            "max_abs_objective_difference": max(differences),
            "correct": {key: sum(row["correct"][key] for row in text) for key in questions},
            "violations": sum(value for row in text for value in row["violation"].values()),
            "median_seconds": statistics.median(row["seconds"] for row in text),
            "max_seconds": max(row["seconds"] for row in text),
        },
        "misreadings": {name: _graded([row["misreadings"][name] for row in evidence], objectives)
                        for name in MISREADINGS},
        "v1_ceilings": {name: _graded([row["v1_ceilings"][name] for row in evidence], objectives)
                        for name in evidence[0]["v1_ceilings"]},
        "assembly_from_p3_answers": {
            "mean_candidates": statistics.mean(row["assembly"]["candidates"] for row in evidence),
            "single_candidate_graphs": sum(row["assembly"]["candidates"] == 1 for row in evidence),
            "all_candidates_correct_graphs": sum(row["assembly"]["correct"] == row["assembly"]["candidates"]
                                                 for row in evidence),
            "random_candidate_correct_rate": statistics.mean(share),
            "random_candidate_relative_excess_pct_mean": statistics.mean(excess),
        },
    }


def accepted(summary: Record) -> bool:
    n, text = summary["graphs"], summary["text_only_program"]
    return (text["objective_equal"] == text["exact_cost_equal"] == n and not text["violations"]
            and all(value == n for value in text["correct"].values())
            and summary["prompts"]["v1_text_kept"] == summary["prompts"]["parsed"]
            and summary["prompts"]["v1_prompts_rejected"] == summary["prompts"]["parsed"])


def check(prompts_dir: Path, out: Path) -> Record:
    v1 = load_config("v1")
    graphs = load_graphs(v1)
    manifest = json.loads((prompts_dir / "manifest.json").read_bytes())
    verify(graphs, prompts_dir, manifest)
    prompts = load_prompts(prompts_dir)
    old = prompts_by_graph(v1, list(MODES))
    if any(len(prompts[mode]) != sum(map(len, old[mode].values())) for mode in MODES):
        raise LlmError("Prompt counts differ from the v1 export")
    counts: Counter[str] = Counter()
    evidence = []
    for graph in graphs:
        asked = [node["id"] for node in graph["nodes"] if node["stage"] in STAGES]
        kept = rejected = 0
        for mode in MODES:
            for question in asked:
                previous = old[mode][graph["id"]][question]
                kept += without_additions(prompts[mode][graph["id"], question]) == previous
                try:
                    parse(previous)
                except StatementError:
                    rejected += 1
        grade = Grader(graph, counts)
        solved, misread = text_only(graph, prompts, grade)
        evidence.append({**{key: graph[key] for key in ("id", "profile", "seed", "policy", "objective")},
                         "text_only": solved, "misreadings": misread, "v1_ceilings": ceilings(graph, grade),
                         "assembly": assembly(graph, grade), "v1_text_kept": kept, "v1_prompts_rejected": rejected})
    out.mkdir(parents=True, exist_ok=False)
    write_gzip(out / EVIDENCE, b"".join(canonical(row) + b"\n" for row in evidence))
    summary = {**summarize(evidence), "machine": platform.platform(), "python": platform.python_version(),
               "solves": sum(counts.values()), "prompts_manifest": digest(prompts_dir / "manifest.json")}
    summary["accepted"] = accepted(summary)
    (out / SUMMARY).write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                               encoding="utf-8", newline="\n")
    (out / "manifest.json").write_bytes(canonical({"algorithm": "SHA256", "files": {
        name: digest(out / name) for name in (EVIDENCE, SUMMARY)}}) + b"\n")
    return summary


def replay(prompts_dir: Path, directory: Path) -> Record:
    """Recompute the summary from the saved per-graph evidence without solving."""
    files = json.loads((directory / "manifest.json").read_bytes())["files"]
    if set(files) != {EVIDENCE, SUMMARY} or any(digest(directory / name) != value for name, value in files.items()):
        raise LlmError("Statement check files differ from their manifest")
    evidence = list(read_jsonl(directory / EVIDENCE))
    saved = json.loads((directory / SUMMARY).read_text(encoding="utf-8"))
    fresh = json.loads(json.dumps(summarize(evidence)))
    if any(saved[key] != value for key, value in fresh.items()) or saved["accepted"] != accepted(saved):
        raise LlmError("Statement check summary does not follow from its evidence")
    if saved["prompts_manifest"] != digest(prompts_dir / "manifest.json"):
        raise LlmError("Statement check used other prompt files")
    return {"graphs": saved["graphs"], "accepted": saved["accepted"], "solves": 0}
