# 历史条件情景树：第二次开发试跑（v2）/ History-conditioned scenario trees: second development pilot (v2)

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

### 范围

按[开发协议 v2](rolling_tree_protocol_v2.md) 执行一次，属于**开发诊断，不是确认结论**：

- 4 条新开发路径：种子 72019 的 stable、volatile、upshift、downshift；
- 3 个规划器采样种子：924601、924611、924617；
- 选参只用选参划分，没有看任何成本；
- 确认数据没有生成、查看或运行；没有训练学习策略，没有调用 API。

证据在：
- [`benchmark_results/rolling_tree_v2_tuning/`](../benchmark_results/rolling_tree_v2_tuning/)（选参）；
- [`benchmark_results/rolling_tree_v2_pilot/`](../benchmark_results/rolling_tree_v2_pilot/)（试跑）；
- [`benchmark_results/rolling_tree_v2_continuation_check/`](../benchmark_results/rolling_tree_v2_continuation_check/)（看过结果后补做的检查）。

### 选参结果

- **先验强度 τ = 192**：一步联合 energy score 为 1.4907，48 是 1.4945，12 是 1.4972。
- **树形 (9, 3)，每片叶子 1 条延续路径，共 27 叶**：
  - 第一期样本误差 0.32，B1 自身 7 个情景为 1.02；
  - M1 在线时间 p95 1.87 秒，平局稳健 M2\* 为 8.52 秒；
  - 排在前面的 (9, 3) 加 3 条延续路径有一次平局求解超过 30 秒，不合格。
- **等时间开环 B4 用 216 条路径**：平均在线时间 0.50 秒，M1 为 0.46 秒。
- 用量：204 次求解，206 秒。

### 计算

- 2,318 次求解，墙钟 599 秒，未触发预算停止。
- 两次 M2\* 的平局求解到达 30 秒上限（volatile 种子 924601 第 7 期即 t=6，downshift 种子 924611 第 4 期即 t=3），按协议记为失败、不重试。这两条 M2\* 轨迹不完整，M1−M2\* 因此只有 10 个可比的“路径×种子”。
- 每次决策在线时间（平均 / p95，秒）：B1 0.009 / 0.018，M1 0.203 / 0.343，B4 0.333 / 1.102，B3 0.500 / 1.755，M2\* 0.731 / 2.174。
- 同一台机器同时在跑另一个项目的求解进程，计时只作参考。

### 情景质量已经可比

第一期样本误差（3 个 SKU 绝对值之和，审计状态上的平均）：树 0.34，B1 1.04，B4 0.05。第一次试跑中树为 1.70。

### 第一笔实际改变的决策

在 B1 轨迹的 132 个非强制状态上（4 条路径 × 11 期 × 3 个采样种子）做首期动作审计：

| 比较 | 实质不同 | 相同 | 平局 |
|---|---:|---:|---:|
| 相关性：M1 对 M2\*（同一组逐 SKU 边际情景，只差跨 SKU 配对） | 14 | 117 | 1 |
| 追索：M1 对 B3（同一组叶路径，只差非预知结构） | 83 | 49 | 0 |
| 现行基线：M1 对 B1\*（B1 自身最优动作中、M1 目标下最好的一个） | 80 | 52 | 0 |

**与现行滚动基线相比**：12 个“路径×种子”中，第一笔实质改变都在第 1 期（t=0）。
- B1 用快线发 SKU2（质量 2、积压费 10，三种零件里最贵的积压）：stable、downshift 各 2 件，volatile、upshift 各 1 件；volatile 还用快线发 1 件 SKU3。M1 一件也不走快线，改为把慢线装满（12 个中 11 个用满 8 个质量单位）。
- 排除 B1 自身的并列方案后，B1 的选择在 M1 目标下每个 6 期窗口贵 3.2–8.6，占 M1 窗口目标的 4.6%–16.7%。
- 原因：M1 的树允许看到第一期需求后再用快线补救，B1 的开环计划没有这种“以后再调整”的余地，只能先用快线对冲 SKU2 的积压风险。

