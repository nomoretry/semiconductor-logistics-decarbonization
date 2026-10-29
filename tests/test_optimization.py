"""Independent accounting/timing/feasibility tests for the shared optimizer."""
import unittest

import numpy as np

from shared.optimization import solve_plan


def plan(demand, **changes):
    demand = np.asarray(demand, dtype=float).reshape(-1, 1)
    T = len(demand)
    parameters = dict(demand=demand, initial_inventory=[0],
                      pipeline_arrivals=np.zeros((T, 1)), lead_times=[1],
                      unit_costs=[[2]], unit_emissions=[[3]], holding_cost=[1],
                      backlog_cost=[10], route_capacity=np.full((T, 1), 10),
                      warehouse_emissions=[0], time_limit=5)
    parameters.update(changes)
    return solve_plan(**parameters)


class OptimizationTests(unittest.TestCase):
    def test_dispatch_receives_one_period_later_and_clears_final_demand(self):
        result = plan([0, 2, 0])
        self.assertTrue(result["success"])
        self.assertTrue(result["optimal"])
        np.testing.assert_array_equal(result["orders"][:, 0, 0], [2, 0, 0])
        np.testing.assert_array_equal(result["arrivals"][:, 0], [0, 2, 0])
        self.assertEqual(result["total_cost"], 4)
        self.assertEqual(result["total_emissions"], 6)

    def test_initial_shortage_is_carried_then_filled_not_lost(self):
        result = plan([2, 0, 0])
        np.testing.assert_array_equal(result["backlog"][:, 0], [2, 0, 0])
        self.assertEqual(result["backlog_cost"], 20)
        self.assertEqual(result["total_cost"], 24)

    def test_initial_pipeline_transport_is_sunk_but_storage_counts(self):
        result = plan([1, 1, 1], initial_inventory=[1],
                      pipeline_arrivals=[[0], [3], [0]], warehouse_emissions=[.5])
        self.assertTrue(result["success"])
        self.assertEqual(result["orders"].sum(), 0)
        np.testing.assert_array_equal(result["inventory"][:, 0], [0, 2, 1])
        self.assertEqual(result["total_cost"], 3)
        self.assertEqual(result["transport_emissions"], 0)
        self.assertEqual(result["warehouse_emissions"], 1.5)

    def test_carbon_cap_changes_mode_and_preserves_service(self):
        common = dict(lead_times=[1, 2], unit_costs=[[10], [12]],
                      unit_emissions=[[20], [1]], route_capacity=np.full((4, 2), 10))
        free = plan([0, 0, 4, 0], **common)
        clean = plan([0, 0, 4, 0], carbon_cap=4, **common)
        self.assertEqual(free["orders"][:, 0].sum(), 4)
        self.assertEqual(clean["orders"][:, 1].sum(), 4)
        self.assertEqual(clean["total_emissions"], 4)
        self.assertEqual(clean["backlog"][-1, 0], 0)
        self.assertEqual(clean["total_cost"], 48)
        self.assertGreater(clean["total_cost"], free["total_cost"])

    def test_infeasible_carbon_budget_is_reported_without_fake_results(self):
        result = plan([0, 2, 0], carbon_cap=5)
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], 2)
        for key in ("orders", "inventory", "backlog", "total_cost", "total_emissions"):
            self.assertIsNone(result[key])

    def test_warehouse_budget_avoids_unnecessary_early_inventory(self):
        result = plan([0, 0, 2], unit_emissions=[[0]],
                      warehouse_emissions=[1], carbon_cap=0)
        self.assertTrue(result["success"])
        np.testing.assert_array_equal(result["orders"][:, 0, 0], [0, 2, 0])
        self.assertEqual(result["warehouse_emissions"], 0)

    def test_route_capacity_is_shared_across_skus(self):
        result = solve_plan(demand=[[0, 0], [3, 3], [0, 0]], initial_inventory=[0, 0],
                            pipeline_arrivals=np.zeros((3, 2)), lead_times=[1],
                            unit_costs=[[1, 1]], unit_emissions=[[1, 1]],
                            holding_cost=[1, 1], backlog_cost=[10, 10],
                            route_capacity=[[4], [4], [4]], warehouse_emissions=[0, 0])
        self.assertTrue(result["success"])
        self.assertLessEqual(result["orders"].sum(axis=2).max(), 4)
        self.assertEqual(result["backlog"][1].sum(), 2)
        self.assertEqual(result["orders"].sum(), 6)

    def test_time_varying_lead_indexes_dispatch_period(self):
        result = plan([0, 0, 3, 0], lead_times=[[3], [1], [1], [1]])
        self.assertTrue(result["success"])
        self.assertEqual(result["orders"][1, 0, 0], 3)
        self.assertEqual(result["arrivals"][2, 0], 3)
        self.assertEqual(result["backlog"].sum(), 0)

    def test_integer_orders_and_explicit_lp_relaxation(self):
        integer = plan([0, 1.5], holding_cost=[.1])
        relaxed = plan([0, 1.5], holding_cost=[.1], integer=False)
        self.assertEqual(integer["orders"][0, 0, 0], 2)
        self.assertAlmostEqual(relaxed["orders"][0, 0, 0], 1.5)
        self.assertTrue(integer["integer_orders"])
        self.assertFalse(relaxed["integer_orders"])

    def test_terminal_stock_and_separate_initial_backlog(self):
        result = plan([0, 0, 0], initial_inventory=[1], initial_backlog=[3],
                      terminal_inventory=[2])
        self.assertTrue(result["success"])
        self.assertEqual(result["orders"].sum(), 4)
        self.assertEqual(result["inventory"][-1, 0], 2)
        self.assertEqual(result["backlog"][0, 0], 2)

    def test_invalid_inputs_are_rejected(self):
        invalid = [dict(lead_times=[0]), dict(lead_times=[1.5]),
                   dict(carbon_cap=-1), dict(unit_costs=[[-1]]),
                   dict(route_capacity=[[float("nan")]]), dict(time_limit=0),
                   dict(terminal_inventory=[-1]), dict(integer="True")]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                plan([0, 2, 0], **changes)

    def test_hard_period_service_constraint_cannot_hide_unserved_orders(self):
        result = plan([2, 0, 0], backlog_limit=0)
        self.assertFalse(result["success"])
        feasible = plan([2, 0, 0], initial_inventory=[2], backlog_limit=0)
        self.assertTrue(feasible["success"])
        self.assertEqual(feasible["backlog"].sum(), 0)

    def test_joint_origin_capacity_couples_air_and_ocean_dispatches(self):
        # Two routes each allow 10, but their shared factory permits only 3.
        common = dict(lead_times=[1, 1], unit_costs=[[1], [2]],
                      unit_emissions=[[1], [1]], route_capacity=np.full((3, 2), 10),
                      route_origin=["factory", "factory"], origin_capacity=[[3], [3], [3]])
        result = plan([0, 4, 0], **common)
        self.assertTrue(result["success"])
        self.assertEqual(result["orders"][0].sum(), 3)
        self.assertEqual(result["backlog"][1, 0], 1)
        self.assertEqual(result["origin_order"], ["factory"])

    def test_ineligible_low_cost_route_is_never_used(self):
        result = plan([0, 2, 0], lead_times=[1, 1], unit_costs=[[0], [5]],
                      unit_emissions=[[0], [0]], route_capacity=np.full((3, 2), 10),
                      eligibility=[[False], [True]])
        self.assertTrue(result["success"])
        self.assertEqual(result["orders"][:, 0].sum(), 0)
        self.assertEqual(result["orders"][:, 1].sum(), 2)
        self.assertEqual(result["total_cost"], 10)


if __name__ == "__main__":
    unittest.main()
