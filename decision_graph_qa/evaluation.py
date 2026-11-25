"""Render DQ-2 inputs and evaluate responses against the frozen decision graphs."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from functools import partial
from pathlib import Path
from typing import TypeVar

from rolling_inventory.environment import Environment
from rolling_inventory.planning import base_stock

from .ablation import ABLATIONS, ablation_action
from .consequence import Consequences, ContinuationFailure
from .dataset import SEEDS, records
from .graph import compact, context, structure
from .planner import (
    AuditFailure,
    Model,
    PlannerMismatch,
    Record,
    SolveFailure,
    scenarios,
    tolerance,
    window,
)
from .scoring import answer_map, constrained, grade_graph

MODES = ("None", "Chain", "Graph")
SOURCES = ("gold", "own")
LANGUAGES = ("zh", "en")
ANSWERERS = ("gold", "perturbed", "rule", "file")
ABSENT = object()
MISSING_CONTEXT = {"status": "unanswered"}
Response = Callable[[str, str], object]
Result = TypeVar("Result")


class EvaluationStop(RuntimeError):
    """An evaluation acceptance condition was violated."""


def read_answers(path: Path) -> dict[str, Record]:
    submissions: dict[str, Record] = {}
    for row in records(path):
        gid, answers = row.get("id"), row.get("answers")
        if not isinstance(gid, str) or not isinstance(answers, dict) or gid in submissions:
            raise ValueError(f"{path.name}: invalid or duplicate response record")
        submissions[gid] = answers
    return submissions


def rule_answers(graph: Record) -> Record:
    obs = graph["observation"]
    action, _ = base_stock(obs, 1.0)  # type: ignore[no-untyped-call]
    zero = [[0 for _ in obs["public"]["lead"]] for _ in obs["public"]["mass"]]
    # DQ-1 builds P1/P2 directly from the observation and P3 from the first action.
    nodes, _ = structure(obs, [action, *([zero] * (window(obs) - 1))])
    return {node["id"]: node["answer"] for node in nodes}


def render_answers(graph: Record, mode: str, source: str, lang: str,
                   respond: Response) -> tuple[Record, int]:
    if source not in SOURCES:
        raise ValueError("unknown upstream answer source")
    upstream: Record | None = {node["id"]: MISSING_CONTEXT for node in graph["nodes"]} if source == "own" else None
    answers: Record = {}
    characters = 0
    for node in graph["nodes"]:
        key = node["id"]
        prompt = context(graph, key, mode, lang, upstream)
        characters += len(prompt)
        value = respond(key, prompt)
        if value is not ABSENT:
            answers[key] = value
            if upstream is not None:
                upstream[key] = value
    return answers, characters


def export_prompts(data: Path, *, split: str, mode: str, source: str, lang: str,
                   out: Path, submissions: Mapping[str, Record] | None = None) -> Record:
    if split not in SEEDS or mode not in MODES or source not in SOURCES or lang not in LANGUAGES:
        raise ValueError("unknown split, context mode, source or language")
    if source == "own" and submissions is None:
        raise ValueError("own context requires an answer file")
    n = characters = 0
    with out.open("x", encoding="utf-8", newline="\n") as output:
        for graph in records(data / f"{split}.jsonl"):
            submitted = {} if submissions is None else submissions.get(graph["id"], {})
            upstream = ({node["id"]: submitted.get(node["id"], MISSING_CONTEXT) for node in graph["nodes"]}
                        if source == "own" else None)
            for node in graph["nodes"]:
                key = node["id"]
                prompt = context(graph, key, mode, lang, upstream)
                output.write(compact({"id": graph["id"], "node_id": key, "stage": node["stage"],
                                      "mode": mode, "source": source, "lang": lang,
                                      "prompt": prompt, "characters": len(prompt)}) + "\n")
                n += 1
                characters += len(prompt)
    return {"prompts": n, "characters": characters}


def empty_graph(graph: Record) -> Record:
    return {key: graph[key] for key in ("id", "split", "profile", "seed", "policy", "objective")}


def _stored_reply(answers: Record, key: str, _prompt: str) -> object:
    return answers.get(key, ABSENT)


def gold_check(graph: Record, scored: Record, *, expected: int | None = None) -> None:
    nodes = scored["nodes"]
    outcome = scored["consequence"]
    size = len(graph["nodes"]) if expected is None else expected
    if (nodes is None or len(nodes) != size or not all(node["correct"] for node in nodes)
            or outcome is None or outcome["status"] != "ok"):
        raise EvaluationStop(f"{graph['id']}: gold score or realized consequence failed")
    excess = next(node["excess"] for node in nodes if node["id"] == "B")
    if excess is None or abs(excess) > tolerance(graph["objective"]) or any(
        abs(value) > tolerance(outcome["reference"][key]) for key, value in outcome["delta"].items()
    ):
        raise EvaluationStop(f"{graph['id']}: nonzero gold B difference")


def evaluate_graph(graph: Record, env: Environment, submitted: Record, row: Record,
                   counts: Counter[str], prior_calls: int, prior_failures: int) -> None:
    """Populate the raw row even when a registered stopping condition fires."""
    consequence = Consequences(env, graph, counts)
    gold = answer_map(graph)
    responders = {"gold": gold, "perturbed": answer_map(graph, perturb=True),
                  "rule": rule_answers(graph), "file": submitted}
    unknown = submitted.keys() - gold.keys()
    if unknown:
        raise EvaluationStop(f"{graph['id']}: unknown submitted node IDs: {sorted(unknown)}")
    score_cache: dict[str, Record] = {}

    def attempt(label: str, operation: Callable[[], Result]) -> Result | None:
        try:
            return operation()
        except (AuditFailure, PlannerMismatch) as exc:
            row["errors"].append({"label": label, "message": str(exc), "type": type(exc).__name__,
                                  "diagnostics": getattr(exc, "diagnostics", None)})
            row["failed_calls"] += 1
            raise EvaluationStop(f"{graph['id']} {label}: {exc}") from exc
        except SolveFailure as exc:
            cached = isinstance(exc, ContinuationFailure) and exc.cached
            row["errors"].append({"label": label, "message": str(exc), "type": type(exc).__name__,
                                  "cached": cached, "evidence": getattr(exc, "evidence", None)})
            row["failed_calls"] += int(not cached)
            if (prior_failures + row["failed_calls"]) / (prior_calls + counts.total()) > 0.01:
                raise EvaluationStop(f"{graph['id']} {label}: failed solve rate exceeded 1%") from exc
            return None

    def compare(label: str, b: object) -> Record | None:
        return attempt(label, lambda: consequence.compare(b))

    try:
        for name in ANSWERERS:
            reply = responders[name]
            modes: Record = {}
            row["baselines"][name] = modes
            for mode in MODES:
                modes[mode] = {}
                for source in SOURCES:
                    answers, chars = render_answers(graph, mode, source, "en", partial(_stored_reply, reply))
                    signature = compact(answers)
                    if signature not in score_cache:
                        nodes = attempt(f"{name}:score", partial(grade_graph, graph, answers, counts))
                        b = answers.get("B")
                        effects = compare(f"{name}:B", b) if "B" in answers else None
                        if nodes is not None and effects is not None:
                            dispatch = next(node for node in nodes if node["id"] == "B")
                            if dispatch["violation"] != (effects["status"] == "violation"):
                                raise EvaluationStop(f"{graph['id']} {name}: planned and realized feasibility disagreed")
                        score_cache[signature] = {"answers": answers, "nodes": nodes, "action": b,
                                                  "consequence": effects}
                    else:
                        scored = score_cache[signature]
                        if scored["consequence"] is not None and "B" in answers:
                            compare(f"{name}:B", answers["B"])
                    result = {**score_cache[signature], "prompt_characters": chars}
                    modes[mode][source] = result
                    if name == "gold":
                        gold_check(graph, result)

        obs = graph["observation"]
        model = Model(obs, scenarios(obs), counts)
        for name in ABLATIONS:
            result = dict.fromkeys(("changed", "plan_excess", "relative_plan_excess", "cost_delta",
                                    "fill_rate_delta", "emissions_delta", "violation", "action", "consequence"))
            row["ablations"][name] = result
            action = attempt(f"{name}:action", partial(ablation_action, graph, name, counts))
            if action is None:
                continue
            result.update(action=action, changed=action != gold["B"])
            # Gold's fixed-action solve already supplies the excess when B is unchanged.
            if action == gold["B"]:
                fit: tuple[bool, float | None] | None = True, graph["objective"]
            else:
                fit = attempt(f"{name}:score", partial(
                    constrained, model, "B", action, graph_id=graph["id"], reference_plan=gold["M"],
                    reference_objective=graph["objective"],
                ))
            effects = compare(f"{name}:B", action)
            result["consequence"] = effects
            if fit is not None:
                feasible, value = fit
                result["violation"] = not feasible
                if value is not None:
                    result["plan_excess"] = value - graph["objective"]
                    if graph["objective"]:
                        result["relative_plan_excess"] = result["plan_excess"] / graph["objective"]
            if effects is not None:
                violation = effects["status"] == "violation"
                if fit is not None and violation != result["violation"]:
                    raise EvaluationStop(f"{graph['id']} {name}: planned and realized feasibility disagreed")
                result["violation"] = violation
                if not violation:
                    for key in ("cost", "fill_rate", "emissions"):
                        result[f"{key}_delta"] = effects["delta"][key]
    finally:
        row["cache_hits"] = consequence.cache_hits


def check_submissions(items: Iterable[Record], answers: dict[str, Record]) -> None:
    unknown = answers.keys() - {row["id"] for row in items}
    if unknown:
        raise ValueError(f"unknown submitted graph IDs: {sorted(unknown)}")
