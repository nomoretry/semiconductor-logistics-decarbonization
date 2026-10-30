# 滚动库存基线结果 / Rolling inventory baseline results

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

按[事前协议](rolling_inventory_protocol.md)，已实现未知需求、历史需求预测更新、在途到货、欠单和累计碳预算的滚动环境。四个过程各3个校准情境、8个开发情境，共44条不同需求路径；每条12期、3 SKU、2路线。校准集合选择base-stock的z=1：z=0/1/2的平均成本为450.3333/385.1583/392.3000。未用开发结果重新选择z。

32条开发路径分别运行4个可部署基线及1个预知需求下界，共160条结果。另保留36条校准规则运行，总共196条轨迹、2,352个逐期决策记录。情境种子不是训练种子，没有训练BC/PPO，没有建立新正式测试集。

### 成本与服务

| Method | Mean cost | Immediate fill | Emissions | Backlog unit-periods | Final stock | MILP calls/episode |
|---|---:|---:|---:|---:|---:|---:|
| Base-stock | 330.6219 | 82.68% | 95.0000 | 16.0938 | 10.2500 | 0 |
| Marginal-cost greedy | 427.9937 | 77.83% | 91.4375 | 26.3750 | 6.3125 | 0 |
| Mean MPC | 391.2625 | 74.28% | 108.4375 | 19.6250 | 4.9688 | 12 |
| Scenario MPC | 282.2406 | 89.61% | 109.6875 | 7.9062 | 11.3438 | 12 |
| Perfect-information bound | 111.1891 | 98.63% | 69.4062 | 1.0625 | 0.0000 | 1 |

平均成本是各情境实际仿真成本的均值，包含运费、碳价、持有、逐期欠单和末期欠单费用。排放为未校准仿真单位，不是企业吨CO2。满足率先清偿旧欠单，再计算新需求的即时履约；最终库存不享受残值。完整分项成本在[outcomes.jsonl](../benchmark_results/rolling_inventory_development/outcomes.jsonl)。

- 情景MPC平均成本比base-stock低48.3813（约14.63%），32情境中19个更好、13个更差；即时满足率89.61%对82.68%，但平均排放109.6875对95.0000，期末库存也更高。因此不能写成同时降低成本与排放。
- 均值MPC平均成本391.2625，高于base-stock的330.6219；22个情境更差。显式求解优化模型不保证在有预测误差的实际路径上更优。
- 贪心成本427.9938，也不优于规则。这保留了固定逐期碳配额及“之后不再发货”近似的弱点，没有调整实例让它获胜。
- 全期预知需求下界111.1891只用于参照。它提前知道所有实际需求，不可部署；差距包含不可得信息的价值、预测偏差、样本近似、预算分配和截断规划影响，不能全部解释为RL可消除的损失。

### 分过程结果

| Process | Base-stock | Greedy | Mean MPC | Scenario MPC | Offline bound |
|---|---:|---:|---:|---:|---:|
| downshift | 186.4500 | 222.7937 | 176.6812 | 194.4250 | 63.3500 |
| stable | 215.4000 | 245.1375 | 277.2938 | 208.8938 | 85.6687 |
| upshift | 610.7688 | 815.3125 | 737.8562 | 482.7875 | 197.3813 |
| volatile | 309.8687 | 428.7312 | 373.2188 | 242.8562 | 98.3563 |

需求下降时均值MPC更好，情景MPC会付出额外库存成本；上升与波动过程是情景规划最明显的开发信号。此处仅描述结果，不进行事后选择方法或正式显著性宣称。总体预测MAE为1.0821单位/SKU/期；实际减预测的平均误差0.0108接近零，并不意味着逐期误差小。预测完全独立于策略，因此不同策略的预测误差相同。

### 计算与核验

| Method | Mean planning seconds / 12-period episode |
|---|---:|
| Base-stock | 0.002925 |
| Marginal-cost greedy | 0.033550 |
| Mean MPC | 0.078622 |
| Scenario MPC | 0.072002 |
| Perfect-information bound | 0.005861 |

