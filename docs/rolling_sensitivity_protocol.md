# 滚动环境敏感性协议 / Rolling sensitivity protocol

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

本协议在运行完整比较之前写定，承接[首轮滚动环境](rolling_inventory_protocol.md)。旧代码、数据及结果保持原身份。问题是碳预算的时间分配、期末库存可回收价值和需求情景数量是否改变成本/服务/排放判断，以及目前是否有足够理由开始学习策略。参数是显式仿真假设，不据此估计企业真实财务收益。

### 固定设计

沿用12期、3 SKU、2路线、6期规划及历史需求EWMA预测。新增6个需求种子×4种过程，共24条不同开发路径，均与原12校准及32开发路径的种子分开；固定使用原校准所得base-stock z=1，不在新路径调参。新情境仍是开发集，不是最终留出集。

主实验为3种碳分配×3种期末价值×3种情景数量×3个情景采样种子的完整组合，每路径81条情景MPC运行。另比较9条均值MPC、3条补货规则及3条预知需求下界，共每路径96条、全实验2,304条轨迹（27,648期）。情景采样种子重复不增加不同需求路径数。以完全相同的需求路径配对，所有未来发货变量仍在情景间共用。

### 三个因素

碳分配只改变MPC的规划窗口额度，实际全期硬预算不变：

- uniform：剩余预算×规划窗口期数/剩余期数，复用原方法。
- forecast：剩余预算×（窗口内预测需求质量+当前欠单质量）/（全部剩余预测需求质量+当前欠单质量）；只使用当前公开预测和欠单，无未来实际需求。
- free：窗口可使用全部剩余预算，但后续没有补充。它用于量化提前耗尽预算风险，不是放宽全期碳约束。

期末价值比例ρ取0、0.5、0.9，每SKU单位信用额为ρ×质量×最低路线单位运输含碳成本。**仅在真实第12期期末**对现货库存返还一次，欠单、在途和滚动窗口中间截点不返还。ρ<1，低于新增一单位的最低运输成本；仍保留容量、非负库存和欠单约束。它是以运费为尺度的敏感性假设，不是采购价、企业残值或已验证的持续经营价值。报告返还前运营成本、返还额、净成本和最终库存，不能把会计返还直接说成决策改善。

需求情景数量取1、7、21；1表示一次随机需求路径，不等于均值预测。3个采样种子独立于真实需求种子。相同采样种子和期数下，小情景集是大情景集的前缀；同一真实路径的各策略预测不依赖动作，因此可作配对比较。采样分布仍为公开均值下Poisson，不假装已经拟合私有共同波动过程。

### 分析与学习判断

主要比较固定ρ=0、7情景下的碳分配；固定uniform、7情景下的ρ；固定uniform、ρ=0下的情景数量。另报告完整交叉单元均值及过程分组，查看交互和排名变化，不用全组合中的最低值替换原主方法。

期末价值效果分解为：保持ρ=0动作不变时的库存返还（会计效应），以及在相同ρ下重新规划相对该固定动作的净成本差（行为效应）。情景数量按3个采样种子分别报告配对均值和范围；可汇总但不把重复当作72条独立需求路径。时间只作本地测量，报告每决策均值与P95及MILP变量规模，不宣称同调用数等于同计算量。

每个ρ重算对应物理约束下的全期预知需求最优值。它只是不可部署的下界；与它的距离包含不可得信息价值，不能当作RL可改进空间。零价值uniform配置必须数值复现旧求解器；独立原始账本验证全部运输、库存、欠单和运营费用；另核对期末信用额及净成本。保存配置、任务、所有单元和逐期轨迹、配对分解、时间、源码身份；重新生成并重执行全部结果。保持失败/负结果，求解不达最优就报错。

学习判断不会仅依靠情景数或离线下界差距。先检查同信息强基线的稳定性、预算/终端假设是否主导排名，以及是否存在明确在线时限和可用教师。缺少这些证据时，结论为继续基线与预测验证，不自动训练BC/PPO。本轮没有新的训练任务、正式千题测试或API调用。

