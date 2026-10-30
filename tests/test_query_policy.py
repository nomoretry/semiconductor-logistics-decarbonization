"""Learning, information boundaries and checkpoint-bound evidence contracts."""
import copy
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from notice_benchmark.api_runner import canonical_bytes, sha256
from scripts.audit_decision_scale import Planner,generate
from query_policy.features import encode
from query_policy.model import initialize,loss_gradient,probabilities,train,serialize,deserialize
from query_policy.experiment import config,tasks,teacher,batch,learned_tree,run,verify


class QueryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.public = generate(4,2,1001)

    def test_analytic_gradient_matches_central_difference_with_multiple_positives(self):
        p = initialize(9,hidden=3)
        x = np.random.default_rng(2).normal(size=(2,3,37))
        mask = np.array([[True,True,False],[True,True,True]])
        positive = np.array([[True,False,False],[False,True,True]])
        weights = np.array([.4,1.6])
        _, grads = loss_gradient(p,x,mask,positive,weights)
        for key, positions in {"w":[(0,0),(15,2),(36,1)],"b":[(0,),(2,)],"v":[(0,),(2,)]}.items():
            for index in positions:
                with self.subTest(key=key,index=index):
                    original = p[key][index]
                    p[key][index] = original+1e-5; high = loss_gradient(p,x,mask,positive,weights)[0]
                    p[key][index] = original-1e-5; low = loss_gradient(p,x,mask,positive,weights)[0]
                    p[key][index] = original
                    self.assertAlmostEqual(grads[key][index],(high-low)/2e-5,places=7)

    def test_dynamic_candidates_are_permutation_equivariant(self):
        x,mask = encode(self.public,(-1,-1));p=initialize(17)
        original = probabilities(p,x,mask)[0]
        permutation = np.array([2,0,1])
        np.testing.assert_allclose(probabilities(p,x[permutation],mask[permutation])[0],original[permutation])

    def test_teacher_and_private_fields_cannot_enter_policy_features(self):
        for key in ("private_evaluation_bits","task_id","seed","q_values","oracle"):
            c = copy.deepcopy(self.public);c[key]=[]
            with self.assertRaisesRegex(ValueError,"public_context_fields"):
                encode(c,(-1,-1))
        c = copy.deepcopy(self.public);c["known_orders"][0]["teacher"] = 2
        with self.assertRaises(ValueError):encode(c,(-1,-1))

    def test_encoder_does_not_call_solver(self):
        with patch.object(Planner,"_terminal",side_effect=AssertionError("no solver in encoder")):
            x,mask=encode(self.public,(-1,-1))
        self.assertEqual(x.shape,(3,37));self.assertEqual(mask.tolist(),[True,True,True])

    def test_mask_matches_independent_environment_budget_rules(self):
        for n,k,seed in ((4,2,1001),(8,4,2001),(12,6,3001)):
            c=generate(n,k,seed); p=Planner(c)
            for state in teacher({"id":"x","split":"train","public":c},1e-7)["states"]:
                h=tuple(state["history"]); _,mask=encode(c,h)
                self.assertEqual(mask.tolist(),[True,*[i in p.legal(h) for i in range(k)]])

    def test_illegal_history_and_masked_positive_are_rejected(self):
        with self.assertRaises(ValueError):encode(self.public,(True,-1))
        p=initialize(1);x,mask=encode(self.public,(-1,-1));mask[2]=False
        positive=np.array([[False,False,True]])
        with self.assertRaisesRegex(ValueError,"positive_mask"):
            loss_gradient(p,x[None],mask[None],positive,np.ones(1))

    def test_all_positive_set_has_zero_loss_and_gradient(self):
        p=initialize(3);x,mask=encode(self.public,(-1,-1))
        loss,grad=loss_gradient(p,x[None],mask[None],mask[None],np.ones(1))
        self.assertAlmostEqual(loss,0.)
        for g in grad.values():np.testing.assert_allclose(g,0.,atol=1e-12)

    def test_teacher_q_values_equal_explicit_bellman_values(self):
        t={"id":"t","split":"train","public":self.public};p=Planner(self.public)
        for s in teacher(t,1e-7)["states"]:
            h=tuple(s["history"])
            self.assertAlmostEqual(min(v for v in s["q_values"] if v is not None),p.value(h,2)[0])
            self.assertTrue(any(s["positives"]))

    def test_contexts_are_disjoint_and_training_contexts_have_equal_weight(self):
        cfg=config(True);cfg["delay_bits"]=[2,4];ts=tasks(cfg)
        self.assertEqual(len({sha256(canonical_bytes(t["public"])) for t in ts}),len(ts))
        teachers=[teacher(t,1e-7) for t in ts]
        data=batch(ts,teachers,"train");counts=[sum(sum(v is not None for v in s["q_values"])>1 for s in t["states"]) for t in teachers if t["split"]=="train"]
        weights=data[3];self.assertAlmostEqual(weights[:counts[0]].sum(),weights[counts[0]:].sum())

    def test_learning_changes_weights_and_replays_deterministically(self):
        cfg=config(True);cfg["epochs"]=5;ts=tasks(cfg);teacher_rows=[teacher(t,1e-7) for t in ts]
        a,b=batch(ts,teacher_rows,"train"),batch(ts,teacher_rows,"dev")
        first=train(a,b,cfg);second=train(a,b,cfg)
        self.assertGreater(first[2]["updates"],0)
        self.assertLess(first[2]["epochs"][-1]["train"]["set_nll"],first[2]["epochs"][0]["train"]["set_nll"])
        self.assertEqual(first[2],second[2]);self.assertEqual(serialize(first[1]),serialize(second[1]))

    def test_learned_policy_expected_loss_matches_full_world_enumeration(self):
        p=initialize(17);tree=learned_tree(self.public,"bc",p);lookup={tuple(n["history"]):n for n in tree["nodes"]}
        expected=0.;model=Planner(self.public)
        for truth in itertools.product((0,1),repeat=2):
            weight=np.prod([pr if bit else 1-pr for pr,bit in zip(self.public["prior"],truth)])
            h=(-1,-1);fees=0
            while lookup[h]["action"] != -1:
                i=lookup[h]["action"];fees+=self.public["query_fees"][i];h=list(h);h[i]=truth[i];h=tuple(h)
            expected+=weight*(fees+model.shipping(lookup[h]["commit_plan"],truth)["loss"])
        self.assertAlmostEqual(expected,tree["expected_loss"])
        self.assertAlmostEqual(sum(n["probability"]*n["milp_calls"] for n in tree["nodes"]),1.)

    def test_checkpoint_shapes_and_nonfinite_values_are_rejected(self):
        p=serialize(initialize(3));p["v"][0]=float("nan")
        with self.assertRaises(ValueError):deserialize(p,32)

    def test_carbon_slack_tolerance_uses_exact_physical_loss(self):
        from query_policy.solver import Planner as CheckedPlanner
        model=CheckedPlanner(generate(12,6,1004))
        h=(-1,-1,-1,1,1,1)
        cost,plan=model.terminal(h)
        self.assertAlmostEqual(cost,420.45)
        self.assertEqual(cost,model.shipping(plan,h)["loss"])

    def test_bundle_retrains_and_replays_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp,True);self.assertTrue(verify(tmp)["checkpoint_replayed"])
            with self.assertRaisesRegex(ValueError,"output_not_empty"):run(tmp,True)

    def test_modified_checkpoint_rejected_even_with_updated_file_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp,True);root=Path(tmp)
            p=json.loads((root/"checkpoint.json").read_text());p["v"][0]+=.1
            (root/"checkpoint.json").write_bytes(canonical_bytes(p)+b"\n")
            m=json.loads((root/"manifest.json").read_text());m["files"]["checkpoint.json"]=sha256((root/"checkpoint.json").read_bytes())
            (root/"manifest.json").write_bytes(canonical_bytes(m)+b"\n")
            with self.assertRaises(ValueError):verify(tmp)


if __name__ == "__main__":unittest.main()
