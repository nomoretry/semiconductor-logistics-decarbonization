# Real-notice excerpt audit

This package leaves every `notice_benchmark/*.py` file unchanged. It validates
the separate recorded official-notice corpus and compares the frozen rule
extractor with always-clarify and always-noop baselines. It never resolves an API
credential or sends a request.

The original task remains `NL_ocean` on the published 16-week dispatch grid.
Official service names, voyage numbers, publication dates, and calendar weeks do
not create a missing route or calendar mapping. The reviewed narrow references
are assistant decisions pending independent human review. The corpus is an
exploratory short-excerpt abstention audit, not a held-out extraction benchmark.
An all-clarification corpus cannot establish useful update extraction: the
always-clarify baseline obtains the same reference agreement.

```bash
python -m real_notice_eval validate --dataset benchmarks/real_notices_v1/dataset.json
python -m real_notice_eval offline --dataset benchmarks/real_notices_v1/dataset.json --output artifacts/real_notice/offline
python -m real_notice_eval export-api --dataset benchmarks/real_notices_v1/dataset.json --output artifacts/real_notice/input_dataset.json
python -m real_notice_eval score-api --dataset benchmarks/real_notices_v1/dataset.json --input-dataset artifacts/real_notice/input_dataset.json --run-dir artifacts/real_notice/api --output artifacts/real_notice/assessment.json
```

The `offline` command writes `report.json` and `report.md`. `score-api` writes the
requested JSON and a Markdown file beside it. Both accept `--github-summary FILE`
to append a sanitized numeric assessment without raw provider text.

The corpus validator checks assistant/pending declarations, the exact recorded
excerpt and SHA-256, recorded official-source provenance, fixed inference
context, reference schema, and case/source/event/correlation identities. Source
URLs are unique after removing fragments. Empty development data is allowed; if
both splits contain cases, source documents, excerpt hashes, event groups, and
correlation groups cannot overlap. Exclusions have explicit identities and
reasons and remain visible in reports. Unknown publication dates remain null.
Hashes verify the stored excerpt, not official authenticity or human review.
Full source pages are not archived, so the package cannot independently replay
the assistant's full-page review.

The input export contains only case IDs and exact `model_input` objects within
the split arrays. References, source records, rationale, and broad factual
annotations remain in the original corpus, whose canonical SHA-256 is recorded
outside the inference payload. The unmodified original API runner can consume
this export; running it without `--execute` remains a credential-free dry run.
Execution is a separate manual workflow with its own explicit budget cap.

The API assessment validates the export against the corpus and replays manifest,
request, input, frozen-code, prompt, schema, ledger-chain, anchor, and raw-response
identities using the frozen runner's helpers. It distinguishes mock transport
from recorded live transport. This is an integrity check, not an independent
attestation that a provider transaction occurred. Missing runs or no completed
outputs produce unavailable agreement, not an invented zero. For partial runs,
completed-output agreement and all-planned-output agreement are separate, and
errors, unknown outcomes, and unattempted requests remain explicit. Raw provider
JSON is checked more strictly for duplicate keys than the archival parser.

Broad factual annotations are retained separately and minimally schema checked.
They are not scored, injected into inference context, or treated as human gold.
