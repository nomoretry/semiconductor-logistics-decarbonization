# 滚动库存实验协议 / Rolling inventory protocol

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

本协议在完整实验运行前写定。问题是：未知需求、滞后预测和在途库存共同存在时，多SKU共享路线容量与全期碳预算下，简单规则和滚动优化各付出什么成本？这是新合成开发环境，不延伸原已查看千题集，不训练BC/PPO，不预设方法必须获胜。本轮预测和在途信息免费可见，供应端可补货量不受限，先隔离滚动运输与补货问题；未与有价查询策略联训。

### 信息、物理顺序与成本

每个情境12期、3个SKU、2条路线；运输提前期分别为2期和1期。各期先接收到期货物并优先清偿旧欠单，发布当前库存、欠单、逐期在途表和仅用历史需求更新的预测；策略随后决定整数发货量；最后揭示当期需求、履约、计持有与欠单成本。订单不可撤销，零提前期运输不存在。逐SKU满足“期末净库存 = 初始净库存 + 累计到货 − 累计需求”；发货另守恒于到货与在途。

所有需求均可观察，未即时履约需求保留为欠单，不是丢失销量。即时满足率只统计新需求被当期剩余现货满足的数量，先清偿旧欠单。末期欠单加收配置中的终端成本；期末剩余库存无残值，禁止下达在实验结束后才到货的订单。初始库存是固定、已沉没的共同资源，模型只计运输、持有、欠单、终端欠单及碳价格成本，不声称包含完整采购经济性。所有价格、容量、排放和碳预算都是仿真单位。

路线容量按SKU质量共享，每期重置；碳预算全期共享且扣除后不恢复。独立环境在任何写入前检查整数、非负、路线容量、剩余碳预算及到货期限。无效动作被拒绝并报错，不隐藏修复。

### 需求、预测和划分

四种合成过程：平稳、共同波动、未公告上升和未公告下降。实际需求是带公开周期性均值的Poisson抽样；波动/改变因子仅在仿真器内生成。预测使用公开基准均值、周期因子和截至上一期的去周期需求EWMA，alpha=0.35；它不读取过程标签、私有种子、当前或未来实际需求。公开观测不含这些字段。记录每期预测误差与平均绝对误差，不把准确预测当成前提。

每过程3个校准种子，共12个情境，用于在z={0,1,2}中按平均实际总成本选择补货规则的安全系数。随后在每过程8个其他种子、共32个开发情境比较；它们不是正式测试集。方法在完全相同的需求路径与初始资源上配对。情境种子不是学习算法种子；没有模型训练。

### 基线与参照

1. 在途感知base-stock：按预计到货时点的累计需求、已有在途、净库存和z√需求的安全量计算缺口；按欠单成本/质量排序，优先选择便宜路线，再处理剩余近端紧缺。碳使用按剩余期数均匀配额。z只在校准情境选择。
2. marginal_cost：反复试加一单位当前发货，用6期预测下“之后不再新增发货”的持有/欠单/终端成本变化扣除运费和碳价，选择正边际收益最大的可行动作；不调用MILP。这是当前期贪心，不是多期最优算法。
3. mpc_mean：每期用6期均值预测建立整数运输规划，仅执行第一期动作，然后重新预测与规划。
4. mpc_scenarios：从同一公开均值生成7条Poisson情景，优化平均成本；**全部未来发货变量在情景间共享**，库存和欠单按情景分开，因此没有预知情景的后续动作。它是开环随机MPC，不是完整多阶段随机最优控制，也没有精确拟合私有波动过程。

MPC的规划期碳额度为“剩余预算×规划期数/剩余期数”；两种MPC使用相同规则。贪心使用当前期均匀碳配额。所有方法最终均受同一实际全期约束。这些是各方法的预算分配近似，不作等计算预算比较。记录求解次数与实际规划时间；情景MILP的一次调用不等于均值MILP的一次计算量。

另外对每条需求路径求解全期预知需求MILP，在相同物理约束下取得离线最优成本。它是不可部署的下界，不参与基线排名，不能把与它的差距解释为可被RL消除的损失。求解必须证明最优且通过独立计划成本复算；超时/失败不得记作成功。

### 证据、验收与范围

保存配置、全部44个需求路径、校准选择、逐期观测/动作/到货/需求/库存/欠单/在途/费用、基线与下界结果、运行时间及源文件哈希。核验重新生成数据、重新选择校准参数、重新执行全部策略和下界；运行时间只保留原测量，不要求重放相同。有限范围含跨平台数值容差，整数动作仍严格对照。

测试必须覆盖：未来需求不能改变当前观测/动作；运输不得提前到达；欠单服务顺序；容量/碳/非整数动作原子拒绝；流水库存守恒；微型枚举对照MILP；实际策略成本不低于预知需求下界；篡改轨迹即使重写哈希仍被重放发现。报告总成本、分项成本、即时满足率、欠单单位期、碳排放、期末剩余库存、预测误差和计算量。32个开发情境只报告描述性配对差异与过程分组，不作正式显著性检验。

进入学习阶段前，先核对强基线是否已足够好、代价来自信息不可得还是策略失误、情景采样和碳预算分配是否成为主要弱点；当前不设置必须通过的RL收益门槛，也不创建新千题最终集。

### 文献来源

