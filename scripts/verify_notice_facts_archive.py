"""Read-only replay of the archived eight-call real quantity evaluation."""
import hashlib
import json
from pathlib import Path

from notice_facts.api import verify as verify_run
from notice_facts.evaluate import offline

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = {"offline.json", "api/estimate.json", "api/manifest.json", "api/inputs.jsonl",
           "api/records.jsonl", "api/ledger-anchor.json", "api/prompt.txt",
           "api/schema.json", "api/assessment.json"}


def verify():
    root = ROOT / "benchmark_results/notice_facts_api"
    provenance = json.loads((root / "provenance.json").read_text())
    if set(provenance["original_files_sha256"]) != MEMBERS:
        raise ValueError("Archive member coverage mismatch")
    for name, digest in provenance["original_files_sha256"].items():
        path = root / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Original artifact changed: " + name)
    result = verify_run(root / "api", split="exploratory")
    if result != json.loads((root / "api/assessment.json").read_text()):
        raise ValueError("Saved assessment differs from raw response replay")
    if offline() != json.loads((root / "offline.json").read_text()):
        raise ValueError("Saved baselines differ from frozen rule replay")
    if result["requested"] != 8 or not result["complete"] or result["transport"] != "openai_https":
        raise ValueError("Unexpected archived run coverage")
    return {"verified": True, "completed_calls": result["completed"],
            "reference_agreement": result["metrics"]["exact_match_planned"],
            "rules_agreement": result["frozen_rules"]["exact_match_planned"],
            "human_review": "pending", "original_files": len(MEMBERS)}


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
