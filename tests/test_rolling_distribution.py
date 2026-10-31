import copy
from pathlib import Path
import tempfile
import unittest
import numpy as np
from rolling_inventory.environment import Environment, generate
from rolling_inventory.experiment import close, digest, write
from rolling_inventory.planning import path_cost
from rolling_sensitivity.planning import samples, solve
from rolling_distribution.forecasting import fit, observation, estimate, sample, couple, nll, ensemble_scores, select
from rolling_distribution.experiment import settings, run, verify, read, save_rows


class DistributionTests(unittest.TestCase):
    def fixture(self):
        cfg, physical = settings(True)
        fitting = generate(physical, 'distribution-fit', cfg['fit_seeds'])
        prior, _ = fit(fitting)
        task = generate(physical, 'distribution-tune', cfg['tune_seeds'])[0]
        return cfg, task, prior

    def test_poisson_baseline_is_unchanged(self):
        cfg, task, prior = self.fixture(); obs = observation(Environment(task).observe())
        values, kappa = sample(obs, prior, 12, 'poisson', 7, 901337)
        np.testing.assert_array_equal(values, samples(obs, 7, 901337))
        np.testing.assert_array_equal(kappa, np.zeros(3))

    def test_future_and_private_labels_do_not_enter_distribution(self):
        cfg, task, prior = self.fixture(); altered = copy.deepcopy(task)
        altered.update(id='secret_id', profile='secret_profile', demand=[[999]*3]*4)
        a = observation(Environment(task).observe()); b = observation(Environment(altered).observe())
        close(a, b)
        np.testing.assert_array_equal(sample(a, prior, 12, 'residual_nb', 7, 9)[0],
                                      sample(b, prior, 12, 'residual_nb', 7, 9)[0])
        a['history'] = [[1, 2, 3]]
        with self.assertRaisesRegex(ValueError, 'history_boundary'):
            estimate(a, prior, 12)

    def test_fit_tune_split_guards_and_all_candidates_saved(self):
        cfg, task, prior = self.fixture()
        with self.assertRaisesRegex(ValueError, 'fit_split_required'): fit([task])
        selection, rows = select([task], prior, cfg)
        self.assertEqual(len(rows), 3*task['public']['periods'])
        self.assertEqual(selection['selected_index'], int(np.argmin(selection['candidate_nll'])))
        task['split'] = 'distribution-confirmation'
        with self.assertRaisesRegex(ValueError, 'tune_split_required'): select([task], prior, cfg)

    def test_nll_poisson_and_geometric_closed_forms(self):
        np.testing.assert_allclose(nll([0, 1, 2], [1, 1, 1], [0, 0, 0]), [1, 1, 1+np.log(2)])
        # NB kappa=1, mean=1 is geometric p=1/2.
        np.testing.assert_allclose(nll([0, 1, 2], [1, 1, 1], [1, 1, 1]), np.log(2)*np.array([1, 2, 3]))

    def test_dispersion_uses_only_past_and_clips(self):
        cfg, task, prior = self.fixture(); env = Environment(task); obs = observation(env.observe())
        expected = np.clip(np.array(prior['numerator_mean'])/prior['denominator_mean'], 0, 2)
        np.testing.assert_allclose(estimate(obs, prior, 12), expected)
        env.step(np.zeros((3, 2), dtype=int)); obs = observation(env.observe())
        self.assertTrue(np.all((estimate(obs, prior, 12) >= 0) & (estimate(obs, prior, 12) <= 2)))

    def test_coupling_preserves_entire_paths_and_objective(self):
        cfg, task, prior = self.fixture(); obs = observation(Environment(task).observe())
        x, _ = sample(obs, prior, 12, 'residual_nb', 7, 77)
        joint = couple(x, obs, prior, 12, 77)
        for i in range(3):
            self.assertEqual(sorted(map(tuple, x[:, :, i])), sorted(map(tuple, joint[:, :, i])))
        plan, info = solve(obs, x); other, info2 = solve(obs, joint)
        self.assertAlmostEqual(info['objective'], info2['objective'], places=6)
        # Every feasible schedule, not only optima, must retain its objective.
        for q in [plan, other, np.zeros((x.shape[1], 3, 2), dtype=int)]:
            self.assertAlmostEqual(np.mean([path_cost(obs, q, d) for d in x]),
                                   np.mean([path_cost(obs, q, d) for d in joint]), places=8)

    def test_scores_detect_dependence_with_identical_margins(self):
        correlated = np.array([[0, 0], [2, 2]])
        opposite = np.array([[0, 2], [2, 0]])
        a = ensemble_scores(correlated, [0, 0]); b = ensemble_scores(opposite, [0, 0])
        self.assertEqual(a['marginal_crps'], b['marginal_crps'])
        self.assertEqual(a['variogram_p05'], 0.)
        self.assertGreater(b['variogram_p05'], 0.)
        self.assertLess(a['energy'], b['energy'])
        point = ensemble_scores([[1, 2, 3]], [1, 2, 3])
        self.assertEqual(point['energy'], 0.); self.assertEqual(point['coverage80'], 1.)

    def test_formal_counts_and_smoke_isolation(self):
        cfg, p = settings(); tiny, _ = settings(True)
        self.assertEqual(len(cfg['confirmation_seeds'])*len(p['profiles']), 64)
        for key in ['fit_seeds', 'tune_seeds', 'confirmation_seeds']:
            self.assertFalse(set(cfg[key]) & set(tiny[key]))

    def test_full_smoke_replay_and_rehashed_action_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp); result = run(out, True)
            self.assertEqual(result['trajectories'], 4)
            self.assertTrue(verify(out)['policies_reexecuted'])
            target = out/'traces-00.jsonl.gz'; rows = read(target)
            rows[0]['rows'][0]['action'][0][0] += 1
            save_rows(target, rows); manifest = read(out/'manifest.json')
            manifest['files'][target.name] = digest(target); write(out/'manifest.json', manifest)
            with self.assertRaises(ValueError): verify(out)

    def test_negative_timing_rejected_after_rehash(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp); run(out, True)
            target = out/'timing.jsonl.gz'; rows = read(target); rows[0]['decision_seconds'][0] = -1
            save_rows(target, rows); manifest = read(out/'manifest.json')
            manifest['files'][target.name] = digest(target); write(out/'manifest.json', manifest)
            with self.assertRaisesRegex(ValueError, 'invalid_timing'): verify(out)


if __name__ == '__main__': unittest.main()
