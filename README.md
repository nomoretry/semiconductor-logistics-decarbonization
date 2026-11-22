# Semiconductor Logistics Decarbonization

English | [简体中文](README.zh-CN.md) · [Documentation index](docs/README.md)

[![Python](https://img.shields.io/badge/Python-3.12-3776AB.svg)](https://www.python.org/) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Semiconductor spare parts and finished goods move between a few sites on air, ocean and road lanes with limited weekly capacity, committed delivery dates and a carbon budget. When a carrier announces a delay or a capacity cut, a planner has to decide what to ship, on which lane and when, and what the change costs in money, service and emissions.

This repository addresses that problem in two ways:

- **A decision tool.** A planning engine (mixed-integer and two-stage stochastic programming) and a notice-to-memo workflow turn a carrier notice into a confirmed disruption scenario, solved plans, a cost/service/emissions comparison and a decision memo. Every number in the output comes from the solver, and every parameter shows where it came from.
- **Reproducible studies.** The research question is when acquiring information and modelling forecasts improves logistics decisions enough to justify their cost, under shared transport capacity, inventory dynamics and carbon constraints. Each study keeps its protocol, configuration, per-case evidence and a replay command.

It is meant for supply-chain planners who want to see the trade-offs of a disruption response, for operations-research and machine-learning researchers who want to replay or extend the studies, and for developers working on a tool-calling planning agent.

The two cases, [ASML-inspired spare parts](asml/README.md) and [Marvell-inspired finished goods](marvell/README.md), are simulations. Orders, prices, capacities and disruption sizes are synthetic assumptions; distances and emission factors come from cited public sources. No company data are used.

## Quick start: from a carrier notice to a decision memo

Python 3.12 is recommended. The lock files in `requirements/` pin every dependency with hashes.

```bash
git clone https://github.com/nomoretry/semiconductor-logistics-decarbonization.git
cd semiconductor-logistics-decarbonization
python -m pip install --require-hashes -r requirements/planning.txt
python -m pip install --no-deps --no-build-isolation -e .
python -m planning_agent flow
```

The last command runs offline with the rule parser; it needs no API key and calls no model. It:

1. reads the built-in notice (Red Sea diversion via the Cape, ocean lanes delayed two weeks in weeks 4–12, 30% less space) and shows the parsed scenario, the notice text behind each parameter and the default assumptions;
2. asks for confirmation and solves nothing until you answer `y` (`e` edits the disruption, `n` cancels);
3. solves the normal and the disrupted plan with HiGHS and compares total cost, service level, emissions and air share;
4. writes a Markdown decision memo and prints its path.

With the default settings (12 synthetic SKUs, 16 weeks) the disrupted plan costs 60,711 USD against 55,253 USD (+9.88%) and emits 27.12 t CO2e against 20.82 t (+30.26%), at 100% service. The command-line and web interface text is in Chinese; the documentation is in English and Chinese.

Other ways to run the same workflow:

```bash
python -m planning_agent flow --mode notice              # also retrieve real carrier notices and cite them
python -m planning_agent flow --mode replay --case D13   # parameters a real model produced in the recorded evaluation
python -m streamlit run planning_agent/app.py            # web page with the same steps
```

`--mode live` asks a model through the LangGraph agent; it needs `LLM_API_KEY` and a token cap (`--max-tokens`) and is a paid call. See the [workflow guide](docs/decision_workflow.md) for all options.

## What works today

| Component | What it does | Verified by |
|---|---|---|
| [Network planning engine](docs/network_planning.md) (`network_planning/`) | Fixed-charge multi-SKU, multi-modal MILP with disruption-dependent lead times and capacities, air block-space reservation, service floors and carbon caps or prices; two-stage stochastic planning with VSS/EVPI and MIP-gap intervals; carbon frontier with marginal abatement cost and LP shadow prices; independent re-accounting of every plan | Unit tests and an [archived report](benchmark_results/network_planning/report.md) |
| [Notice-to-memo workflow](docs/decision_workflow.md) (`planning_agent/workflow.py`, `app.py`) | Parameters and assumptions → confirmation → plan comparison → memo, from the command line or a web page; parameter sources `rule`, `notice`, `replay` and `live` | Offline tests including a headless web-page test; `live` has only been tested with a scripted client |
| [Notice retrieval](docs/notice_retrieval.md) (`planning_agent/retrieval.py`) | BM25 search over 24 carrier-notice excerpts with a Chinese–English glossary; sources, links, the basis of each parameter and missing information in the workflow and memo; optional local full text (pages are not stored in the repository) | Development check on 38 questions (see results) |
| [Planning agent](docs/planning_agent.md) (`planning_agent/`) | Tool-calling agent over eight validated tools with a numeric faithfulness guardrail, also as a LangGraph state graph; a rule agent is the offline fallback and baseline | 24-question evaluation; offline replay of the recorded model runs |
| Research environments | Notice extraction benchmarks, tool workflows, budgeted query planning with BC/PPO, rolling inventory under unknown demand | Archived evidence with `verify` commands (see [research guide](docs/research_guide.md)) |

## Main results

| Question | Result | Evidence |
|---|---|---|
| Disruption impact (planning engine, 12 SKUs, 16 weeks) | ASML-inspired Red Sea diversion: +12.38% cost, +28.4% CO2e. Marvell-inspired typhoon: +2.17% cost | [Report](benchmark_results/network_planning/report.md) |
| Cost of a 25% CO2e cut at 98% service | ASML: +1.76% cost, average MAC 187 USD/t, shadow price 277 USD/t. Marvell: +13.12%, average MAC 24,756 USD/t | [Report](benchmark_results/network_planning/report.md) |
| Value of planning for the disruption scenarios (VSS) | ASML: 864 USD (1.51%). Marvell: about zero, inside the MIP-gap interval | [Report](benchmark_results/network_planning/report.md) |
| Planning agent, 24 planner questions (14 development, 10 robustness, one author) | Rule agent 14/14 and 4/10. gpt-6.1-sol (xhigh, one run, rescored offline after a guardrail fix) 9/14 and 9/10 with 100% numeric faithfulness. Replaying the recorded runs through the LangGraph agent reproduces every score (18/24 succeed); it is not a new model run | [Agent](docs/planning_agent.md) |
| Notice retrieval, 38 questions over 19 event groups | First result in the right event group for 37/38 (Chinese questions without the glossary: 4/19). Written by one author after reading the corpus: a development check, not an independent test | [Retrieval](docs/notice_retrieval.md) |
| Notice extraction on 400 synthetic held-out notices | Fixed model 400/400 (a repeat of the same 400 also 400/400); frozen rules 204/400 | [Results](docs/results/api_test.md) |
| Real carrier notices | 16 excerpts all need clarification; model and always-clarify both agree with the references on 16/16, so no extraction skill is shown. Quantity extraction on 8 cases: model 7/8, rules 6/8. References are provisional and have not been human-reviewed | [Corpus](docs/data/real_notices.md), [quantities](docs/results/notice_facts_api.md) |
| Query policies, frozen 1,000 contexts, five training seeds | Mean regret BC 3.1179%, PPO 3.1477%; PPO−BC +0.0298 pp, 95% interval [−0.1817, +0.2540]. Two-step search 0.6309% and iterative DP 0.0528% remain better. No stable PPO benefit | [Results](docs/query_final_results.md) |
| Rolling inventory under unknown demand | Scenario MPC 282.2406 vs base-stock 330.6219 cost on 32 development paths, with higher emissions. Faster forecasts raise cost (+7.19%, +8.48%); a negative-binomial demand model costs +2.06% with an interval crossing zero. No rolling BC/PPO was trained | [Baselines](docs/rolling_inventory_results.md), [forecasts](docs/rolling_forecast_results.md), [distributions](docs/rolling_distribution_results.md) |

Negative and failed results are kept in the result documents, including the failed equal-budget screen and the failed rolling teacher screen.

## Limitations

- All operational data are synthetic. Results compare policies under stated assumptions; they are not measurements of company operations or emission reductions.
- The research lines are evaluated separately; no end-to-end validation links notice extraction, learned queries and rolling control.
- Real-notice evaluations are small and exploratory. Their reference labels have not been human-reviewed, and real notices rarely state parameters a plan can use directly; carrier services are not mapped to internal lanes.
- The agent and retrieval evaluations were written by one author. The model run of the agent evaluation was executed once; the workflow's `live` mode has not been run against a real model. Conversation memory lasts only for one process.
- Engineering: CI runs on Ubuntu with Python 3.12 only; there is no tagged release yet; Ruff and strict mypy cover the planning packages, not the archived study packages; some earlier protocol and result documents exist in Chinese only.

## Reproduce and verify

```bash
python -m pip install --require-hashes -r requirements/dev.txt   # the research studies only need this lock
python -m pip install --no-deps --no-build-isolation -e .
make test          # offline tests (planning tests run when the planning lock is installed)
make planning-ci   # planning tests, report, rule evaluation, replay and both workflow modes
make quality       # Ruff and strict mypy on network_planning and planning_agent
make lock-check    # the lock files still match pyproject.toml and constraints.txt
make verify-final  # replay one archived study; the research guide lists all verify commands
```

Without Make, run `python -m unittest discover -s tests` and the Python commands in the [command reference](docs/commands.md). No default check calls a model API.

## Documentation

The [documentation index](docs/README.md) groups every document by purpose: user guides, architecture and design, methods and protocols, data, results, and reproduction. Start with the [architecture](docs/architecture.md), the [research design](docs/research_design.md) and the [research guide](docs/research_guide.md).

## Repository layout

| Path | Contents |
|---|---|
| `network_planning/` | Planning engine: MILP, stochastic planning, carbon frontier, accounting and report |
| `planning_agent/` | Decision workflow and web page, notice retrieval, tool-calling and LangGraph agents, rule agent, guardrail, memos and evaluation |
| `semiconductor_logistics/` | Command line for the research studies (`python -m semiconductor_logistics`) |
| `shared/` | Inventory conservation, MILP solver and experiment orchestration for the original case studies |
| `notice_benchmark/`, `notice_facts/`, `real_notice_eval/` | Notice extraction benchmarks, real-notice validation and API evaluation |
| `decision_benchmark/`, `coupled_decision/`, `budgeted_decision/` | Query and planning environments with strong search baselines |
| `query_policy/`, `query_ppo/`, `query_study/`, `query_components/` | Query-policy BC and PPO, multi-seed study and component audit |
| `rolling_inventory/`, `rolling_sensitivity/`, `rolling_forecast/`, `rolling_distribution/`, `rolling_recourse/` | Rolling inventory under unknown demand and its follow-up studies |
| `asml/`, `marvell/` | Case-study configurations and descriptions |
| `benchmarks/`, `llm/` | Frozen datasets, prompts and question sets |
| `benchmark_results/`, `reports/`, `reviews/` | Archived per-case evidence, verification manifests, generated reports and the open review form for real-notice labels |
| `data_sources/` | Source manifests, selected public factors, data audits and notice corpus manifest |
| `scripts/` | Data download, report generation, evidence audits and package checks |
| `tests/` | Unit, replay and command-line tests |
| `requirements/`, `constraints.txt` | Hash-locked dependencies and the tested versions they are resolved from |
| `docs/` | User guides, architecture, methods, protocols and results |

## Licence and attribution

The project's code and documentation are released under the [MIT License](LICENSE); cite it with [CITATION.cff](CITATION.cff). Third-party datasets, carrier notice excerpts, stored outputs of external models and one reference-code helper keep their own terms and are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). [Provenance and attribution](docs/source_history.md) records which external designs and code informed the project.
