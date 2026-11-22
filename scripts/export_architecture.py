"""Draw the planning agent architecture as SVG and PDF for formal reports (docs/figures/).

The Mermaid diagram in docs/technical_overview.md shows the same connections on GitHub.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

INK, MUTED, EDGE = "#0b0b0b", "#52514e", "#8a8984"
FILL = {"input": "#ffffff", "agent": "#dbe9fb", "solver": "#d8f1e7", "check": "#fdeedb", "output": "#ffffff",
        "guard": "#f1f0ec"}
BOXES = {
    "notice": (0.00, 0.60, "input", "Business question or\ncarrier notice", ""),
    "parse": (0.215, 0.80, "agent", "Retrieval and parsing", "retrieval.py, rules.py, model"),
    "confirm": (0.43, 0.80, "check", "Planner confirms", "workflow.py"),
    "agent": (0.215, 0.40, "agent", "Agent decisions", "graph.py, agent.py, rules.py"),
    "tools": (0.43, 0.40, "agent", "Tool layer", "tools.py: 8 tools, validation"),
    "solver": (0.645, 0.60, "solver", "Optimisation (HiGHS)", "network_planning: MILP, two-stage"),
    "check": (0.645, 0.20, "check", "Result checks", "accounting.py, guardrails.py"),
    "memo": (0.86, 0.20, "output", "Decision report", "memo.py"),
    "limits": (0.215, 0.08, "guard", "Limits and key handling", "spending.py, llm.py"),
}
WIDTH, HEIGHT = 0.172, 0.13
ARROWS = (("notice", "parse", ""), ("notice", "agent", ""), ("parse", "confirm", ""), ("confirm", "tools", ""),
          ("agent", "tools", "calls"), ("tools", "agent", "results"), ("tools", "solver", ""), ("solver", "check", ""),
          ("check", "tools", ""), ("check", "memo", ""), ("limits", "agent", "before each request"))


def draw(output: Path) -> list[Path]:
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "path", "pdf.fonttype": 42})
    fig, ax = plt.subplots(figsize=(13, 5.6))
    ax.set_xlim(-0.005, 1.045)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title("Planning agent: from a notice to a decision report", loc="left", fontsize=14, color=INK, pad=12)
    for x, y, kind, title, source in BOXES.values():
        ax.add_patch(FancyBboxPatch((x, y), WIDTH, HEIGHT, boxstyle="round,pad=0.004,rounding_size=0.012",
                                    facecolor=FILL[kind], edgecolor=EDGE, linewidth=1.0))
        ax.text(x + WIDTH / 2, y + HEIGHT * (0.62 if source else 0.5), title, ha="center", va="center", fontsize=9,
                color=INK, fontweight="bold")
        if source:
            ax.text(x + WIDTH / 2, y + HEIGHT * 0.27, source, ha="center", va="center", fontsize=6.8, color=MUTED)

    def anchor(name: str, towards: str) -> tuple[float, float]:
        x, y = BOXES[name][:2]
        tx, ty = BOXES[towards][:2]
        if abs(tx - x) >= abs(ty - y) and tx != x:
            return (x + WIDTH if tx > x else x), y + HEIGHT / 2
        return x + WIDTH / 2, (y + HEIGHT if ty > y else y)

    for start, end, label in ARROWS:
        a, b = anchor(start, end), anchor(end, start)
        bend = 0.18 if {start, end} == {"agent", "tools"} else 0.0
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=11, linewidth=1.0, color=MUTED,
                                     connectionstyle=f"arc3,rad={bend}",
                                     linestyle="--" if start == "limits" else "-"))
        if label:
            offset = 0.05 if start == "agent" else -0.05
            ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + offset, label, ha="center", va="center", fontsize=7.5,
                    color=MUTED)
    fig.text(0.02, 0.02, "Every number comes from the solver and is checked against tool results. Networks, demand and "
             "rates are synthetic. Earlier research lines (notice benchmark, query learning, rolling inventory) are "
             "separate paths.", fontsize=7.5, color=MUTED)
    output.mkdir(parents=True, exist_ok=True)
    paths = [output / "system_architecture.svg", output / "system_architecture.pdf"]
    for path in paths:
        fig.savefig(path, bbox_inches="tight", metadata={"Date": None} if path.suffix == ".svg" else None)
    plt.close(fig)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("docs/figures"))
    for path in draw(parser.parse_args().output):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
