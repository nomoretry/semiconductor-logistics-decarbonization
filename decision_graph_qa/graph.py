"""Visible questions, dependency edges and context rendering."""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

import numpy as np

from rolling_inventory.environment import carbon

from .planner import Model, Record, Schedule, allowance, original, scenarios, window


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


LABELS = {
    "t": ("决策期", "Decision period"), "public": ("公开参数", "Public parameters"),
    "stock": ("可用库存", "Available stock"), "backlog": ("未清积压", "Outstanding backlog"),
    "arrivals": ("本期到达", "Current arrivals"), "served_old": ("已清旧积压", "Old backlog served"),
    "pipeline": ("在途到达（绝对期次）", "Pipeline arrivals by absolute period"),
    "carbon_remaining": ("剩余排放预算", "Remaining emissions budget"),
    "history": ("历史需求", "Past demand"), "forecast": ("从当前起的均值预测", "Mean forecast from now"),
}


def state_text(obs: Record) -> dict[str, str]:
    if set(obs) != set(LABELS):
        raise ValueError("observation fields differ from the frozen environment")
    return {lang: "\n".join(f"{names[j]} ({key}) = {compact(obs[key])}"
                            for key, names in LABELS.items()) for j, lang in enumerate(("zh", "en"))}


def predictions(obs: Record, demand: Any) -> Record:
    h = window(obs)
    p = obs["public"]
    d = np.asarray(demand[:h])
    pipeline = np.asarray(obs["pipeline"][obs["t"]:obs["t"] + h])
    balances = np.subtract(obs["stock"], obs["backlog"]) + np.cumsum(pipeline - d, axis=0)
    peaks = np.maximum(0, -balances.min(axis=0))
    answers: Record = {}
    for i, peak in enumerate(peaks):
        offsets = np.flatnonzero(balances[:, i] < 0)
        answers[f"P2.sum.{i}"] = float(d[:3, i].sum())
        answers[f"P2.first.{i}"] = int(offsets[0]) if len(offsets) else None
        answers[f"P2.peak.{i}"] = float(peak)
    kg = float(peaks @ p["mass"])
    answers["P2.capacity"] = kg > p["capacity"][0] * max(0, h - p["lead"][0])
    answers["P2.carbon"] = kg * p["emissions"][0] > allowance(obs)
    return answers


