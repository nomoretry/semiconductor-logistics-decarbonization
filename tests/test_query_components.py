"""Mask isolation, terminal shaping, train-only fitting and evidence rejection."""
import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from query_study.development import datasets, prepare_teachers
from query_policy.solver import Planner
from query_policy.model import deserialize, probabilities
from query_ppo.algorithm import initialize_critic
from query_ppo.experiment import config as ppo_config
from query_ppo.training import train as old_train
from query_policy.experiment import close
from query_components import experiment as e
from query_components.potential import fit, phi
from query_components.environment import inputs, step, tree
from query_components.training import collect, train


class QueryComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks, cls.audit = datasets(True)
        cls.teachers = prepare_teachers(cls.tasks)
        cls.cfg = e.config(True)
        cls.settings = {**ppo_config(True), "action_mask": True, "shaping": True, "invalid_action_penalty": 25.}
        cls.fitted = fit([t for t in cls.tasks if t["split"] == "train"], cls.teachers, cls.cfg, 100.)
        cls.actor = deserialize(e.previous_bc(17), 32)

    def test_fitting_rejects_validation_and_has_no_validation_target_dependence(self):
        with self.assertRaisesRegex(ValueError, "training_contexts"):
            fit(self.tasks, self.teachers, self.cfg, 100.)
        poisoned = copy.deepcopy(self.teachers)
        for row in poisoned:
            if row["split"] == "dev":
                for state in row["states"]: state["q_values"][0] = 1e10
        other = fit([t for t in self.tasks if t["split"] == "train"], poisoned, self.cfg, 100.)
        self.assertEqual(self.fitted, other)

    def test_potential_is_solver_free_and_zero_at_terminal(self):
        c = self.tasks[0]["public"]; h = (-1,) * c["delay_bits"]
        with patch.object(Planner, "_terminal", side_effect=AssertionError("no solver in potential")):
            self.assertTrue(np.isfinite(phi(c, h, self.fitted)))
            self.assertEqual(phi(c, h, self.fitted, terminal=True), 0.)

    def test_mask_switch_preserves_features_and_only_removes_probability_filter(self):
        c = self.tasks[0]["public"]; h = [0] + [-1] * (c["delay_bits"] - 1)
        x, legal, masked = inputs(c, h, True)
        y, still_legal, unmasked = inputs(c, h, False)
        np.testing.assert_array_equal(x, y); np.testing.assert_array_equal(legal, still_legal)
        self.assertFalse(masked[1]); self.assertTrue(unmasked.all())
        self.assertEqual(probabilities(self.actor, x, masked)[0][1], 0.)
        self.assertGreater(probabilities(self.actor, x, unmasked)[0][1], 0.)

    def test_duplicate_budget_and_query_limit_rejections_do_not_mutate_history(self):
        for kind in ("duplicate", "budget", "limit"):
            c = copy.deepcopy(self.tasks[0]["public"])
            c["query_fees"] = [2] * c["delay_bits"]
            c["query_budget"] = 2 if kind == "budget" else 8
            c["max_queries"] = 1 if kind == "limit" else 3
            h = [0] + [-1] * (c["delay_bits"] - 1); before = copy.deepcopy(c)
            model = Planner(c); action = 1 if kind == "duplicate" else 2
            r = step(model, h, action, None, self.settings, self.fitted)
            self.assertTrue(r["invalid"]); self.assertTrue(r["done"])
            self.assertEqual(r["next_history"], h); self.assertEqual(c, before)
            self.assertAlmostEqual(r["base_reward"], -(model.terminal(tuple(h))[0] + 25.) / 100.)
            self.assertEqual(r["phi_after"], 0.)

    def test_potential_telescopes_for_commit_and_rejected_paths(self):
        c = self.tasks[0]["public"]; model = Planner(c); root = (-1,) * model.k
        commit = step(model, root, 0, None, self.settings, self.fitted)
        query = step(model, root, 1, 0, self.settings, self.fitted)
        stop = step(model, query["next_history"], 0, None, self.settings, self.fitted)
        reject = step(model, query["next_history"], 1, None, self.settings, self.fitted)
        expected = -phi(c, root, self.fitted)
        self.assertAlmostEqual(commit["shaping_reward"], expected)
        for last in (stop, reject):
            self.assertAlmostEqual(query["shaping_reward"] + last["shaping_reward"], expected)
            self.assertAlmostEqual(query["reward"] + last["reward"] - query["base_reward"] - last["base_reward"], expected)

    def test_neutral_component_reproduces_original_optimizer_and_selection(self):
        settings = {**self.settings, "shaping": False}
        original = old_train(self.tasks, self.actor, ppo_config(True))
        current = train(self.tasks, self.actor, settings)
        for old, new in zip(original[:4], current[:4]): close(old, new)
        self.assertGreater(current[3]["total_updates"], 0)

    def test_variable_candidates_keep_padding_masked_when_legality_mask_off(self):
        tasks, _ = datasets(False)
        selected = [next(t for t in tasks if t["split"] == "train" and t["public"]["delay_bits"] == k) for k in (2, 6)]
        models = {t["id"]: Planner(t["public"]) for t in selected}
        cfg = {**self.settings, "action_mask": False}
        data, episodes = collect(selected, models, self.actor, initialize_critic(18), cfg, np.random.default_rng(17), 1, self.fitted)
        x, masks = data[:2]
        for features, mask in zip(x, masks):
            size = int(round(features[0, 1] * 6)) + 1
            self.assertTrue(mask[:size].all()); self.assertFalse(mask[size:].any())
        for episode in episodes: self.assertLessEqual(len(episode["steps"]), 4)

    def test_compact_records_reconstruct_rewards_and_reject_changed_potential(self):
        tasks = [t for t in self.tasks if t["split"] == "train"]
        models = {t["id"]: Planner(t["public"]) for t in tasks}
        _, episodes = collect(tasks, models, self.actor, initialize_critic(18), self.settings, np.random.default_rng(17), 1, self.fitted)
        rows = e.pack(episodes)
        close(episodes, e.expand(rows, tasks, self.settings, self.fitted))
        rows[0][3][0][3] += .01
        with self.assertRaises(ValueError): e.expand(rows, tasks, self.settings, self.fitted)

    def test_development_replays_and_rehashed_reward_tampering_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); result = e.run(p, True)
            self.assertEqual(result["policy_evaluations"], 18)
            self.assertFalse(result["new_final_test"])
            self.assertTrue(e.verify(p)["verified"])
            name = "episodes/17-masked_potential.jsonl"
            rows = e.read_lines(p / name); rows[0][3][0][2] += .1
            e.write_lines(p / name, rows); e.seal(p, True)
            with self.assertRaises(ValueError): e.verify(p)

    def test_selected_checkpoint_binds_full_parameters_not_only_summary(self):
        cfg = {**self.settings, "shaping": False}
        initial, selected, last, log, _, checkpoints = train(self.tasks, self.actor, cfg)
        payload = {"initial": initial, "selected": selected, "last": last, "training": log, "checkpoints": checkpoints}
        changed = copy.deepcopy(payload); changed["selected"]["actor"]["w"][0][0] += .01
        with self.assertRaises(ValueError): e.compare_training(payload, changed)


if __name__ == "__main__": unittest.main()