Undermind核对摘要和元数据：Dural-Selcuk等，[The benefit of receding horizon control](https://doi.org/10.1016/j.omega.2019.07.007)；Conte与Pennesi，[Inventory control by model predictive control methods](https://doi.org/10.3182/20050703-6-CZ-1902.01498)。阅读范围仅摘要，未获得全文。二者支持将未知需求库存控制表述为滚动决策并与既有策略比较；不据此声称复现其算法、最优性或数值结果。既有在途库存研究来源见[资料依据](research_basis.md)。参数未用ASML或Marvell私有业务数据校准。

## English

This protocol is written before the full experiment. The question is how rules and rolling optimization trade costs under unknown demand, lagged forecasts, inventory in transit, shared route capacities and a cumulative carbon budget. This is a separate synthetic development environment. It does not extend the inspected final query benchmark, train BC/PPO, or require a particular method to win. Forecast and pipeline information are free, upstream replenishment is unlimited, and this stage isolates rolling transport/replenishment rather than jointly training paid-query policies.

### Information, timing and costs

Each context has 12 periods, three SKUs and two routes with lead times two and one. Each period receives due shipments and serves old backorders first; publishes stock, backlog, dated pipeline and forecasts using past demand only; accepts integer dispatches; then reveals current demand, serves customers and charges holding/backlog costs. Orders are irrevocable; zero-lead transport is unavailable. Per-SKU net inventory equals initial net stock plus cumulative arrivals minus cumulative demand. Dispatches equal received plus outstanding units.

All demand is observed. Unfilled units remain backordered, not lost. Immediate fill rate counts only new demand met from current remaining stock, after old backorders. Final backlog incurs an additional configured charge; final stock has no salvage value and dispatches arriving after the episode are forbidden. Initial stock is a common sunk resource. Costs include freight, holding, backlog, final backlog and carbon prices, not full procurement economics. All prices, capacities, emissions and budgets are simulated units.

Route capacity is shared by SKU mass and resets each period. The carbon budget is cumulative and never replenished. Before any mutation the environment independently checks integer nonnegative dispatches, route capacities, remaining carbon and arrival deadlines. Invalid actions raise errors without silent repair.

### Demand, forecasts and splits

Four synthetic processes are stable, common volatility, unannounced upward shift and unannounced downward shift. Demand is sampled from Poisson means with public seasonality; latent multipliers remain inside the simulator. Forecasts use the public base mean, seasonal factors and an EWMA of deseasonalized demand observed through the previous period (alpha=0.35). Policies receive no process label, private seed or present/future demand. Forecast errors and MAE are reported.

Twelve calibration contexts (three seeds per process) choose the base-stock safety multiplier from {0,1,2} by mean realized total cost. Thirty-two other development contexts (eight seeds per process) then compare methods on identical demand paths and initial resources. These are development cases, not a formal test. Scenario seeds are not learned-model training seeds; no policy is trained.

### Baselines and reference

1. Pipeline-aware base-stock compares cumulative demand through each arrival date and a z√demand safety quantity against net stock and dated pipeline. It prioritizes backlog cost per mass, uses cheap transport first, then remaining near-term shortages. Carbon is paced evenly across remaining periods. Only calibration contexts choose z.
2. Marginal-cost greedy repeatedly adds a feasible current-period dispatch unit with the largest positive reduction in six-period forecast holding/backlog/final costs, net of freight and carbon price, assuming no further dispatches. It makes no MILP calls and is not a multi-period optimum.
3. Mean MPC plans six periods using mean forecasts, executes only the first action, then updates and replans.
4. Scenario MPC samples seven Poisson paths from the same public forecasts and minimizes average cost. **All future dispatch variables are shared across scenarios**; only inventory/backlog variables differ. Thus later actions cannot anticipate a sampled scenario. This is open-loop stochastic MPC, not optimal multi-stage control or an exact fit of the latent demand process.

Both MPC methods allocate remaining carbon × planning periods / remaining periods. Rules use the evenly paced current-period allowance. The actual cumulative budget is identical for all methods; pacing is a policy approximation. This is not an equal-compute comparison: report calls and measured planning time, since one scenario MILP is not computationally equivalent to one mean MILP.

A full-horizon perfect-information MILP knows realized demand and provides an offline lower bound under the same physical constraints. It is not deployable or ranked as a policy, and its gap is not necessarily reducible by RL. Every solve must prove optimality and pass an independently recomputed physical plan objective; failures/timeouts cannot count as successes.

### Evidence, acceptance and scope

Archive settings, all 44 demand paths, calibration selection, period observations/actions/arrivals/demand/stock/backlog/pipeline/costs, policies and lower bounds, timings and source hashes. Verification regenerates data, repeats calibration, reruns every policy and lower bound. Timing values remain recorded measurements rather than reproducible equality targets. Numeric tolerances permit limited floating-point variation; integer actions are compared exactly.

Tests cover future-demand noninterference, lead times, backlog priority, atomic rejection of capacity/carbon/noninteger violations, inventory/pipeline conservation, tiny exhaustive checks of the MILP, the perfect-information lower bound, and rejection of rehashed trajectory tampering. Report total/component costs, immediate fill rate, backlog unit-periods, emissions, final stock, forecast errors and computation. Development comparisons are descriptive paired differences and process groups, not confirmatory significance tests.

Before training, determine whether strong baselines are already adequate, whether remaining costs reflect unavailable information or poor choices, and whether scenario sampling/carbon allocation dominates. No required RL win or new thousand-case final set is introduced here.

### Literature

Undermind abstracts and metadata were checked for Dural-Selcuk et al., [The benefit of receding horizon control](https://doi.org/10.1016/j.omega.2019.07.007), and Conte and Pennesi, [Inventory control by model predictive control methods](https://doi.org/10.3182/20050703-6-CZ-1902.01498). Full texts were unavailable. They motivate rolling inventory control with unknown demand and policy comparisons; this implementation does not reproduce their algorithms, optimality results or experiments. Existing pipeline-inventory references are in [research basis](research_basis.md). No private ASML or Marvell operations data calibrate these settings.
