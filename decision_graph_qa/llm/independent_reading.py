"""Run and grade the archived program that was written from the question texts alone.

The program is an exact integer dynamic programme. It was written with access to the stored question texts and the
fixed answer instructions only, not to this repository, the data or the reference answers, and it is kept as written.
"""
from __future__ import annotations

import importlib.util
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path
from types import ModuleType

from ..planner import Record, tolerance
from ..scoring import answer_map, grade_graph
from .data import LlmError, canonical, digest, load_config, read_jsonl
from .statement import STAGES, prompt_file, write_gzip
from .statement_check import load_graphs

PROGRAM = "solver.py"
EVIDENCE = "answers.jsonl.gz"
SUMMARY = "summary.json"
FILES = (PROGRAM, EVIDENCE, SUMMARY)


def load_program(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("independent_text_solver", path)
    if spec is None or spec.loader is None:
        raise LlmError("The archived program cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def answer(program: ModuleType, texts: dict[str, str]) -> Record:
    """Answer the questions of one graph, each from its own text, and list every optimal current dispatch."""
    cost: Fraction | None = None
    dispatches: list[list[list[int]]] = []
    answers: Record = {}
    for node, text in texts.items():
        data, question = program.parse(text)
        kind, argument = program.parse_question(question)
        problem = program.Problem(data)
        solution = program.solve_problem(problem)
        if cost is not None and (cost, dispatches) != (solution["cost"], solution["matrices"]):
            raise LlmError("Texts of one graph lead to different optima")
        cost, dispatches = solution["cost"], solution["matrices"]
        chosen = dispatches[program.choose(kind, argument, dispatches)]
        answers[node] = program.answer_from(problem, chosen, kind, argument)
    return {"answers": answers, "cost": str(cost), "dispatches": dispatches}


def run(program: ModuleType, prompts_dir: Path, graphs: list[Record]) -> list[Record]:
    texts: dict[str, dict[str, str]] = {}
    for row in read_jsonl(prompts_dir / prompt_file("None")):
        texts.setdefault(row["id"], {})[row["node_id"]] = row["prompt"]
    return [{"id": graph["id"], **answer(program, texts[graph["id"]])} for graph in graphs]


def summarize(rows: list[Record], graphs: list[Record]) -> Record:
    """Grade with the frozen scorer and compare the optimal dispatches with the dataset's tie audit."""
    counts: Counter[str] = Counter()
    correct: Counter[str] = Counter()
    asked: Counter[str] = Counter()
    agreement: Counter[str] = Counter()
    violations = 0
    for graph, row in zip(graphs, rows, strict=True):
        if row["id"] != graph["id"] or set(row["answers"]) != {
                node["id"] for node in graph["nodes"] if node["stage"] in STAGES}:
            raise LlmError(f"{graph['id']}: answers do not cover the questions")
        for grade in grade_graph(graph, row["answers"], counts):
            if grade["provided"]:
                asked[grade["id"]] += 1
                correct[grade["id"]] += grade["correct"]
                violations += grade["violation"]
        ties, mass, optimum = graph["ties"], graph["observation"]["public"]["mass"], graph["objective"]
        options = row["dispatches"]
        loads = [[sum(m * units[j] for m, units in zip(mass, option, strict=True)) for option in options]
                 for j in range(len(ties["load_ranges"]))]
        flags = [len({any(option[i]) for option in options}) > 1 for i in range(len(mass))]
        agreement["objective"] += abs(float(Fraction(row["cost"])) - optimum) <= tolerance(optimum)
        agreement["other optimal dispatch exists"] += (len(options) > 1) == ties["other_action"]
        agreement["dispatch flags with both values"] += flags == ties["opposite_flags"]
        agreement["route load ranges"] += [[min(load), max(load)] for load in loads] == ties["load_ranges"]
        agreement["reference dispatch is listed"] += answer_map(graph)["B"] in options
    states = {json.dumps(graph["observation"], sort_keys=True) for graph in graphs}
    return {"graphs": len(graphs), "different_states": len(states), "questions": sum(asked.values()),
            "correct": dict(sorted(correct.items())), "violations": violations,
            "graphs_with_several_optimal_dispatches": sum(len(row["dispatches"]) > 1 for row in rows),
            "agreement_with_dataset": dict(sorted(agreement.items()))}


def check(prompts_dir: Path, directory: Path) -> Record:
    """Run the archived program on every stored question and write the evidence next to it."""
    graphs = load_graphs(load_config("v1"))
    rows = run(load_program(directory / PROGRAM), prompts_dir, graphs)
    summary = {**summarize(rows, graphs), "prompts_manifest": digest(prompts_dir / "manifest.json"),
               "contexts": ["None"]}
    write_gzip(directory / EVIDENCE, b"".join(canonical(row) + b"\n" for row in rows))
    (directory / SUMMARY).write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                                     encoding="utf-8", newline="\n")
    (directory / "manifest.json").write_bytes(canonical({"algorithm": "SHA256", "files": {
        name: digest(directory / name) for name in FILES}}) + b"\n")
    return summary


def replay(prompts_dir: Path, directory: Path, limit: int | None = None) -> Record:
    """Repeat the program on the first graphs (all by default) and compare it with the saved evidence."""
    files = json.loads((directory / "manifest.json").read_bytes())["files"]
    if set(files) != set(FILES) or any(digest(directory / name) != value for name, value in files.items()):
        raise LlmError("Independent reading files differ from their manifest")
    graphs = load_graphs(load_config("v1"))[:limit]
    saved = list(read_jsonl(directory / EVIDENCE))
    rows = run(load_program(directory / PROGRAM), prompts_dir, graphs)
    if rows != saved[:len(graphs)]:
        raise LlmError("The archived program gave different answers")
    summary = summarize(rows, graphs)
    if limit is None:
        stored = json.loads((directory / SUMMARY).read_text(encoding="utf-8"))
        if any(stored[key] != value for key, value in summary.items()) or (
                stored["prompts_manifest"] != digest(prompts_dir / "manifest.json")):
            raise LlmError("Independent reading summary does not follow from its evidence")
    return summary
