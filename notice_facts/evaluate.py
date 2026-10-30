"""Offline scoring and data validation; assistant references remain provisional."""
from collections import Counter
import json
from pathlib import Path

from .contract import canonical_bytes, sha256, valid, key
from .rules import extract

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"benchmarks/notice_facts_v1/dataset.json"


def load(path=DATA):
    d=json.loads(Path(path).read_text())
    if d.get("schema_version")!="notice-facts-data-v1" or d.get("human_gold") is not False:raise ValueError("invalid_dataset_status")
    ids=set();texts=set();groups={};urls={}
    for split,cases in d["splits"].items():
        groups[split]=set();urls[split]=set()
        for c in cases:
            if c["id"] in ids or c["text"] in texts:raise ValueError("duplicate_case")
            ids.add(c["id"]);texts.add(c["text"])
            if not valid(c["reference"],c["text"]) or sha256(c["text"].encode())!=c["text_sha256"]:raise ValueError("bad_reference_or_excerpt")
            if c["human_review"]!="pending" or not c["source_url"].startswith("https://"):raise ValueError("invalid_source_review")
            if len(c["text"].split())>25:raise ValueError("excerpt_too_long")
            groups[split].add(c["group"]);urls[split].add(c["source_url"])
    if groups["development"] & groups["exploratory"] or urls["development"] & urls["exploratory"]:raise ValueError("source_or_event_overlap")
    freeze=json.loads((ROOT/"notice_facts/freeze.json").read_text())
    for name,h in freeze["files"].items():
        if sha256((ROOT/name).read_bytes())!=h:raise ValueError("frozen_contract_changed")
    return d


def score(cases, predictions):
    expected={c["id"] for c in cases}
    if set(predictions)-expected:raise ValueError("unknown_case")
    tp=fp=fn=exact=completed=invalid=positive_exact=negative_exact=predicted=grounded=0
    rows=[]
    for c in cases:
        output=predictions.get(c["id"])
        ok=valid(output,c["text"])
        present=c["id"] in predictions
        # Keep malformed and missing distinct; missing positive facts still count as missed.
        completed+=present;invalid+=present and not ok
        gold={key(f) for f in c["reference"]["facts"]}
        guess={key(f) for f in output["facts"]} if ok else set()
        correct=ok and guess==gold
        tp+=len(guess & gold);fp+=len(guess-gold);fn+=len(gold-guess);exact+=correct
        positive_exact+=bool(gold) and correct;negative_exact+=not gold and correct
        if isinstance(output,dict) and isinstance(output.get("facts"),list):
            for fact in output["facts"]:
                predicted+=1
                grounded+=isinstance(fact,dict) and isinstance(fact.get("evidence"),str) and bool(fact["evidence"]) and fact["evidence"] in c["text"]
        rows.append({"id":c["id"],"valid":ok,"present":present,"exact":bool(correct),"tp":len(guess&gold),"fp":len(guess-gold),"fn":len(gold-guess)})
    positives=sum(bool(c["reference"]["facts"]) for c in cases);negatives=len(cases)-positives
    return {"cases":len(cases),"completed_outputs":completed,"invalid_outputs":invalid,"missing_outputs":len(cases)-completed,
        "positive_cases":positives,"negative_cases":negatives,"exact_match_planned":exact/len(cases) if cases else None,
        "positive_exact_match":positive_exact/positives if positives else None,"negative_exact_match":negative_exact/negatives if negatives else None,
        "fact_precision":tp/(tp+fp) if tp+fp else None,"fact_recall":tp/(tp+fn) if tp+fn else None,
        "tp":tp,"fp":fp,"fn":fn,"evidence_substring_rate":grounded/predicted if predicted else None,
        "evidence_note":"Substring support is a necessary syntactic check, not semantic entailment or route grounding.","per_case":rows}


def offline(path=DATA):
    d=load(path)
    return {"dataset_sha256":sha256(Path(path).read_bytes()),"scope":"assistant_reference_agreement_not_human_gold",
        "live_api_calls":0,"splits":{s:{"frozen_rules":score(rows,{c["id"]:extract(c["text"]) for c in rows}),
            "always_empty":score(rows,{c["id"]:{"facts":[]} for c in rows})} for s,rows in d["splits"].items()}}
