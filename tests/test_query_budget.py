"""Budget interruption, independent path accounting and evidence mutation checks."""
import copy
import gzip
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from budgeted_decision.planning import Decision, METHODS, Exhausted, cache_hash
from budgeted_decision.audit import evaluate, sampled_path, tasks, run, verify, canonical, sha256, summarize, configuration
from scripts.audit_decision_scale import generate, Planner


class QueryBudgetTests(unittest.TestCase):
    def setUp(self):
        self.c = generate(4, 2, 61)

    def test_hard_limit_counts_actual_backend_calls(self):
        oracle = Planner(self.c); requests = []
        def backend(h):
            requests.append(h)
            return oracle._terminal(h)
        session = Decision(self.c, 2, backend=backend)
        result, _ = session.choose((-1, -1), "iterative_dp")
        self.assertEqual(result["milp_calls"], 2)
        self.assertEqual(len(requests), 2)
        self.assertEqual(result["action"], -1)
        self.assertEqual(result["completed_candidates"], [])
        self.assertTrue(result["interrupted"])
        with self.assertRaises(Exhausted):session.solve((1, 1))
        self.assertEqual(len(requests), 2)

    def test_budget_one_is_feasible_commit_for_every_method(self):
        for method in METHODS:
            result, _ = evaluate(self.c, method, 1)
            self.assertEqual(result["expected_queries"], 0)
            self.assertEqual(result["expected_milp_calls"], 1)
            node = result["nodes"][0]
            self.assertEqual(node["action"], -1)
            self.assertAlmostEqual(Planner(self.c).shipping(node["commit_plan"], (-1, -1))["loss"], result["expected_loss"])

    def test_cache_copy_and_hit_accounting(self):
        parent = Decision(self.c, 5)
        _, inherited = parent.choose((-1, -1), "myopic_priority")
        before = cache_hash(inherited)
        a = Decision(self.c, 3, inherited); b = Decision(self.c, 3, inherited)
        a.solve((0, 0))
        self.assertEqual(cache_hash(inherited), before)
        self.assertEqual(cache_hash(b.cache), before)
        self.assertNotIn((0, 0), b.cache)
        self.assertEqual(len(a.solves), 1)
        a.solve((0, 0))
        self.assertEqual(len(a.solves), 1)

    def test_unlimited_iterative_search_equals_exact_dp(self):
        for bits in (2, 4):
            public = generate(3, bits, 73)
            result, _ = evaluate(public, "iterative_dp", 1000)
            oracle = Planner(public)
            self.assertAlmostEqual(result["expected_loss"], oracle.value((-1,)*bits, public["max_queries"])[0], places=6)

    def test_full_tree_matches_independent_world_enumeration(self):
        result, _ = evaluate(self.c, "lookahead_two", 5)
        total_loss = total_calls = total_queries = 0.
        longest = 0
        for truth in itertools.product((0, 1), repeat=2):
            weight = 1.
            for bit, prior in zip(truth, self.c["prior"]):weight *= prior if bit else 1-prior
            trace = sampled_path(self.c, truth, result["nodes"])
            total_loss += weight*trace["realized_loss"]
            total_calls += weight*trace["milp_calls"]
            total_queries += weight*(len(trace["nodes"])-1)
            longest = max(longest, trace["milp_calls"])
        self.assertAlmostEqual(result["expected_loss"], total_loss)
        self.assertAlmostEqual(result["expected_milp_calls"], total_calls)
        self.assertAlmostEqual(result["expected_queries"], total_queries)
        self.assertEqual(result["max_path_milp_calls"], longest)
        self.assertTrue(all(n["milp_calls"] <= 5 for n in result["nodes"]))

    def test_private_truth_never_enters_policy_and_no_free_budget(self):
        for budget in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):Decision(self.c, budget)
        c = copy.deepcopy(self.c); c["private_evaluation_bits"] = [0, 1]
        with self.assertRaises(ValueError):Decision(c, 5)
        for h in ((-1,), (2, -1), (True, -1)):
            with self.assertRaises(ValueError):Decision(self.c, 5).choose(h, "myopic_priority")

    def test_exhausted_query_fee_budget_forces_commit(self):
        c = copy.deepcopy(self.c);c["query_budget"] = 0
        result, _ = evaluate(c, "iterative_dp", 65)
        self.assertEqual(result["expected_queries"], 0)
        self.assertEqual(result["expected_milp_calls"], 1)

    def test_old_new_coverage_is_explicit(self):
        ts = tasks()
        self.assertEqual(len(ts), 54)
        self.assertEqual(sum(t["cohort"] == "old18" for t in ts), 18)
        self.assertEqual(sum(t["cohort"] == "new36" for t in ts), 36)
        self.assertEqual(len({t["id"] for t in ts}), 54)

    def test_gate_ignores_starved_low_budget_success_signal(self):
        cfg = configuration(); rows = []
        for cohort in ("old18", "new36"):
            for budget in cfg["budgets"]:
                for method in cfg["methods"]:
                    rows.append({"id": cohort, "cohort": cohort, "budget": budget, "method": method,
                                 "regret": 1. if budget < 13 else .001,
                                 "expected_milp_calls": 1., "max_path_milp_calls": 1, "expected_queries": 0.})
        self.assertFalse(summarize(rows)["bc_feasibility_gate_passed"])

    def test_replay_rejects_rehashed_action_cost_and_call_count_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp, smoke=True)
            self.assertTrue(verify(tmp)["verified"])
            root = Path(tmp); trace_path = root/"traces.jsonl.gz"
            original = gzip.decompress(trace_path.read_bytes())
            for field in ("action", "predicted_loss", "milp_calls"):
                traces = [json.loads(line) for line in original.splitlines()]
                traces[0]["runs"][0]["nodes"][0][field] += 1
                trace_path.write_bytes(gzip.compress(b"".join(canonical(t)+b"\n" for t in traces), mtime=0))
                manifest_path = root/"manifest.json"; manifest = json.loads(manifest_path.read_text())
                manifest["files"][str(trace_path.relative_to(root))] = sha256(trace_path.read_bytes())
                manifest_path.write_bytes(canonical(manifest)+b"\n")
                with self.assertRaises(ValueError):verify(tmp)


if __name__ == "__main__":unittest.main()
