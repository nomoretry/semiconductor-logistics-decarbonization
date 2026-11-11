# 文档索引 / Documentation index

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

文档按用途分组。标“仅中文”的是较早的文档；标“冻结”的协议与实验证据按源码哈希绑定，保持原文不改，修改会使对应证据的校验失败。

### 使用指南

- [使用手册](user_guide.md)：从安装到运行：四种模式、密钥配置、命令行和网页步骤、完整示例、排错和可分享的导出。
- [命令参考](commands.md)：规划引擎、决策流程、研究实验和校验命令。
- [公告到备忘录的决策流程](decision_workflow.md)：参数与假设、人工确认、方案对比和备忘录；四种参数来源。
- [实时模型调用的配置与限额](live_model_safety.md)：密钥、请求前生效的限额、公开网页的开关和三种证据的区分。
- [规划 Agent](planning_agent.md)：工具、数字护栏、LangGraph 编排、24 题评测与回放。
- [网络规划引擎](network_planning.md)：模型、随机规划、碳前沿和独立核算。
- [真实公告检索](notice_retrieval.md)：语料、检索方法、评测和下载原文的方式。
- [供应链计划副驾驶 PRD](planning_agent_prd.md)：产品目标、用户、风险和路线图。
- [API 配置](secure_api_connection.md)（仅中文）：手动工作流与仓库 Secret。

### 架构与设计

- [技术总览](technical_overview.md)：背景、架构、数学模型、Agent 设计、强化学习和预测研究、实验与局限。
- [系统结构](architecture.md)：各研究线的实现、连接和信息边界。
- [研究问题、设计与验收](research_design.md)：研究问题、方法选择和验收条件。
- [研究说明与证据索引](research_guide.md)：各研究的模型口径、结果边界和复算命令。
- [文献与公开资料](research_basis.md)（仅中文）：文献和公司披露如何进入模型。

### 方法与协议

- [静态模型与公告方法](methodology.md)：已知订单的库存–运输模型和公告方法。
- [通知理解与工具规划基准](notice_benchmark_stage1.md)（仅中文）。
- [信息成本与物流决策环境](decision_environment.md)（仅中文，冻结）。
- [多 SKU 与共享容量环境](coupled_environment.md)（仅中文）。
- [真实事实抽取与内部更新分开评测](real_fact_protocol.md)（仅中文）。
- 冻结协议：[同求解预算](query_budget_protocol.md)（仅中文）、[查询策略 BC](query_policy_protocol.md)（仅中文）、[查询策略 PPO](query_ppo_protocol.md)、[多种子与冻结评测](query_study_protocol.md)、[动作掩码与势函数](query_components_protocol.md)、[滚动库存](rolling_inventory_protocol.md)、[滚动敏感性](rolling_sensitivity_protocol.md)、[预测与滚动决策](rolling_forecast_protocol.md)、[需求分布](rolling_distribution_protocol.md)、[有限情景追索](rolling_recourse_protocol.md)。

### 数据

- [数据与评测](benchmark.md)（仅中文）：合成数据、外部压力测试和公开明细的范围。
- [真实运输公告](data/real_notices.md)（仅中文）：摘录、来源审核和参考边界。
- [ASML 数据审核](../data_sources/data_audit_asml.md)、[Marvell 数据审核](../data_sources/data_audit_marvell.md)、[Monash 汽车备件数据](../data_sources/carpartsREADME.md)（均为中文）。
- [第三方声明](../THIRD_PARTY_NOTICES.md)：数据许可、公告摘录、模型输出和参考代码。

### 结果

- 规划 Agent：[评测 v2（20 题，每题 3 次，真实模型）](results/planning_agent_v2.md)及其[协议](../benchmarks/planning_agent_v2/PROTOCOL.md)；[后续报告](results/planning_agent_v2_followup.md)（A04 修复与复测、修正评分）；[20×3 结果表与评分说明](results/planning_agent_v2_scoring.md)；[C03 待人工复核案例](results/c03_review_case.md)。
- 规划引擎：[公告影响范围读错的后果与事先确认的价值](results/scope_misread.md)（A04 之后的物流实验，不调用模型）。
- 规划引擎：[网络规划报告](../benchmark_results/network_planning/report.md)。原始案例研究：[实验报告](../reports/study_report.md)。
- 公告抽取：[合成留出集](results/api_test.md)（仅中文）、[连接测试](results/api_smoke.md)（仅中文）、[真实数量抽取](results/notice_facts_api.md)（仅中文）。
- 查询规划：[规模审计](decision_scale.md)（仅中文）、[计算预算](query_budget_results.md)（仅中文）、[BC](query_policy_results.md)（仅中文）、[PPO](query_ppo_results.md)、[多种子开发](query_study_development_results.md)、[冻结千题](query_final_results.md)、[组件对照](query_components_results.md)。
- 滚动库存：[基线](rolling_inventory_results.md)、[敏感性](rolling_sensitivity_results.md)、[预测](rolling_forecast_results.md)、[需求分布](rolling_distribution_results.md)、[有限情景追索](rolling_recourse_results.md)。

### 复现与证据

- [研究说明](research_guide.md)中的 `verify` 命令表。
- [证据格式与复现](query_study_evidence.md)。
- 证据归档记录：[敏感性](rolling_sensitivity_publication.md)、[预测](rolling_forecast_publication.md)、[需求分布](rolling_distribution_publication.md)。

### 来源