以上是单次本地测量，受机器、求解器缓存及执行顺序影响；不能据此宣布端到端加速。两种MPC每期1次MILP，共12次；最大6期时均值模型36个整数发货变量、36个连续库存/欠单变量，7情景模型共享36个整数变量但有252个连续变量。情景数增加约束与变量，不增加MILP调用计数。

[证据包](../benchmark_results/rolling_inventory_development)保存任务、校准选择、逐期公开观测和私有需求揭示、全部动作/库存/在途/费用、结果、计时、运行版本和源码哈希。复算重新生成44条路径，重复校准并重跑全部196条轨迹及预知需求下界；另用独立账本核对库存守恒、履约顺序、费用、容量及累计碳预算。轨迹以确定性gzip保存（`traces.jsonl.gz`），解压后逐字节等于原JSONL；归档方式改变不改动作或结果。315项离线测试通过；新增9项覆盖未来需求隔离、运输提前期、原子拒绝、微型枚举、情景共用动作和重写哈希后的篡改拒绝。轮子安装与命令入口检查通过，Haswell BLAS分派下完整复算通过。

```bash
python -m semiconductor_logistics rolling-inventory run --output artifacts/rolling_inventory
python -m semiconductor_logistics rolling-inventory verify --output artifacts/rolling_inventory
python -m semiconductor_logistics rolling-inventory verify
make verify-rolling
```

前两个命令在新空目录重现，第三个核验仓库归档。所有命令离线运行，不调用LLM API。CI分开执行基础/既有训练、冻结千题、组件实验和本轮滚动实验，保留原全部验收项。

### 下一项研究

先检查碳预算均匀分配与规划截断的影响，再比较预测模型和情景数量在新开发路径上的稳定性；明确不可得信息造成的损失。当前不据这32个开发情境训练RL，也不把它们变成正式留出集。本轮在途时长固定、信息免费、供给无限、期末无残值；未与付费查询耦合，也未用企业真实订单或运输数据校准。长期连续运营需要终端价值/延长评估窗检验。历史文档双语补齐、完整依赖锁和正式发布仍待完成。

## English

The [prewritten protocol](rolling_inventory_protocol.md) introduces unknown demand, forecasts updated from observed history, pipeline arrivals, backorders and a cumulative carbon budget. Four processes have three calibration and eight development contexts each: 44 distinct demand paths, each with 12 periods, three SKUs and two routes. Calibration chooses base-stock z=1: mean costs for z=0/1/2 are 450.3333/385.1583/392.3000. Development outcomes do not reselect z.

The 32 development paths compare four deployable baselines and one perfect-information bound, yielding 160 outcomes. Another 36 calibration rule runs are retained, for 196 trajectories and 2,352 period records in total. Context seeds are not training seeds. No BC/PPO is trained and no new final test is created.

### Cost and service

| Method | Mean cost | Immediate fill | Emissions | Backlog unit-periods | Final stock | MILP calls/episode |
|---|---:|---:|---:|---:|---:|---:|
| Base-stock | 330.6219 | 82.68% | 95.0000 | 16.0938 | 10.2500 | 0 |
| Marginal-cost greedy | 427.9937 | 77.83% | 91.4375 | 26.3750 | 6.3125 | 0 |
| Mean MPC | 391.2625 | 74.28% | 108.4375 | 19.6250 | 4.9688 | 12 |
| Scenario MPC | 282.2406 | 89.61% | 109.6875 | 7.9062 | 11.3438 | 12 |
| Perfect-information bound | 111.1891 | 98.63% | 69.4062 | 1.0625 | 0.0000 | 1 |

Mean cost averages realized simulated freight, carbon-price, holding, period-backlog and final-backlog charges. Emissions are uncalibrated simulation units, not corporate tonnes of CO2. Immediate fill serves old backlog first and counts new demand met immediately; final stock has no salvage value. Component costs are in [outcomes.jsonl](../benchmark_results/rolling_inventory_development/outcomes.jsonl).