## English

This protocol is written before the full comparison and extends the [initial rolling environment](rolling_inventory_protocol.md). Existing source, data and results retain their identities. It asks whether carbon pacing, final inventory credit and scenario count change cost/service/emissions conclusions, and whether evidence currently justifies learning a policy. Parameters are explicit simulation assumptions, not estimates of corporate financial benefits.

### Fixed design

Keep 12 periods, three SKUs, two routes, six-period planning and historical-demand EWMA forecasts. Six new demand seeds across four processes give 24 distinct development paths, disjoint from the original calibration/development seeds. Retain the previously calibrated base-stock z=1 without new tuning. These remain development data, not a final holdout.

The full factorial has three allocations × three final values × three scenario counts × three sampling seeds: 81 scenario-MPC runs per path. Add nine mean-MPC, three base-stock and three perfect-information runs, yielding 96 per path, 2,304 trajectories and 27,648 period records. Sampling repeats do not add demand paths. Comparisons share realized demand; all future dispatch variables remain common across scenarios.

### Three factors

Carbon pacing changes only the MPC planning-window allowance; the actual cumulative hard budget is identical:

- uniform: remaining budget × planning periods / remaining periods, the existing approach.
- forecast: remaining budget × (forecast mass inside the window + current backlog mass) / (all remaining forecast mass + current backlog mass). No future realized demand is used.
- free: the window may spend all remaining budget, with no later replenishment. This diagnoses early exhaustion rather than relaxing the physical constraint.

Final-credit fraction ρ is 0, 0.5 or 0.9. Per-SKU credit equals ρ × mass × the cheapest route's freight-plus-carbon-price cost. It is paid once on positive stock **only at the actual final period**, not on backlog, pipeline or intermediate planning cutoffs. Credit is below the cheapest new unit's transport cost. It is a freight-scaled sensitivity assumption, not procurement price, corporate salvage value or validated continuing-operation value. Report operating cost before credit, the credit, net cost and final stock separately; accounting changes are not automatically better decisions.

Scenario counts are 1, 7 and 21. One random scenario differs from a mean forecast. Three sampling seeds are independent of actual demand seeds. For the same seed/period, smaller sample sets are prefixes of larger sets; all policies on a path share forecasts because demand observation is action-independent. Sampling remains Poisson around public means, not a fitted model of latent common volatility.

### Analysis and learning decision

Primary contrasts vary allocation at ρ=0 and seven scenarios, value at uniform/seven scenarios, and count at uniform/ρ=0. Also report all crossed cells and process breakdowns to expose interactions and ranking changes, without promoting the post-hoc minimum to the primary method.

Decompose final-value changes into credit on the unchanged ρ=0 actions (accounting) and the net-cost difference from replanning at the same ρ (behavior). Report scenario-count paired averages separately for each of the three sampling seeds and their range. Aggregation does not turn repeats into 72 independent demand paths. Timings are local measurements: report mean/P95 per decision and variable counts, not equal-compute claims based on call counts.

Recompute a perfect-information full-horizon optimum for each ρ under identical physics. Its gap includes unavailable information and is not an RL-improvement target. Zero-value/uniform settings must numerically reproduce the old solver. The original independent ledger audits all transport, stock, backlog and operating charges; separately verify final credit and net cost. Archive settings, tasks, cells, period records, paired decompositions, timings and source identities; regenerate and reexecute everything. Preserve failures and negative findings; unproven solver results raise errors.

The learning decision does not follow from scenario count or a clairvoyant gap alone. Check same-information baseline stability, sensitivity-driven ranking changes, and whether a concrete online time limit and teacher exist. Without that evidence, continue baseline/forecast validation rather than automatically training BC/PPO. This study creates no new training task, formal thousand-case final set or API calls.