**与只知道边际分布相比（相关性的作用）**：132 个状态中 14 个实质不同。
- 12 个“路径×种子”中 4 个从未出现；其余 8 个的第一笔分别在不同期次（t=0 到 t=9）。
- 一半发生在慢线已满的时候，改变的是慢线容量在 SKU 之间怎么分。例如：
  - downshift 种子 924601 第 1 期：SKU3 多 1 件、SKU1 少 1 件；
  - upshift 种子 924601 第 4 期：慢线上 SKU2 少 1 件、SKU3 多 2 件，超额 1.16，占窗口目标 1.3%。
- 其余是某个 SKU 增减 1 件。
- 超额只占窗口目标的 0.008%–1.3%，多数低于 0.7%。

### 这笔决定值不值得改

在 B1 的真实轨迹上只替换一期动作，其余各期照常由 B1 重新规划：

- **第 1 期改用 M1 的动作（相对 B1）**：
  - stable 省 8.5、8.5、10.35；
  - downshift 各省 3.0；
  - upshift 多花 8.6、0.4、6.6；
  - volatile 多花 10.0、9.8、13.5。
  - 平均 +1.05（6 好 6 坏）。排放变化在 −9 到 +2 之间；除 stable 外，即时满足率都降 1.9–3.8 个百分点。
- **第一个相关性实质状态改用 M1 而不是 M2\* 的动作**：8 个可比情形中 3 好、4 坏、1 相同，平均 +1.37。

在这 4 条路径上，这两类改变都**没有表现出可靠的实际价值**。单条路径只是一次实现，只作描述。

### 策略层面（12 个“路径×种子”，只来自 4 条独立路径，不给区间）

| 对比 | 成本差均值 | 相对 | 更好 / 更差 / 相同 | 各采样种子的均值 | 满足率差 | 排放差 |
|---|---:|---:|---|---|---:|---:|
| M1−M2\*（10 个） | −2.77 | −1.5% | 5 / 2 / 3 | −9.42，+0.27，−0.06 | +0.005 | +0.4 |
| M1−B3 | −8.29 | −4.8% | 10 / 2 / 0 | −13.74，−3.13，−8.01 | −0.028 | −9.3 |
| M1−B4 | −8.85 | −4.7% | 9 / 3 / 0 | −12.96，−7.00，−6.60 | −0.032 | −6.9 |
| M1−B1 | −7.43 | −4.2% | 9 / 3 / 0 | −17.41，−2.65，−2.21 | −0.035 | −17.5 |
| B4−B1 | +1.43 | +0.8% | 2 / 10 / 0 | −4.45，+4.35，+4.39 | −0.003 | −10.6 |

M1 比所有对照便宜、排放更低，主要因为运得更少：运费、碳成本和持有成本更低，积压更多。即时满足率比 B1、B3、B4 低 2.8–3.5 个百分点，超出协议的 0.5 个百分点护栏，所以这是成本与服务的取舍，不是单纯改善。相关性的对比 M1−M2\* 有一个种子为正，方向不一致。

### 看过结果后补做的检查（探索）

选中的树每片叶子只有 1 条延续路径，第 3 个窗口期以后的决策按叶子分开，规划里等于知道这条叶路径的未来，可能高估“先等等”的价值。在同样 132 个状态上，把 M1 改为每个第二层节点 3 条延续路径重新求解：

- M1 的首期动作有 66 个改变，是相关性改变（14 个）的近 5 倍；
- B1 的动作在新 M1 目标下仍有 90 个实质次优；
- 第 1 期 M1 开始在 4 / 12 个情形里用快线（1 条延续路径时为 0 / 12，B1 为 12 / 12）。

因此：“少用快线”在多数情形下站得住，但 M1 自己的首期决策对树的近似方式很敏感，敏感程度比相关性的作用还大。

### 判读

