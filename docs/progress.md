# 项目进度 / Research progress

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

**公开归档待批准：** 本地实验和复算已完成，35份新证据尚未完整公开，PR保持草稿。清单、审批原因和操作见[归档状态](rolling_distribution_publication.md)。

当前架构与证据口径见[研究说明](research_guide.md)；逐步记录见[研究日志](research_log.md)。完成状态按实际代码、实验和复算判断，不按计划数量判断。

| 阶段 | 已执行 | 结论与剩余项 |
|---|---|---|
| 1. 固定LLM与规则 | 120开发、400独立合成测试及同400条重复；16真实澄清、8真实数量案例 | 合成LLM400/400、规则204/400；真实材料只有助手参考，未验证内部路线更新 |
| 2. 多步工具与强基线 | 固定流程、付费信息、多SKU/共享容量、等求解预算审计 | 强搜索仍很有效；不能仅凭增加任务数量声称需要RL |
| 3. BC/PPO | 公开37维特征、BC、成本PPO、5种子开发及掩码/势函数对照 | 小型查询策略，不是LLM训练；单种子提升未稳定复现 |
| 4. 冻结千题 | 1,000不同情境、5实际训练种子、27,000评估；参数消融、逐策略重执行 | BC/PPO遗憾3.1179%/3.1477%，区间跨零；最多3次查询。组件对照尚无新留出确认 |
| 5. 未知需求滚动 | 原基线44路径；敏感性24新路径/2,304轨迹；均值预测44新路径/352轨迹；分布16拟合+16选参+64确认/512轨迹 | 残差NB成本+2.06%，主区间跨零，教师筛选失败；当前MPC对跨SKU完整路径配对不敏感；未训练滚动BC/PPO |

### 已成立的结果

- [冻结查询评测](query_final_results.md)：PPO−BC遗憾+0.0298个百分点，近似95%区间[−0.1817,+0.2540]；两步搜索/迭代DP为0.6309%/0.0528%，学习策略调用数少，但不等于已测部署加速。
- [组件审计](query_components_results.md)：掩码减少拒绝；有掩码时势函数无稳定收益，数据仍为已查看开发集。
- [滚动基线](rolling_inventory_results.md)：情景MPC较base-stock成本/服务更好，排放更高。
- [敏感性](rolling_sensitivity_results.md)：1→7情景成本−37.48%；7→21仅−0.36%且采样种子方向混合；期末价值主要改变记账。
- [均值预测](rolling_forecast_results.md)：快速EWMA/季节短窗成本+7.19%/+8.48%，保留原EWMA。
- [分布确认](rolling_distribution_results.md)：NB−Poisson成本+5.5615（+2.06%），95%区间[−0.9259,+12.7341]；31路径改善、33变差。768次配对不变性审计最大目标偏差1.14×10⁻¹³。

### 接下来应解决什么

先明确联合服务风险或非预知未来的追索决策是否符合业务目标，才能设计有能力利用相关性的规划问题。当前可分期望成本模型不能用更多相关性情景产生该收益。质量教师筛选未通过；计算时限和允许质量损失仍无业务定义，因此不启动滚动BC/PPO。新的问题必须另存协议和独立确认数据，不改旧结果或反复使用已查看测试。

### 工程与文档

[架构](architecture.md)、[研究说明](research_guide.md)、[静态方法](methodology.md)及新协议/结果均提供中文在前、英文在后。旧哈希绑定协议原文保留，[翻译索引](documentation_plan.md)继续记录历史逐篇翻译；不能称全部历史文档已完成英文版。尚缺正式Release、完整依赖锁、静态检查和跨平台验收。三条研究线尚未形成整体端到端验证。

PR #16已合并，六项主分支CI通过。本轮新增分布复算检查；新提交需要七项CI验收。已保存实验自查：`python -m scripts.check_research_progress`；完整分布重执行：`make verify-distribution`。自查不调用API或查询远端CI。具体人工步骤见[操作说明](manual_steps.md)。

## English

**Publication pending approval:** local experiments/replay are complete; the 35-file public archive is incomplete and the PR remains draft. See [publication status](rolling_distribution_publication.md).

The [research guide](research_guide.md) defines current scope; the [research log](research_log.md) retains each step. Completion is based on implemented, executed and replayed work, not plans.

| Stage | Executed | Findings and remaining work |
|---|---|---|
| 1. Fixed LLM/rules | 120 development,400 distinct synthetic tests plus same-case repeat;16 clarification and 8 quantity cases | LLM 400/400 vs rules 204/400; real references are assistant-generated, with no internal-route validation |
| 2. Tools/strong baselines | Fixed workflow, paid information, shared multi-SKU capacity, matched solver budgets | Strong search remains effective; task count alone does not motivate RL |
| 3. BC/PPO | Public 37-feature input, BC, cost PPO, five-seed development and mask/potential study | Small query policies, not LLM training; early single-seed gains are unstable |
| 4. Frozen final | 1,000 distinct contexts, five training seeds,27,000 evaluations, ablations and policy replay | BC/PPO regret 3.1179%/3.1477%, interval crosses zero; at most three queries. Components lack new heldout confirmation |
| 5. Rolling demand |44 original paths;24 new sensitivity paths/2,304 trajectories;44 new forecast paths/352 trajectories;16 fit+16 tune+64 confirmation distribution paths/512 trajectories | NB cost+2.06%, interval crosses zero, teacher screen fails; current MPC is invariant to cross-SKU whole-path pairing; no rolling BC/PPO |

### Established results

Frozen query PPO−BC regret is+0.0298 percentage points, approximate 95% interval[−0.1817,+0.2540]. Two-step search/iterative DP achieve 0.6309%/0.0528%; fewer learned-policy solver calls are not demonstrated deployment speedups. Masks reduce rejections; masked potential shaping has no stable benefit on inspected development data.

Scenario MPC improves rolling cost/service over base-stock with higher emissions. Sensitivity shows 37.48% lower cost from one to seven scenarios, only 0.36% from seven to 21 with mixed seed directions; terminal credit mainly changes accounting. Fast EWMA/seasonal-window forecasts raise cost 7.19%/8.48%. In distribution confirmation, NB−Poisson is+5.5615 (+2.06%),95% interval[−0.9259,+12.7341];31 paths improve and 33 worsen. Across 768 dependence audits, maximum objective discrepancy is 1.14×10⁻¹³. The linked Chinese bullets lead to bilingual result pages with full evidence.

### Next decision

Clarify whether joint service risk or nonclairvoyant recourse represents the business objective before constructing a planner capable of using dependence. More correlated scenarios cannot create that benefit in the current separable expected-cost model. The quality-teacher screen fails; no deployment deadline or acceptable quality loss has been specified. Do not start rolling BC/PPO. New questions require separate protocols and fresh confirmation data; do not rewrite old results or repeatedly reuse inspected tests.

### Engineering and documentation

Architecture, integrated research explanation, static methods and new protocols/results have Chinese-first/English-second text. Hash-bound historical protocols retain original bytes; the translation index still tracks per-document historical work. Not all historical documentation is translated. Formal Release, full dependency locking, static checks and cross-platform acceptance remain unfinished. The three research lines lack integrated end-to-end validation.

PR #16 is merged with six successful main-branch jobs. This change adds distribution replay and requires seven current-commit checks. Use `python -m scripts.check_research_progress` for stored-result inventory and `make verify-distribution` for full replay. Inventory makes no API calls and does not query remote CI. See the manual-steps page for user actions.
