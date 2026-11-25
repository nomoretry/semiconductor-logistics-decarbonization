"""Plot the decision graph model pilot (protocol v2) from its saved evidence.

Run from the repository root:
    python -m scripts.plot_decision_graph_llm
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmark_results" / "decision_graph_qa_llm_v2"
OUTPUT = ROOT / "docs" / "results" / "decision_graph_qa_llm_pilot"
CONTEXTS = ("None", "Chain", "Graph")
COLORS = {"None": "#0072B2", "Chain": "#E69F00", "Graph": "#009E73"}
REFERENCE, INK, MUTED = "#9AA0A6", "#202124", "#5F6368"


def load() -> tuple[dict, list[dict], dict[str, int]]:
    from decision_graph_qa.llm.data import read_jsonl

    summary = json.loads((RESULTS / "pilot_S" / "summary_pilot_S.json").read_text(encoding="utf-8"))
    answers = list(read_jsonl(RESULTS / "pilot_S" / "responses.jsonl"))
    candidates = {row["id"]: row["assembly"]["candidates"]
                  for row in read_jsonl(RESULTS / "statement_check" / "statement_check.jsonl.gz")}
    return summary, answers, candidates


def correct_rates(summary: dict) -> list[tuple[str, float, str]]:
    references = summary["statement_references"]
    mean_forecast = references["misreadings"]["mean forecast used instead of the scenarios"]["correct_rate"]
    picked = references["assembly_from_p3_answers"]["random_candidate_correct_rate"]
    rows = [("Replenishment rule", summary["dq2_baselines"]["rule"]["stages"]["B"]["accuracy"], REFERENCE),
            ("Plan on the mean forecast", mean_forecast, REFERENCE),
            ("Random dispatch that agrees\nwith the P3 answers", picked, REFERENCE)]
    for context in CONTEXTS:
        rows.append((f"Model, {context}", summary["contexts"][context]["primary"]["metrics"]["accuracy"]["mean"],
                     COLORS[context]))
    return rows


def means(answers: list[dict], candidates: dict[str, int], field: str) -> dict[str, list[tuple[int, float]]]:
    groups: dict[str, list[tuple[int, float]]] = {}
    for context in CONTEXTS:
        rows = [row for row in answers if row["context"] == context]
        split = ([row for row in rows if candidates[row["graph"]] == 1],
                 [row for row in rows if candidates[row["graph"]] > 1])
        groups[context] = [(len(part), statistics.mean(float(row[field]) for row in part)) for part in split]
    return groups


def bars(axis, groups: dict[str, list[tuple[int, float]]], title: str, unit: str, style: str) -> None:
    width = 0.26
    for index, context in enumerate(CONTEXTS):
        for position, (_, value) in enumerate(groups[context]):
            x = position + (index - 1) * (width + 0.02)
            axis.bar(x, value, width, color=COLORS[context], label=context if position == 0 else None)
            axis.annotate(style.format(value), (x, value), xytext=(0, 3), textcoords="offset points", ha="center",
                          fontsize=9, color=INK)
    counts = [count for count, _ in groups["None"]]
    axis.set_xticks([0, 1], [f"P3 answers leave\none dispatch ({counts[0]} graphs)",
                             f"P3 answers leave\nseveral ({counts[1]} graphs)"], fontsize=9)
    axis.set_ylabel(unit, fontsize=9, color=MUTED)
    axis.set_title(title, fontsize=10.5, loc="left", color=INK)
    axis.set_ylim(0, max(value for group in groups.values() for _, value in group) * 1.18)


def plot() -> list[Path]:
    summary, answers, candidates = load()
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.hashsalt": "decision-graph-qa-llm-pilot"})
    figure, axes = plt.subplots(1, 3, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1.25, 1, 1]})
    rows = correct_rates(summary)
    axis = axes[0]
    for position, (_, rate, color) in enumerate(reversed(rows)):
        axis.barh(position, 100 * rate, 0.62, color=color)
        axis.annotate(f"{100 * rate + 1e-9:.1f}%", (100 * rate, position), xytext=(4, 0), textcoords="offset points",
                      va="center", fontsize=9, color=INK)
    axis.set_yticks(range(len(rows)), [label for label, _, _ in reversed(rows)], fontsize=9)
    axis.set_xlim(0, 118)
    axis.set_xticks([0, 25, 50, 75, 100])
    axis.set_xlabel("Optimal current dispatches (%)", fontsize=9, color=MUTED)
    axis.set_title("Optimal dispatches on the 32 pilot graphs", fontsize=10.5, loc="left", color=INK)
    bars(axes[1], means(answers, candidates, "actual_usd"), "Cost per decision", "Mean US$", "{:.3f}")
    bars(axes[2], means(answers, candidates, "seconds"), "Time per decision", "Mean seconds", "{:.0f}")
    axes[1].legend(title="Context", fontsize=8.5, title_fontsize=8.5, frameon=False, loc="upper left")
    for axis in axes:
        axis.tick_params(colors=MUTED, length=0)
        for side in ("top", "right", "left"):
            axis.spines[side].set_visible(False)
        axis.spines["bottom"].set_color("#DADCE0")
    axes[1].grid(axis="y", color="#ECEFF1", linewidth=0.8)
    axes[2].grid(axis="y", color="#ECEFF1", linewidth=0.8)
    axes[0].grid(axis="x", color="#ECEFF1", linewidth=0.8)
    for axis in axes:
        axis.set_axisbelow(True)
    figure.suptitle("A language model on 32 small dispatch problems: every answer optimal, and the planning answers save "
                    "cost only where they fix the dispatch", fontsize=12, x=0.01, ha="left", color=INK)
    timing = summary["reference_timing"]["reference_median_seconds"]
    total = summary["cumulative_selected_task_ledger"]["settled_usd"]
    figure.text(0.01, 0.005, (
        f"gpt-6.2-sol, effort max, one run per question, 96 calls, US${total:.2f} in total. Reference planner: median "
        f"{timing:.3f} s, no fee. 32 of 32 correct: exact 95% lower bound 89.1%. One synthetic environment, protocol v2.\n"
        "Data: benchmark_results/decision_graph_qa_llm_v2 (pilot_S, statement_check). None: rules, state, scenarios; "
        "Chain: plus direct parents' answers; Graph: plus all ancestors' answers."),
        fontsize=8, color=MUTED, ha="left", va="bottom")
    figure.tight_layout(rect=(0, 0.085, 1, 0.985))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    paths = [OUTPUT.with_suffix(".png"), OUTPUT.with_suffix(".svg")]
    figure.savefig(paths[0], dpi=170, metadata={"Software": None})
    figure.savefig(paths[1], metadata={"Date": None})
    plt.close(figure)
    return paths


if __name__ == "__main__":
    for path in plot():
        print(path.relative_to(ROOT))
