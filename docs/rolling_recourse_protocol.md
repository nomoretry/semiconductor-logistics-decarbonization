# 有限情景追索检查 / Finite-support recourse check

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

### 问题与来源

R30证明原MPC在固定各SKU完整路径边际分布时，对跨SKU路径配对不敏感。本检查询问：在相同信息、相同物理成本与容量约束下，允许未来发货依据**已观察**需求调整，是否改变这一性质？

方法依据：Forel与Grunow，[Dynamic stochastic lot sizing with forecast evolution in rolling-horizon planning](https://doi.org/10.1111/poms.13881)，其情景树将可观察历史相同的决策绑定；Gioia、Fadda与Brandimarte，[Rolling horizon policies for multi-stage stochastic assemble-to-order problems](https://arxiv.org/abs/2210.00491v3)，研究情景树、容量和相关需求的关系。这里只借鉴信息约束和对照设计，不移用论文结果或公司数据。

### 在计算结果前规定的构造

这是刻意构造的机制检查，不是新的正式确认集。2 SKU、2路线、3期；初始库存各1；慢/快路线提前期2/1，运费1/3，排放1/3；持有成本各1，逐期积压成本各6，期末额外积压成本各6，碳价0。没有外生初始在途库存、期末返还或丢失销售。

每SKU最终需求为`2H`，`H`边际Bernoulli(1/2)。首期需求`S`是有噪声的信号，`P(S=H)`取1/2或3/4，各SKU信号噪声在给定H后独立。中间期需求为0。H跨SKU取正相关、独立或负相关；三者每SKU**完整路径**边际分布完全相同。3种快线容量(1/2/4) × 2种碳预算(6/100) × 2种信号准确率 × 3种配对，共36个有限模型；这些不是36条独立测试路径。

时序与原环境一致：到货、清旧欠货、发货、揭示本期需求、计费。t=0的发货对所有叶节点相同；t=1只能使用t=0观察到的S，两种终端需求仍可能具有相同历史；t=2没有能够在期内到达的新发货。碳约束按实际路径累计，不能把互斥分支的排放相加。策略知道规定的概率模型，不知道实际H；这不是从历史拟合的预测器。

### 精确对照与验收

整数枚举所有可行首期动作与第二期动作。用整数概率权重计算期望，字典序仅用于确定平局。比较：

1. **固定计划**：t=0、t=1动作都跨所有叶节点共享；对应原可分期望目标。
2. **滚动固定计划**：按上述目标选t=0动作，t=1按已观察S重新优化；这是必须保留的强对照，不能把完全不重规划的差距当作追索优势。
3. **历史追索**：选择t=0动作时，预先考虑t=1会按S优化；相同S强制同一动作。
4. **完全预知下界**：首期就知道完整路径，只作不可部署下界。

对每个模型保存概率、路径、首期动作、各历史节点动作及逐叶成本；逐期用原`Environment`独立重放并核对成本、容量、碳与在途库存。固定计划另与旧SciPy/HiGHS规划器比较；检查全局次序`完全预知 ≤ 历史追索 ≤ 滚动固定计划 ≤ 固定计划`。每SKU边际必须完全相同，固定计划目标必须相同。记录追索收益为零的模型和不同最优动作的平局。

只检查相关性何时进入决策。无新训练、置信区间、企业参数或速度收益声明。机制成立后，下一步应实现三期以外的非预知情景树和历史条件分布，评估同信息滚动强基线；另固定新路径后才能报告确认结果。未知业务时限下仍不启动BC/PPO。

## English

### Question and sources

R30 establishes invariance of the original MPC to cross-SKU pairing when complete SKU-path marginals are fixed. Can future dispatch conditioned only on **observed** demand break this invariance under the same information, physical costs and resource constraints?

Forel and Grunow, [Dynamic stochastic lot sizing with forecast evolution in rolling-horizon planning](https://doi.org/10.1111/poms.13881), motivates history-linked scenario-tree decisions. Gioia, Fadda and Brandimarte, [Rolling horizon policies for multi-stage stochastic assemble-to-order problems](https://arxiv.org/abs/2210.00491v3), motivates inspecting capacity and demand dependence together. We borrow information constraints and comparison design, not published effect sizes or company data.

### Construction specified before computing outcomes

This is a deliberately constructed mechanism check, not heldout confirmation. Two SKUs, two routes, three periods; initial stock one per SKU; slow/fast lead times 2/1, freight 1/3 and emissions 1/3. Holding costs are one per SKU, backlog costs six, additional final backlog costs six; carbon price is zero. There is no exogenous initial pipeline, terminal credit or lost sales.

Terminal demand is `2H`, each H marginally Bernoulli(1/2). First-period demand S is a noisy signal: `P(S=H)` is 1/2 or 3/4, with conditionally independent signal errors across SKUs. Middle-period demand is zero. Positive, independent and negative coupling of H preserve each SKU's **complete-path** marginal. Three fast capacities (1/2/4), two carbon budgets (6/100), two signal accuracies and three couplings produce 36 finite models, not 36 independent test paths.

Events match the existing environment: arrivals, old backlog service, dispatch, current-demand revelation, costs. Dispatch at t=0 is common to every leaf. At t=1 only observed S is available; different terminal demands can share that history. No useful dispatch remains at t=2. Carbon is constrained along each realized path, never summed across mutually exclusive branches. Policies know the specified probability model, not realized H. This is not a history-fitted forecaster.

### Exact comparisons and acceptance

Enumerate every feasible integer first and second action; evaluate expectations using integer probability weights, with lexicographic tie-breaking. Compare:

1. **Open loop:** both actions shared across all leaves; the original separable expected-cost objective.
2. **Rolling open loop:** choose the first action by that objective, then reoptimize after observing S. This strong comparator prevents attributing all replanning benefits to anticipatory recourse.
3. **History recourse:** choose the first action anticipating the later conditional optimization; enforce one action per identical S.
4. **Perfect information:** entire path known at the first action; a nondeployable lower bound only.

Save probabilities, demand paths, initial actions, history-node actions and leaf costs. Replay through the original Environment to independently check cost, capacity, carbon and pipeline evolution. Compare open-loop values with the original SciPy/HiGHS planner. Require `perfect information ≤ history recourse ≤ rolling open loop ≤ open loop`, identical SKU marginals and identical open-loop objectives across couplings. Retain zero-gain models and tied optimal actions.

This checks when dependence enters decisions. No learning, confidence intervals, enterprise calibration or speedup claims. A successful mechanism check motivates a longer nonanticipative scenario-tree planner and history-conditional distributions evaluated against equal-information rolling baselines. Separate fresh paths must be fixed before confirmation. BC/PPO remains deferred without an applicable teacher or computation target.
