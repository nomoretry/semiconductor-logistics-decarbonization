import importlib.util
import unittest

import numpy as np

PLANNING = all(importlib.util.find_spec(name) for name in ("pulp", "highspy"))


@unittest.skipUnless(PLANNING, "requires the optional planning extra: pip install -e '.[planning]'")
class NetworkPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from network_planning import build_network
        cls.net = build_network("asml", n_skus=6, weeks=16, seed=3)

    def tiny(self):
        from network_planning.data import Lane, Network, Sku
        lane = Lane("X_road", "X", "road", 1, 100.0, 1.0, 1000.0, 0.0, 0.1)
        sku = Sku("part", "part", "X", 10.0, 520.0, 5.0, 1e5, ("X_road",))
        demand = np.zeros((1, 8), dtype=int)
        demand[0, 1:3] = 5
        return Network("tiny", "tiny", 8, 0, [sku], {"X_road": lane}, demand, np.zeros(1), np.zeros((1, 8)),
                       np.zeros(1), carry_rate_week=0.2 / 52, warehouse_usd=0.0, warehouse_kg=0.0,
                       air_spot_premium=1.25, reservation_usd_per_kg_week=0.5, terminal_penalty_weeks=2,
                       scenario_specs={"normal": {"probability": 1.0}}, stochastic_set=("normal",))

    def test_hand_checked_optimum(self):
        from network_planning import solve
        plan = solve(self.tiny(), integer_shipments=True)
        # Ten units of 10 kg: freight 1 USD/kg -> 100; transit capital 520*0.2/52*1 week*10 -> 20.
        self.assertAlmostEqual(plan.objective, 120.0, places=6)
        self.assertEqual(plan.solution["ship"], {(0, 0, "X_road", 0): 5, (0, 0, "X_road", 1): 5})
        self.assertAlmostEqual(plan.kpis["emissions_t"], 10 * 10 / 1000 * 100 * 0.1 / 1000)

    def test_independent_accounting_matches_solver(self):
        from network_planning import solve
        for scenario in ("normal", "red_sea"):
            plan = solve(self.net, [self.net.scenario(scenario, 1.0)])
            self.assertEqual(plan.issues, [])
            self.assertLess(plan.stats["objective_drift"], 1e-6)
            self.assertAlmostEqual(plan.kpis["service_level"], 1.0, places=6)

    def test_disruption_raises_cost_and_emissions(self):
        from network_planning import solve
        normal = solve(self.net)
        red_sea = solve(self.net, [self.net.scenario("red_sea", 1.0)])
        self.assertGreater(red_sea.kpis["total_cost_usd"], normal.kpis["total_cost_usd"])
        self.assertGreater(red_sea.kpis["emissions_t"], normal.kpis["emissions_t"])

    def test_carbon_cap_holds_with_nonnegative_shadow_price(self):
        from network_planning import solve
        base = solve(self.net, terminal_hard=True)
        cap = 0.8 * base.kpis["emissions_t"] * 1000
        capped = solve(self.net, carbon_cap_kg=cap, terminal_hard=True, duals=True, mip_gap=1e-4)
        self.assertLessEqual(capped.kpis["emissions_t"] * 1000, cap * (1 + 1e-6))
        self.assertGreaterEqual(capped.kpis["total_cost_usd"], base.kpis["total_cost_usd"] * (1 - 1e-3))
        self.assertGreater(capped.duals["carbon_usd_per_t"], 0)
        self.assertEqual(capped.issues, [])

    def test_frontier_costs_rise_as_cap_tightens(self):
        from network_planning.analysis import carbon_frontier
        frontier = carbon_frontier(self.net, levels=(0.8, 0.6), mip_gap=1e-4)
        costs = [p["total_cost_usd"] for p in frontier["points"]]
        self.assertEqual(costs, sorted(costs))
        self.assertTrue(all(p["mac_vs_baseline_usd_per_t"] > 0 for p in frontier["points"][1:]))
        self.assertLess(frontier["min_emissions_t"], frontier["points"][-1]["emissions_t"])

    def test_stochastic_value_bounds_and_nonanticipativity(self):
        from network_planning.analysis import stochastic_value
        result = stochastic_value(self.net, reveal_week=3, mip_gap=1e-4)
        tolerance = 1e-3 * result["RP"]
        self.assertGreaterEqual(result["VSS"], -tolerance)
        self.assertGreaterEqual(result["EVPI"], -tolerance)
        self.assertLessEqual(result["VSS_interval"][0], result["VSS"] + 1e-6)
        ship = result["plans"]["stochastic"].solution["ship"]
        early = {}
        for (k, s, l, t), units in ship.items():
            if t < 2:
                early.setdefault((s, l, t), set()).add(round(units, 6))
        self.assertTrue(all(len(v) == 1 for v in early.values()))
        counts = {(s, l, t): sum(1 for key in ship if key[1:] == (s, l, t)) for (s, l, t) in early}
        self.assertTrue(all(c == len(result["scenarios"]) for c in counts.values()))

    def test_integer_shipments_are_integral(self):
        from network_planning import solve
        plan = solve(self.net, integer_shipments=True)
        self.assertTrue(all(isinstance(v, int) for v in plan.solution["ship"].values()))
        self.assertEqual(plan.issues, [])

    def test_invalid_scenarios_are_rejected(self):
        from network_planning import Disruption, Scenario, solve
        with self.assertRaisesRegex(ValueError, "weeks"):
            solve(self.net, [Scenario("bad", 1.0, (Disruption(("NL_ocean",), 3, 99),))])
        with self.assertRaisesRegex(ValueError, "unknown lanes"):
            solve(self.net, [Scenario("bad", 1.0, (Disruption(("XX",), 3, 4),))])
        with self.assertRaisesRegex(ValueError, "reveal_week"):
            solve(self.net, self.net.scenarios(), reveal_week=6)


if __name__ == "__main__":
    unittest.main()
