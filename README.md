# Semiconductor Logistics Decarbonization

English | [简体中文](README.zh-CN.md)

[![Python](https://img.shields.io/badge/Python-3.12-3776AB.svg)](https://www.python.org/)

A research framework for joint inventory and transport optimization in semiconductor spare-parts and finished-goods logistics. It uses SciPy/HiGHS to solve mixed-integer models with delivery, transport-capacity and carbon-budget constraints, and includes fixed-configuration LLM notice extraction, multi-step tool environments, query-policy behavior cloning (BC), cost-based PPO, and reproducible evaluation.

Two company-inspired case studies share the solver while retaining separate operating assumptions: [ASML spare-parts logistics](asml/README.md) and [Marvell finished-goods logistics](marvell/README.md).

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
| Verification | Input and source hashes, per-case rescoring, logistics-plan replay and training re-execution | Offline verification commands and automated tests |

The original fixed tool workflow produced 127 feasible plans and 73 correct clarification handoffs on its development tasks. The [information-cost environment](docs/decision_environment.md) then introduced consequential choices about querying, clarification and planning. Current acceptance criteria and remaining work are recorded in the [progress ledger](docs/progress.md).

The [query-policy BC experiment](docs/query_policy_results.md) is complete at development scale. BC uses one final transport solve per task with 2.0833% mean cost regret; two-step search with a per-decision budget of 13 uses about 16.15 solves per task with 0.3140% regret. BC reduces online solver calls but does not yet match strong search on decision quality. The next [shared-start PPO experiment](docs/query_ppo_results.md) is also complete at development scale: on 36 new contexts, mean regret falls from BC’s 2.6486% to 1.9416%, with one final MILP per path. Six contexts improve and 30 tie; this single-seed result still falls short of strong search. The subsequent [five-seed, frozen 1,000-context evaluation](docs/query_final_results.md) is now complete: BC/PPO mean regret is 3.1179%/3.1477%. The PPO−BC difference is +0.0298 percentage points, with approximate paired 95% interval [−0.1817, +0.2540]. It does not establish a stable PPO benefit. Both strong search baselines remain better on cost; all negative results are retained.

The failed screening result from the [equal-budget experiment](docs/query_budget_results.md) is preserved. BC addresses a separate question under the [computation-amortization protocol](docs/query_policy_protocol.md). The [framework comparison](docs/framework_comparison.md) maps the implementation and remaining gaps against Agentic Tool RL; the [research log](docs/research_log.md) records each change and its evidence.

The [real-source quantity evaluation](docs/results/notice_facts_api.md) is archived: model outputs agree with assistant references on 7/8 cases, compared with 6/8 for frozen rules. These results remain exploratory and have not undergone independent human review. They do not block environment research or require another API run. Any necessary user actions are listed in the [manual steps](docs/manual_steps.md).

See [architecture](docs/architecture.md), [data and benchmarks](docs/benchmark.md), and [methods and reproduction](docs/methodology.md). New detailed research documents provide Chinese first and English afterward. Historical pages will receive complete English explanations at final delivery; see the [documentation plan](docs/documentation_plan.md).

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
```

The API command estimates cost by default:

```bash
semiconductor-logistics api --dataset benchmarks/notices_v1/dataset.json --split test --max-calls 400 --output artifacts/notice_api
```

Live calls use a manual GitHub Actions workflow and a repository Secret. The `smoke20` profile uses development data; `test400` uses the frozen held-out set. See [API setup](docs/secure_api_connection.md).

## CLI reference

| Command | Purpose |
|---|---|
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
| `asml/`, `marvell/` | Case-study configurations |
| `benchmarks/` | Frozen notice datasets, rule identities and source records |
| `benchmark_results/` | Per-case predictions, API responses, tool traces and verification manifests |
| `scripts/` | Data acquisition, experiments, reporting and package checks |
| `tests/` | Optimization, extraction, replay and CLI tests |
| `docs/` | Architecture, methods, benchmarks and results |

## Data and scope

Orders, prices, shipment weights, capacities and storage parameters are simulation assumptions. Emission factors, route geometry and demand analogues have recorded sources and checksums. See the [ASML data audit](data_sources/data_audit_asml.md), [Marvell data audit](data_sources/data_audit_marvell.md), and [third-party notices](THIRD_PARTY_NOTICES.md).

The base optimization uses known committed orders and announced disruptions. The query-policy experiments add uncertain route states with disclosed priors while retaining known orders. Results compare policies under these simulation assumptions; they are not measurements of company operations or emissions reductions, and they do not establish broad LLM generalization. Unknown demand, forecast error and rolling decisions have not yet been implemented.
