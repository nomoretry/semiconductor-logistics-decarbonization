"""Cross-check physical accounting, admissibility, planning and evidence replay."""
import copy
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from coupled_decision.audit import generate, run_audit, verify
from coupled_decision.env import Environment, run
from coupled_decision.model import allocations, physical, validate
from coupled_decision.planning import Planner, INITIAL, METHODS


class CoupledTests(unittest.TestCase):
    def setUp(self):
        self.c = generate(1,61803)[0]["context"]

    def test_deterministic_generation(self):
        self.assertEqual(generate(6,17),generate(6,17))
        self.assertNotEqual(generate(6,17),generate(6,18))

    def test_illegal_call_is_atomic(self):
        e = Environment(self.c,0,[0,0,0])
        before = e.observation()
        with self.assertRaises(ValueError): e.step("commit")
        self.assertEqual(before,e.observation())

    def test_hidden_world_noninterference(self):
        a = Environment(self.c,0,[0,0,0]); b = Environment(self.c,3,[1,1,0])
        self.assertEqual(a.observation(),b.observation())
        self.assertEqual(a.step("solve_bayes"),b.step("solve_bayes"))
        a.step("commit"); b.step("commit")
        self.assertNotEqual(a.evaluation(),b.evaluation())

    def test_public_observation_is_copy(self):
        e=Environment(self.c,0,[0,0,0]); before=e.observation()
        changed=e.observation();changed["context"]["skus"][0]["quantity"]=999
        self.assertEqual(before,e.observation())

    def test_capacity_and_quantity_enforced(self):
        c=copy.deepcopy(self.c)
        c["routes"][0]["capacity_kg"]=1
        air=tuple((s["quantity"],0,0) for s in c["skus"])
        with self.assertRaises(ValueError): physical(c,air,0)
        malformed=tuple((0,0,0) for s in c["skus"])
        with self.assertRaises(ValueError): physical(c,malformed,0)
        for plan in allocations(c):
            out=physical(c,plan,0)
            self.assertTrue(all(x<=r["capacity_kg"] for x,r in zip(out["route_load_kg"],c["routes"])))

    def test_known_hand_computed_inventory(self):
        c=copy.deepcopy(self.c)
        c["routes"][1]["capacity_kg"]=100
        plan=tuple((0,s["quantity"],0) for s in c["skus"])
        out=physical(c,plan,2)
        for sku,ledger in zip(c["skus"],out["sku_ledger"]):
            self.assertEqual(ledger["arrivals"][4],sku["quantity"])
            self.assertEqual(sum(ledger["backlog"]),sku["quantity"]*(4-sku["due_week"]))
            self.assertEqual(ledger["inventory"], [0]*6)

    def test_budget_reserves_solver_and_limits_queries(self):
        c=copy.deepcopy(self.c);c["query_budget"]=1
        p=Planner(c)
        self.assertEqual(p.legal_queries(INITIAL),())
        self.assertEqual(p.action(INITIAL,"exact_dp"),-1)
        c["query_budget"]=100;c["max_queries"]=1
        p=Planner(c)
        self.assertEqual(p.legal_queries((0,-1,-1)),())

    def test_bayes_posterior_joint_information(self):
        p=Planner(self.c)
        b=p.belief((1,-1,-1))
        self.assertEqual(b[:2],(0.,0.))
        self.assertAlmostEqual(sum(b),1)
        with self.assertRaises(ValueError): p.belief((2,-1,-1))

    def test_full_policy_tree_vs_separate_recursive_search(self):
        # No calls to lookahead() or expected() in this independent recursion.
        c=copy.deepcopy(self.c);c["query_budget"]=40;c["max_queries"]=3
        p=Planner(c)
        def exhaustive(history):
            weights=list(c["prior"])
            for q,a in zip(c["queries"],history):
                if a!=-1:
                    weights=[x*(l if a else 1-l) for x,l in zip(weights,q["positive_likelihood"])]
            z=sum(weights);weights=[x/z for x in weights]
            stop=c["solve_fee"]+min(sum(physical(c,plan,w)["shipping_loss"]*weights[w] for w in range(4)) for plan in allocations(c))
            spent=sum(q["fee"] for q,a in zip(c["queries"],history) if a!=-1)
            if sum(a!=-1 for a in history)>=c["max_queries"]: return stop
            for i,q in enumerate(c["queries"]):
                if history[i]!=-1 or spent+q["fee"]+c["solve_fee"]>c["query_budget"]: continue
                total=q["fee"]
                for answer in (0,1):
                    probability=sum(x*(l if answer else 1-l) for x,l in zip(weights,q["positive_likelihood"]))
                    if probability>1e-14:
                        nxt=list(history);nxt[i]=answer
                        total+=probability*exhaustive(tuple(nxt))
                stop=min(stop,total)
            return stop
        self.assertAlmostEqual(p.expected(INITIAL,"exact_dp"),exhaustive(INITIAL),places=9)

    def test_policies_never_beat_exact_and_relaxation(self):
        for task in generate(8,79):
            c=task["context"]; p=Planner(c); exact=p.expected(INITIAL,"exact_dp")
            for method in METHODS:
                self.assertGreaterEqual(p.expected(INITIAL,method)+1e-8,exact)
            self.assertLessEqual(Planner(c,shared=False).expected(INITIAL,"exact_dp"),exact+1e-8)

    def test_no_private_inputs_in_run_trace(self):
        tr=run(self.c,0,[0,0,0],"exact_dp")["trace"]
        for x in tr:
            for side in ("before","after"):
                self.assertEqual(set(x[side]),{"context","history","posterior","legal_tools","spent","candidate","done"})

    def test_model_rejects_nonfinite_or_bad_likelihood(self):
        for key,value in (("carbon_price",float("nan")),("query_budget",True)):
            c=copy.deepcopy(self.c);c[key]=value
            with self.assertRaises(ValueError): validate(c)
        c=copy.deepcopy(self.c);c["queries"][0]["positive_likelihood"][0]=2
        with self.assertRaises(ValueError): validate(c)

    def test_evidence_replay_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);run_audit(p,3,81)
            self.assertTrue(verify(p)["verified"])
            rows=json.loads((p/"outcomes.json").read_text());rows[0]["expected_loss"]+=1
            (p/"outcomes.json").write_text(json.dumps(rows))
            with self.assertRaises(ValueError):verify(p)


if __name__ == "__main__": unittest.main()