- [来源与归属](source_history.md)。[`framework_comparison.md`](framework_comparison.md) 只为冻结协议里的旧链接保留。

## English

Documents are grouped by purpose. "Chinese only" marks earlier documents; "frozen" protocols and experiment evidence are bound by source hashes and keep their original text, because editing them would fail the corresponding evidence checks.

### User guides

- [User guide](user_guide.md): from installation to running: the four modes, key setup, command line and web steps, a complete example, troubleshooting and shareable exports.
- [Command reference](commands.md): planning engine, decision workflow, research studies and verification commands.
- [Notice-to-memo decision workflow](decision_workflow.md): parameters and assumptions, confirmation, plan comparison and memo; four parameter sources.
- [Live model calls: configuration and limits](live_model_safety.md): the key, limits applied before a request, the switch on the public page and how evidence is labelled.
- [Planning agent](planning_agent.md): tools, numeric guardrail, LangGraph orchestration, 24-question evaluation and replay.
- [Network planning engine](network_planning.md): model, stochastic planning, carbon frontier and independent accounting.
- [Notice retrieval](notice_retrieval.md): corpus, method, evaluation and how to download the original pages.
- [Planning copilot PRD](planning_agent_prd.md): product goals, users, risks and roadmap.
- [API setup](secure_api_connection.md) (Chinese only): manual workflow and repository Secret.

### Architecture and design

- [Technical overview](technical_overview.md): background, architecture, the mathematical model, agent design, RL and forecasting studies, experiments and limits.
- [Architecture](architecture.md): implementation, connections and information boundaries of each research line.
- [Research questions, design and acceptance](research_design.md).
- [Research guide and evidence index](research_guide.md): model scope, result boundaries and replay commands per study.
- [Literature and public sources](research_basis.md) (Chinese only): how literature and company disclosures enter the models.

### Methods and protocols

- [Static optimization and notice methods](methodology.md): the known-order inventory–transport model and notice methods.
- [Notice understanding and tool-planning benchmark](notice_benchmark_stage1.md) (Chinese only).
- [Information-cost decision environment](decision_environment.md) (Chinese only, frozen).
- [Multi-SKU shared-capacity environment](coupled_environment.md) (Chinese only).
- [Real source facts versus internal updates](real_fact_protocol.md) (Chinese only).
- Frozen protocols: [equal solver budget](query_budget_protocol.md) (Chinese only), [query-policy BC](query_policy_protocol.md) (Chinese only), [query-policy PPO](query_ppo_protocol.md), [multi-seed and frozen evaluation](query_study_protocol.md), [masks and potentials](query_components_protocol.md), [rolling inventory](rolling_inventory_protocol.md), [rolling sensitivity](rolling_sensitivity_protocol.md), [forecasts](rolling_forecast_protocol.md), [demand distributions](rolling_distribution_protocol.md), [finite-support recourse](rolling_recourse_protocol.md).

### Data

- [Data and benchmarks](benchmark.md) (Chinese only): synthetic data, external stress test and the scope of published records.
- [Real transport notices](data/real_notices.md) (Chinese only): excerpts, source review and reference limits.
- [ASML data audit](../data_sources/data_audit_asml.md), [Marvell data audit](../data_sources/data_audit_marvell.md), [Monash car-parts data](../data_sources/carpartsREADME.md) (all in Chinese).
- [Third-party notices](../THIRD_PARTY_NOTICES.md): data licences, notice excerpts, model outputs and reference code.

### Results

- Planning agent: [evaluation v2 (20 tasks, three runs each, real model)](results/planning_agent_v2.md) and its [protocol](../benchmarks/planning_agent_v2/PROTOCOL.md); [follow-up report](results/planning_agent_v2_followup.md) (the A04 fix and retest, corrected scoring); [the 20 × 3 table and scoring notes](results/planning_agent_v2_scoring.md); [C03 case pending human review](results/c03_review_case.md).
- Planning engine: [what misreading a notice's scope costs, and what confirming it is worth](results/scope_misread.md) (the logistics study after A04; no model call).
- Planning engine: [network planning report](../benchmark_results/network_planning/report.md). Original case studies: [study report](../reports/study_report.md).
- Notice extraction: [synthetic held-out set](results/api_test.md) (Chinese only), [connection smoke test](results/api_smoke.md) (Chinese only), [real quantity extraction](results/notice_facts_api.md) (Chinese only).
- Query planning: [scale audit](decision_scale.md) (Chinese only), [computation budgets](query_budget_results.md) (Chinese only), [BC](query_policy_results.md) (Chinese only), [PPO](query_ppo_results.md), [multi-seed development](query_study_development_results.md), [frozen 1,000 contexts](query_final_results.md), [components](query_components_results.md).
- Rolling inventory: [baselines](rolling_inventory_results.md), [sensitivity](rolling_sensitivity_results.md), [forecasts](rolling_forecast_results.md), [demand distributions](rolling_distribution_results.md), [finite-support recourse](rolling_recourse_results.md).

### Reproduction and evidence

- The `verify` command table in the [research guide](research_guide.md).
- [Evidence format and reproduction](query_study_evidence.md).
- Evidence archive records: [sensitivity](rolling_sensitivity_publication.md), [forecasts](rolling_forecast_publication.md), [demand distributions](rolling_distribution_publication.md).

### Provenance

- [Provenance and attribution](source_history.md). [`framework_comparison.md`](framework_comparison.md) is kept only for old links in frozen protocols.
