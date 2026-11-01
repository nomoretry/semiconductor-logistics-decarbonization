# Semiconductor Logistics Decarbonization

[研究说明 / Research guide](docs/research_guide.md) · [系统结构 / Architecture](docs/architecture.md)

English | [简体中文](README.zh-CN.md)

[![Python](https://img.shields.io/badge/Python-3.12-3776AB.svg)](https://www.python.org/)

A research framework for joint inventory and transport optimization in semiconductor spare-parts and finished-goods logistics. It uses SciPy/HiGHS to solve mixed-integer models with delivery, transport-capacity and carbon-budget constraints, and includes fixed-configuration LLM notice extraction, multi-step tool environments, query-policy behavior cloning (BC), cost-based PPO, and reproducible evaluation.

Two company-inspired case studies share the solver while retaining separate operating assumptions: [ASML spare-parts logistics](asml/README.md) and [Marvell finished-goods logistics](marvell/README.md).

The [distribution confirmation study](docs/rolling_distribution_results.md) holds mean forecasts and MPC fixed. Residual-NB cost is 275.8435 versus Poisson 270.2820; the paired 95% cost interval crosses zero. It improves marginal NLL slightly but fails the teacher screen. A structural audit proves and numerically verifies that current additive, shared-schedule MPC cannot exploit cross-SKU pairing when complete SKU path marginals are preserved. No rolling BC/PPO is trained. Notice extraction, query learning and rolling control remain separately evaluated research lines.

The 35-file distribution archive is complete under the explicitly approved SHA256 manifest. Require all seven checks on the current commit before merge; see the [publication record](docs/rolling_distribution_publication.md).

The central question is when information acquisition and forecast modeling improve logistics decisions enough to justify their cost, under shared transport capacity, inventory dynamics and carbon constraints. The [research design](docs/research_design.md) connects each method to this question and separates implemented evidence from unproven contributions.

## OR planning engine and planning agent

A self-contained layer turns the study into a decision tool:

- **[Network planning engine](docs/network_planning.md)** (`network_planning/`, PuLP + HiGHS): a fixed-charge multi-SKU, multi-modal MILP with disruption-dependent lead times and capacities, air block-space reservation, service floors and carbon caps or prices; two-stage stochastic programming with VSS/EVPI and MIP-gap-aware intervals; an epsilon-constraint frontier with marginal abatement cost and LP shadow prices; independent accounting of every solution.
- **[Planning copilot agent](docs/planning_agent.md)** (`planning_agent/`): an OpenAI-compatible tool-calling agent with eight validated tools, a numeric faithfulness guardrail, decision memos and a 24-question evaluation; a rule agent is the offline fallback and baseline. Product framing: [PRD](docs/planning_agent_prd.md).
- **[Notice-to-memo decision workflow](docs/decision_workflow.md)** (`planning_agent/workflow.py`, web page `planning_agent/app.py`, optional `ui` extra): enter a carrier notice, review the parsed parameters with their source text and default assumptions, confirm, then compare the normal and disrupted plans (cost, service level, emissions, air share) and download a decision memo. Parameters come from the offline rule parser, a recorded model run (labelled as a replay) or a live model call that needs a key and a token cap; plans are solved only after confirmation.
- **[Retrieval over real carrier notices](docs/notice_retrieval.md)** (`planning_agent/retrieval.py`): the workflow's notice mode searches the 24 carrier notice excerpts already in the repository (BM25; Chinese questions expanded through a Chinese-English glossary), shows each source with its link, states the basis of every parameter, lists what the notices leave out and cites the notices in the memo. The repository stores links and hashes only (`data_sources/notice_corpus.json`); downloading the original pages needs explicit consent. On 38 questions over 19 event groups the first result belongs to the right event for 37 questions (4 of 19 Chinese questions without the glossary). One author wrote the questions and the glossary after reading the corpus, so this is a development check, not an independent evaluation.
- **[LangGraph orchestration](docs/planning_agent.md#langgraph-编排)** (`planning_agent/graph.py`, optional `agent` extra): the same model client, tools and guardrail as a state graph, with in-process conversation memory, an optional approval step before tools run and streamed steps. An offline replay of the 24 recorded gpt-6.1-sol runs scores every case the same as the recording (18/24 succeed, as in the recorded run); it checks orchestration, not a new model run.

Selected results with 12 synthetic SKUs per network over 16 weeks ([full report](benchmark_results/network_planning/report.md)):

| Question | ASML-inspired spare parts | Marvell-inspired chips |
|---|---|---|
| Cost impact of a disruption | Red Sea diversion: +12.38% cost, +28.4% CO2e | Typhoon: +2.17% cost |
| Cost of a 25% CO2e cut at 98% service | +1.76%; average MAC 187 USD/t; shadow price 277 USD/t | +13.12%; average MAC 24,756 USD/t |
| Value of the two-stage plan (VSS) | 864 USD (1.51%): 6.0% cheaper if the Red Sea scenario occurs, 0.33% dearer otherwise | About zero (inside the MIP-gap interval): the nominal plan is already robust |
| Planning agent on 24 planner questions | Rule baseline: 14/14 development, 4/10 robustness. gpt-6.1-sol (xhigh): 9/14 and 9/10 after a guardrail fix, 100% numeric faithfulness | |

```bash
python -m pip install -c constraints.txt -e ".[planning]"
python -m network_planning solve --network asml --scenario red_sea --explain
python -m planning_agent ask "How would a Red Sea diversion change ASML spare-parts cost and emissions?"
python -m planning_agent demo
python -m pip install -c constraints.txt -e ".[planning,agent]"
python -m planning_agent replay --output artifacts/planning/replay
python -m planning_agent flow
python -m planning_agent flow --mode notice
python -m planning_agent corpus search "Rotterdam strike"
python -m pip install -c constraints.txt -e ".[planning,agent,ui]"
python -m streamlit run planning_agent/app.py
```

## Design and experiments

| Module | Implementation | Experiments and evidence |
|---|---|---|
| Inventory and transport | Integer shipments; conservation of in-transit inventory, on-hand inventory and backlog | 60 synthetic order instances; 360 policy solves |
| Cost and carbon budgets | Freight, capital, storage and logistics emissions; three carbon-budget settings | Cost–emissions comparisons; 339 feasible plans and recorded infeasible cases |
| Notice extraction | Fixed prompts, JSON Schema, frozen rules and fixed model settings | 120 development texts; 400 synthetic held-out texts |
| LLM API evaluation | Responses API, request budgets, caching and raw response records | 400/400 on both the main run and a repeat of the same 400 cases |
| Multi-step tool environment | Inspect notices, extract and validate facts, read state, solve, audit and commit | 200 development tasks with step-level traces and deterministic replay |
| Shared capacity and queries | 3–4 SKUs, air/ocean allocation, joint disruption priors and a shared query budget | 120 development contexts; six methods; 720 runs and replay |
| Real-source quantity extraction | Transit durations and changes, original units, ranges, qualifiers and supporting text | 16 development excerpts; eight new source documents; model 7/8 and rules 6/8 against assistant references; no human review |
| Query-planning scale study | 4–12 SKUs, 2–6 disruptions, a shared capacity pool across routes and integer allocation | 18 development tasks; 72 runs; one-step/two-step mean cost gaps of 0.5378%/0.0811% |
| Equal computation budgets | Per-decision MILP limits, interruption fallback, branch-local caches and full-path accounting | 54 development contexts; 1,080 runs; best method at the primary budget: 0.6253% mean regret and 15.9217% worst-case regret |
| Query-policy BC | Public candidate features, multi-positive imitation, validation-based checkpoint selection and policy re-execution | 72/18/36 training/validation/development-evaluation contexts; 2.0833% mean regret with one final MILP per task |
| Query-policy PPO | Shared BC initialization, cost rewards, GAE, clipped policy/value updates and validation selection | One training seed; 36 new development contexts; BC/PPO mean regret 2.6486%/1.9416% |
| Five-seed frozen evaluation | Independently trained BC starts; PPO, entropy and GAE-decay ablations; paired seed/context intervals | 1,000 frozen contexts; 27,000 evaluations; BC/PPO regret 3.1179%/3.1477%; no demonstrated stable PPO benefit |
| Mask and cost-potential audit | Shared BC starts; 2×2 design; train-only frozen potential | Five seeds, 20 PPO runs, 1,332 development evaluations; masking reduces rejection, no stable masked-shaping benefit |
| Rolling sensitivity | Carbon pacing, final-stock credit and 1/7/21 scenarios | 24 new paths, three sampling seeds, 2,304 trajectories; 21 vs seven scenarios has no consistent seed-level benefit |
| Unknown-demand rolling inventory | Dated pipeline, history-only forecasts, shared capacities and cumulative carbon | 12 calibration + 32 development paths; four baselines; scenario MPC improves cost/service with higher emissions |
| Forecast comparison | Calibration-only parameter selection; the same scenario MPC for all predictors | 12 calibration + 32 new development paths, 352 trajectories; fast EWMA and seasonal-window costs rise 7.19%/8.48% versus original EWMA |
| Demand distribution | Fixed EWMA means; past-residual NB dispersion; whole-SKU-path dependence audit | 16 fit + 16 tune + 64 confirmation paths, 512 trajectories; NB cost +2.06%, no stable teacher; 768 dependence audits preserve the objective |
| Verification | Input and source hashes, per-case rescoring, logistics-plan replay and training re-execution | Offline verification commands and automated tests |

The original fixed tool workflow produced 127 feasible plans and 73 correct clarification handoffs on its development tasks. The [information-cost environment](docs/decision_environment.md) then introduced consequential choices about querying, clarification and planning. Current acceptance criteria and remaining work are recorded in the [progress ledger](docs/progress.md).

The [query-policy BC experiment](docs/query_policy_results.md) is complete at development scale. BC uses one final transport solve per task with 2.0833% mean cost regret; two-step search with a per-decision budget of 13 uses about 16.15 solves per task with 0.3140% regret. BC reduces online solver calls but does not yet match strong search on decision quality. The next [shared-start PPO experiment](docs/query_ppo_results.md) is also complete at development scale: on 36 new contexts, mean regret falls from BC’s 2.6486% to 1.9416%, with one final MILP per path. Six contexts improve and 30 tie; this single-seed result still falls short of strong search. The subsequent [five-seed, frozen 1,000-context evaluation](docs/query_final_results.md) is now complete: BC/PPO mean regret is 3.1179%/3.1477%. The PPO−BC difference is +0.0298 percentage points, with approximate paired 95% interval [−0.1817, +0.2540]. It does not establish a stable PPO benefit. Both strong search baselines remain better on cost; all negative results are retained.

The [component audit](docs/query_components_results.md) is complete on 36 already inspected development contexts. Removing masks raises penalty-inclusive regret from 2.5362% to 4.6288%, with 14.3215% rejection probability. Masked potential shaping yields 2.7956% regret, without a stable benefit. This does not reevaluate or replace the frozen final results.

The [rolling inventory study](docs/rolling_inventory_results.md) implements the next stage: 44 distinct synthetic paths, four deployable baselines and a perfect-information lower bound. On 32 development paths, scenario MPC costs 282.2406 versus base-stock 330.6219, with higher immediate fill but higher emissions. Mean MPC does not beat the rule overall; no RL is trained.

The failed screening result from the [equal-budget experiment](docs/query_budget_results.md) is preserved. BC addresses a separate question under the [computation-amortization protocol](docs/query_policy_protocol.md). The [research design](docs/research_design.md) defines our logistics questions, method choices and acceptance criteria; the [research log](docs/research_log.md) records each change and its evidence.

The [real-source quantity evaluation](docs/results/notice_facts_api.md) is archived: model outputs agree with assistant references on 7/8 cases, compared with 6/8 for frozen rules. These results remain exploratory and have not undergone independent human review. They do not block environment research or require another API run. Any necessary user actions are listed in the [manual steps](docs/manual_steps.md).

See [architecture](docs/architecture.md), [data and benchmarks](docs/benchmark.md), and [methods and reproduction](docs/methodology.md). New detailed research documents provide Chinese first and English afterward. Historical pages will receive complete English explanations at final delivery; see the [documentation plan](docs/documentation_plan.md).

The sensitivity archive is complete and PR #15 is merged after all five checks passed. [File identities and verification](docs/rolling_sensitivity_publication.md) cover all 2,304 trajectories.

The [rolling sensitivity study](docs/rolling_sensitivity_results.md) now quantifies carbon pacing, final-stock value and scenario count on 24 new paths. Seven scenarios lower cost by 37.48% versus one; 21 lower it by only 0.36% versus seven, with mixed sampling-seed effects. Final-stock credit mainly changes accounting. The [forecast comparison](docs/rolling_forecast_results.md) is now complete: both calibration-selected alternatives have higher mean cost and worse marginal prediction scores than original EWMA on 32 new paths. Three paths improve forecast NLL while worsening decision cost. No new teacher passes the fixed descriptive screen; rolling BC/PPO remains deferred.

The forecast archive is complete: all 73 evidence files were uploaded with the explicitly approved SHA256 digests. See the [file identities and verification](docs/rolling_forecast_publication.md). PR #16 is merged with all six main-branch checks successful. The current distribution extension requires seven checks.

The [finite recourse check](docs/rolling_recourse_results.md) adds 36 constructed models, 36 MILP cross-checks and 1,920 physical replays. All apparent gains over the lexicographic rolling baseline disappear after considering its optimal first-action ties. Cross-coupling policy evaluation shows no regret in this construction. This is a mechanism check, not new heldout confirmation or a rolling learning result. Reproduce with `make verify-recourse`.

## Quick start

Python 3.12 is recommended. `constraints.txt` pins the numerical dependencies used for validation, replay and CI.

```bash
git clone https://github.com/nomoretry/semiconductor-logistics-decarbonization.git
cd semiconductor-logistics-decarbonization
python -m pip install -c constraints.txt -e ".[dev]"
make test
make smoke
```

On Windows without Make, use the Python entry points:

```bash
python -m unittest discover -s tests
python -m semiconductor_logistics --help
python -m semiconductor_logistics evaluate --output artifacts/rules
python -m semiconductor_logistics verify-run --output artifacts/rules
```

Default checks use local synthetic data and do not call the API. `make smoke` exercises rule evaluation, tool environments, small BC/PPO training runs and replay verification.

## Optimization experiments

```bash
semiconductor-logistics download-data
semiconductor-logistics optimize --project asml --smoke
semiconductor-logistics optimize --project marvell --smoke
semiconductor-logistics optimize --project both
semiconductor-logistics sensitivity --project both
semiconductor-logistics report
```

`download-data` downloads and verifies third-party source files against the source manifest. The full optimization grid includes an external automotive spare-parts monthly-demand stress test, so its source data must be downloaded first. Main experiments write to `reports/`; running a single case study also replaces the main summaries in that directory. See [data and benchmarks](docs/benchmark.md) for the scope of the published synthetic records and external stress-test summaries.

Python scripts produce the [Markdown study report](reports/study_report.md), CSV/JSON results and Matplotlib figures.

## Notice extraction evaluation

| Method | Split | Texts | Whole-notice extraction accuracy |
|---|---|---:|---:|
| Frozen rules | Development | 120 | 100% |
| Frozen rules | Synthetic held-out | 400 | 51.0% (204/400) |
| Always clarify | Synthetic held-out | 400 | 44.0% |
| Ignore notice | Synthetic held-out | 400 | 16.5% |
| GPT-6 Luna | Synthetic held-out, main run | 400 | 100% (400/400) |
| GPT-6 Luna | Repeat of the same held-out set | 400 | 100% (400/400) |

The main run exceeds frozen rules by 49.0 percentage points. Parsed outputs match across the main and repeat runs; both use the same 400 distinct cases. Per-case results, grouped intervals and raw responses are in the [evaluation report](docs/results/api_test.md). The separate 20-case development run is documented as a [connection smoke test](docs/results/api_smoke.md).

The [real-notice corpus](docs/data/real_notices.md) contains short excerpts from 16 official transport documents, checked in two assistant reviews. The fixed model completed all 16 calls and agreed with assistant references on every case; the always-clarify baseline also scored 100%. Raw records are archived, and human review has not been performed. Because every reference requires clarification, this audit does not establish extraction skill for real operational updates. The [source-fact protocol](docs/real_fact_protocol.md) evaluates source quantities separately from internal-route updates.

```bash
semiconductor-logistics evaluate
semiconductor-logistics verify-run
semiconductor-logistics workflow-audit
semiconductor-logistics workflow-audit --verify
semiconductor-logistics compare-api --run benchmark_results/api_test --repeat-run benchmark_results/api_repeat
semiconductor-logistics real-notices offline --dataset benchmarks/real_notices_v1/dataset.json --output artifacts/real_notices
semiconductor-logistics decision-audit --tasks 200 --output artifacts/decision_audit
semiconductor-logistics coupled-audit --contexts 120 --output artifacts/coupled_development
python -m scripts.verify_real_notice_archive
semiconductor-logistics notice-facts offline --output artifacts/notice_facts
semiconductor-logistics scale-audit --verify --output benchmark_results/decision_scale
semiconductor-logistics query-budget --verify --output benchmark_results/query_budget_development
semiconductor-logistics query-bc --verify --output benchmark_results/query_bc_development
semiconductor-logistics query-ppo --verify --output benchmark_results/query_ppo_development
semiconductor-logistics query-study verify-development
semiconductor-logistics query-study verify-final
semiconductor-logistics query-components verify
semiconductor-logistics rolling-inventory verify
semiconductor-logistics rolling-sensitivity verify
semiconductor-logistics rolling-forecast verify
```

The API command estimates cost by default:

```bash
semiconductor-logistics api --dataset benchmarks/notices_v1/dataset.json --split test --max-calls 400 --output artifacts/notice_api
```

Live calls use a manual GitHub Actions workflow and a repository Secret. The `smoke20` profile uses development data; `test400` uses the frozen held-out set. See [API setup](docs/secure_api_connection.md).

## CLI reference

| Command | Purpose |
|---|---|
| `rolling-forecast` | Compare history-only predictors and replay forecasts, calibration and rolling decisions |
| `generate` | Generate notice development/test splits and verification metadata |
| `optimize` | Run the ASML and Marvell inventory–transport experiments |
| `evaluate` | Evaluate frozen rules and diagnostic baselines |
| `api` | Estimate or execute fixed-configuration model extraction |
| `score-api` | Verify request records and recompute API metrics |
| `compare-api` | Recompute paired model–rule differences and repeat-run agreement |
| `real-notices` | Validate real-source data, run offline baselines, export inputs and rescore responses |
| `decision-audit` | Audit information costs, planning choices and strong adaptive baselines |
| `coupled-audit` | Audit multi-SKU shared capacity, query budgets, exact planning and lookahead baselines |
| `notice-facts` | Validate quantity data, score rules, estimate/execute API requests and rescore outputs |
| `scale-audit` | Replay larger SKU/disruption grids and verify expected costs, traces and integer plans |
| `query-budget` | Compare query planners under equal MILP-call limits and replay policy trees and call ledgers |
| `query-bc` | Generate query teachers, train BC, compare strong search and re-execute checkpoints |
| `query-ppo` | Train PPO from the frozen BC actor and replay trajectories, updates and checkpoints |
| `query-study` | Retrain paired seeds, run ablations, freeze new tasks and verify the final study |
| `rolling-inventory` | Run and replay history-based inventory planning under unknown demand |
| `rolling-sensitivity` | Quantify carbon allocation, final-stock value and scenario count; replay all factorial trajectories |
| `workflow-audit` | Run or replay multi-step tool tasks |
| `verify-run` | Verify offline data, predictions, metrics and source identity |
| `sensitivity` | Run parameter and emissions-boundary sensitivity experiments |
| `report` | Generate Markdown reports, tables and figures |

All installed commands are also available through `python -m semiconductor_logistics`. Outside the repository, pass `--workspace /path/to/repository` to select the checkout containing the required data and configurations.

## Repository structure

| Path | Contents |
|---|---|
| `semiconductor_logistics/` | Python CLI |
| `shared/` | Inventory conservation, MILP solver and experiment orchestration |
| `notice_benchmark/` | Frozen synthetic notices, rules, API evaluation, metrics and the original tool environment |
| `real_notice_eval/` | Real-notice source validation and exploratory evaluation |
| `notice_facts/` | Quantity-extraction schema, frozen rules, budgeted API evaluation and raw-response rescoring |
| `decision_benchmark/` | Query costs, physical logistics outcomes and decision baselines |
| `coupled_decision/` | Multi-SKU integer allocation, shared capacity, budgeted queries and full replay |
| `budgeted_decision/` | Query planning under computation limits, interruption handling and branch-level verification |
| `query_policy/` | Public features, NumPy BC, teacher generation and checkpoint-bound verification |
| `query_ppo/` | Episode-safe GAE, cost-based PPO, validation selection and complete training replay |
| `query_study/` | Multi-seed training, lossless evidence records, task/model freezing and paired statistics |
| `rolling_inventory/`, `rolling_sensitivity/` | Unknown-demand inventory simulation, baseline planning and sensitivity replay |
| `query_components/` | Mask/potential factorial, rejection semantics and complete development replay |
| `network_planning/` | Fixed-charge MILP, two-stage stochastic planning, carbon frontier and independent accounting (PuLP + HiGHS) |
| `planning_agent/` | Tool-calling planning agent, tools, numeric guardrail, rule baseline, memos and evaluation |
| `asml/`, `marvell/` | Case-study configurations |
| `benchmarks/` | Frozen notice datasets, rule identities and source records |
| `benchmark_results/` | Per-case predictions, API responses, tool traces and verification manifests |
| `scripts/` | Data acquisition, experiments, reporting and package checks |
| `tests/` | Optimization, extraction, replay and CLI tests |
| `docs/` | Architecture, methods, benchmarks and results |

## Data and scope

Orders, prices, shipment weights, capacities and storage parameters are simulation assumptions. Emission factors, route geometry and demand analogues have recorded sources and checksums. See the [ASML data audit](data_sources/data_audit_asml.md), [Marvell data audit](data_sources/data_audit_marvell.md), and [third-party notices](THIRD_PARTY_NOTICES.md).

The base optimization uses known committed orders and announced disruptions. The query-policy experiments add uncertain route states with disclosed priors while retaining known orders. Results compare policies under these simulation assumptions; they are not measurements of company operations or emissions reductions, and they do not establish broad LLM generalization. A separate rolling environment now studies unknown demand, forecast error and pipeline evolution; these results are kept separate from the original known-order experiments.
