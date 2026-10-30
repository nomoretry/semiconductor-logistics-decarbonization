from copy import deepcopy
import itertools
import gzip
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from rolling_inventory.environment import Environment,generate
from rolling_inventory.planning import decide,solve
from rolling_inventory.experiment import ROOT,audit,run,verify,digest,write


class RollingTests(unittest.TestCase):
    def setUp(self):
        self.cfg=json.loads((ROOT/'rolling_inventory/config.json').read_text())
        self.task=generate(self.cfg,'test',[59])[0]

    def tiny(self):
        t=deepcopy(self.task);p=t['public']
        p.update(periods=3,horizon=3,holding=[.4],backlog=[7.],terminal_backlog=[21.],
                 mass=[1],lead=[1],capacity=[2],freight=[1.],emissions=[1],
                 initial_inventory=[0],initial_pipeline=[[0],[0],[0]],base_mean=[1.],carbon_budget=3)
        t['demand']=[[0],[1],[1]]
        return t

    def test_future_noninterference_for_all_baselines(self):
        b=deepcopy(self.task);b['demand'][1:]=[[99,99,99] for _ in b['demand'][1:]]
        aenv,benv=Environment(self.task),Environment(b)
        for env in (aenv,benv):env.step([[0,0]]*3)
        self.assertEqual(aenv.observe(),benv.observe())
        for method in self.cfg['methods']:
            self.assertEqual(decide(aenv.observe(),method),decide(benv.observe(),method))
        self.assertNotIn('seed',aenv.observe());self.assertNotIn('demand',aenv.observe())
        self.assertNotIn('profile',aenv.observe()['public'])

    def test_transit_not_available_before_due(self):
        t=deepcopy(self.task);t['demand']=[[0,0,0]]*12
        t['public']['initial_inventory']=[0,0,0];t['public']['initial_pipeline']=[[0,0,0]]*12
        env=Environment(t);env.step([[1,0],[0,1],[0,0]])
        self.assertEqual(env.observe()['stock'],[0,1,0])
        env.step([[0,0]]*3)
        self.assertEqual(env.observe()['stock'],[1,1,0])

    def test_old_backlog_is_served_before_new_fill(self):
        t=self.tiny();t['demand']=[[2],[1],[0]];env=Environment(t)
        env.step([[2]])
        row=env.step([[0]])
        self.assertEqual(row['observation']['served_old'],[2])
        self.assertEqual(row['filled_new'],[0]);self.assertEqual(row['backlog_end'],[1])

    def test_invalid_actions_are_atomic(self):
        for action in ([[9,0],[0,0],[0,0]],[[4,0],[3,0],[0,0]],[[.5,0],[0,0],[0,0]],[[-1,0],[0,0],[0,0]],[[True,False]]*3):
            env=Environment(self.task);before=deepcopy(env.__dict__)
            with self.assertRaises(ValueError):env.step(action)
            np.testing.assert_array_equal(before['pipeline'],env.pipeline)
            self.assertEqual(before['history'],env.history);self.assertEqual(env.t,0)
        env=Environment(self.task);env.remaining=0;obs=env.observe()
        with self.assertRaisesRegex(ValueError,'carbon'):env.step([[1,0],[0,0],[0,0]])
        self.assertEqual(env.observe(),obs)

    def test_arrival_beyond_terminal_rejected(self):
        env=Environment(self.tiny())
        env.step([[0]]);env.step([[0]])
        with self.assertRaisesRegex(ValueError,'arrival'):env.step([[1]])
        self.assertEqual(env.t,2)

    def test_tiny_milp_matches_exhaustive_physics(self):
        task=self.tiny();obs=Environment(task).observe()
        plan,info=solve(obs,[task['demand']],paced=False)
        allcost=[]
        for q in itertools.product(range(3),repeat=2):
            if sum(q)>3:continue
            env=Environment(task)
            allcost.append(sum(env.step([[v]])['cost'] for v in (*q,0)))
        self.assertAlmostEqual(info['objective'],min(allcost))
        env=Environment(task);rows=[env.step(a) for a in plan]
        audit(task,rows)
        self.assertAlmostEqual(sum(x['cost'] for x in rows),info['objective'])

    def test_shared_scenario_dispatch_not_clairvoyant(self):
        t=self.tiny();obs=Environment(t).observe()
        plan,info=solve(obs,[[[0],[0],[0]],[[0],[2],[2]]],paced=False)
        self.assertEqual(np.array(plan).shape,(3,1,1))
        self.assertEqual(info['dispatch_variables'],3)
        self.assertEqual(info['continuous_variables'],12)

    def test_ledger_detects_inventory_creation_and_cost_changes(self):
        env=Environment(self.tiny());rows=[env.step([[0]]) for _ in range(3)]
        audit(self.tiny(),rows)
        changed=deepcopy(rows);changed[1]['stock_end']=[1]
        with self.assertRaises(ValueError):audit(self.tiny(),changed)
        changed=deepcopy(rows);changed[1]['costs']['backlog']=0.
        with self.assertRaises(ValueError):audit(self.tiny(),changed)

    def test_smoke_replay_and_rehashed_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(tmp,True);self.assertTrue(verify(tmp)['verified'])
            p=Path(tmp);rows=[json.loads(x) for x in gzip.decompress((p/'traces.jsonl.gz').read_bytes()).decode().splitlines()]
            rows[0]['rows'][0]['demand'][0]+=1
            (p/'traces.jsonl.gz').write_bytes(gzip.compress(''.join(json.dumps(x)+'\n' for x in rows).encode(),mtime=0))
            manifest=json.loads((p/'manifest.json').read_text())
            manifest['files']['traces.jsonl.gz']=digest(p/'traces.jsonl.gz');write(p/'manifest.json',manifest)
            with self.assertRaises(ValueError):verify(tmp)


if __name__=='__main__':unittest.main()
