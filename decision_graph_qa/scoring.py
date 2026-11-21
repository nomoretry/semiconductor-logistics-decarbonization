"""Grade each response independently, allowing alternate optimal decisions."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np

from .planner import (
    INF,
    Model,
    Record,
    Row,
    allowance,
    feasible_plan,
    physical_cost,
    scenarios,
    tolerance,
)


def matches(expected: Any, reply: Any) -> bool:
    if isinstance(expected, float):
        return (type(reply) in (int, float) and abs(reply) < 1e100
                and math.isfinite(reply) and abs(reply - expected) <= tolerance(expected))
    if type(expected) is not type(reply):
        return False
    if isinstance(expected, list):
        return len(expected) == len(reply) and all(matches(a, b) for a, b in zip(expected, reply))
    return bool(expected == reply)


def constrained(model: Model, key: str, reply: Any) -> tuple[bool, float | None]:
    rows: list[Row] = []
    if key == "B":
        if not feasible_plan(model.obs, [reply], first=True):
            return False, None
        rows.extend(({k: 1.0}, q, q) for k, q in enumerate(v for row in reply for v in row))
    elif key.startswith("P3.ship."):
        if type(reply) is not bool:
            return False, None
        flag = model.flags[int(key.split(".")[2])]
        rows.append((flag, 1, INF) if reply else (flag, 0, 0))
    else:
        if type(reply) is not int or reply < 0:
            return False, None
        if key == "P3.emission":
            terms, cap = model.emission, allowance(model.obs)
        else:
            j = int(key.split(".")[2])
            terms, cap = model.loads[j], model.obs["public"]["capacity"][j]
        if reply > cap:
            return False, None
        rows.append((terms, reply, reply))
    plan = model.optimize("score_constraint", tuple(rows))
    return (False, None) if plan is None else (True, model.value(plan))


def grade_graph(graph: Record, answers: Record, counts: Counter[str]) -> list[Record]:
    obs = graph["observation"]
    d = scenarios(obs)
    model = Model(obs, d, counts)
    expected_ids = {n["id"] for n in graph["nodes"]}
    if answers.keys() - expected_ids:
        raise ValueError(f"unknown node IDs for {graph['id']}")
    out: list[Record] = []
    for node in graph["nodes"]:
        key, stage = node["id"], node["stage"]
        row: Record = {"id": key, "stage": stage, "provided": key in answers,
                       "correct": False, "violation": False, "excess": None, "l1": None}
        out.append(row)
        if key not in answers:
            continue
        reply = answers[key]
        if stage in ("P1", "P2"):
            row["correct"] = matches(node["answer"], reply)
            continue
        if stage == "M":
            feasible = feasible_plan(obs, reply)
            value = physical_cost(obs, reply, d) if feasible else None
            if feasible:
                row["l1"] = int(np.abs(np.subtract(reply, node["answer"])).sum())
        else:
            feasible, value = constrained(model, key, reply)
        row["violation"] = not feasible
        if value is not None:
            row["excess"] = value - graph["objective"]
            row["correct"] = row["excess"] <= tolerance(graph["objective"])
    return out


def answer_map(graph: Record, perturb: bool = False) -> Record:
    answers = {n["id"]: n["answer"] for n in graph["nodes"]}
    if perturb:
        answers["P1.stock.0"] += 1
        answers["P2.capacity"] = not answers["P2.capacity"]
        answers["P3.emission"] = -1
        answers["B"] = [[-1, 0], [0, 0], [0, 0]]
        answers["M"] = []
    return answers

