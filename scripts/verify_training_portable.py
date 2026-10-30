"""Replay frozen trainers across BLAS implementations with bound checkpoints.

The original strict verifiers remain unchanged. A companion certificate stores
the actual intermediate coefficients behind their recorded SHA256 identities.
Only those hash leaves may differ during replay, and only after comparing their
coefficient arrays with the original numerical comparator. No result, update,
action, seed, reward, or checkpoint-selection field is skipped.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
from unittest.mock import patch

from query_policy.experiment import close as numeric_close
from query_ppo import training, experiment as pilot
from query_study import development
from query_study.common import ROOT, canonical, sha256, read, write

DEFAULT = ROOT / "benchmark_results/training_replay_checkpoints.json"
PILOT = ROOT / "benchmark_results/query_ppo_development"
STUDY = ROOT / "benchmark_results/query_study_development"
HASH_FIELDS = {"checkpoint_sha256", "bc_start_sha256"}


def bindings():
    return {str(p.relative_to(ROOT)): sha256(p.read_bytes()) for p in
            (PILOT / "manifest.json", STUDY / "manifest.json")}


def required_hashes():
    result = set()
    records = [read(PILOT / "training.json")]
    for path in sorted((STUDY / "models").glob("*.json")):
        payload = read(path)
        if "variant" in payload:
            result.add(payload["bc_start_sha256"])
            records.append(payload["training"])
    for record in records:
        result.update(row["checkpoint_sha256"] for row in record["validation"])
    return result


@contextmanager
def capture_checkpoints():
    original = training.checkpoint
    captured = {}

    def capture(actor, critic):
        payload = original(actor, critic)
        for item in (payload, payload["actor"]):
            captured[sha256(canonical(item))] = item
        return payload

    with patch.object(training, "checkpoint", capture):
        yield captured


def validate_coefficients(records):
    if not isinstance(records, dict) or not records:
        raise ValueError("missing_checkpoint_coefficients")
    for identity, payload in records.items():
        if identity != sha256(canonical(payload)):
            raise ValueError("checkpoint_coefficient_hash")
        if set(payload) == {"actor", "critic"}:
            from query_policy.model import deserialize
            from query_ppo.algorithm import decode_critic
            deserialize(payload["actor"], 32)
            decode_critic(payload["critic"])
        else:
            from query_policy.model import deserialize
            deserialize(payload, 32)


class BoundComparison:
    def __init__(self, archived, fresh):
        validate_coefficients(archived)
        self.archived = archived
        self.fresh = fresh
        self.different_hash_pairs = set()

    def __call__(self, actual, expected, field=None):
        if field in HASH_FIELDS:
            if actual not in self.archived or expected not in self.fresh:
                raise ValueError("unbound_training_checkpoint")
            saved, regenerated = self.archived[actual], self.fresh[expected]
            if sha256(canonical(saved)) != actual or sha256(canonical(regenerated)) != expected:
                raise ValueError("checkpoint_coefficient_hash")
            numeric_close(saved, regenerated)
            if actual != expected:
                self.different_hash_pairs.add((actual, expected))
        elif isinstance(actual, dict) and isinstance(expected, dict):
            if set(actual) != set(expected):
                raise ValueError("replay_dictionary_keys")
            for key in actual:
                self(actual[key], expected[key], key)
        elif isinstance(actual, list) and isinstance(expected, list):
            if len(actual) != len(expected):
                raise ValueError("replay_list_length")
            for a, b in zip(actual, expected):
                self(a, b)
        else:
            numeric_close(actual, expected)


def record(path):
    path = Path(path)
    if path.exists():
        raise ValueError("certificate_already_exists")
    # Recording is allowed only on a runtime that passes original strict replay.
    with capture_checkpoints() as captured:
        pilot.verify(PILOT)
        development.verify(STUDY)
    needed = required_hashes()
    if not needed <= captured.keys():
        raise ValueError("missing_original_checkpoint")
    coefficients = {h: captured[h] for h in sorted(needed)}
    validate_coefficients(coefficients)
    write(path, {"schema": "training-replay-checkpoints-v1", "bindings": bindings(),
                 "recorded_after_strict_replay": True, "coefficients": coefficients})
    return {"recorded": True, "bound_checkpoints": len(coefficients)}


def verify(path):
    certificate = read(path)
    if (set(certificate) != {"schema", "bindings", "recorded_after_strict_replay", "coefficients"}
            or certificate["schema"] != "training-replay-checkpoints-v1"
            or certificate["recorded_after_strict_replay"] is not True
            or certificate["bindings"] != bindings()
            or set(certificate["coefficients"]) != required_hashes()):
        raise ValueError("training_certificate_binding")
    with capture_checkpoints() as fresh:
        compare = BoundComparison(certificate["coefficients"], fresh)
        with patch.object(pilot, "close", compare), patch.object(development, "close", compare):
            pilot_result = pilot.verify(PILOT)
            study_result = development.verify(STUDY)
    return {"verified": True, "pilot": pilot_result, "study": study_result,
            "bound_checkpoints": len(certificate["coefficients"]),
            "numerically_matching_different_hash_pairs": len(compare.different_hash_pairs),
            "scope": "bound_coefficient_and_full_training_replay_not_cross_platform_byte_identity"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certificate", type=Path, default=DEFAULT)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    print(json.dumps(record(args.certificate) if args.record else verify(args.certificate), sort_keys=True))


if __name__ == "__main__":
    main()
