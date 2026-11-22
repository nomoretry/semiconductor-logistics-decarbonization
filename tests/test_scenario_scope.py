"""Which lanes a disruption covers, in every form the argument can arrive. Offline; no model is called."""
import importlib.util
import json
import os
import unittest
from pathlib import Path

from tests.test_llm_safety import KEY, Base

PLANNING = all(importlib.util.find_spec(name) for name in ("pulp", "highspy"))
ROOT = Path(__file__).resolve().parents[1]
WEEKS = {"start_week": 7, "end_week": 9}


@unittest.skipUnless(PLANNING, "requires the planning extra")
class ScenarioScopeTests(unittest.TestCase):
    def build(self, *disruptions, network="marvell", **session_options):
        from planning_agent.tools import Session
        session = Session(n_skus=6, seed=3, **session_options)
        result = session.call("create_scenario", {"network": network, "name": "scope_check",
                                                  "disruptions": list(disruptions)})
        return session, result

    def covered(self, *disruptions, **options):
        _, result = self.build(*disruptions, **options)
        self.assertNotIn("error", result)
        return [d["lanes"] for d in result["definition"]["disruptions"]]

    def error(self, *disruptions, **options):
        session, result = self.build(*disruptions, **options)
        self.assertIn("error", result)
        self.assertNotIn(("marvell", "scope_check"), session.custom)  # nothing is built on a bad request
        return result["error"]

    def test_lanes_alone_cover_exactly_those_lanes(self):
        self.assertEqual(self.covered({"lanes": ["TW_air"], **WEEKS}), [["TW_air"]])
        self.assertEqual(self.covered({"lanes": ["TW_air", "MY_road"], **WEEKS}), [["TW_air", "MY_road"]])

    def test_mode_alone_covers_every_lane_of_that_mode(self):
        self.assertEqual(self.covered({"mode": "air", **WEEKS}), [["TW_air", "MY_air"]])
        self.assertEqual(self.covered({"mode": "road", **WEEKS}), [["MY_road"]])

    def test_lanes_decide_the_scope_when_mode_agrees(self):
        self.assertEqual(self.covered({"mode": "air", "lanes": ["TW_air"], **WEEKS}), [["TW_air"]])
        self.assertEqual(self.covered({"mode": "air", "lanes": ["TW_air", "MY_air"], **WEEKS}), [["TW_air", "MY_air"]])

    def test_a_lane_of_another_mode_is_an_error_and_names_the_conflict(self):
        message = self.error({"mode": "road", "lanes": ["TW_air"], **WEEKS})
        self.assertIn("TW_air", message)
        self.assertIn("road", message)
        self.assertIn("MY_road", self.error({"mode": "air", "lanes": ["TW_air", "MY_road"], **WEEKS}))

    def test_null_and_empty_mean_not_given(self):
        self.assertEqual(self.covered({"mode": None, "lanes": ["TW_air"], **WEEKS}), [["TW_air"]])
        self.assertEqual(self.covered({"mode": "air", "lanes": None, **WEEKS}), [["TW_air", "MY_air"]])
        self.assertEqual(self.covered({"mode": "air", "lanes": [], **WEEKS}), [["TW_air", "MY_air"]])
        for empty in ({"mode": None, "lanes": None}, {"mode": None, "lanes": []}, {}):
            self.assertIn("give 'mode'", self.error({**empty, **WEEKS}))

    def test_unknown_lanes_and_modes_are_errors(self):
        self.assertIn("unknown lanes ['SG_rail']", self.error({"lanes": ["SG_rail"], **WEEKS}))
        self.assertIn("unknown lanes ['SG_rail']", self.error({"mode": "air", "lanes": ["TW_air", "SG_rail"], **WEEKS}))
        self.assertIn("no 'rail' lanes", self.error({"mode": "rail", **WEEKS}))
        self.assertIn("no 'road' lanes", self.build({"mode": "road", **WEEKS}, network="asml")[1]["error"])
        self.assertIn("list of lane ids", self.error({"lanes": "TW_air", **WEEKS}))

    def test_a_repeated_lane_counts_once(self):
        self.assertEqual(self.covered({"lanes": ["TW_air", "TW_air"], **WEEKS}), [["TW_air"]])

    def test_null_optional_fields_are_reported_as_assumptions_not_errors(self):
        _, result = self.build({"lanes": ["TW_air"], "extra_lead_weeks": None, "capacity_change_pct": -20,
                                "cost_change_pct": None, "distance_factor": None, **WEEKS})
        self.assertNotIn("error", result)
        self.assertEqual(len(result["assumptions"]), 3)
        self.assertTrue(any("cost_change_pct not given" in a for a in result["assumptions"]))
        disruption = result["definition"]["disruptions"][0]
        self.assertEqual((disruption["extra_lead_weeks"], disruption["cost_factor"]), (0, 1.0))

    def test_null_arguments_to_any_tool_mean_not_given(self):
        from planning_agent.tools import Session
        session = Session(n_skus=6, seed=3)
        plan = session.call("solve_plan", {"network": "marvell", "scenario": None, "carbon_cap_pct": None,
                                           "carbon_price_usd_per_t": None, "service_level_pct": None, "label": None})
        self.assertNotIn("error", plan)
        self.assertEqual(plan["scenario"], "normal")

    def test_the_arguments_a_model_really_sent_for_a04_now_cover_only_taiwan(self):
        rows = [json.loads(line) for line in (ROOT / "benchmark_results/planning_agent_v2/gpt-6.1-sol-max/runs.jsonl")
                .read_text(encoding="utf-8").splitlines() if line.strip()]
        calls = [c for r in rows if r["case_id"] == "A04" for c in r["tool_calls"] if c["name"] == "create_scenario"]
        self.assertEqual(len(calls), 37)
        widened = sum(c["result"]["definition"]["disruptions"][0]["lanes"] == ["TW_air", "MY_air"] for c in calls)
        self.assertEqual(widened, 36)  # what the recorded tool did
        for call in calls:
            item = call["arguments"]["disruptions"][0]
            if item["mode"] == "air":
                self.assertEqual(self.covered(item), [["TW_air"]])
            else:
                self.assertIn("not 'road' lanes", self.error(item))

    def test_on_a04_the_wrong_scope_happens_to_give_the_same_totals(self):
        from planning_agent.tools import Session
        session = Session()
        disruption = {"start_week": 7, "end_week": 9, "capacity_change_pct": -100 / 3, "cost_change_pct": 15}
        totals = []
        for name, scope in (("taiwan", ["TW_air"]), ("wider", ["TW_air", "MY_air"])):
            session.call("create_scenario", {"network": "marvell", "name": name,
                                             "disruptions": [{"lanes": scope, **disruption}]})
            plan = session.call("solve_plan", {"network": "marvell", "scenario": name})
            totals.append((plan["total_cost_usd"], float(plan["emissions_t"])))
        self.assertEqual(totals[0], (467188, 9.76))
        self.assertEqual(totals[0], totals[1])

    def test_recorded_runs_can_still_be_replayed_with_the_behaviour_they_saw(self):
        self.assertEqual(self.covered({"mode": "air", "lanes": ["TW_air"], **WEEKS}, additive_mode_lanes=True),
                         [["TW_air", "MY_air"]])
        self.assertEqual(self.covered({"mode": "road", "lanes": ["TW_air"], **WEEKS}, additive_mode_lanes=True),
                         [["TW_air", "MY_road"]])

    def test_the_schema_explains_the_contract(self):
        from planning_agent.tools import TOOLS
        properties = TOOLS["create_scenario"].schema()["function"]["parameters"]["properties"]
        item = properties["disruptions"]["items"]["properties"]
        self.assertIn("when lanes is not given", item["mode"]["description"])
        self.assertIn("only these lanes", item["lanes"]["description"])


