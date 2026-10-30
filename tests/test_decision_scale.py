"""Independent enumeration checks the scalable MILP; replay rejects altered evidence."""
import copy
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_decision_scale import Planner, generate, audit, verify, canonical, sha256


class ScaleTests(unittest.TestCase):
    def test_milp_matches_exhaustive_dispatch_and_world_expectation(self):
        c=generate(2,2,31);p=Planner(c)
        rows=[]
        for s in c["known_orders"]:
            q=s["quantity"]
            rows.append([(a,b,q-a-b) for a in range(q+1) for b in range(q-a+1)])
        for h in ((-1,-1),(0,1),(1,0)):
            costs=[]
            for plan in itertools.product(*rows):
                try:costs.append(p.shipping(plan,h)["loss"])
                except ValueError:continue
            loss,plan=p.terminal(h)
            self.assertAlmostEqual(loss,min(costs),places=6)
            if h==(-1,-1):
                expected=0
                for world in itertools.product((0,1),repeat=2):
                    weight=1
                    for value,prior in zip(world,c["prior"]):weight*=prior if value else 1-prior
                    expected+=weight*p.shipping(plan,world)["loss"]
                self.assertAlmostEqual(loss,expected,places=6)

    def test_query_dp_matches_unmemoized_policy_tree(self):
        c=generate(2,2,47);p=Planner(c)
        def independent(h,spent,queries):
            result=p.terminal(h)[0]
            for i in range(2):
                if h[i]!=-1 or queries>=c["max_queries"] or spent+c["query_fees"][i]>c["query_budget"]:continue
                total=c["query_fees"][i]
                for value,weight in ((0,1-c["prior"][i]),(1,c["prior"][i])):
                    nxt=list(h);nxt[i]=value
                    total+=weight*independent(tuple(nxt),spent+c["query_fees"][i],queries+1)
                result=min(result,total)
            return result
        self.assertAlmostEqual(p.expected((-1,-1),"exact_dp"),independent((-1,-1),0,0))

    def test_budget_capacity_and_private_state_boundaries(self):
        c=generate(2,2,31);c["query_budget"]=0;p=Planner(c)
        self.assertEqual(p.legal((-1,-1)),())
        self.assertEqual(p.action((-1,-1),"exact_dp"),-1)
        with self.assertRaisesRegex(ValueError,"sku_coverage"):p.shipping([],(-1,-1))
        with self.assertRaisesRegex(ValueError,"capacity_violation"):
            p.shipping([(s["quantity"],0,0) for s in c["known_orders"]],(-1,-1))
        c["private_evaluation_bits"]=[0,1]
        with self.assertRaisesRegex(ValueError,"private_state"):Planner(c)

    def test_replay_rejects_forged_metrics_and_post_commit_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit(tmp,smoke=True);self.assertTrue(verify(tmp)["verified"])
            path=Path(tmp)/"outcomes.json";original=path.read_bytes()
            for mutation in ("regret","post_commit"):
                rows=json.loads(original)
                if mutation=="regret":rows[0]["normalized_regret"]+=.1
                else:rows[0]["trace"].append(copy.deepcopy(rows[0]["trace"][-1]))
                path.write_bytes(canonical(rows)+b"\n")
                manifest_path=Path(tmp)/"manifest.json";manifest=json.loads(manifest_path.read_text())
                manifest["files"]["outcomes.json"]=sha256(path.read_bytes())
                manifest_path.write_bytes(canonical(manifest)+b"\n")
                with self.assertRaises(ValueError):verify(tmp)


if __name__=="__main__":unittest.main()
