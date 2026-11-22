"""Electric freight on the Malaysia-Singapore corridor: inputs, physics, accounting and the joint model."""
import copy
import importlib.util
import os
import unittest
from pathlib import Path

PLANNING = all(importlib.util.find_spec(name) for name in ("pulp", "highspy"))
UM_CHECKOUT = Path(os.environ.get("UM_RESEARCH_CHECKOUT", Path(__file__).resolve().parents[3] / "um-research"))


@unittest.skipUnless(PLANNING, "requires the optional planning extra")
class ElectricFreightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from electric_freight.data import export_orders, load_config, orders_from
        cls.cargo = export_orders("normal")
        cls.orders = orders_from(cls.cargo)
        cls.air = cls.cargo["air_fallback"]
        cls.config = load_config()

    def test_orders_are_the_weekly_plans_road_dispatches_in_kilograms(self):
        self.assertAlmostEqual(self.cargo["total_kg"], 2511.67, places=2)
        self.assertAlmostEqual(self.cargo["peak_weekly_kg"], 276.6, places=1)
        self.assertEqual({o["origin"] for o in self.cargo["orders"]}, {"MY"})  # Taiwan SKUs cannot use MY_road
        self.assertAlmostEqual(sum(o.kg for o in self.orders), self.cargo["total_kg"], places=2)
        self.assertEqual(self.air["available_kg"][14], 0.0)  # week 15: the weekly plan uses all spot air space

    def test_trip_physics(self):
        from electric_freight.data import SG, build_blocks, sites_from
        sites = sites_from(self.config)
        blocks = {b.id: b for b in build_blocks(self.config, sites, ["normal", "congested"])}
        base = blocks["normal:none"].timelines[0]
        self.assertEqual(base.trips, 3)
        self.assertAlmostEqual(sum(base.drive_kwh), 3 * 2 * 400 * 1.13 + 3 * 2 * 5 * 1)
        self.assertTrue(all(base.location[t] == SG for t in range(len(base.location)) if base.plug["SG_HUB"][t]))
        self.assertEqual(sum(base.plug["SG_HUB"]) - sum(base.plug["SG_YARD"]), 3)  # the yard waits one hour
        congested = blocks["congested:none"].timelines[0]
        self.assertAlmostEqual(sum(congested.drive_kwh) - sum(base.drive_kwh), 3 * 2 * 5 * 2)

    def test_aggregate_bridge_absorbs_the_excess_only_by_a_chain_of_early_dispatches(self):
        from electric_freight.model import aggregate_absorption
        result = aggregate_absorption(self.cargo["weekly_kg"], 200, early_weeks=1)
        self.assertAlmostEqual(result["excess_over_capacity_kg"], 193.52, places=2)
        self.assertEqual(result["unabsorbed_kg"], 0)
        self.assertGreater(sum(result["moved_kg"].values()), 1000)

    def test_normal_week_chips_ride_on_spare_space_and_change_nothing(self):
        from electric_freight.model import solve
        joint = solve(self.config, self.orders, air=self.air)
        empty = solve(self.config, [], air=self.air)
        self.assertEqual(joint["accounting"]["issues"], [])
        self.assertAlmostEqual(joint["objective_usd"], empty["objective_usd"], places=2)
        self.assertEqual(joint["accounting"]["delivered_kg"]["consolidated"], 2511.67)
        fixed = solve(self.config, self.orders, air=self.air, fixed_equipment=joint["solution"]["equipment"])
        self.assertAlmostEqual(fixed["objective_usd"], joint["objective_usd"], places=2)
        diesel = solve(self.config, self.orders, mode="diesel", air=self.air)
        self.assertEqual(diesel["accounting"]["energy_kwh"], {})
        self.assertGreater(diesel["accounting"]["diesel_litres"], 0)

    def test_the_accounting_finds_broken_plans(self):
        from electric_freight.accounting import evaluate
        from electric_freight.model import solve
        plan = solve(self.config, self.orders, mode="diesel", air=self.air)["solution"]
        missing = copy.deepcopy(plan)
        missing["shipments"] = missing["shipments"][1:]
        self.assertTrue(any("units delivered" in i for i in evaluate(self.config, self.orders, missing,
                                                                     mode="diesel", air=self.air)["issues"]))
        crowded = copy.deepcopy(plan)
        crowded["shipments"][0]["units"] *= 1000
        crowded["shipments"][0]["channel"] = "premium"
        issues = evaluate(self.config, self.orders, crowded, mode="diesel", air=self.air)["issues"]
        self.assertTrue(any("exceeds" in i for i in issues))

    def test_capital_is_charged_for_the_modelled_weeks_only(self):
        from electric_freight.data import capital_share
        rate, years = 0.08, 10
        crf = rate * (1 + rate) ** years / ((1 + rate) ** years - 1)
        self.assertAlmostEqual(capital_share(self.config, 16), crf * 16 / 52)

    @unittest.skipUnless((UM_CHECKOUT / "src" / "um_charging" / "model.py").exists(), "needs a UM-RESEARCH checkout")
    def test_the_um_charging_model_finds_the_same_week(self):
        from electric_freight.bridge import cross_check
        for block in ("normal:none", "normal:day"):
            result = cross_check(self.config, UM_CHECKOUT, block)
            self.assertTrue(result["um_validation_passed"])
            self.assertLess(abs(result["difference"]), 1e-6)
            self.assertEqual(result["um_new_connectors"], {j: float(n) for j, n in result["ours_connectors"].items()})


if __name__ == "__main__":
    unittest.main()
