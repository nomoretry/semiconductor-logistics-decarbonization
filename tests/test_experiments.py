"""Checks for experiment units, notice compilation and common service targets."""

import contextlib
import copy
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from shared import experiments


def tiny_config():
    """One-tonne SKU makes the kg-to-tonne conversion independently visible."""
    return {
        "routes": [
            {"name": "NL_air", "origin": "NL", "mode": "air", "lead": 1,
             "distance_km": 100, "freight_usd_per_kg": 2, "capacity": 20},
            {"name": "NL_ocean", "origin": "NL", "mode": "ocean", "lead": 2,
             "distance_km": 200, "freight_usd_per_kg": .5, "capacity": 20},
        ],
        "route_origin": ["NL", "NL"], "origin_capacity": [30],
        "eligibility": [[1], [1]], "mass_kg": [1000],
        "unit_value_usd": [5200], "annual_carry_rate": .1,
        "warehouse_usd_per_unit_period": 3,
        "warehouse_kgco2e_per_unit_period": .25,
        "mean_order_units": [1], "zero_demand_probability": .1,
        "period": "week", "horizon": 6,
    }


class NoticeCompilerTests(unittest.TestCase):
    def test_one_based_inclusive_dispatch_periods_and_no_input_mutation(self):
        original = tiny_config()
        snapshot = copy.deepcopy(original)
        notice = {"status": "ready", "changes": [
            {"op": "add_lead", "route": "NL_ocean", "start_week": 2, "end_week": 3, "value": 2},
            {"op": "set_distance", "route": "NL_ocean", "start_week": 2, "end_week": 3, "value": 300},
            {"op": "set_capacity", "route": "NL_air", "start_week": 6, "end_week": 6, "value": 4},
        ]}
        compiled = experiments.compile_notice(original, notice)
        self.assertEqual(original, snapshot)
        np.testing.assert_array_equal(np.asarray(compiled["lead_schedule"])[:, 1], [2, 4, 4, 2, 2, 2])
        np.testing.assert_array_equal(np.asarray(compiled["distance_schedule"])[:, 1], [200, 300, 300, 200, 200, 200])
        np.testing.assert_array_equal(np.asarray(compiled["capacity_schedule"])[:, 0], [20, 20, 20, 20, 20, 4])
        # A dispatch in period2 still receives a four-period lead even if its
        # arrival is beyond the announced notice's active dispatch interval.
        args, _ = experiments.planning_inputs(compiled, np.ones((6, 1), dtype=int))
        self.assertEqual(args["lead_times"][1, 1], 4)

    def test_ambiguous_status_bad_indices_unknown_entities_and_units_fail_closed(self):
        base = tiny_config()
        valid = {"op": "add_lead", "route": "NL_air", "start_week": 1, "end_week": 2, "value": 1}
        invalid = [
            {"status": "needs_clarification", "changes": [valid]},
            {"status": "ready", "changes": [dict(valid, start_week=0)]},
            {"status": "ready", "changes": [dict(valid, end_week=7)]},
            {"status": "ready", "changes": [dict(valid, start_week=True)]},
            {"status": "ready", "changes": [dict(valid, start_week=2, end_week=1)]},
            {"status": "ready", "changes": [dict(valid, route="unknown")]},
            {"status": "ready", "changes": [dict(valid, value=.5)]},
            {"status": "ready", "changes": [dict(valid, value=True)]},
            {"status": "ready", "changes": [dict(valid, value=float("nan"))]},
            {"status": "ready", "changes": [dict(valid, units="days")]},
            {"status": "ready", "changes": [dict(valid, op="execute_code")]},
            {"status": "ready", "changes": [{"op": "carbon_reduction_fraction", "value": 1}]},
        ]
        for extraction in invalid:
            with self.subTest(extraction=extraction), self.assertRaises(ValueError):
                experiments.compile_notice(base, extraction)

    def test_origin_capacity_has_first_appearance_group_order(self):
        base = tiny_config()
        base["routes"].append(dict(base["routes"][0], name="MY_air", origin="MY"))
        base["route_origin"] = ["NL", "NL", "MY"]
        base["origin_capacity"] = [30, 70]
        compiled = experiments.compile_notice(base, {"status": "ready", "changes": [
            {"op": "multiply_origin_capacity", "origin": "MY", "start_week": 2, "end_week": 3, "value": .5},
        ]})
        np.testing.assert_array_equal(np.asarray(compiled["origin_schedule"])[:, 0], [30] * 6)
        np.testing.assert_array_equal(np.asarray(compiled["origin_schedule"])[:, 1], [70, 35, 35, 70, 70, 70])


