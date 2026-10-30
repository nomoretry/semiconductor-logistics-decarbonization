"""PPO math, rollout boundaries, frozen initialization and replay contracts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from notice_benchmark.api_runner import canonical_bytes as canonical,sha256
from query_policy.features import encode
from query_policy.model import initialize,probabilities,serialize
from query_policy.solver import Planner
from query_ppo.algorithm import actor_objective,critic_objective,gae,initialize_critic,value,decode_critic
from query_ppo.experiment import config,tasks,initial_actor,run,verify,BC_SHA
from query_ppo.training import collect,train


class QueryPPOTests(unittest.TestCase):
    def test_gae_does_not_cross_episodes(self):
        a,r=gae([1,2,100,200],[.1,.2,5,6],np.array([False,True,False,True]),1.,.95)
        left=gae([1,2],[.1,.2],np.array([False,True]),1.,.95)
        right=gae([100,200],[5,6],np.array([False,True]),1.,.95)
        np.testing.assert_allclose(a,np.r_[left[0],right[0]])
        np.testing.assert_allclose(r,np.r_[left[1],right[1]])
        self.assertAlmostEqual(a[1],1.8)

    def test_gae_lambda_one_matches_monte_carlo_return(self):
        _,r=gae([-2,-3,-80],[4,8,-6],np.array([False,False,True]),1.,1.)
        np.testing.assert_allclose(r,[-85,-83,-80])

    def test_incomplete_and_nonfinite_trajectories_rejected(self):
        for rewards,dones in (([1],[False]),([float("nan")],[True])):
            with self.assertRaises(ValueError):gae(rewards,[0],np.array(dones))

    def check_gradient(self,p,objective,positions):
        _,grads,*_=objective()
        for key,indices in positions.items():
            for index in indices:
                old=p[key][index];p[key][index]=old+1e-5;hi=objective()[0]
                p[key][index]=old-1e-5;lo=objective()[0];p[key][index]=old
                self.assertAlmostEqual(grads[key][index],(hi-lo)/2e-5,places=7)

    def test_clipped_actor_and_entropy_gradients_by_finite_difference(self):
        p=initialize(10,hidden=3);x=np.random.default_rng(7).normal(size=(4,3,37))
        mask=np.array([[1,1,0],[1,1,1],[1,1,1],[1,0,1]],bool)
        actions=np.array([0,1,2,2]);adv=np.array([-1.,1.,2.,-2.])
        probs=probabilities(p,x,mask)[0]
        old=np.log(probs[np.arange(4),actions])-np.log([.5,1.5,.9,1.1])
        objective=lambda:actor_objective(p,x,mask,actions,old,adv,.2,.03)
        self.check_gradient(p,objective,{"w":[(0,0),(36,2)],"b":[(1,)],"v":[(0,),(2,)]})
        self.assertAlmostEqual(objective()[2]["clip_fraction"],.5)

    def test_clipped_branches_have_zero_policy_gradient(self):
        p=initialize(2);x=np.ones((2,2,37));mask=np.ones((2,2),bool)
        probs=probabilities(p,x,mask)[0];actions=np.array([0,1])
        old=np.log(probs[np.arange(2),actions])-np.log([1.5,.5])
        _,grads,_=actor_objective(p,x,mask,actions,old,np.array([1.,-1.]),.2,0.)
        for g in grads.values():np.testing.assert_allclose(g,0.,atol=1e-12)

    def test_clipped_value_gradients_by_finite_difference(self):
        p=initialize_critic(8,hidden=3);x=np.random.default_rng(2).normal(size=(4,20))
        prediction=value(p,x)[0];old=prediction+np.array([-.4,.4,.05,-.05])
        returns=prediction+np.array([1.,-1.,.4,-.7])
        objective=lambda:critic_objective(p,x,old,returns,.2)
        self.check_gradient(p,objective,{"w":[(0,0),(19,2)],"b":[(2,)],"v":[(0,)],"c":[(0,)]})

    def test_forced_commit_has_no_actor_gradient(self):
        p=initialize(3);x=np.ones((1,3,37));mask=np.array([[True,False,False]])
        _,g,_=actor_objective(p,x,mask,np.array([0]),np.array([0.]),np.array([2.]),.2,.01)
        for a in g.values():np.testing.assert_allclose(a,0.,atol=1e-12)

    def test_invalid_training_action_and_nonfinite_checkpoint_rejected(self):
        p=initialize(3);x=np.ones((1,3,37));mask=np.array([[True,False,False]])
        for action in (-1,1,3):
            with self.assertRaises(ValueError):actor_objective(p,x,mask,np.array([action]),np.array([0.]),np.array([1.]),.2,.01)
        cp=serialize(initialize_critic(2));cp["c"][0]=float("nan")
        with self.assertRaises(ValueError):decode_critic(cp)

    def test_new_pilot_has_no_old_contexts(self):
        ts=tasks(config());identities=[sha256(canonical(t["public"])) for t in ts]
        self.assertEqual(len(ts),126);self.assertEqual(len(set(identities)),126)
        self.assertEqual(sum(t["split"]=="pilot" for t in ts),36)

    def test_sampled_rewards_masks_and_advantages_recompute(self):
        cfg=config(True);ts=[t for t in tasks(cfg,True) if t["split"]=="train"]
        cfg["episodes_per_context"]=10
        models={t["id"]:Planner(t["public"]) for t in ts}
        data,episodes=collect(ts,models,initial_actor(),initialize_critic(18),cfg,np.random.default_rng(17),1)
        for e in episodes:
            public=ts[0]["public"];model=Planner(public);h=(-1,)*public["delay_bits"]
            for s in e["steps"]:
                self.assertEqual(s["history"],list(h))
                mask=encode(public,h)[1];self.assertTrue(mask[s["action"]])
                if s["done"]:
                    self.assertEqual(s["action"],0);self.assertIsNone(s["answer"])
                    self.assertAlmostEqual(s["reward"],-model.terminal(h)[0]/100)
                else:
                    i=s["action"]-1;self.assertAlmostEqual(s["reward"],-public["query_fees"][i]/100)
                    h=list(h);h[i]=s["answer"];h=tuple(h)
            self.assertTrue(e["steps"][-1]["done"])
            self.assertLessEqual(len(e["steps"]),4)
        self.assertEqual(len(data[0]),sum(len(e["steps"]) for e in episodes))

    def test_training_has_shared_bc_start_real_updates_and_no_teacher_q(self):
        cfg=config(True);ts=[t for t in tasks(cfg,True) if t["split"]!="pilot"]
        actor=initial_actor();before=serialize(actor)
        with patch.object(Planner,"_value",side_effect=AssertionError("teacher Q forbidden")):
            first=train(ts,actor,cfg);second=train(ts,actor,cfg)
        self.assertEqual(first,second);self.assertEqual(first[0]["actor"],before)
        self.assertEqual(serialize(actor),before)
        self.assertGreater(first[3]["last_actor_l2_from_bc"],0)
        self.assertGreater(first[3]["total_updates"],0)
        selected=first[3]["selected_iteration"]
        costs=first[3]["validation"]
        self.assertAlmostEqual(next(x["mean_expected_loss"] for x in costs if x["iteration"]==selected),min(x["mean_expected_loss"] for x in costs))

    def test_training_rejects_pilot_split(self):
        cfg=config(True)
        with self.assertRaisesRegex(ValueError,"only_train_and_dev"):
            train(tasks(cfg,True),initial_actor(),cfg)

    def test_full_smoke_replay_and_rehashed_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp,True);result=verify(tmp);self.assertTrue(result["shared_bc_start"])
            with self.assertRaisesRegex(ValueError,"output_not_empty"):run(tmp,True)
            root=Path(tmp);original=(root/"episodes.jsonl").read_bytes()
            rows=[json.loads(s) for s in original.splitlines()];rows[0]["steps"][0]["reward"]+=.1
            (root/"episodes.jsonl").write_bytes(b"".join(canonical(r)+b"\n" for r in rows))
            m=json.loads((root/"manifest.json").read_text());m["files"]["episodes.jsonl"]=sha256((root/"episodes.jsonl").read_bytes())
            (root/"manifest.json").write_bytes(canonical(m)+b"\n")
            with self.assertRaises(ValueError):verify(tmp)
            (root/"episodes.jsonl").write_bytes(original);m["files"]["episodes.jsonl"]=sha256(original)
            p=json.loads((root/"selected.json").read_text());p["actor"]["v"][0]+=.1
            (root/"selected.json").write_bytes(canonical(p)+b"\n");m["files"]["selected.json"]=sha256((root/"selected.json").read_bytes())
            (root/"manifest.json").write_bytes(canonical(m)+b"\n")
            with self.assertRaises(ValueError):verify(tmp)


if __name__=="__main__":unittest.main()
