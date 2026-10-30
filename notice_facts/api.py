"""Bounded manual Responses runner and raw-evidence replay for quantity facts.

Uses the unchanged earlier transport/locking/hash-chain helpers. No retries or
automatic resume: an interrupted reservation remains an unknown billed outcome.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
import time

from notice_benchmark import api_runner as transport
from . import contract
from .evaluate import load, score, ROOT, DATA
from .rules import extract

INPUT_RATE=Decimal("0.10")
OUTPUT_RATE=Decimal("0.50")
MODEL="gpt-6-luna"


def write(p,value):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes(contract.canonical_bytes(value)+b"\n")


def parse(response,text):
    result={"status":"invalid_output","output":None,"usage":None,"usage_cost_usd":None,
            "returned_model":response.get("model") if isinstance(response,dict) else None}
    if not isinstance(response,dict):return result
    usage=response.get("usage")
    if isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in ("input_tokens","output_tokens")):
        result["usage"]={k:usage[k] for k in ("input_tokens","output_tokens")}
        result["usage_cost_usd"]=str((usage["input_tokens"]*INPUT_RATE+usage["output_tokens"]*OUTPUT_RATE)/1_000_000)
    if response.get("error") is not None:
        result["status"]="api_error";return result
    if not isinstance(response.get("model"),str) or not response["model"]:
        result["status"]="missing_model_identity";return result
    if response["model"]!=MODEL and not response["model"].startswith(MODEL+"-"):
        result["status"]="model_identity_mismatch";return result
    if response.get("status")!="completed":
        result["status"]="incomplete_response";return result
    parts=[]
    outputs=response.get("output",[])
    if not isinstance(outputs,list):return result
    for msg in outputs:
        if not isinstance(msg,dict) or msg.get("type")!="message":continue
        content=msg.get("content",[])
        if not isinstance(content,list):continue
        for item in content:
            if not isinstance(item,dict):continue
            if item.get("type")=="refusal":result["status"]="refusal";return result
            if item.get("type")=="output_text" and isinstance(item.get("text"),str):parts.append(item["text"])
    try: output=contract.strict_json("".join(parts))
    except (TypeError,ValueError):return result
    # A structurally completed JSON response may contain an incorrect fact. Score
    # semantic correctness separately. Invalid evidence remains a model failure.
    if contract.valid(output,text):result.update(status="completed",output=output)
    return result


def plan(dataset_path,split):
    d=load(dataset_path)
    if split not in d["splits"]:raise ValueError("unknown_split")
    cases=d["splits"][split]
    requests=[]
    for c in cases:
        body=contract.request(c["text"],MODEL)
        bound=len(contract.canonical_bytes(body))+4096
        if bound>32768:raise ValueError("input_bound_exceeded")
        reserved=((bound*INPUT_RATE+768*OUTPUT_RATE)/1_000_000).quantize(Decimal(".00000001"),rounding=ROUND_CEILING)
        requests.append({"case_id":c["id"],"request_sha256":contract.sha256(contract.canonical_bytes(body)),
                         "reservation_usd":str(reserved),"body":body})
    source_files=["notice_facts/api.py","notice_facts/contract.py","notice_facts/evaluate.py",
                  "notice_facts/rules.py","notice_facts/freeze.json","notice_benchmark/api_runner.py"]
    identity={"dataset_sha256":contract.sha256(Path(dataset_path).read_bytes()),"split":split,
              "model":MODEL,"model_version_fully_pinned":False,"endpoint":transport.ENDPOINT,
              "prompt_sha256":contract.sha256(contract.PROMPT.encode()),"schema_sha256":contract.sha256(contract.canonical_bytes(contract.SCHEMA)),
              "source_sha256":{n:contract.sha256((ROOT/n).read_bytes()) for n in source_files},
              "input_usd_per_million":str(INPUT_RATE),"output_usd_per_million":str(OUTPUT_RATE),
              "pricing_note":"Declared undiscounted rates retained from prior verified runs, not a provider invoice.",
              "max_output_tokens":768,"automatic_retries":0}
    return cases,requests,identity


def run(output,*,dataset_path=DATA,split="exploratory",execute=False,max_usd=None,perform=None,api_key=None):
    cases,requests,identity=plan(dataset_path,split)
    total=sum(Decimal(x["reservation_usd"]) for x in requests)
    estimate={"calls":len(requests),"reserved_upper_bound_usd":str(total),"execute":execute,"split":split,
              "note":"No API request or credential read during estimation."}
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if not execute:
        write(output/"estimate.json",estimate);return estimate
    cap=transport._money(max_usd,positive=True)
    if total>cap:raise ValueError("budget_cap_exceeded_before_requests")
    with transport._run_lock(output):
        if any((output/n).exists() for n in ("manifest.json","records.jsonl","ledger-anchor.json")):
            raise ValueError("existing_run_not_overwritten_or_retried")
        key=api_key if perform is not None else transport._load_api_key()
        if perform is not None and not isinstance(key,str):raise ValueError("mock_key_required")
        manifest={"schema_version":"notice-facts-api-v1","identity":identity,"max_usd":str(cap),
                  "transport":"injected_mock" if perform else "openai_https",
                  "requests":[{k:v for k,v in x.items() if k!="body"} for x in requests]}
        manifest["sha256"]=contract.sha256(contract.canonical_bytes(manifest))
        write(output/"manifest.json",manifest)
        (output/"prompt.txt").write_text(contract.PROMPT)
        write(output/"schema.json",contract.SCHEMA)
        (output/"inputs.jsonl").write_bytes(b"".join(contract.canonical_bytes({"case_id":c["id"],"text":c["text"]})+b"\n" for c in cases))
        previous="0"*64
        for c,item in zip(cases,requests):
            reservation={"kind":"reservation","request_key":item["case_id"],"case_id":item["case_id"],
                         "request_sha256":item["request_sha256"],"reservation_usd":item["reservation_usd"]}
            previous=transport._append_log(output/"records.jsonl",reservation,previous)
            start=time.perf_counter()
            try:
                raw=(perform or transport._default_transport)(item["body"],key,60.)
                raw=transport._redact(raw,key)
                result=parse(raw,c["text"])
                result.update(raw_response=raw,raw_sha256=contract.sha256(contract.canonical_bytes(raw)))
            except transport.TransportError as exc:
                result={"status":"transport_error","output":None,"usage":None,"usage_cost_usd":None,
                        "http_status":exc.status,"error_type":exc.error_type,"error_code":exc.error_code}
            except Exception as exc:
                result={"status":"transport_error","output":None,"usage":None,"usage_cost_usd":None,
                        "error_type":transport._safe_error_token(type(exc).__name__)}
            result.update(kind="result",request_key=c["id"],case_id=c["id"],elapsed_seconds=time.perf_counter()-start)
            previous=transport._append_log(output/"records.jsonl",transport._redact(result,key),previous)
            if result.get("usage_cost_usd") is not None and Decimal(result["usage_cost_usd"])>Decimal(item["reservation_usd"]):
                raise ValueError("observed_usage_exceeded_reservation")
            if result["status"]!="completed":break
    report=verify(output,dataset_path=dataset_path,split=split)
    write(output/"assessment.json",report)
    return report


def verify(output,*,dataset_path=DATA,split="exploratory"):
    cases,requests,identity=plan(dataset_path,split)
    output=Path(output)
    if (output/"manifest.json").is_symlink():raise ValueError("symlink_manifest")
    manifest=contract.strict_json((output/"manifest.json").read_text())
    digest=manifest.pop("sha256")
    if contract.sha256(contract.canonical_bytes(manifest))!=digest:raise ValueError("manifest_digest_mismatch")
    if manifest.get("identity")!=identity or manifest.get("schema_version")!="notice-facts-api-v1":raise ValueError("run_identity_mismatch")
    if manifest.get("transport") not in ("openai_https","injected_mock"):raise ValueError("unknown_transport")
    if manifest["requests"]!=[{k:v for k,v in x.items() if k!="body"} for x in requests]:raise ValueError("request_manifest_mismatch")
    expected={"prompt.txt":contract.PROMPT.encode(),"schema.json":contract.canonical_bytes(contract.SCHEMA)+b"\n",
              "inputs.jsonl":b"".join(contract.canonical_bytes({"case_id":c["id"],"text":c["text"]})+b"\n" for c in cases)}
    for n,b in expected.items():
        if (output/n).is_symlink() or (output/n).read_bytes()!=b:raise ValueError("static_input_mismatch")
    log=output/"records.jsonl"
    if log.exists():
        if log.is_symlink():raise ValueError("symlink_ledger")
        for line in log.read_text().splitlines():contract.strict_json(line)
    records,_=transport._read_log(log)
    reservations={};results={};by_id={c["id"]:c for c in cases};planned={r["case_id"]:r for r in requests}
    pending=None;stopped=False
    for row in records:
        ident=row.get("case_id")
        if ident not in by_id or row.get("request_key")!=ident:raise ValueError("unknown_case_in_ledger")
        if row["kind"]=="reservation":
            if pending is not None or stopped or ident!=cases[len(reservations)]["id"]:raise ValueError("request_sequence_mismatch")
            if ident in reservations or any(row.get(k)!=planned[ident][k] for k in ("request_sha256","reservation_usd")):raise ValueError("reservation_mismatch")
            reservations[ident]=row
            pending=ident
        elif row["kind"]=="result":
            if ident!=pending or ident not in reservations or ident in results:raise ValueError("result_order_mismatch")
            if "raw_response" in row:
                if contract.sha256(contract.canonical_bytes(row["raw_response"]))!=row.get("raw_sha256"):raise ValueError("raw_hash_mismatch")
                parsed=parse(row["raw_response"],by_id[ident]["text"])
                if any(row.get(k)!=v for k,v in parsed.items()):raise ValueError("response_replay_mismatch")
            elif row.get("status")!="transport_error" or any(row.get(k) is not None for k in ("output","usage","usage_cost_usd")):
                raise ValueError("unbacked_model_result")
            if row.get("usage_cost_usd") is not None and Decimal(row["usage_cost_usd"])>Decimal(planned[ident]["reservation_usd"]):raise ValueError("usage_above_bound")
            results[ident]=row
            pending=None;stopped=row["status"]!="completed"
        else:raise ValueError("unknown_ledger_kind")
    reserved=sum(Decimal(x["reservation_usd"]) for x in reservations.values())
    if reserved>transport._money(manifest["max_usd"],positive=True):raise ValueError("reservation_above_cap")
    predictions={i:x["output"] for i,x in results.items() if x["status"]=="completed"}
    scored=score(cases,predictions) if predictions else None
    rules=score(cases,{c["id"]:extract(c["text"]) for c in cases})
    empty=score(cases,{c["id"]:{"facts":[]} for c in cases})
    matched=[c for c in cases if c["id"] in predictions]
    paired=None
    if matched:
        model_rows={r["id"]:r["exact"] for r in scored["per_case"]}
        rule_rows={r["id"]:r["exact"] for r in rules["per_case"]}
        paired={"completed_case_count":len(matched),
                "model_only_correct":sum(model_rows[c["id"]] and not rule_rows[c["id"]] for c in matched),
                "rules_only_correct":sum(rule_rows[c["id"]] and not model_rows[c["id"]] for c in matched)}
    return {"scope":"quantity_reference_agreement_exploratory_pending_human_review","transport":manifest["transport"],
            "requested":len(cases),"attempted":len(reservations),"completed":len(predictions),
            "errors":len(results)-len(predictions),"unknown_outcomes":len(reservations)-len(results),"unattempted":len(cases)-len(reservations),
            "complete":len(predictions)==len(cases),"reserved_usd":str(reserved),
            "usage_reported_usd":str(sum(Decimal(x["usage_cost_usd"]) for x in results.values() if x.get("usage_cost_usd") is not None)),
            "results_without_usage":sum(x.get("usage") is None for x in results.values()),
            "returned_models":sorted({x["returned_model"] for x in results.values() if isinstance(x.get("returned_model"),str)}),
            "metrics":scored,"frozen_rules":rules,"always_empty":empty,"paired_completed":paired,
            "source_documents":len({c["source_url"] for c in cases}),"event_groups":len({c["group"] for c in cases}),
            "model_version_fully_pinned":False,"dataset_sha256":identity["dataset_sha256"]}