class AccountingAndServiceTests(unittest.TestCase):
    def test_factors_match_saved_primary_rows_and_uplift_is_not_applied_twice(self):
        source = json.loads((experiments.ROOT / "data_sources/selected_emission_factors.json").read_text())
        combined = source["combined_factors"]
        self.assertAlmostEqual(experiments.EF["air"], combined["air_without_rf"]["direct"] + combined["air_without_rf"]["wtt"])
        self.assertAlmostEqual(experiments.EF["ocean"], combined["container_ship_average"]["direct"] + combined["container_ship_average"]["wtt"])
        self.assertAlmostEqual(experiments.EF["road"], source["road_factor_extension"]["combined_kgco2e_per_tonne_km"])
        args, _ = experiments.planning_inputs(tiny_config(), np.ones((6, 1), dtype=int))
        # One tonne at100km uses100 tonne.km, without another8% multiplier.
        self.assertAlmostEqual(args["unit_emissions"][0, 0, 0], 100 * .66646)
        self.assertAlmostEqual(args["unit_emissions"][0, 1, 0], 200 * .01977)

    def test_in_transit_capital_and_warehouse_holding_are_separate(self):
        c = tiny_config()
        args, components = experiments.planning_inputs(c, np.ones((6, 1), dtype=int))
        #5200USD x10% /52weeks =10USD per unit-week of tied-up capital.
        np.testing.assert_array_equal(components["freight"][0, :, 0], [2000, 500])
        np.testing.assert_array_equal(components["transit"][0, :, 0], [10, 20])
        np.testing.assert_array_equal(args["holding_cost"], [13])
        np.testing.assert_array_equal(args["unit_costs"][0, :, 0], [2010, 520])
        np.testing.assert_array_equal(args["warehouse_emissions"], [.25])
        c["period"] = "month"
        monthly, monthly_components = experiments.planning_inputs(c, np.ones((6, 1), dtype=int))
        self.assertAlmostEqual(monthly_components["transit"][0, 0, 0], 520 / 12)
        self.assertAlmostEqual(monthly["holding_cost"][0], 520 / 12 + 3)

    def test_input_units_do_not_silently_truncate_leads_or_assume_months(self):
        for kind in ("fractional_lead", "fractional_schedule", "unknown_period"):
            c = tiny_config()
            if kind == "fractional_lead":
                c["routes"][0]["lead"] = 1.5
            elif kind == "fractional_schedule":
                c["lead_schedule"] = [[1.5, 2]] * 6
            else:
                c["period"] = "days"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                experiments.planning_inputs(c, np.ones((6, 1), dtype=int))

    def test_mass_and_cost_conservation_and_identical_hard_service_targets(self):
        c = tiny_config()
        demand = np.ones((6, 1), dtype=int)
        initial_stocks = []
        for policy in ("cost_only", "fast_only", "slow_only"):
            with self.subTest(policy=policy):
                result, args = experiments.solve_policy(c, demand, policy)
                self.assertTrue(result["success"])
                initial_stocks.append(np.asarray(args["initial_inventory"]))
                np.testing.assert_array_equal(args["terminal_inventory"], args["initial_inventory"])
                np.testing.assert_allclose(result["inventory"][-1], args["initial_inventory"])
                self.assertEqual(args["backlog_limit"], 0)
                self.assertEqual(result["backlog"].sum(), 0)
                self.assertEqual(result["fill_rate"], 1)
                #Equal initial/final inventories and no pipeline imply every
                #mode transports exactly the total demand, not less cargo.
                self.assertEqual(result["orders"].sum(), demand.sum())
                transported_kg = float((result["orders"] * np.array(c["mass_kg"])).sum())
                self.assertEqual(transported_kg, 6000)
                self.assertAlmostEqual(result["total_cost"], result["freight_cost"] + result["transit_capital_cost"] + result["holding_cost"])
                self.assertAlmostEqual(result["total_emissions"], result["transport_emissions"] + result["warehouse_emissions"])
                self.assertAlmostEqual(result["warehouse_emissions"], .25 * result["inventory"].sum())
                np.testing.assert_allclose(result["inventory"], np.asarray(args["initial_inventory"]) + np.cumsum(result["arrivals"] - demand, axis=0))
                if policy == "fast_only":
                    self.assertEqual(result["orders"][:, 1].sum(), 0)
                    self.assertEqual(result["air_mass_share"], 1)
                elif policy == "slow_only":
                    self.assertEqual(result["orders"][:, 0].sum(), 0)
                    self.assertEqual(result["air_mass_share"], 0)
        for stock in initial_stocks[1:]:
            np.testing.assert_array_equal(stock, initial_stocks[0])

    def test_marvell_qualification_and_common_origin_caps_are_preserved(self):
        c = experiments.config("marvell")
        demand = np.zeros((c["horizon"], 4), dtype=int)
        args, _ = experiments.planning_inputs(c, demand)
        np.testing.assert_array_equal(args["eligibility"], c["eligibility"])
        self.assertEqual(args["route_origin"], ["TW", "TW", "MY", "MY"])
        np.testing.assert_array_equal(args["origin_capacity"], [[160, 160]] * c["horizon"])
        np.testing.assert_array_equal(args["eligibility"][:2, 2:], False)
        np.testing.assert_array_equal(args["eligibility"][2:, :2], False)