- **协议门槛**：
  - 树的第一期误差 0.34，高于 B4 的 0.05 加 0.1，不满足；
  - M1−B4 为 −4.7%，在 ±5% 内，满足；
  - M1−M2\* 三个种子方向不一致，不满足。
  - 按协议**不扩大到 32 条开发路径**，确认集仍不生成。
- **结论**：掌握共同冲击，会在约 11% 的状态改变首期动作，主要是满载的慢线在 SKU 之间重新分配 1–2 件。但这些改变在规划目标里很小，在真实路径上没有稳定的成本、交付或排放收益。
- **为什么作用小**：
  - **关联本身弱**：共同因子方差约 0.077（历史条件后为 0.03–0.11）。在每期 1–2 件的需求下，它带来的跨 SKU 需求相关系数只有约 0.1（μv/(1+μv)），Poisson 噪声占主导。
  - **先验压得很紧**：τ=192 时，单条路径的观测几乎改变不了共同因子方差。即使 volatile 路径的真实相关更强（σ=0.4，约 0.2），规划器也看不出来。
  - **耦合只来自共享运力和碳预算**：慢线 8、快线 4 个质量单位。M1 首期动作中慢线满载约 35%，快线约 13%。只有运力绑紧时，相关性才影响怎么分。
  - **已有策略先拿走了大部分信息**：B1 每期用 EWMA 重新预测、重新规划，持续的共同变化（upshift、downshift）会逐步进入均值。真正改变动作的是“能否以后再调整”（追索：83 / 132）和树的近似方式（66 / 132），而不是跨 SKU 配对。

### 下一项验收条件

- 先让 M1 的首期决策对树的近似方式稳定下来，再谈相关性的价值。例如在求解时间预算内增加延续路径，或用分解法求更大的树。
- 稳定性要事先定义：在审计状态上，延续路径数从 3 加到下一档时，首期动作改变不超过 10%。
- 满足之后，才用新的开发路径检验 M1−M2\* 的方向；32 条开发路径和确认集仍不动。

### 复现

- 选参：`python -m semiconductor_logistics rolling-tree tune2 --output <空目录>`；
- 试跑：`python -m semiconductor_logistics rolling-tree pilot2 --output <空目录>`，会消耗求解预算；
- 复算：`python -m semiconductor_logistics rolling-tree verify2`，不求解；重新生成任务、132 棵情景树、100 条轨迹的台账和全部汇总，并核对哈希；
- 补做检查：`python -m semiconductor_logistics rolling-tree check2 --output <空目录>`，264 次求解。

## English

### Scope

One run of [development protocol v2](rolling_tree_protocol_v2.md). This is a **development diagnostic, not confirmation**:

- four new development paths: seed 72019 under stable, volatile, upshift and downshift;
- three planner sampling seeds: 924601, 924611 and 924617;
- tuning used the tuning split only and consulted no cost;
- no confirmation data was generated, viewed or run; no learned policy and no API call.

Evidence:
- [`benchmark_results/rolling_tree_v2_tuning/`](../benchmark_results/rolling_tree_v2_tuning/) (tuning);
- [`benchmark_results/rolling_tree_v2_pilot/`](../benchmark_results/rolling_tree_v2_pilot/) (pilot);
- [`benchmark_results/rolling_tree_v2_continuation_check/`](../benchmark_results/rolling_tree_v2_continuation_check/) (a check added after seeing the results).

### Tuning

- **Prior strength τ = 192**: one-step joint energy score 1.4907, against 1.4945 for 48 and 1.4972 for 12.
- **Tree (9, 3) with one continuation path per leaf, 27 leaves**:
  - first-period sample error 0.32, against 1.02 for B1's own seven scenarios;
  - M1 online p95 1.87 s, tie-robust M2\* 8.52 s;
  - the (9, 3) candidate with three continuation paths, listed first, had one tie solve over 30 s and did not qualify.
- **Equal-time open loop B4 uses 216 paths**: mean online 0.50 s, against 0.46 s for M1.
- 204 solves, 206 s.

### Computation

