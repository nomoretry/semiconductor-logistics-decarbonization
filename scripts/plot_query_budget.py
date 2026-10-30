"""Plot measured development quality and complete-task solver effort."""
import argparse
import json
from pathlib import Path


def plot(summary, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.hashsalt": "query-budget-v1", "font.size": 10})
    labels = {"myopic_index": "One-step / index", "myopic_priority": "One-step / priority",
              "lookahead_two": "Two-step lookahead", "iterative_dp": "Iterative DP"}
    caps = [5, 13, 33, 65]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for (method, label), marker, style in zip(labels.items(), ("o", "s", "^", "D"), ("-", "--", "-.", ":")):
        cells = [summary["cohorts"]["all"][str(b)][method] for b in caps]
        axes[0].plot(caps, [100*c["mean_regret"] for c in cells], marker=marker, linestyle=style, label=label)
        axes[1].plot(caps, [c["expected_milp_calls"] for c in cells], marker=marker, linestyle=style)
    axes[0].set_yscale("log")
    axes[0].set_ylabel("Mean cost gap to exact DP (%) — log scale")
    axes[1].set_ylabel("Expected MILP calls per complete task")
    for ax in axes:
        ax.set_xlabel("MILP call cap per decision")
        ax.set_xticks(caps); ax.grid(alpha=.2)
    axes[0].legend(fontsize=9)
    fig.suptitle("54 development contexts · Same per-decision call caps")
    fig.text(.5, .015, "Known orders and disclosed priors. Calls are a compute proxy, not equal wall time. Budget 1 omitted from plot.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .045, 1, .96))
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"Date": None} if output.suffix == ".svg" else None
    fig.savefig(output, metadata=metadata, dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=Path("benchmark_results/query_budget_development/summary.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/query_budget_tradeoff.svg"))
    args = parser.parse_args(); plot(json.loads(args.summary.read_text()), args.output)


if __name__ == "__main__":main()
