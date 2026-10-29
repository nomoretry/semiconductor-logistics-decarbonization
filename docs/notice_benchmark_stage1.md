# Narrow-scope notice benchmark: first implementation

This work follows the agreed sequence: independent text evaluation, then a multi-step tool environment and strong-workflow difficulty audit, then BC/PPO **only if that audit establishes a substantive learning problem**. Unknown demand and rolling decisions remain a later stage.

## Scope and data

The scenario is ASML-inspired Netherlands-to-Singapore spare-parts replenishment, restricted to announced `NL_ocean` transit delays. It is not ASML company data. Committed orders are known; the inventory/transport MILP remains the decision engine.

The deterministic synthetic benchmark contains 120 development and 400 test records across 18 semantic categories. Development/test event IDs, inference payloads and rendering-family IDs are disjoint. Each split has 36 rendering families. A generated event ID is not evidence of an independent real-world event: shared render templates induce dependence, so template-cluster results are reported alongside nominal event counts.

The only inference payload is `model_input={text, context}`. References, categories, event identifiers, template names and generation parameters never enter the rule or model request. References distinguish actionable updates, explicit no-ops, and insufficient information. Arrival dates are not silently treated as dispatch dates. Whole-week conversion requires an exact conversion or an explicit business rounding rule.

Dataset identity: `1508cf37714eaa11542f151fe05d57d450f4c2e2f01bbea3c08437696d0a8a94`.

## Frozen rule evaluation

The rule extractor was developed using only development data and independent semantic unit tests. Its SHA-256 was frozen before the first test execution:

`c692440d148cd37329a5524a6cf22684409eed3631095ad5ce19ede319b0bb73`

| Method | Whole-notice exact matches | Test accuracy |
|---|---:|---:|
| Frozen rule parser | 204/400 | 51.0% |
| Always ask for clarification | 176/400 | 44.0% |
| Ignore notice / no update | 66/400 | 16.5% |
| Correct reference input | 400/400 | 100.0% |
| Fixed API LLM | Not executed | Not available |

The reference is an annotation upper bound, not a deployable policy. Always-clarify and ignore-notice are diagnostic controls, not substitutes for the rule baseline.

The rule parser's development exact match was 120/120; its 51.0% test result is retained without further tuning on that test. It has 100% JSON/schema validity, but correctly processes only 45/224 fully specified notices (20.09% correct-ready coverage). It incorrectly emits ready for 17/176 insufficient-information notices (9.66%). These semantic failures are not concealed by valid JSON or abstention.

Nominal event-based Wilson 95% interval for rule exact match is approximately [46.1%,55.9%]. Because rendering families are shared, the separately reported 36-family bootstrap interval is substantially wider (approximately [34.6%,66.7%] for macro accuracy). Neither interval establishes performance on actual company traffic. Per-category results and every prediction are included.

Strict structure matching and compiled weekly lead-schedule equivalence are reported separately. Equivalent interval decompositions can have different JSON while inducing the same planning parameters. Matching clarification outcomes remain separate from successfully producing an actionable shipping plan.

## Real text: source discovery, not a completed gold set

`notice_benchmark/real_source_registry.json` contains 13 inspected official carrier sources. They are conservatively grouped into 10 operational event groups and 7 broader correlated disruptions. They are not 13 statistically independent gold notices. Every source is `pending_human_review` and `usable_as_frozen_gold=false`.

No performance is reported on this registry. A human must verify the full announcement, route mapping, version precedence, effective dates, numeric sufficiency and reference annotation before an item can enter a real held-out evaluation. Carrier announcements are not ASML internal documents. Titles, links and short paraphrases are retained; source texts are not replaced by invented notices.

## API status and estimated cost

OpenAI Platform rejected the authorized key-creation request without a detailed cause. No project API inference was executed, no API key was saved, and no LLM score is reported. The API runner is tested using mocked transport; those tests are not model-performance evidence.

The candidate low-cost model is `gpt-6-luna`. Its official model page lists Standard short-context rates of USD 0.10/input million tokens and USD 0.50/output million tokens as checked on 2026-10-30: https://developers.openai.com/api/docs/models/gpt-6-luna . Account availability has not been tested. The visible model page does not supply a dated immutable snapshot, so a run using this ID must explicitly record that limitation rather than claim backend snapshot pinning.

The dry-run estimates a conservative reservation from the complete request bytes plus overhead and the maximum output tokens. This is a planning bound under the recorded rate assumptions, not a token count or actual charge. Live execution requires a positive explicit USD cap, reserves each attempt before sending, does not automatically retry, and never silently changes models. It records request/input/prompt/schema/model hashes, returned model, response IDs, token usage and failures. The fixed endpoint disallows redirects. Keys and request authentication headers never enter the logs.

## Reproduce

```bash
python -m notice_benchmark.data --output benchmarks/notices_v1
python -m notice_benchmark.run_offline --freeze-rules
python -m notice_benchmark.verify_offline
python -m notice_benchmark.api_runner --dataset benchmarks/notices_v1/dataset.json --split test --output benchmark_results/api_dry_run_v1
python -m notice_benchmark.run_workflow_audit
python -m notice_benchmark.run_workflow_audit --verify
python -m unittest discover -s tests -v
```

The first freeze command creates or checks an identity, and refuses to replace a different one. Re-running the frozen evaluation is evidence recomputation, not a new independent experiment. Any rule/prompt change motivated by these test errors requires a fresh, independently constructed holdout for a new final claim.

## Development workflow findings

The first difficulty audit ran 200 known-order numerical configurations, reusing 98 distinct development notice events, with two extractors in the same fixed workflow (400 method runs). Both the frozen rule parser and the annotation upper bound completed 200/200 expected workflow outcomes: 127 feasible shipping plans and 73 correct clarification handoffs. Handoffs are never counted as successful shipping. The average tool count was 5.905 and each method used 127 MILP calls.

This audit uses development notices, where the rule parser was tuned. Its result must not be presented as 100% heldout language understanding. It shows that the current tool sequence is already handled by a fixed workflow; it does not establish a substantive PPO problem. Thus the RL-training gate is explicitly false. A later environment needs genuine information/tool-budget trade-offs, followed by another strong-baseline audit before any BC/PPO benefit claim.

Task configurations, all 400 outcomes and step traces are retained. The verifier hashes inputs and sources, reexecutes both workflows and compares tasks, outcomes, summary and traces byte-for-byte. Solver walltime is recorded separately and excluded from deterministic equality. This is not the approximately 1,000-task canonical final test planned for a later training phase.

## Completion gates

1. **Text layer:** synthetic dataset, rule baseline, strict/effect scoring, failure evidence and API-run controls implemented. Live fixed-model comparison and human-annotated real holdout remain outstanding.
2. **Tool environment:** known-order, simulated tool execution only; no real external messages or shipment commitments. A difficulty audit uses development scenarios and must keep correct handoff separate from successful shipping.
3. **BC/PPO:** do not train merely to learn a fixed, already-sufficient tool sequence. Establish meaningful information/tool-budget choices against the strong fixed workflow first; Action Mask must not reveal the correct or optimal decision.
4. **Final comparison:** freeze approximately 1,000 independent numerical task configurations with clearly reported text/event grouping, then use five training seeds, matched information/solver budgets, ablations and replayable checkpoints. Repeated seeds do not create new independent tasks.
5. **Rolling control:** unknown demand, forecast errors and future unannounced disruptions are outside this first implementation.
