"""Verify report populations, paired comparisons, and generated artifacts."""

import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import create_reports


def episode(seed, policy, cost=100, emissions=100, feasible=True, **changes):
    row = {
        "project": "asml", "case": "normal", "demand_set": "synthetic_weekly",
        "seed": seed, "policy": policy, "feasible": feasible, "optimal": feasible,
        "total_cost": cost if feasible else None,
        "total_emissions": emissions if feasible else None,
        "freight_cost": 0, "transit_capital_cost": 0, "holding_cost": 0,
        "mean_total_inventory": 0, "air_mass_share": 0, "fill_rate": 1,
    }
    row.update(changes)
    return row


class PairedReportTests(unittest.TestCase):
    def test_pairs_use_same_seed_and_ignore_external_or_infeasible_rows(self):
        rows = [
            episode(1, "cost_only", 100, 100),
            episode(2, "cost_only", 300, 300),
            episode(1, "carbon_minus25", 120, 80),
            episode(2, "carbon_minus25", 330, 240),
            episode(3, "cost_only", feasible=False),
            episode(3, "carbon_minus25", 999, 1),
            episode(4, "cost_only", 100, 100),
            episode(4, "carbon_minus25", feasible=False),
            episode(5, "carbon_minus25", 999, 1),
            episode(1, "carbon_minus25", 999, 1, demand_set="real_carparts_monthly"),
        ]
        result = create_reports.paired_tradeoffs(rows, bootstrap_samples=1000)
        self.assertEqual(len(result), 1)
        comparison = result[0]
        self.assertEqual(comparison["n"], 2)
        self.assertEqual(comparison["cost_reference"], 200)
        self.assertEqual(comparison["cost_budget25"], 225)
        self.assertAlmostEqual(comparison["cost_increase_pct"], 12.5)
        self.assertAlmostEqual(comparison["emissions_reduction_pct"], 20)
        self.assertEqual(result, create_reports.paired_tradeoffs(list(reversed(rows)), 1000))

    def test_frontier_requires_all_four_policies_on_same_seeds(self):
        rows = [episode(seed, policy, cost=100 + i, emissions=100 - i)
                for seed in (1, 2)
                for i, policy in enumerate(("cost_only", "carbon_minus10", "carbon_minus25", "carbon_minus50"))]
        rows[-1] = episode(2, "carbon_minus50", feasible=False)
        with tempfile.TemporaryDirectory() as directory:
            counts = create_reports.create_frontier_plot(rows, Path(directory))
            self.assertIn(("asml", "normal", 1), counts)
            self.assertEqual(create_reports.paired_tradeoffs(rows)[0]["n"], 2)
            self.assertTrue((Path(directory) / "cost_carbon_frontier.png").is_file())
            self.assertTrue((Path(directory) / "cost_carbon_frontier.svg").is_file())

    def test_archived_means_do_not_replace_current_detail_statistics(self):
        rows = [episode(1, "cost_only", 100, 100), episode(1, "carbon_minus25", 110, 75)]
        archive = [
            {"project": "asml", "demand_set": "synthetic_weekly", "n": 360},
            {"project": "asml", "demand_set": "real_carparts_monthly", "policy": "cost_only",
             "n": 40, "feasible_n": 40, "total_cost": 999999, "total_emissions": 999999},
        ]
        pilot = {"numerical_replays": [], "notices": 12, "exact_matches": 12, "ambiguity_abstentions": 2}
        counts = [("asml", case, 0) for case in create_reports.CASES]
        report = create_reports.render_report(
            rows, archive, {"total_solves": 400}, pilot,
            create_reports.paired_tradeoffs(rows), counts, 24,
        )
        self.assertIn("含2次周度求解", report)
        self.assertIn("合计400次求解", report)
        self.assertIn("40次来自汽车备件月度需求", report)
        self.assertIn("| ASML | 正常运输 | 1 | 100.00 | 110.00 | +10.00%", report)
        current_tables, external_section = report.split("## 外部月度需求：归档压力测试")
        self.assertNotIn("999,999.00", current_tables)
        self.assertIn("999,999.00", external_section)


class ReportGenerationTests(unittest.TestCase):
    def test_main_generates_markdown_tables_and_external_plot_files(self):
        source = Path(__file__).resolve().parents[1] / "reports"
        with tempfile.TemporaryDirectory() as directory:
            report_dir = Path(directory) / "reports"
            report_dir.mkdir()
            for name in ("episodes", "summary", "notice_pilot", "run_manifest", "sensitivity"):
                shutil.copyfile(source / f"{name}.json", report_dir / f"{name}.json")
            with patch.object(create_reports, "ROOT", Path(directory)), contextlib.redirect_stdout(io.StringIO()):
                create_reports.main()
            report = (report_dir / "study_report.md").read_text(encoding="utf-8")
            self.assertTrue(report.startswith("# 低碳半导体物流"))
            self.assertIn("(cost_carbon_frontier.png)", report)
            self.assertNotIn("data:image", report)
            self.assertNotIn("<html", report)
            self.assertFalse((report_dir / "study_report.html").exists())
            self.assertTrue((report_dir / "cost_carbon_frontier.png").read_bytes().startswith(b"\x89PNG"))
            self.assertIn("<svg", (report_dir / "cost_carbon_frontier.svg").read_text())
            pairs = json.loads((report_dir / "paired_tradeoffs.json").read_text())
            self.assertEqual(len(pairs), 6)
            self.assertTrue(all(row["n"] == 10 for row in pairs))
            self.assertEqual(len((report_dir / "paired_tradeoffs.csv").read_text().splitlines()), 7)

    def test_help_exits_without_reading_or_writing_report_files(self):
        with patch.object(create_reports, "ROOT", Path("/nonexistent-report-fixture")), \
                contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as exit_status:
            create_reports.main(["--help"])
        self.assertEqual(exit_status.exception.code, 0)
        self.assertIn("Markdown study report", output.getvalue())


if __name__ == "__main__":
    unittest.main()
