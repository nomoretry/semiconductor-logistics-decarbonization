"""Bound checkpoint replay must never treat a mismatched hash as a free pass."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from query_policy.model import initialize, serialize
from query_ppo.algorithm import initialize_critic
from query_ppo.training import checkpoint
from query_study.common import canonical, sha256, read, write
from scripts import verify_training_portable as replay


class PortableTrainingTests(unittest.TestCase):
    def setUp(self):
        self.saved = checkpoint(initialize(17), initialize_critic(18))
        self.identity = sha256(canonical(self.saved))

    def comparator(self, changed):
        other = sha256(canonical(changed))
        return replay.BoundComparison({self.identity: self.saved}, {other: changed}), other

    def test_different_hash_requires_numerically_matching_full_coefficients(self):
        changed = copy.deepcopy(self.saved)
        changed["critic"]["w"][0][0] += 1e-12
        compare, other = self.comparator(changed)
        self.assertNotEqual(self.identity, other)
        compare({"checkpoint_sha256": self.identity}, {"checkpoint_sha256": other})
        self.assertEqual(len(compare.different_hash_pairs), 1)

    def test_changed_coefficient_rejected_despite_valid_new_hash(self):
        changed = copy.deepcopy(self.saved)
        changed["actor"]["w"][0][0] += .01
        compare, other = self.comparator(changed)
        with self.assertRaises(ValueError):
            compare({"checkpoint_sha256": self.identity}, {"checkpoint_sha256": other})

    def test_omitted_or_forged_checkpoint_rejected(self):
        compare = replay.BoundComparison({self.identity: self.saved}, {})
        with self.assertRaisesRegex(ValueError, "unbound"):
            compare({"checkpoint_sha256": self.identity}, {"checkpoint_sha256": self.identity})
        with self.assertRaisesRegex(ValueError, "coefficient_hash"):
            replay.BoundComparison({"0" * 64: self.saved}, {})

    def test_only_explicit_checkpoint_fields_have_numeric_hash_comparison(self):
        changed = copy.deepcopy(self.saved)
        changed["actor"]["b"][0] += 1e-12
        compare, other = self.comparator(changed)
        with self.assertRaises(ValueError):
            compare({"model_sha256": self.identity}, {"model_sha256": other})

    def test_actions_rewards_and_selection_are_still_checked(self):
        compare, _ = self.comparator(self.saved)
        for key, before, after in (("action", 1, 2), ("reward", -.03, -.02),
                                   ("selected_iteration", 0, 5), ("seed", 17, 29)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                compare({key: before}, {key: after})

    def test_certificate_replay_and_rebound_archive_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p, s = root / "pilot", root / "study"
            replay.pilot.run(p, True)
            replay.development.run(s, True)
            certificate = root / "coefficients.json"
            with patch.object(replay, "ROOT", root), patch.object(replay, "PILOT", p), patch.object(replay, "STUDY", s):
                replay.record(certificate)
                self.assertTrue(replay.verify(certificate)["verified"])
                # Even after updating the archive and companion manifest binding,
                # a changed actual reward must fail full trainer reexecution.
                episode = s / "episodes/17-ppo.jsonl"
                lines = episode.read_text().splitlines()
                import json
                row = json.loads(lines[0]); row[3][0][2] += .1
                lines[0] = canonical(row).decode().rstrip()
                episode.write_text("\n".join(lines) + "\n")
                manifest = read(s / "manifest.json")
                manifest["files"]["episodes/17-ppo.jsonl"] = sha256(episode.read_bytes())
                write(s / "manifest.json", manifest)
                cert = read(certificate); cert["bindings"] = replay.bindings(); write(certificate, cert)
                with self.assertRaises(ValueError):
                    replay.verify(certificate)


if __name__ == "__main__":
    unittest.main()