class ExternalDemandTests(unittest.TestCase):
    def test_series_selection_uses_history_activity_not_holdout_activity(self):
        lines = ["# synthetic TSF fixture", "@frequency monthly", "@data"]
        histories = {}
        for i in range(40):
            history = [i % 3 + 1] * 39
            future = [0 if i == 0 else i % 4] * 12
            histories[f"T{i}"] = (history, future)
            lines.append(f"T{i}:1998-01-01 00-00-00:" + ",".join(map(str, history + future)))
        #A huge future cannot rescue a series with insufficient historic demand.
        lines.append("HISTORY_INACTIVE:date:" + ",".join(map(str, [0] * 39 + [999] * 12)))
        lines.append("MISSING:date:" + ",".join(["1"] * 50 + ["?"]))
        fixture = "\n".join(lines).encode("cp1252")

        class FixtureZip:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def namelist(self):
                return ["fixture.tsf"]

            def read(self, name):
                return fixture

        with patch.object(experiments.zipfile, "ZipFile", FixtureZip):
            groups = list(experiments.external_carparts_groups())
            repeated = list(experiments.external_carparts_groups())
        self.assertEqual(len(groups), 10)
        selected = []
        for (seed, ids, orders, means), second in zip(groups, repeated):
            self.assertEqual(seed, second[0])
            self.assertEqual(ids, second[1])
            np.testing.assert_array_equal(orders, second[2])
            self.assertEqual(orders.shape, (12, 4))
            self.assertTrue(np.issubdtype(orders.dtype, np.integer))
            for j, series_id in enumerate(ids):
                history, future = histories[series_id]
                self.assertEqual(means[j], np.mean(history))
                np.testing.assert_array_equal(orders[:, j], future)
                selected.append(series_id)
        self.assertEqual(set(selected), set(histories))
        self.assertEqual(len(selected), len(set(selected)))
        self.assertIn("T0", selected)  #Zero holdout demand is retained.

    def test_monthly_analogue_keeps_months_and_ceil_converts_weekly_leads(self):
        original = experiments.config("asml")
        seen = []

        def fake_solver(c, orders, policy, **kwargs):
            seen.append(copy.deepcopy(c))
            self.assertEqual(orders.shape, (12, 4))
            return {"success": False, "optimal": False, "status": 2,
                    "mip_gap": None, "solve_seconds": 0}, None

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(experiments, "ROOT", Path(directory)), \
                 patch.object(experiments, "config", side_effect=lambda project: copy.deepcopy(original)), \
                 patch.object(experiments, "case_config", side_effect=lambda project, case: copy.deepcopy(original)), \
                 patch.object(experiments, "external_carparts_groups", return_value=iter([(4100, ["a", "b", "c", "d"], np.ones((12, 4), dtype=int), np.ones(4))])), \
                 patch.object(experiments, "solve_policy", side_effect=fake_solver), \
                 patch.object(experiments, "sha256", return_value="0" * 64), \
                 contextlib.redirect_stdout(io.StringIO()):
                experiments.run_grid(projects=("asml",), seeds=(), include_analogue=True)
        self.assertEqual(len(seen), 3)
        for c in seen:
            self.assertEqual(c["period"], "month")
            self.assertEqual(c["horizon"], 12)
            self.assertEqual([r["lead"] for r in c["routes"]], [math.ceil(r["lead"] * 12 / 52) for r in original["routes"]])
            self.assertEqual([r["lead"] for r in c["routes"]], [1, 2])
            self.assertAlmostEqual(c["warehouse_usd_per_unit_period"], .4 * 52 / 12)
            self.assertAlmostEqual(c["warehouse_kgco2e_per_unit_period"], .04 * 52 / 12)


if __name__ == "__main__":
    unittest.main()