class StrictSettingTests(Base):
    def test_responses_requests_state_that_tools_are_not_strict(self):
        from tests.test_planning_eval_v2 import responses_reply
        os.environ["LLM_API_STYLE"] = "responses"
        reply = {**responses_reply("done"), "tools": [{"type": "function", "strict": False}]}
        fake = self.provider(default=(200, reply))
        client = self.client(fake)
        tools = [{"type": "function", "function": {"name": "t", "description": "d", "parameters": {}}}]
        client.chat([{"role": "user", "content": "hi"}], tools)
        self.assertIs(fake.requests[0]["body"]["tools"][0]["strict"], False)
        self.assertEqual(client.request_log[0]["tool_strict"], ["False"])

    def test_a_stored_response_can_be_read_back_without_touching_the_meter(self):
        from planning_agent.llm import OpenAICompatibleClient
        from planning_agent.spending import Limits
        fake = self.provider(default=(200, {"id": "resp_1", "tools": [{"name": "t", "strict": True}]}))
        client = OpenAICompatibleClient(api_key=KEY, base_url=fake.url, model="m", limits=Limits(1, 1000, 10))
        self.assertTrue(client.stored_response("resp_1")["tools"][0]["strict"])
        self.assertEqual(client.spending()["requests"], 0)
        self.assertEqual(fake.requests[0]["path"], "/v1/responses/resp_1")


if __name__ == "__main__":
    unittest.main()