def structure(obs: Record, plan: Schedule) -> tuple[list[Record], list[Record]]:
    p = obs["public"]
    t, h = obs["t"], window(obs)
    sku = range(len(p["mass"]))
    route = range(len(p["lead"]))
    pred = predictions(obs, obs["forecast"])
    nodes: list[Record] = []
    edges: list[Record] = []

    def node(key: str, zh: str, en: str, answer: Any) -> None:
        nodes.append({"id": key, "stage": key.split(".")[0], "question": {"zh": zh, "en": en},
                      "answer": answer})

    def parents(child: str, layer: str, keys: list[str]) -> None:
        edges.extend({"from": parent, "to": child, "layer": layer} for parent in keys)

    for i in sku:
        node(f"P1.stock.{i}", f"SKU {i} 可用库存多少件？", f"How many units of SKU {i} are available?",
             obs["stock"][i])
        node(f"P1.backlog.{i}", f"SKU {i} 未清积压多少件？", f"How many units of SKU {i} remain backlogged?",
             obs["backlog"][i])
        node(f"P1.pipeline.{i}", f"SKU {i} 各窗口期在途到达多少件（本期到达已入账）？",
             f"What outstanding arrivals of SKU {i} are due at each window offset (current receipts credited)?",
             [row[i] for row in obs["pipeline"][t:t + h]])
    node("P1.remaining", "剩余排放预算多少？", "What emissions budget remains?", obs["carbon_remaining"])
    node("P1.allowance", "本窗口排放额度多少？", "What is the paced emissions allowance for this window?",
         allowance(obs))
    parents("P1.allowance", "task", ["P1.remaining"])
    node("P1.routes", "本期发运且能在周期结束前到达的路线编号有哪些？",
         "Which route indices can deliver before episode end if dispatched now?",
         [j for j in route if t + p["lead"][j] < p["periods"]])
    for i in sku:
        descriptions = (
            ("sum", f"SKU {i} 接下来最多三期的预测需求合计多少件？",
             f"What is total forecast demand for SKU {i} over the next up to three periods?"),
            ("first", f"不再发货时 SKU {i} 首次预测缺口在哪个窗口偏移（没有填 null）？",
             f"With no new dispatch, at which offset does SKU {i} first have a forecast shortage (null if none)?"),
            ("peak", f"不再发货时 SKU {i} 的窗口最大累计预测缺口多少件？",
             f"With no new dispatch, what is SKU {i}'s peak cumulative forecast shortage in units?"))
        for name, zh, en in descriptions:
            key = f"P2.{name}.{i}"
            node(key, zh, en, pred[key])
            if name != "sum":
                parents(key, "task", [f"P1.{field}.{i}" for field in ("stock", "backlog", "pipeline")])
    for key, zh, en, parent in (
        ("P2.capacity", "各 SKU 最大缺口的总质量是否超过窗口内可达的慢线总运力？",
         "Does the mass of all SKU peak shortages exceed deliverable slow-route capacity?", "P1.routes"),
        ("P2.carbon", "若各 SKU 最大缺口均由慢线补货，排放是否超窗口额度？",
         "Would supplying all peak shortages by slow route exceed the window emissions allowance?", "P1.allowance")):
        node(key, zh, en, pred[key])
        parents(key, "object", [f"P2.peak.{i}" for i in sku])
        parents(key, "task", [parent])
    pressures = ["P2.capacity", "P2.carbon"]
    for i in sku:
        key = f"P3.ship.{i}"
        node(key, f"参照最优计划本期是否发运 SKU {i}？", f"Does an optimal plan dispatch SKU {i} now?",
             any(plan[0][i]))
        parents(key, "task", [f"P2.{name}.{i}" for name in ("sum", "first", "peak")])
        parents(key, "object", pressures)
    for j in route:
        key = f"P3.load.{j}"
        node(key, f"参照最优计划本期在路线 {j} 用多少 kg？",
             f"How many kg use route {j} now in an optimal plan?",
             sum(p["mass"][i] * plan[0][i][j] for i in sku))
        parents(key, "task", pressures)
    node("P3.emission", "参照最优计划本期发运排放多少？", "What are current dispatch emissions in an optimal plan?",
         carbon(plan[0], p))
    parents("P3.emission", "task", pressures)
    p3 = [n["id"] for n in nodes if n["stage"] == "P3"]
    node("B", "本期最优发运矩阵是什么（SKU × 路线，件）？",
         "What is an optimal current dispatch matrix (SKU × route, units)?", plan[0])
    parents("B", "task", [*p3, *pressures])
    node("M", "整个窗口的最优发运计划是什么（窗口偏移 × SKU × 路线，件）？",
         "What is an optimal full-window schedule (offset × SKU × route, units)?", plan)
    parents("M", "task", ["B", *p3])
    return nodes, edges


def context(graph: Record, node_id: str, mode: str, lang: str = "en",
            answers: Record | None = None) -> str:
    if mode not in graph["modes"] or lang not in ("zh", "en"):
        raise ValueError("unknown context mode or language")
    by_id = {n["id"]: n for n in graph["nodes"]}
    needed: set[str] = set()
    if mode != "None":
        for edge in reversed(graph["edges"]):
            if edge["to"] == node_id or (mode == "Graph" and edge["to"] in needed):
                needed.add(edge["from"])
    lines = [graph["state_text"][lang]]
    for key, n in by_id.items():
        if key in needed:
            answer = n["answer"] if answers is None else answers[key]
            lines.append(n["question"][lang] + "\n" + compact(answer))
    lines.append(by_id[node_id]["question"][lang])
    return "\n\n".join(lines)


def make_graph(task: Record, policy: str, obs: Record, counts: Counter[str]) -> Record:
    d = scenarios(obs)
    plan, optimum = original(obs, d, counts, "reference")
    ties = Model(obs, d, counts).audit(plan, optimum)
    nodes, edges = structure(obs, plan)
    actual = task["demand"][obs["t"]:obs["t"] + window(obs)]
    known, _ = original(obs, [actual], counts, "known_path")
    return {"id": f"{task['id']}/{policy}/{obs['t']}", "split": task["split"],
            "profile": task["profile"], "seed": task["seed"], "policy": policy,
            "observation": obs, "state_text": state_text(obs), "nodes": nodes, "edges": edges,
            "modes": ["None", "Chain", "Graph"], "objective": optimum, "ties": ties,
            "hindsight": {"prediction": predictions(obs, actual),
                          "first_action_with_known_demand": known[0]}}

