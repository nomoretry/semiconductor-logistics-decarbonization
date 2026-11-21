"""Model v2: truck schedules, charging, equipment and grid access. Small instances; local solver only."""
import copy
import importlib.util
import unittest
from itertools import pairwise

PLANNING = all(importlib.util.find_spec(name) for name in ("pulp", "highspy"))
SMALL = {"horizon.weeks": 2, "corridor.sg_max_dwell_hours": 6}


@unittest.skipUnless(PLANNING, "requires the optional planning extra")
class FleetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from electric_freight.fleet import load_v2, make_scenario, solve
        cls.config = load_v2(SMALL)
        cls.scenario = make_scenario(cls.config, "small", 1.0, with_chips=False)
        cls.joint = solve(cls.config, [cls.scenario], mode="joint", mip_gap=1e-6, time_limit=120)
        cls.diesel = solve(cls.config, [cls.scenario], mode="diesel", mip_gap=1e-6, time_limit=120)

    def test_a_round_trip_keeps_its_hours(self):
        from electric_freight.fleet import leg
        drive, kwh = leg(self.config, "normal")
        self.assertEqual(drive, 7)
        self.assertAlmostEqual(kwh, 400 * 1.13 + 5 * 1)
        for trip in self.joint["solution"]["small"]["types"]["normal|0"]["trips"]:
            self.assertEqual(trip["arrive"], trip["depart"] + drive)
            self.assertEqual(trip["back"], trip["arrive"] + trip["dwell"])
            self.assertEqual(trip["home"], trip["back"] + drive)

    def test_every_background_trip_runs_once_within_its_window(self):
        from electric_freight.fleet import windows_of
        windows = windows_of(self.config, "base")
        trips = self.joint["solution"]["small"]["types"]["normal|0"]["trips"]
        self.assertEqual(sorted(t["kind"] for t in trips), [f"task{b}" for b in range(len(windows))])
        for trip in trips:
            self.assertIn(trip["depart"], windows[int(trip["kind"][4:])])

    def test_the_accounting_agrees_with_the_solver(self):
        from electric_freight.fleet_accounting import evaluate
        for result, mode in ((self.joint, "joint"), (self.diesel, "diesel")):
            account = evaluate(self.config, self.scenario, result["first_stage"], result["solution"]["small"],
                               mode=mode)
            self.assertEqual(account["issues"], [])
            self.assertAlmostEqual(account["total_cost_usd"], result["objective_usd"],
                                   delta=1e-4 * result["objective_usd"])

    def test_week_bounds_hold_the_actual_week(self):
        from electric_freight.fleet import week_bounds
        from electric_freight.fleet_accounting import evaluate
        account = evaluate(self.config, self.scenario, self.joint["first_stage"], self.joint["solution"]["small"],
                           mode="joint")
        low_t, high_t, low_e, high_e = week_bounds(self.config, "joint", "normal", 6, 3)
        weeks = 2
        transport = account["cost_usd"]["trips"] + account["cost_usd"]["waiting"]
        self.assertLessEqual(low_t * weeks, transport * (1 + 1e-6) + 1e-6)  # a plan may sit exactly on a bound
        self.assertLessEqual(transport, high_t * weeks)
        self.assertLessEqual(low_e * weeks, account["cost_usd"]["energy"] * (1 + 1e-6) + 1e-6)
        self.assertLessEqual(account["cost_usd"]["energy"], high_e * weeks)

    def test_unused_week_types_have_no_trips(self):
        solution = self.joint["solution"]["small"]
        self.assertEqual(set(solution["types"]), set(solution["week_types"].values()))

    def test_fixing_the_first_stage_never_does_worse_than_the_joint_incumbent(self):
        from electric_freight.fleet import solve
        again = solve(self.config, [self.scenario], mode="joint", fixed_first_stage=self.joint["first_stage"],
                      mip_gap=1e-6, time_limit=120)
        self.assertEqual(again["first_stage"], self.joint["first_stage"])
        self.assertLessEqual(again["objective_usd"], self.joint["objective_usd"] * (1 + 1e-6))
        if self.joint["status"] == "optimal" and self.joint["stats"]["mip_gap"] <= 1e-6:
            self.assertAlmostEqual(again["objective_usd"], self.joint["objective_usd"],
                                   delta=1e-4 * again["objective_usd"])

    def test_a_starting_solution_is_kept_as_the_first_incumbent(self):
        from electric_freight.fleet import solve
        fixed = solve(self.config, [self.scenario], mode="joint", fixed_first_stage=self.joint["first_stage"],
                      mip_gap=1e-6, time_limit=120)
        started = solve(self.config, [self.scenario], mode="joint", start=fixed["values"], mip_gap=1e-6,
                        time_limit=20)
        self.assertLessEqual(started["objective_usd"], fixed["objective_usd"] * (1 + 1e-6))

    def test_the_accounting_finds_broken_plans(self):
        from electric_freight.fleet_accounting import evaluate
        solution = copy.deepcopy(self.joint["solution"]["small"])
        trips = solution["types"]["normal|0"]["trips"]
        trips[0]["depart"] = trips[0]["depart"] + 9  # outside its window, and overlapping
        issues = evaluate(self.config, self.scenario, self.joint["first_stage"], solution, mode="joint")["issues"]
        self.assertTrue(any("outside its window" in i for i in issues))
        fewer = copy.deepcopy(self.joint["first_stage"])
        for name in fewer["plant"]["n"]:
            fewer["plant"]["n"][name] = 0
        issues = evaluate(self.config, self.scenario, fewer, self.joint["solution"]["small"], mode="joint")["issues"]
        self.assertTrue(any("connectors in use" in i for i in issues))

    def test_a_truck_cannot_run_trips_it_has_no_time_for(self):
        from electric_freight.fleet import load_v2, make_scenario, solve
        config = load_v2({**SMALL, "background.instances.base.own_trucks": 1, "fleet.lease": {}})
        busy = make_scenario(config, "one_truck", 1.0, with_chips=False)
        result = solve(config, [busy], mode="diesel", time_limit=60)
        self.assertIn(result["status"], ("optimal", "infeasible"))
        if result["status"] == "optimal":
            trips = sorted(t["depart"] for t in result["solution"]["one_truck"]["types"]["normal|0"]["trips"])
            self.assertTrue(all(b - a >= 2 * 7 + 4 + 2 for a, b in pairwise(trips)))

    def test_the_horizon_check_starts_from_the_representative_weeks(self):
        from electric_freight.fleet import horizon_check
        from electric_freight.fleet_accounting import evaluate_horizon
        plan = self.joint
        operating = plan["objective_usd"] - plan["first_stage_cost_usd"]  # no chips, so no cargo cost
        fixed = horizon_check(self.config, self.scenario, plan, mip_gap=1e-6, time_limit=30)
        self.assertIn("used as the start", fixed["start"])
        self.assertLessEqual(fixed["operating_cost_usd"], operating * (1 + 1e-6) + 1e-6)
        free = horizon_check(self.config, self.scenario, plan, free_first_stage=True, mip_gap=1e-6, time_limit=30)
        self.assertIn("used as the start", free["start"])
        self.assertLessEqual(free["objective_usd"], plan["objective_usd"] * (1 + 1e-6) + 1e-6)
        for result in (fixed, free):
            account = evaluate_horizon(self.config, self.scenario, result, plan["solution"]["small"]["week_types"])
            self.assertEqual(account["issues"], [])
            self.assertAlmostEqual(account["total_cost_usd"], result["objective_usd"], places=3)

    def test_the_decomposition_brackets_the_stochastic_plan(self):
        from electric_freight.fleet import load_v2, make_scenario
        from electric_freight.stochastic import decompose
        config = load_v2({**SMALL, "horizon.weeks": 1})
        scenarios = [make_scenario(config, "calm", 0.7, with_chips=False),
                     make_scenario(config, "weak_grid", 0.3, with_chips=False,
                                   overrides={"substations.SG_SUB_N.headroom_kw": 100})]
        out = decompose(config, scenarios, deterministic="calm", workers=2,
                        options={"time_limit": 60, "mip_gap": 1e-6}, log=lambda _: None)
        self.assertLessEqual(out["WS"]["value"], out["RP"]["expected_usd"] + 1e-6)
        self.assertLessEqual(out["RP"]["expected_usd"], out["EEV"]["expected_usd"] + 1e-6)
        self.assertGreaterEqual(out["VSS"]["value"], -1e-6)
        self.assertGreaterEqual(out["EVPI"]["value"], -1e-6)
        self.assertTrue(out["start_for_equivalent"])
        self.assertTrue(all(not row["accounting"]["issues"] for row in out["solves"] if row["objective_usd"]))

    def test_sensitivity_jobs_and_capital_prices(self):
        import json

        from electric_freight.fleet import load_v2
        from scripts.run_fleet import PROTOCOL, protocol, sensitivity_jobs
        spec = protocol()
        original = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        jobs = sensitivity_jobs(spec)
        self.assertEqual(original["sensitivity"]["plans"], ["A", "C"])
        self.assertEqual(len(jobs), 24)
        for case in original["sensitivity"]["cases"]:
            self.assertEqual([j["plans"] for j in jobs if j["meta"]["case"] == case], ["A", "BC"])
        base = load_v2()
        for job in jobs:
            case = original["sensitivity"]["cases"][job["meta"]["case"]]
            if "capex_scale" not in case:
                self.assertEqual(job["config_overrides"], case)
                continue
            scaled = load_v2(job["config_overrides"])
            factor = case["capex_scale"]
            for name, site in base["sites"].items():
                changed = scaled["sites"][name]
                self.assertEqual(changed["open_capex_usd"], site["open_capex_usd"] * factor)
                self.assertEqual(changed["energy_usd_per_kwh"], site["energy_usd_per_kwh"])
                for q, tier in site["tiers"].items():
                    self.assertEqual(changed["tiers"][q]["capex_usd"], tier["capex_usd"] * factor)
                for a, b in zip(site["upgrades"], changed["upgrades"], strict=True):
                    self.assertEqual(b["capex_usd"], a["capex_usd"] * factor)
                self.assertEqual(changed["connections"], {k: v * factor for k, v in site["connections"].items()})
            for name, sub in base["substations"].items():
                for a, b in zip(sub["expansions"], scaled["substations"][name]["expansions"], strict=True):
                    self.assertEqual(b["capex_usd"], a["capex_usd"] * factor)

    def test_sensitivity_summary_uses_accounts_and_baseline(self):
        from scripts.summarize_fleet import sensitivity
        rows = []
        for group, costs in (("deterministic", [100, 145, 130, 120]), ("sensitivity", [110, 142, 128, 125])):
            for p, v in zip(("A", "B", "B*", "C"), costs, strict=True):
                rows.append({"group": group, "instance": "base", "scenario": "normal", "case": "test", "plan": p,
                             "first_stage": {"lease": {}}, "status": "optimal", "stats": {"mip_gap": 0.0005},
                             "objective_usd": 999, "accounting": {"total_cost_usd": v, "total_emissions_kg": 650,
                                                                  "peak_kw": {"MY_DEPOT": 24.5}}})
        table = "\n".join(sensitivity(rows))
        self.assertIn("| test | 110.00 | 142.00 | 128.00 | 125.00 | 15.00 | 17.00 | 3.00 | 650.00", table)
        self.assertIn("| Change vs base normal | 10.00 | -3.00 | -2.00 | 5.00 | -5.00 | -8.00 | -7.00", table)
        self.assertIn("24.50 | optimal, gap 0.05%", table)

    def test_fixing_saved_trips_keeps_them_and_their_cost(self):
        from electric_freight.fleet import solve
        solution = self.joint["solution"]["small"]
        trips = {"small": {typ: ops["trips"] for typ, ops in solution["types"].items()}}
        again = solve(self.config, [self.scenario], mode="joint", neighbourhood={"trips": trips, "free": []},
                      mip_gap=1e-6, time_limit=60)
        for typ, ops in again["solution"]["small"]["types"].items():
            self.assertEqual(ops["trips"], trips["small"][typ])
        self.assertLessEqual(again["objective_usd"], self.joint["objective_usd"] * (1 + 1e-6) + 1e-6)

    def test_the_search_never_raises_the_cost_of_a_saved_plan(self):
        from electric_freight.search import default_parts, improve
        solution = self.joint["solution"]["small"]
        trips = {"small": {typ: ops["trips"] for typ, ops in solution["types"].items()}}
        parts = default_parts(self.config, "base")
        self.assertEqual(len(parts), 3 + 7)  # two own trucks and one leasable, seven 48-hour windows
        out = improve(self.config, [self.scenario], trips, parts=parts, sub_time_limit=20, mip_gap=1e-6, rounds=1,
                      log=lambda _: None)
        self.assertLessEqual(out["objective_usd"], self.joint["objective_usd"] * (1 + 1e-6) + 1e-6)
        values = [h["objective_usd"] for h in out["search"]["history"] if h["objective_usd"] is not None]
        self.assertLessEqual(out["objective_usd"], min(values) + 1e-6)

    def test_a_fixed_cargo_plan_keeps_a_tolerance_band(self):
        import pulp

        from electric_freight.fleet import _cargo, make_scenario, week_types
        sc = make_scenario(self.config, "c", 1.0)
        types = week_types(sc)
        free = _cargo(pulp.LpProblem("free", pulp.LpMinimize), sc, types, None)
        key = next(iter(free["ship"]))
        plan = {"solution": {"c": {
            "week_types": {str(w): f"{c}|0" for w, c in enumerate(sc.conditions, start=1)},
            "shipments": [{"order": key[0], "week": key[1], "channel": key[2], "units": 2.5}], "air": []}}}
        fixed = _cargo(pulp.LpProblem("fixed", pulp.LpMinimize), sc, types, plan)
        chosen = fixed["ship"][key]
        self.assertAlmostEqual(chosen.lowBound, 2.5 - 1e-6, places=12)
        self.assertAlmostEqual(chosen.upBound, 2.5 + 1e-6, places=12)
        other = next(v for k, v in fixed["ship"].items() if k != key)
        self.assertEqual((other.lowBound, other.upBound), (0.0, 1e-6))

    def test_week_type_fixing_keeps_week_types_and_frees_quantities(self):
        import pulp

        from electric_freight.fleet import _cargo, make_scenario, week_types
        sc = make_scenario(self.config, "c", 1.0)
        types = week_types(sc)
        key = next(iter(_cargo(pulp.LpProblem("free", pulp.LpMinimize), sc, types, None)["ship"]))
        plan = {"cargo_fixing": "week_types", "solution": {"c": {
            "week_types": {str(w): f"{c}|0" for w, c in enumerate(sc.conditions, start=1)},
            "shipments": [{"order": key[0], "week": key[1], "channel": key[2], "units": 2.5}], "air": []}}}
        fixed = _cargo(pulp.LpProblem("fixed", pulp.LpMinimize), sc, types, plan)
        self.assertEqual((fixed["ship"][key].lowBound, fixed["ship"][key].upBound), (0, None))
        for (_, _, n), v in fixed["z"].items():
            self.assertEqual((v.lowBound, v.upBound), (float(n == 0), float(n == 0)))

    def test_a_solver_seed_changes_only_the_search(self):
        from electric_freight.fleet import solve
        seeded = solve(self.config, [self.scenario], mode="diesel", mip_gap=1e-6, time_limit=120, random_seed=3)
        self.assertEqual(seeded["status"], self.diesel["status"])
        self.assertAlmostEqual(seeded["objective_usd"], self.diesel["objective_usd"],
                               delta=1e-5 * self.diesel["objective_usd"])

    def test_presolve_off_keeps_the_small_diesel_plan_cost(self):
        from electric_freight.fleet import solve
        from electric_freight.fleet_accounting import audit_plan
        result = solve(self.config, [self.scenario], mode="diesel", highs_options={"presolve": "off"},
                       mip_gap=1e-6, time_limit=120, start=self.diesel["values"])
        account = audit_plan(self.config, self.scenario, result, "diesel")
        self.assertAlmostEqual(account["total_cost_usd"], self.diesel["objective_usd"], places=3)

    def test_presolve_selection_requires_a_saved_incumbent(self):
        from scripts.check_fleet_presolve import eligible
        self.assertFalse(eligible({"status": "infeasible", "mip_gap": 0.0}))
        self.assertFalse(eligible({"objective_usd": 3.0, "status": "feasible", "mip_gap": 0.002}))
        self.assertTrue(eligible({"objective_usd": 3.0, "status": "feasible", "stats": {"mip_gap": 0.001}}))

    def test_diesel_runs_every_background_trip(self):
        account = self.diesel["solution"]["small"]
        self.assertEqual(len(account["types"]["normal|0"]["trips"]), 6)
        self.assertNotIn("plant", self.diesel["first_stage"])


if __name__ == "__main__":
    unittest.main()