- 2,318 solves, 599 s of wall time, no budget stop.
- Two M2\* tie solves reached the 30 s limit (volatile, seed 924601, period 7; downshift, seed 924611, period 4). Per the protocol they are recorded as failures and not retried. Those two M2\* trajectories are incomplete, so M1−M2\* has 10 comparable path×seed cases.
- Online seconds per decision (mean / p95): B1 0.009 / 0.018, M1 0.203 / 0.343, B4 0.333 / 1.102, B3 0.500 / 1.755, M2\* 0.731 / 2.174.
- Another project's solver processes shared the machine, so timings are indicative.

### Scenario quality is now comparable

First-period sample error (sum over the three SKUs, mean over audited states): tree 0.34, B1 1.04, B4 0.05. The first pilot's tree had 1.70.

### The first decision that actually changes

First-action audits on the 132 non-forced states of B1's trajectories (4 paths × 11 periods × 3 sampling seeds):

| Comparison | Material | Identical | Tie |
|---|---:|---:|---:|
| Dependence: M1 against M2\* (same per-SKU marginal scenarios; only cross-SKU pairing differs) | 14 | 117 | 1 |
| Recourse: M1 against B3 (same leaf paths; only the nonanticipative structure differs) | 83 | 49 | 0 |
| Rolling baseline: M1 against B1\* (the best under M1 among B1's own optimal actions) | 80 | 52 | 0 |

**Against the rolling baseline**: in all 12 path×seed cases the first material change is in period 1 (t=0).
- B1 ships SKU2 (mass 2, backlog 10 per unit-period, the costliest of the three to leave short) by the fast route: 2 units on stable and downshift, 1 on volatile and upshift; on volatile it also sends 1 unit of SKU3 fast. M1 ships nothing by the fast route and fills the slow route instead (all 8 mass units in 11 of 12 cases).
- Even after excluding B1's own ties, B1's choice costs 3.2–8.6 more per six-period window under M1's objective, 4.6%–16.7% of M1's window objective.
- Reason: M1's tree can still send SKU2 by the fast route after seeing first-period demand, while B1's open-loop plan has no such later adjustment and hedges SKU2's backlog risk with the fast route up front.

**Against knowing only the marginals (what dependence adds)**: 14 of 132 states differ materially.
- 4 of the 12 path×seed cases never show one; in the other 8 the first falls in different periods (t=0 to t=9).
- Half occur when the slow route is full and change how its capacity is split between SKUs. For example:
  - downshift, seed 924601, period 1: one more SKU3 and one fewer SKU1;
  - upshift, seed 924601, period 4: one fewer SKU2 and two more SKU3 on the slow route, excess 1.16, 1.3% of the window objective.
- The rest change one SKU by one unit.
- Excesses are 0.008%–1.3% of the window objective, mostly below 0.7%.

### Is the change worth making?

On B1's real trajectory only one period's action is replaced and B1 re-plans every other period:

- **M1's action in period 1 (against B1)**:
  - stable saves 8.5, 8.5 and 10.35;
  - downshift saves 3.0 each time;
  - upshift costs 8.6, 0.4 and 6.6 more;
  - volatile costs 10.0, 9.8 and 13.5 more.
  - Mean +1.05 (6 better, 6 worse). Emissions change by −9 to +2; except on stable, the immediate fill rate drops 1.9–3.8 points.
- **M1's action instead of M2\*'s at the first material dependence state**: 3 better, 4 worse and 1 equal among 8 comparable cases; mean +1.37.

On these four paths **neither kind of change shows a reliable realized value**. Each path is a single realization and is reported descriptively.

### Policies (12 path×seed cases from only 4 independent paths; no intervals)

| Contrast | Mean cost difference | Relative | Better / worse / same | Mean by sampling seed | Fill difference | Emissions difference |
|---|---:|---:|---|---|---:|---:|
| M1−M2\* (10) | −2.77 | −1.5% | 5 / 2 / 3 | −9.42, +0.27, −0.06 | +0.005 | +0.4 |
| M1−B3 | −8.29 | −4.8% | 10 / 2 / 0 | −13.74, −3.13, −8.01 | −0.028 | −9.3 |
| M1−B4 | −8.85 | −4.7% | 9 / 3 / 0 | −12.96, −7.00, −6.60 | −0.032 | −6.9 |
| M1−B1 | −7.43 | −4.2% | 9 / 3 / 0 | −17.41, −2.65, −2.21 | −0.035 | −17.5 |
| B4−B1 | +1.43 | +0.8% | 2 / 10 / 0 | −4.45, +4.35, +4.39 | −0.003 | −10.6 |

M1 is cheaper and emits less than every comparator mainly because it ships less: lower freight, carbon and holding, more backlog. Its immediate fill rate is 2.8–3.5 points below B1, B3 and B4, beyond the protocol's 0.5-point guardrail, so this is a cost-service tradeoff rather than an improvement. The dependence contrast M1−M2\* is positive under one seed: no consistent direction.

### Check added after seeing the results (exploratory)

With one continuation path per leaf, decisions from the third window period on are leaf-specific and in the plan know that leaf's future, which can overstate the value of waiting. On the same 132 states M1 was re-solved with three continuation paths per depth-2 node:

- M1's first action changes in 66 states, nearly five times the dependence changes (14);
- B1's action stays materially suboptimal under the new M1 in 90;
- in period 1, M1 now uses the fast route in 4 of 12 cases (0 of 12 with one path; B1 in 12 of 12).

So "less fast-route shipping" mostly holds, but M1's own first decision is sensitive to how the tree is approximated, more than to dependence.

### Reading

- **Protocol gate**:
  - the tree's first-period error 0.34 is above B4's 0.05 plus 0.1: not met;
  - M1−B4 at −4.7% is within ±5%: met;
  - M1−M2\* does not have one direction across the three seeds: not met.
  - Per the protocol, **the 32-path development batch is not run**, and confirmation data stays ungenerated.
- **Finding**: knowing the common shock changes the first action in about 11% of states, mostly by reallocating one or two units of a full slow route between SKUs. These changes are small in the planning objective and show no stable cost, delivery or emission gain on real paths.
- **Why the effect is small**:
  - **The dependence is weak**: the common-factor variance is about 0.077 (0.03–0.11 once conditioned on history). With 1–2 units of demand a period, it implies a cross-SKU demand correlation of only about 0.1 (μv/(1+μv)); Poisson noise dominates.
  - **The prior is tight**: at τ=192 one path's observations barely move the variance. Even where the volatile path's true dependence is stronger (σ=0.4, about 0.2), the planner does not see it.
  - **Coupling comes only from shared capacity and the carbon budget**: 8 mass units on the slow route and 4 on the fast. The slow route is full in about 35% of M1's first actions and the fast route in about 13%; only binding capacity lets dependence affect the split.
  - **Existing policy takes most of the information first**: B1 re-forecasts by EWMA and re-plans every period, so persistent common shifts (upshift, downshift) reach its mean step by step. What actually changes actions is the possibility of adjusting later (recourse: 83 of 132) and how the tree is approximated (66 of 132), not cross-SKU pairing.

### Next acceptance condition

- First make M1's first decision stable under the tree approximation, before asking what dependence is worth; for example more continuation paths within a solve-time budget, or decomposition for larger trees.
- Stability is fixed in advance: on audited states, raising the continuation count from three to the next level changes no more than 10% of first actions.
- Only then test the direction of M1−M2\* on new development paths. The 32 development paths and the confirmation set stay untouched.

### Reproduction

- Tuning: `python -m semiconductor_logistics rolling-tree tune2 --output <empty directory>`.
- Pilot: `python -m semiconductor_logistics rolling-tree pilot2 --output <empty directory>`; this spends solve budget.
- Verification: `python -m semiconductor_logistics rolling-tree verify2`, no solving. It regenerates the tasks, 132 scenario trees, 100 trajectory ledgers and every summary table, and checks the hashes.
- Added check: `python -m semiconductor_logistics rolling-tree check2 --output <empty directory>`, 264 solves.
