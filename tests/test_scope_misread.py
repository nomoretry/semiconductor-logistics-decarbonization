"""Planning under a wrong reading of a notice's scope and living through the right one. Offline, local solver."""
import importlib.util
import unittest

PLANNING = all(importlib.util.find_spec(name) for name in ("pulp", "highspy"))
DISRUPTION = {"start_week": 7, "end_week": 9, "capacity_factor": 2 / 3, "cost_factor": 1.15}


@unittest.skipUnless(PLANNING, "requires the optional planning extra")
class ScopeMisreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from network_planning.data import build_network, scenario_from_spec
        cls.net = build_network("marvell")
        cls.actual = scenario_from_spec("actual_scope", {"disruptions": [{"lanes": ["TW_air"], **DISRUPTION}]}, 1.0)
        cls.believed = scenario_from_spec(
            "believed_scope", {"disruptions": [{"lanes": ["TW_air", "MY_air"], **DISRUPTION}]}, 1.0)

    def test_taiwan_and_malaysia_cargo_share_no_lane(self):
        origins = {sku.origin: set(sku.lanes) for sku in self.net.skus}
        self.assertEqual(origins, {"TW": {"TW_air", "TW_ocean"}, "MY": {"MY_air", "MY_road"}})

    def test_on_the_original_case_both_readings_give_the_same_dispatches(self):
        from network_planning.misread import misread_case
        record = misread_case(self.net, self.actual, self.believed, [1, 7, 10])
        self.assertEqual(record["plans_differ"]["shipment_variables_differing"], 0)
        self.assertEqual(record["optimum_difference_usd"], 0)
        self.assertEqual(sum(record["flows_best_plan_kg"]["MY_air"][6:9]), 0)  # MY_air idle in the window
        self.assertEqual(record["no_replanning"]["regret_usd"], 0)
        self.assertTrue(record["no_replanning"]["feasible"])
        self.assertEqual([c["regret_usd"] for c in record["commitments"]], [0, 0, 0])
        self.assertFalse(any(c["distinguishable"] for c in record["commitments"]))

    def test_a_correct_reading_has_no_regret_at_any_commitment(self):
        from network_planning.misread import misread_case, with_lane_capacity
        net = with_lane_capacity(self.net, "MY_road", 90.0)
        record = misread_case(net, self.actual, self.actual, [1, 7, 10])
        for row in record["commitments"]:
            self.assertLessEqual(abs(row["regret_usd"]), 0.05)
        self.assertLessEqual(abs(record["no_replanning"]["regret_usd"]), 0.05)

    def test_regret_is_never_negative_beyond_the_solver_tolerance(self):
        from network_planning.misread import misread_case, with_lane_capacity
        net = with_lane_capacity(self.net, "MY_road", 90.0)
        record = misread_case(net, self.actual, self.believed, [1, 7, 10])
        tolerance = 2e-7 * record["best_plan"]["total_cost_usd"]
        self.assertGreaterEqual(record["no_replanning"]["regret_usd"], -tolerance)
        previous = -tolerance
        for row in record["commitments"]:  # learning later can only cost more
            self.assertGreaterEqual(row["regret_usd"], previous - tolerance)
            previous = row["regret_usd"]
            if "favourable_tie_break" in row:
                self.assertLessEqual(row["favourable_tie_break"]["regret_usd"], row["regret_usd"] + tolerance)
        self.assertGreaterEqual(record["no_replanning"]["regret_usd"], previous - tolerance)

    def test_changing_one_lane_leaves_the_rest_of_the_network_alone(self):
        from network_planning.misread import with_lane_capacity
        net = with_lane_capacity(self.net, "MY_road", 10.0)
        self.assertEqual(net.lanes["MY_road"].capacity_kg, 10.0)
        self.assertEqual(self.net.lanes["MY_road"].capacity_kg, 276.6)
        self.assertEqual({k: v for k, v in net.lanes.items() if k != "MY_road"},
                         {k: v for k, v in self.net.lanes.items() if k != "MY_road"})
        self.assertIs(net.demand, self.net.demand)
        with self.assertRaises(ValueError):
            with_lane_capacity(self.net, "SG_rail", 1.0)


if __name__ == "__main__":
    unittest.main()
