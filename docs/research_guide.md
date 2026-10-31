# 研究说明与证据索引 / Research guide and evidence index

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

**公开归档待批准：** 本地实验和复算已完成，35份新证据尚未完整公开，PR保持草稿。清单、审批原因和操作见[归档状态](rolling_distribution_publication.md)。

### 研究问题

项目研究物流决策中两类信息问题：公告中的事实能否可靠地转为有限结构参数；在信息和计算都需要成本时，应该查询什么、如何运输和维持库存。公司公开材料限定场景和事实语义，不提供真实订单、合同运价或可用容量。当前所有策略收益均来自显式合成环境，不是ASML或Marvell的经营结果。

[架构](architecture.md)说明实际连接和信息边界。[原静态方法](methodology.md)只描述已知订单模型，不能用于解释后来的未知需求环境。研究线分别验收，不将不同数据集上的分数合并为端到端效果。

### 模型口径

静态模型的决策是非负整数发运量；净库存满足上期净库存＋旧在途到货＋按发运期提前期计算的新到货−已知需求。原实验强制每期零积压，并给期末库存共同下限。费用包括运输、在途资金占用、仓储与现货持有；排放包括运输和分配的仓储排放，制造与产品隐含碳不在范围。相同订单/扰动/服务条件下的成本最优解给碳约束基准；不可行实例不填零成本，配对比较使用共同可行实例。

公告独立测试接口只允许`NL_ocean`整数周提前期增量，按发运周、两端包含的窗口应用。缺少关键条件必须澄清；平均运输改善、港口吞吐或行业运力不能自动变成某票运输的确定参数。工具流程的可见审计与隐藏参考审计分离。

查询环境保持订单已知，路线延误的公开先验经付费查询更新。强基线包括无查询、信息价值、两步搜索和精确DP。BC/PPO只选择查询和提交，运输由优化器完成。最终千题最多3次查询；平均遗憾是相对同一情境的参考最优成本损失，不是业务失败率。

滚动环境有未知需求、积压、路线提前期、共享质量容量、在途演化与累计碳预算；不沿用静态零积压约束。历史EWMA提供预测，情景MPC在6期窗口求解并只执行首期动作。需求实现后更新状态。当期新需求满足率不是所有历史订单最终交付率。预知需求方法只作为不可部署下界。

### 结果与边界

| 实验 | 已有证据 | 可以支持的结论 |
|---|---|---|
| [固定LLM](results/api_test.md) | 400个不同合成测试，LLM400/400、规则204/400；重复调用同400条 | 当前接口下模型优于冻结规则；不证明广泛泛化 |
| [真实公告](data/real_notices.md)、[数量抽取](results/notice_facts_api.md) | 16个澄清案例；8个数量案例，模型7/8、规则6/8 | 助手参考一致性；没有人工金标准或真实内部路线更新验证 |
| [五种子千题](query_final_results.md) | 5个真实训练种子、1,000情境、27,000次评估 | BC/PPO遗憾3.1179%/3.1477%；无稳定PPO收益 |
| [组件消融](query_components_results.md) | 掩码×成本势函数，20次PPO训练，36个已查看开发情境 | 掩码减少拒绝；势函数无稳定改善；无新留出确认 |
| [滚动基线](rolling_inventory_results.md) | 12校准+32开发路径 | 情景MPC优于该base-stock，排放也更高 |
| [三因素敏感性](rolling_sensitivity_results.md) | 24新开发路径、2,304轨迹 | 1→7情景改善明显；7→21收益小且跨种子不稳定；期末价值主要改变记账 |
| [均值预测](rolling_forecast_results.md) | 12新校准+32新开发、352轨迹 | 快速EWMA/季节短窗成本+7.19%/+8.48%；保留原EWMA |
| [分布研究](rolling_distribution_protocol.md) | 16拟合+16选参+64确认、512轨迹 | NB成本+2.06%、未通过教师筛选；768次审计验证配对不变性 |

### 学习策略何时有用途

质量目标：新方法在相同可见信息下稳定优于强基线，同时报告服务和排放代价，才形成可进一步研究的教师。计算目标：先给出部署时限和允许质量损失，再研究BC替代优化计算。PPO需在这些强基线之后仍有实际顺序决策损失；模型规模、训练次数、参考项目结构或下界差距均不是充分理由。

本轮分布研究预先固定质量筛选阈值，计算时限仍未指定；[协议](rolling_distribution_protocol.md)区分教师候选与已验证学习收益。即使筛选通过，滚动BC/PPO仍需单独研究。

### 复现与交付

在仓库运行`make sync`。`make test`运行离线测试，`make package-check`检查Python分发包。下列命令读取已归档证据，不调用模型API：

| 命令 | 验证范围 |
|---|---|
| `make verify-core` | 公告、工作流、真实摘录、查询基线及早期训练 |
| `make verify-final` | 冻结千题与检查点执行 |
| `make verify-components` | 掩码和成本势函数 |
| `make verify-rolling` | 原滚动环境 |
| `make verify-sensitivity` | 碳分配、期末价值、情景数 |
| `make verify-forecast` | 均值预测比较 |
| `make verify-distribution` | 分布模型与相关性不变性 |
| `python -m scripts.check_research_progress` | 已保存结果与清单完整性，不重新做实验 |

