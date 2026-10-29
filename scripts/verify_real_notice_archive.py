"""Read-only replay of the archived 16-call real-notice abstention audit."""
from pathlib import Path
import hashlib
import json

from real_notice_eval.api import score_api_run

ROOT = Path(__file__).resolve().parents[1]


def verify():
    root = ROOT/"benchmark_results/real_notice_api"
    provenance = json.loads((root/"provenance.json").read_text())
    for name, sha in provenance["original_files_sha256"].items():
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError("Unsafe archive member")
        path = root/name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError("Original artifact changed: " + name)
    dataset = json.loads((ROOT/"benchmarks/real_notices_v1/dataset.json").read_text())
    result = score_api_run(dataset, root/"input_dataset.json", root/"api")
    retained = json.loads((root/"assessment.json").read_text())
    if result != retained:
        raise ValueError("Assessment differs from raw-ledger replay")
    if result["counts"]["completed_calls"] != 16 or not result["live_api_evidence"]:
        raise ValueError("Unexpected archived coverage")
    return {"verified":True, "completed_calls":16,
            "reference_agreement":result["reference_agreement_completed_outputs"]["exact_reference_match_rate"],
            "scope":result["evaluation_scope"]}


if __name__ == "__main__":
    print(json.dumps(verify(),sort_keys=True))
