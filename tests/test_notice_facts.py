"""Contract edge cases, source separation and paid-call evidence boundaries."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from notice_facts import api, contract
from notice_facts.evaluate import DATA, ROOT, load, offline, score


def response(output, **changes):
    value={"model":"gpt-6-luna-test","status":"completed","error":None,
           "usage":{"input_tokens":100,"output_tokens":50},
           "output":[{"type":"message","content":[{"type":"output_text","text":json.dumps(output)}]}]}
    value.update(changes)
    return value


class FactsTests(unittest.TestCase):
    def setUp(self):
        self.data=load();self.cases=self.data["splits"]["exploratory"]

    def mock(self,body,key,timeout):
        user=json.loads(body["input"][1]["content"][0]["text"])
        self.assertEqual(set(user),{"text"})
        case=next(c for c in self.cases if c["text"]==user["text"])
        return response(case["reference"])

    def run_mock(self,path,perform=None):
        return api.run(path,execute=True,max_usd=".05",perform=perform or self.mock,api_key="unit-test-credential")

    def test_baselines_recompute_saved_evidence(self):
        report=offline()
        saved=json.loads((ROOT/"benchmark_results/notice_facts_development/offline.json").read_text())
        self.assertEqual(report,saved)
        self.assertEqual(report["splits"]["exploratory"]["frozen_rules"]["exact_match_planned"],.75)
        self.assertEqual(report["splits"]["exploratory"]["always_empty"]["exact_match_planned"],.25)

    def test_source_and_event_separation(self):
        dev=self.data["splits"]["development"]
        for field in ("source_url","group","text","id"):
            self.assertFalse({c[field] for c in dev}&{c[field] for c in self.cases})
        self.assertEqual(len({c["group"] for c in self.cases}),7)
        self.assertFalse(self.data["human_gold"])

    def test_units_ranges_qualifiers_are_scored(self):
        c=next(c for c in self.data["splits"]["development"] if any(f["low"]!=f["high"] for f in c["reference"]["facts"]))
        for field,value in (("high",999),("unit","hour"),("qualifier","stated"),("metric","transit_time")):
            with self.subTest(field=field):
                changed=copy.deepcopy(c["reference"]);changed["facts"][0][field]=value
                self.assertEqual(score([c],{c["id"]:changed})["exact_match_planned"],0)

    def test_unsupported_evidence_and_nonfinite_rejected(self):
        c=self.cases[0]
        for field,value in (("evidence","not in source"),("low",True),("low",float("nan")),("high",10**1000),("unit","mile")):
            changed=copy.deepcopy(c["reference"]);changed["facts"][0][field]=value
            self.assertFalse(contract.valid(changed,c["text"]))
        duplicate=copy.deepcopy(c["reference"]);duplicate["facts"]*=2
        self.assertFalse(contract.valid(duplicate,c["text"]))

    def test_strict_json_rejects_duplicate_and_nan(self):
        for text in ('{"facts":[],"facts":[]}','{"facts":[NaN]}'):
            with self.assertRaises(ValueError):contract.strict_json(text)

    def test_missing_output_is_not_negative_correct(self):
        c=next(c for c in self.cases if not c["reference"]["facts"])
        result=score([c],{})
        self.assertEqual(result["exact_match_planned"],0)
        self.assertEqual(result["missing_outputs"],1)

    def test_dry_run_reads_no_key_or_network(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(api.transport,"_load_api_key",side_effect=AssertionError), patch.object(api.transport,"_default_transport",side_effect=AssertionError):
            r=api.run(tmp)
            self.assertEqual(r["calls"],8)
            self.assertFalse((Path(tmp)/"manifest.json").exists())

    def test_budget_rejected_before_key_or_network(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(api.transport,"_load_api_key",side_effect=AssertionError):
            with self.assertRaisesRegex(ValueError,"budget_cap"):
                api.run(tmp,execute=True,max_usd=".00001")
            self.assertFalse((Path(tmp)/"records.jsonl").exists())

    def test_mock_completion_and_paired_scoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.run_mock(tmp)
            self.assertEqual(r["completed"],8);self.assertEqual(r["transport"],"injected_mock")
            self.assertEqual(r["paired_completed"]["model_only_correct"],2)
            self.assertEqual(r,api.verify(tmp))
            with self.assertRaisesRegex(ValueError,"existing_run"):
                self.run_mock(tmp)

    def test_api_error_stops_without_false_zero_accuracy(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.run_mock(tmp,lambda *_:response({},error={"code":"insufficient_quota"}))
            self.assertEqual((r["attempted"],r["completed"],r["errors"],r["unattempted"]),(1,0,1,7))
            self.assertIsNone(r["metrics"])

    def test_error_null_is_success_but_incomplete_is_not(self):
        c=self.cases[0]
        self.assertEqual(api.parse(response(c["reference"]),c["text"])["status"],"completed")
        self.assertEqual(api.parse(response(c["reference"],status="incomplete"),c["text"])["status"],"incomplete_response")

    def test_wrong_model_and_missing_usage_are_explicit(self):
        c=self.cases[0]
        self.assertEqual(api.parse(response(c["reference"],model="different-family"),c["text"])["status"],"model_identity_mismatch")
        with tempfile.TemporaryDirectory() as tmp:
            r=self.run_mock(tmp,lambda body,key,timeout:dict(self.mock(body,key,timeout),usage=None))
            self.assertEqual(r["completed"],8)
            self.assertEqual(r["results_without_usage"],8)

    def test_unknown_outcome_reservation_is_not_retried(self):
        def crash(*_):raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(KeyboardInterrupt):self.run_mock(tmp,crash)
            r=api.verify(tmp)
            self.assertEqual((r["attempted"],r["unknown_outcomes"],r["unattempted"]),(1,1,7))
            with self.assertRaisesRegex(ValueError,"existing_run"):self.run_mock(tmp)

    def test_transport_exception_does_not_expose_message(self):
        def fail(*_):raise RuntimeError("unit-test-credential private transport body")
        with tempfile.TemporaryDirectory() as tmp:
            r=self.run_mock(tmp,fail)
            self.assertEqual(r["errors"],1)
            data=(Path(tmp)/"records.jsonl").read_text()
            self.assertNotIn("unit-test-credential",data)
            self.assertNotIn("private transport body",data)

    def test_edited_response_rejected_even_if_chain_rebuilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_mock(tmp);path=Path(tmp)/"records.jsonl"
            rows,_=api.transport._read_log(path)
            rows[1]["raw_response"]["output"]=[]
            rows[1]["raw_sha256"]=contract.sha256(contract.canonical_bytes(rows[1]["raw_response"]))
            path.unlink();previous="0"*64
            for row in rows:
                row.pop("record_sha256");row.pop("previous_sha256")
                previous=api.transport._append_log(path,row,previous)
            with self.assertRaisesRegex(ValueError,"response_replay"):api.verify(tmp)

    def test_static_input_and_anchor_truncation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_mock(tmp);path=Path(tmp)/"records.jsonl"
            path.write_text(path.read_text().splitlines()[0]+"\n")
            with self.assertRaises(api.transport.RunnerError):api.verify(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            self.run_mock(tmp);(Path(tmp)/"prompt.txt").write_text("changed")
            with self.assertRaisesRegex(ValueError,"static_input"):api.verify(tmp)

    def test_dataset_mutation_rejected(self):
        d=copy.deepcopy(self.data);d["splits"]["exploratory"][0]["group"]=d["splits"]["development"][0]["group"]
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"dataset.json";p.write_text(json.dumps(d))
            with self.assertRaisesRegex(ValueError,"source_or_event_overlap"):load(p)


if __name__=="__main__":unittest.main()
