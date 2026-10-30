import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from rolling_inventory.environment import Environment, generate, seasonal
from rolling_inventory.experiment import close, digest, write
from rolling_sensitivity.planning import decide
from rolling_forecast.forecasting import predict, policy_observation, score_path, select
from rolling_forecast.experiment import settings, rollout, run, verify


class ForecastTests(unittest.TestCase):
    def task(self):
        cfg, physical = settings(True)
        return cfg, generate(physical,'forecast-calibration',cfg['calibration_seeds'])[0]

    def test_original_forecast_and_controller_compatibility(self):
        cfg, task = self.task(); env = Environment(task)
        model = {'family':'ewma','alpha':0.35}
        for _ in range(task['public']['periods']):
            obs = env.observe(); close(obs,policy_observation(obs,model))
            action, _ = decide(obs,{'kind':'scenario','count':7,'sampler':901337,'allocation':'uniform','fraction':0.},1.)
            env.step(action)
        result, rows, _ = rollout(task,'original_ewma',model,901337,cfg)
        self.assertEqual(rows[-1]['stock_end'],env.stock.tolist())
        self.assertEqual(result['remaining_carbon'],env.remaining)

    def test_future_path_and_profile_do_not_enter_policy(self):
        _, task = self.task(); other = copy.deepcopy(task)
        other.update(profile='different_private_label',id='different_private_id')
        other['demand'] = [[900,800,700] for _ in other['demand']]
        model = {'family':'ewma','alpha':0.7}
        close(policy_observation(Environment(task).observe(),model),policy_observation(Environment(other).observe(),model))
        obs = Environment(task).observe(); obs.update(profile='hidden',demand=other['demand'])
        self.assertNotIn('demand',policy_observation(obs,model))
        self.assertNotIn('profile',policy_observation(obs,model))

    def test_history_boundary_rejects_future_observation(self):
        _, task = self.task()
        with self.assertRaisesRegex(ValueError,'history_must_end'):
            predict(task['public'],task['demand'],0,{'family':'ewma','alpha':0.7})

    def test_window_removes_seasonality_and_truncates_history(self):
        _, task = self.task(); p = task['public']
        history = [[100,100,100],(np.array([2,4,6])*seasonal(1)).tolist(),(np.array([4,6,8])*seasonal(2)).tolist()]
        pred = predict(p,history,3,{'family':'window','window':2})
        np.testing.assert_allclose(pred[0],np.array([3,5,7])*seasonal(3))
        close(predict(p,[],0,{'family':'window','window':2})[0],(np.asarray(p['base_mean'])*seasonal(0)).tolist())

    def test_nll_is_exact_distribution_score_not_ensemble_score(self):
        _, task = self.task(); task['public']['base_mean'] = [1/0.85]*3
        task['demand'][0] = [0,1,2]
        row = score_path(task,{'family':'ewma','alpha':0.35},'original')[0]
        np.testing.assert_allclose(row['nll'],[1,1,1+np.log(2)])

    def test_calibration_selection_and_split_guard(self):
        cfg, task = self.task(); cfg['fast_alpha_candidates']=[0.55,0.55]
        selection, candidates = select([task],cfg)
        self.assertEqual(selection['ranking']['fast_ewma']['selected_index'],0)
        self.assertEqual(len(candidates),5)
        task['split']='forecast-development'
        with self.assertRaisesRegex(ValueError,'calibration_only'):
            select([task],cfg)

    def test_smoke_seeds_are_separate_and_full_counts_fixed(self):
        cfg, physical = settings(); smoke, _ = settings(True)
        self.assertFalse(set(smoke['calibration_seeds']+smoke['development_seeds']) & set(cfg['calibration_seeds']+cfg['development_seeds']))
        self.assertEqual(len(cfg['development_seeds'])*len(physical['profiles'])*(3*len(cfg['sampler_seeds'])+2),352)

    def test_complete_smoke_and_rehashed_action_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp); result=run(out,True)
            self.assertEqual(result['trajectories'],5)
            self.assertTrue(verify(out)['all_policies_reexecuted'])
            path=out/'traces-00.jsonl'; rows=[json.loads(x) for x in path.read_text().splitlines()]
            rows[0]['rows'][0]['action'][0][0]+=1
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            manifest=json.loads((out/'manifest.json').read_text()); manifest['files'][path.name]=digest(path)
            write(out/'manifest.json',manifest)
            with self.assertRaises(ValueError): verify(out)

    def test_rehashed_negative_timing_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp); run(out,True)
            path=out/'timing.jsonl'; rows=[json.loads(x) for x in path.read_text().splitlines()]
            rows[0]['decision_seconds'][0]=-1
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            manifest=json.loads((out/'manifest.json').read_text());manifest['files'][path.name]=digest(path)
            write(out/'manifest.json',manifest)
            with self.assertRaisesRegex(ValueError,'invalid_timing'):verify(out)


if __name__=='__main__':unittest.main()