原协议被证据哈希绑定时保留原文，本文是贯通研究的双语说明，不替换冻结记录。[翻译索引](documentation_plan.md)明确哪些历史文档仍需逐篇补英文。尚无正式Release、完整依赖锁或跨平台验收；当前结果足以构成可复算研究原型，但不等于企业部署或完整LLM智能体系统。

## English

**Publication pending approval:** local experiments/replay are complete; the 35-file public archive is incomplete and the PR remains draft. See [publication status](rolling_distribution_publication.md).

### Research questions

The project studies two information problems in logistics: extracting bounded structured facts from notices, and choosing information acquisition, transport and inventory actions when queries and computation incur costs. Public company materials motivate scenarios and constrain factual meaning; they do not supply real orders, contractual prices or usable capacity. All policy benefits are measured in explicit synthetic environments, not ASML or Marvell operations.

The [architecture](architecture.md) describes implemented connections and information boundaries. The [original static method](methodology.md) concerns known orders, not the later unknown-demand model. Research lines are evaluated separately; scores across datasets are not combined into an end-to-end claim.

### Model definitions

The static model chooses nonnegative integer shipments. Net inventory equals previous net inventory plus old pipeline arrivals plus new arrivals determined by dispatch-period lead times minus known demand. Original experiments require zero backlog every period and a common final stock floor. Costs cover freight, pipeline capital, storage and inventory holding; emissions cover transport and allocated storage, excluding manufacturing and embodied product carbon. A matched cost-optimal solution defines carbon constraints. Infeasible cases are not assigned zero costs; paired comparisons use common feasible cases.

The independent notice interface permits only integer-week lead-time increments on `NL_ocean`, applied to inclusive dispatch-week windows. Missing essential conditions require clarification. Average transit improvements, port throughput and industry capacity do not directly establish shipment-specific deterministic updates. Visible workflow audits and hidden-reference audits are separate.

Query environments retain known orders. Paid queries update public route-delay priors. Strong baselines include no queries, value of information, two-step search and exact DP. BC/PPO select queries/commitment; optimization allocates transport. Final tasks permit at most three queries. Mean regret is relative cost loss against the context's reference optimum, not a business failure rate.

The rolling environment includes unknown demand, backlog, route lead times, shared mass capacity, evolving pipeline and cumulative carbon. It does not inherit the static no-backlog constraint. Historical EWMA supplies forecasts; scenario MPC plans six periods but executes only the first action. Realized demand then updates the state. New-demand fill rate is not eventual fulfillment of every past order. Clairvoyance is a nondeployable bound.

### Results and scope

| Experiment | Evidence | Supported conclusion |
|---|---|---|
| [Fixed LLM](results/api_test.md) | 400 distinct synthetic tests: LLM 400/400, rules 204/400; repeat uses the same 400 | Improvement over frozen rules within this interface, not broad generalization |
| [Real excerpts](data/real_notices.md), [quantities](results/notice_facts_api.md) | 16 clarification cases; 8 quantity cases, model 7/8 vs rules 6/8 | Agreement with assistant references, not human gold or internal-route validation |
| [Five-seed final](query_final_results.md) | Five actual training seeds, 1,000 contexts, 27,000 evaluations | BC/PPO regret 3.1179%/3.1477%; no stable PPO gain |
| [Components](query_components_results.md) | Mask×cost potential,20 PPO fits,36 inspected development contexts | Mask reduces rejection; no stable shaping benefit or new heldout confirmation |
| [Rolling baselines](rolling_inventory_results.md) | 12 calibration+32 development paths | Scenario MPC beats this base-stock, with higher emissions |
| [Sensitivity](rolling_sensitivity_results.md) | 24 new development paths,2,304 trajectories | Large 1→7 scenario benefit; small/unstable 7→21 benefit; terminal credit mainly changes accounting |
| [Mean forecasts](rolling_forecast_results.md) | 12 new calibration+32 new development paths,352 trajectories | Fast EWMA/window raise cost 7.19%/8.48%; retain original EWMA |
| [Distribution study](rolling_distribution_protocol.md) | 16 fit+16 tune+64 confirmation paths,512 trajectories | NB cost+2.06%, teacher screen fails;768 audits verify pairing invariance |

### When learned policies are useful

A quality objective needs stable gains over strong baselines under the same visible information, including service/emission tradeoffs, before a new teacher merits study. A compute objective needs a deployment deadline and acceptable quality loss before BC is investigated as a solver substitute. PPO additionally needs meaningful sequential decision loss beyond these baselines. Model size, training count, a reference project's structure and a clairvoyant gap do not suffice.

The distribution [protocol](rolling_distribution_protocol.md) fixes teacher-screening thresholds; deployment timing requirements remain unspecified. A passing teacher screen is not an established learning benefit. Rolling BC/PPO require a separate study even if screening passes.

### Reproduction and delivery

Run `make sync` from the repository. `make test` runs offline tests; `make package-check` checks the Python distribution. The command table above gives read-only archived-evidence verification: core notice/query checks, frozen final checkpoints, components, rolling baselines, sensitivity, mean forecasts and distributions. None calls a model API. `python -m scripts.check_research_progress` inventories stored results and hashes without rerunning experiments.

Hash-bound historical protocols retain their original bytes. This bilingual guide connects the research without replacing those records. The [translation index](documentation_plan.md) explicitly lists remaining per-document English work. A formal Release, full dependency lock and cross-platform acceptance remain unfinished. The repository is a reproducible research prototype, not enterprise deployment or a complete LLM agent system.