- Scenario MPC costs 48.3813 less than base-stock on average (about 14.63%): better on 19 contexts and worse on 13. Immediate fill is 89.61% versus 82.68%, but emissions are 109.6875 versus 95.0000 and final stock is higher. This is not simultaneous cost and emissions reduction.
- Mean MPC costs 391.2625 versus base-stock's 330.6219 and is worse on 22 contexts. Explicit optimization does not guarantee better realized decisions under forecast error.
- Greedy costs 427.9938, also worse than the rule. Its even per-period carbon allocation and no-further-dispatch approximation remain visible; instances were not adjusted to make it win.
- The 111.1891 perfect-information cost is only an offline reference. It knows the entire realized demand path and is not deployable. Its gap includes unavailable information, forecast bias, sampling, budget allocation and truncated planning, not solely losses that RL could eliminate.

### Process breakdown

| Process | Base-stock | Greedy | Mean MPC | Scenario MPC | Offline bound |
|---|---:|---:|---:|---:|---:|
| downshift | 186.4500 | 222.7937 | 176.6812 | 194.4250 | 63.3500 |
| stable | 215.4000 | 245.1375 | 277.2938 | 208.8938 | 85.6687 |
| upshift | 610.7688 | 815.3125 | 737.8562 | 482.7875 | 197.3813 |
| volatile | 309.8687 | 428.7312 | 373.2188 | 242.8562 | 98.3563 |

Mean MPC is better under decreasing demand; scenario MPC carries extra inventory. Upward shifts and volatility provide the clearest development signal for scenario planning. These are descriptive comparisons, without post-hoc method selection or confirmatory significance claims. Overall forecast MAE is 1.0821 units/SKU/period. Mean actual-minus-predicted error of 0.0108 is near zero but does not imply small period errors. All policies share the same forecasts because they do not affect demand observations.

### Computation and verification

| Method | Mean planning seconds / 12-period episode |
|---|---:|
| Base-stock | 0.002925 |
| Marginal-cost greedy | 0.033550 |
| Mean MPC | 0.078622 |
| Scenario MPC | 0.072002 |
| Perfect-information bound | 0.005861 |

Timings are single local measurements affected by hardware, solver caches and order; they do not establish end-to-end speedups. Each MPC uses one MILP per period, 12 per episode. At the six-period maximum, mean MPC has 36 integer dispatch and 36 continuous inventory/backlog variables; seven-scenario MPC shares the same 36 integer variables but has 252 continuous variables. Scenario count changes problem size, not solver-call count.

The [bundle](../benchmark_results/rolling_inventory_development) contains tasks, selection, public observations and revealed private demand, every action/stock/pipeline/cost, outcomes, timings, runtime versions and source hashes. Replay regenerates 44 paths, repeats calibration and all 196 trajectories including the perfect-information bounds. An independent ledger checks conservation, service order, costs, capacities and cumulative carbon. Traces use deterministic gzip (`traces.jsonl.gz`); decompression is byte-identical to the original JSONL, preserving every action and outcome. All 315 offline tests pass; nine new tests cover future-demand isolation, lead times, atomic rejection, tiny exhaustive optimization, shared scenario actions and rehashed tampering. Wheel installation and CLI checks pass, as does full replay under Haswell BLAS dispatch.

```bash
python -m semiconductor_logistics rolling-inventory run --output artifacts/rolling_inventory
python -m semiconductor_logistics rolling-inventory verify --output artifacts/rolling_inventory
python -m semiconductor_logistics rolling-inventory verify
make verify-rolling
```

The first two commands reproduce into a new empty directory; the third verifies the archive. All commands are offline and make no LLM API calls. CI separately executes foundation/existing training, frozen final, component and rolling checks, preserving all previous acceptance tasks.

### Next research step

First isolate the effects of carbon pacing and truncated planning, then test forecast models and scenario counts on new development paths, distinguishing losses caused by unavailable information. Do not train RL from this 32-case result or relabel these cases as untouched final data. Lead times are fixed, information is free, supply is unlimited and final stock has no salvage value. Paid queries are not coupled and real corporate order/transport data do not calibrate this model. Continuous-operation studies require terminal-value or longer-window checks. Historical bilingual documentation, complete dependency locking and formal release remain unfinished.
