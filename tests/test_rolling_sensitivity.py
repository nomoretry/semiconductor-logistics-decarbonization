from copy import deepcopy
import gzip
import itertools
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from rolling_inventory.environment import Environment, generate
from rolling_inventory.planning import solve as original_solve
from rolling_sensitivity.planning import credit_rates, samples, solve, window_budget
from rolling_sensitivity.experiment import ROOT, digest, rollout, run, variant, verify, write


class SensitivityTests(unittest.TestCase):
    def setUp(self):
        self.cfg=json.loads((ROOT/'rolling_inventory/config.json').read_text())
        self.task=generate(self.cfg,'test',[59])[0]

    def tiny(self):
        t=deepcopy(self.task);p=t['public']
        p.update(periods=3,horizon=3,holding=[.4],backlog=[7.],terminal_backlog=[21.],
                 mass=[1],lead=[1],capacity=[2],freight=[1.],emissions=[1],
                 initial_inventory=[2],initial_pipeline=[[0],[0],[0]],base_mean=[1.],carbon_budget=3)
        t['demand']=[[0],[1],[0]]
        return t

    def test_nested_samples_and_private_future_noninterference(self):
        obs=Environment(self.task).observe()
        for n in (1,7):np.testing.assert_array_equal(samples(obs,n,901337),samples(obs,21,901337)[:n])
        changed=deepcopy(self.task);changed['demand']=[[99,99,99]]*12
        other=Environment(changed).observe()
        self.assertEqual(obs,other)
        for a in ('uniform','forecast','free'):
            self.assertEqual(solve(obs,samples(obs,7,901337),a,.9),solve(other,samples(other,7,901337),a,.9))

    def test_carbon_allowances_and_backlog_response(self):
        obs=Environment(self.task).observe();h=6
        self.assertAlmostEqual(window_budget(obs,h,'uniform'),obs['carbon_remaining']/2)
        self.assertEqual(window_budget(obs,h,'free'),obs['carbon_remaining'])
        before=window_budget(obs,h,'forecast');obs['backlog']=[100,100,100]
        self.assertGreater(window_budget(obs,h,'forecast'),before)
        for a in ('uniform','forecast','free'):
            self.assertLessEqual(window_budget(obs,h,a),obs['carbon_remaining'])
        env=Environment(self.task);env.remaining=0
        with self.assertRaisesRegex(ValueError,'cumulative_carbon'):env.step([[1,0],[0,0],[0,0]])

    def test_neutral_extension_matches_frozen_solver(self):
        obs=Environment(self.task).observe();demands=samples(obs,7,901337)
        a,ai=original_solve(obs,demands);b,bi=solve(obs,demands)
        self.assertEqual(a,b);self.assertAlmostEqual(ai['objective'],bi['objective'])

    def test_credit_only_at_actual_episode_end(self):
        obs=Environment(self.task).observe();d=samples(obs,7,901337)
        a,ai=solve(obs,d,'uniform',0);b,bi=solve(obs,d,'uniform',.9)
        self.assertEqual(a,b);self.assertEqual(ai,bi)
        result,rows,_=rollout(self.tiny(),variant('base_stock','uniform',.9),1.)
        self.assertTrue(all(r['terminal_credit']==0 for r in rows[:-1]))
        expected=rows[-1]['stock_end'][0]*credit_rates(self.tiny()['public'],.9)[0]
        self.assertAlmostEqual(expected,result['terminal_credit'])
        self.assertAlmostEqual(result['net_cost'],result['operating_cost']-expected)

    def test_value_milp_matches_exhaustive_cost_and_no_arbitrage(self):
        task=self.tiny();obs=Environment(task).observe()
        for fraction in (0,.5,.9):
            plan,info=solve(obs,[task['demand']],'free',fraction)
            costs=[]
            for q in itertools.product(range(3),repeat=2):
                if sum(q)>3:continue
                env=Environment(task);rows=[env.step([[v]]) for v in (*q,0)]
                costs.append(sum(r['cost'] for r in rows)-rows[-1]['stock_end'][0]*credit_rates(env.p,fraction)[0])
            self.assertAlmostEqual(info['objective'],min(costs))
            self.assertEqual(plan,[[[0]],[[0]],[[0]]])
        for bad in (-.1,1.,float('nan')):
            with self.assertRaises(ValueError):solve(obs,[task['demand']],'free',bad)

    def test_rule_actions_identical_under_credit_rescoring(self):
        a,ar,_=rollout(self.tiny(),variant('base_stock','uniform',0.),1.)
        b,br,_=rollout(self.tiny(),variant('base_stock','uniform',.9),1.)
        self.assertEqual([r['action'] for r in ar],[r['action'] for r in br])
        self.assertEqual(a['operating_cost'],b['operating_cost'])
        self.assertAlmostEqual(a['net_cost']-b['net_cost'],b['terminal_credit'])

    def test_smoke_replay_and_rehashed_credit_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=run(tmp,True);self.assertEqual(result['trajectories'],22)
            self.assertTrue(verify(tmp)['verified'])
            p=Path(tmp);name='traces-00.jsonl.gz'
            rows=[json.loads(x) for x in gzip.decompress((p/name).read_bytes()).splitlines()]
            rows[0]['rows'][-1]['terminal_credit']+=1
            (p/name).write_bytes(gzip.compress(''.join(json.dumps(x)+'\n' for x in rows).encode(),mtime=0))
            m=json.loads((p/'manifest.json').read_text());m['files'][name]=digest(p/name);write(p/'manifest.json',m)
            with self.assertRaises(ValueError):verify(tmp)


if __name__=='__main__':unittest.main()
