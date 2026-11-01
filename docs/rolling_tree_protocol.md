# 历史条件情景树：开发协议 / History-conditioned scenario trees: development protocol

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

### 版本与范围

开发版 v1。本版只覆盖：独立模块的最小实现、正确性测试，以及有预算的小规模开发试跑。完整开发批次和正式确认实验**不在本版范围内**，确认数据不生成、不查看、不运行。确认阶段的样本量、分析方法和停止规则，要依据开发阶段实测的波动和计算情况另行写定并冻结。设计若在开发中修改，追加版本并写明理由，不倒改本版。配置见 [`rolling_tree/config.json`](../rolling_tree/config.json)。

### 问题

现有滚动研究（[滚动基线](rolling_inventory_protocol.md)、[分布确认](rolling_distribution_results.md)、[有限追索](rolling_recourse_results.md)）的决策框架分两层，要分开看：

- **执行层**：情景 MPC 每期都按最新观测重新规划，只执行首期动作。系统本来就会随新需求调整，本研究**不是**第一次让系统根据新需求调整。
- **单次优化内部**：[`rolling_inventory/planning.py`](../rolling_inventory/planning.py) 让所有情景共用同一份未来发货计划，没有“按未来可观察历史分支”的追索；目标按 SKU 可分，所以跨 SKU 怎样配对不改变最优值（768 次审计，最大偏差 1.14×10⁻¹³）。

本研究检验：在已有的滚动执行框架下，单次优化里**显式建模未来的适应性**（非预知情景树）和**跨 SKU 依赖**（同期共同冲击），是否改变首期发货动作（排除平局），并改善实际运行的成本、服务和排放；为此多付出的在线计算是多少。

### 已有结论（保留）

- 7 情景 MPC 成本低于 base-stock，排放更高；7→21 情景收益小，方向不稳。
- 分布确认：残差负二项分布未改善成本，教师筛选未通过。
- 有限追索：36 个构造模型中的表面收益，全部能由最优平局解释；跨模型评估遗憾为 0。
- 没有有效的滚动学习教师；部署时限和允许损失未定义；不训练 BC/PPO。

先验预期是效应可能为零或很小。

### 环境、信息与事件顺序

- **环境**：沿用 [`rolling_inventory/environment.py`](../rolling_inventory/environment.py) 与原配置，原文件不改。12 期、3 SKU、2 路线；路线容量按质量共享，每期重置；全期累计碳预算 132；末期积压另计成本；期末无残值；不得下达期末之后才到货的订单。
- **每期事件顺序**：到货 → 清偿旧积压 → 观测 → 发货（写入前检查整数、容量、剩余碳和到货期限）→ 揭示本期需求 → 计费 → 扣碳、写入历史。
- **策略可见**：期数、公开参数、库存、积压、在途、剩余碳、过去需求、原 EWMA 预测。
- **策略不可见**：隐藏共同因子、过程标签、任务 ID、需求种子、本期及未来需求。
- 预知需求只用于离线下界，不当教师。

### 规划模型

- **窗口与配额**：窗口 h=min(6, 12−t)；碳配额为剩余预算×h/(12−t)；求解器设置与原 MPC 相同（HiGHS，`mip_rel_gap=0`，单次 30 秒上限）。
- **共同冲击情景**：
  - 均值用原 EWMA 预测 μ。
  - 未来每期有一个所有 SKU 共用的乘性因子 F，跨期独立；log F~N(−s²/2, s²)，s²=ln(1+v)。
  - v 是同期跨 SKU 标准化残差乘积 r_i r_j 的均值：先在拟合路径上估计 v_fit，再与本路径已观察的乘积按 τ=48 条伪观测合并，截断到 [0, 2]。
  - 第一版不建模持续的状态切换。模型族是在知道合成生成器之后选的，结论只算合成结构上的匹配。
- **情景树（D=2, b=3, m=3，27 条叶路径）**：
  - 前两期按 F 的 3 个等概率分位点分支（归一到均值 1），各 SKU 需求用 Poisson 抽样；之后每个深度 2 节点下有 3 条延续路径。
  - 随机数只由（采样种子, t, 节点）确定。
- **非预知约束**：阶段 u 的决策变量按“窗口内第 0…min(u, 2)−1 期的**观测需求向量**”编号。观测历史相同的情景必然共用决策，即使它们来自不同的分支编号。深度 2 之后的决策由同一节点下的延续路径共用，这是限制，不会预知未来。
- **约束与目标**：每个节点每条路线一条容量约束；碳按每条叶路径累计，互斥分支不相加；叶路径等权的期望成本。
- **打乱配对（M2）**：在同一棵树上，对 SKU 2、3 按固定种子在每一层做子树置换（索引树自同构）。每个 SKU 的边际情景树与完整路径多重集合完全不变，只改变跨 SKU 配对；约束、窗口、配额和求解设置都不变。

### 方法

| 代号 | 方法 | 说明 |
|---|---|---|
| B0 | base-stock，z=1 | 原规则 |
| B1 | 原 EWMA+Poisson 开环 7 情景 MPC | 原代码，原采样种子 901337 |
| B2 | 开环 MPC，使用与 M1 相同的 27 条叶路径 | 只在审计中求解 |
| B3 | B2 的平局稳健版 | 先求 B2 最优值，再在“B2 目标 ≤ 最优值+容差”内，按 M1 目标选首期动作 |
| M1 | 情景树，共同冲击配对 | 主方法 |
| M2 | 情景树，打乱配对 | 只在审计中求解 |
| M2* | M2 的平局稳健版 | 先求 M2 最优值，再在“M2 目标 ≤ 最优值+容差”内，按 M1 目标选首期动作 |
| B4 | 等时间开环 MPC | S′ 条独立共同冲击路径；S′ 在试跑前 3 个审计状态上校准，使在线时间最接近 M1 |
| LB | 全期预知需求 MILP | 只作下界 |

- **B3 和 M2* 是保守的诊断设计**：它们借用 M1 的目标，只在自身模型的并列最优解里选解，因此 M1−M2* 只计入“实质不同”的动作，M1−B3 只计入平局之外的追索作用。
- 这两种方法只使用规划情景，不使用真实未来需求，也不使用确认集结果；额外求解的时间计入它们的在线时间和预算。
- **三类比较分开报告**：相关性的价值（M1−M2*）、追索的价值（M1−B3）、计算预算（M1−B4，以及与 B1 比较），不混为一谈。

### 动作审计与容差

- 在 B1 轨迹经过的同一组状态上，求 M1、M2、M2*、B2、B3。
- 若 M2* 的首期动作在 M1 目标下比 M1 最优值差出数值容差以上，说明 M2 的所有最优动作在 M1 下都非最优，记为**实质不同**；否则记为平局或相同。B2/B3 同理。
- **数值容差**：相对 1e-6 加绝对 1e-7，只用于区分求解精度内的并列。它**不是**实用等效界。
- **2% 成本下降**只作本项目的实用收益参考，不是企业标准。
- **护栏**：满足率绝对下降不超过 0.005（0.5 个百分点）；排放相对增加不超过 2%；原硬性碳约束不放宽。
- 成本、服务、排放分别报告点估计、区间（样本足够时）和护栏。

### 指标与计算记录

- **实际运行指标**：总成本（运费、碳价、持有、逐期积压、末期积压）、即时满足率、积压单位期、排放、期末库存和积压，以及首期动作审计计数。
- **计算记录**：
  - 每次求解记录：用途、状态、可行解目标、对偶界、gap、节点数、变量数、墙钟时间和进程 CPU 时间。
  - 每次决策记录：情景生成、建模求解、平局处理和核对的时间。
  - 运行环境记录：硬件、并行设置和软件版本。
  - 不以求解次数代替时间。

### 小规模开发试跑（本版唯一的运行）

- **路径**：新开发种子 72001 下的 `volatile` 和 `upshift` 两条路径。预算只够两条完整路径，先看机制最可能出现的两类过程；这个选择有利于发现机制，因此不代表 4 类过程的平均。`stable` 和 `downshift` 留给扩大开发。
- **拟合数据**：拟合种子 71001、71011、71023、71039 的 16 条路径，只用来估计 v_fit，不运行任何策略。
- **采样种子**：一个，913337；置换种子 917351。
- **运行顺序**：两条路径的 B1 轨迹与逐状态审计、LB → B4 校准 → M1、M2*、B3、B4 轨迹。
- **预算**：
  - 最多 300 次求解或 60 分钟墙钟时间，先到者为准；审计和重试都计入。
  - 剩余时间不足 30 秒时不再开始新的求解。
  - 第 11 期没有可到货的发货，新方法直接记为零动作、不求解；原 B1 代码照常求解并计数。
- **失败处理**：
  - 超时或非最优**记为失败**，保存状态、可行解、界和 gap，不重试。
  - 失败的轨迹在该期停止，标为不完整、没有实际成本；失败的审计状态记为“未判定”。
  - 预算用完时，未完成的项目逐项列出，不静默丢弃。
- **判读**（只是开发诊断，不判定假设）：
  - 审计中出现实质不同的动作，即“存在值得继续检验的机制信号”。
  - 全部为平局或相同，即“试跑未见机制信号”。
  - 审计因失败或预算未完成，即“无法判定”。
  - 两条路径的实际成本只作描述。
  - 任何结果都不自动扩大预算、不训练 BC/PPO、不改研究目标。

### 正确性测试（试跑前必须通过）

[`tests/test_rolling_tree.py`](../tests/test_rolling_tree.py) 覆盖：

- 手算台账与原环境的事件顺序一致；
- 观测历史相同则决策相同，分支编号不能区分观测相同的历史；
- 打乱配对保持每个 SKU 的边际情景树、约束与信息条件；
- 开环问题对配对不变；
- b=1 的树退化为开环；
- 小实例上 MILP 与穷举一致，平局稳健选解与穷举一致；
- 碳按路径累计；
- 改变未来需求不改变当期及以前的决策；
- 策略输入中不含隐藏字段；
- 独立台账重放，并能发现篡改。

### 产物与复现

- 试跑证据：`benchmark_results/rolling_tree_pilot/`，含配置、任务、逐次求解记录、逐状态审计、轨迹、结果、运行环境和 SHA256 清单。
- `python -m semiconductor_logistics rolling-tree pilot --output <空目录>` 在空目录重跑试跑。它会再次消耗求解预算。
- `python -m semiconductor_logistics rolling-tree verify` 不求解，只重新生成任务与情景树，独立复算台账和汇总，并核对哈希。

### 版本记录

| 版本 | 内容 |
|---|---|
| v1（开发版） | 修正问题表述（执行层已重规划；单次优化缺少追索）；确定 B3、M2* 的平局规则与 B4；第一版共同冲击跨期独立；限定为最小实现、测试与有预算的试跑 |

## English

### Version and scope

Development version v1. This version covers a minimal implementation in an independent module, correctness tests and one bounded small development pilot only. A full development batch and the formal confirmation experiment are **out of scope**; no confirmation data are generated, inspected or run. Confirmation sample size, analysis and stopping rules will be fixed and frozen separately, using the variability and computation measured during development. Any design change during development adds a version with reasons; this version is not rewritten. Configuration: [`rolling_tree/config.json`](../rolling_tree/config.json).

### Question

The existing rolling studies ([baseline](rolling_inventory_protocol.md), [distribution confirmation](rolling_distribution_results.md), [finite recourse](rolling_recourse_results.md)) have two decision layers, and they must be kept apart:

- **Execution layer**: scenario MPC replans every period from the latest observation and executes only the first action. The system already adapts to new demand; this study does **not** introduce adaptation for the first time.
- **Inside one optimization**: [`rolling_inventory/planning.py`](../rolling_inventory/planning.py) shares one future dispatch plan across all scenarios, with no recourse that branches on future observable history. The objective is separable by SKU, so cross-SKU pairing leaves the optimum unchanged (768 audits, maximum deviation 1.14×10⁻¹³).

The study asks whether, within the existing rolling execution, explicitly modeling **future adaptivity** (a nonanticipative scenario tree) and **cross-SKU dependence** (same-period common shocks) inside one optimization changes first-period dispatch beyond ties and improves realized cost, service and emissions, and at what online computation cost.

### Prior findings retained

- 7-scenario MPC costs less than base-stock but emits more; moving from 7 to 21 scenarios gives a small gain with unstable direction.
- Distribution confirmation: residual negative binomial did not lower cost, and the teacher screen failed.
- Finite recourse: apparent gains in the 36 constructed models were all explained by optimal ties, and cross-model regret was zero.
- There is no validated rolling teacher; the deployment deadline and acceptable loss are undefined; BC/PPO is not trained.

The prior expectation is a zero or small effect.

### Environment, information and event order

- **Environment**: [`rolling_inventory/environment.py`](../rolling_inventory/environment.py) and its configuration are reused without modification. 12 periods, 3 SKUs and 2 routes; route capacity is shared by mass and resets every period; the cumulative carbon budget is 132; final backlog carries an extra cost; there is no salvage value; orders arriving after the horizon are forbidden.
- **Order within each period**: arrivals → clearing old backlog → observation → dispatch (integrality, capacity, remaining carbon and arrival deadline are checked before any state change) → current demand revealed → costs → carbon deducted and history appended.
- **Visible to policies**: period, public parameters, stock, backlog, pipeline, remaining carbon, past demand and the original EWMA forecast.
- **Hidden from policies**: common factors, process labels, task IDs, demand seeds, and current and future demand.
- Clairvoyant demand is used only for the offline bound, never as a teacher.

### Planning model

- **Window and allowance**: window h=min(6, 12−t); carbon allowance is remaining budget×h/(12−t); solver settings match the original MPC (HiGHS, `mip_rel_gap=0`, 30 s per solve).
- **Common-shock scenarios**:
  - Means come from the original EWMA forecast μ.
  - Each future period has one multiplicative factor F shared by all SKUs and independent over time; log F~N(−s²/2, s²) with s²=ln(1+v).
  - v is the mean product r_i r_j of same-period standardized residuals across SKUs: v_fit is estimated on fitting paths, then combined with this path's observed products using τ=48 pseudo-observations and clipped to [0, 2].
  - Persistent regimes are not modeled in this version. The model family was chosen with knowledge of the synthetic generator, so conclusions show a match to the synthetic structure only.
- **Tree (D=2, b=3, m=3; 27 leaf paths)**:
  - The first two periods branch on three equal-probability quantiles of F (normalized to mean 1), with Poisson demand per SKU; each depth-2 node then has three continuation paths.
  - Random numbers depend only on (sampler seed, t, node).
- **Nonanticipativity**: stage-u decision variables are indexed by the **observed demand vectors** of window periods 0…min(u, 2)−1. Scenarios with identical observed history necessarily share decisions, even when they come from different branch indices. Decisions after depth 2 are shared across the node's continuation paths; this is a restriction, not anticipation.
- **Constraints and objective**: one capacity constraint per node and route; carbon is accumulated along each leaf path, never summed across exclusive branches; the objective is the expected cost over equally weighted leaves.
- **Shuffled pairing (M2)**: on the same tree, SKUs 2 and 3 have their subtrees permuted at every level with a fixed seed (an automorphism of the index tree). Each SKU's marginal tree and its multiset of complete paths stay identical; only cross-SKU pairing changes. Constraints, window, allowance and solver settings are unchanged.

### Methods

| Code | Method | Notes |
|---|---|---|
| B0 | Base-stock, z=1 | Original rule |
| B1 | Original EWMA+Poisson open-loop 7-scenario MPC | Original code, original sampler seed 901337 |
| B2 | Open-loop MPC on the same 27 leaves as M1 | Solved in audits only |
| B3 | Tie-robust B2 | Solve B2's optimum, then choose the first action by M1's objective subject to B2 objective ≤ optimum+tolerance |
| M1 | Tree, common-shock pairing | Main method |
| M2 | Tree, shuffled pairing | Solved in audits only |
| M2* | Tie-robust M2 | Solve M2's optimum, then choose the first action by M1's objective subject to M2 objective ≤ optimum+tolerance |
| B4 | Equal-time open-loop MPC | S′ independent common-shock paths; S′ is calibrated on the first three pilot audit states so that online time is closest to M1 |
| LB | Full-horizon clairvoyant MILP | Bound only |

- **B3 and M2* are conservative diagnostic designs**: they borrow M1's objective but choose only among their own model's tied optima. M1−M2* therefore counts only materially different actions, and M1−B3 counts only recourse effects beyond ties.
- These two methods use planning scenarios only, never realized future demand or confirmation results. Their extra solves count toward their online time and the budget.
- **Three comparisons are reported separately**: dependence value (M1−M2*), recourse value (M1−B3) and computation budget (M1−B4, plus the comparison with B1). They are not conflated.

### Action audit and tolerances

- On the same states visited by the B1 trajectory, M1, M2, M2*, B2 and B3 are all solved.
- If M2*'s first action is worse than M1's optimum under M1's objective by more than the numerical tolerance, every M2-optimal action is nonoptimal under M1, and the state is recorded as **materially different**; otherwise it is a tie or identical. B2/B3 are classified the same way.
- **Numerical tolerance**: relative 1e-6 plus absolute 1e-7, used only to separate ties within solver precision. It is **not** a practical equivalence margin.
- **A 2% cost reduction** is only this project's practical-benefit reference, not a company standard.
- **Guardrails**: fill rate may drop by at most 0.005 absolute (0.5 percentage points); emissions may rise by at most 2% relative; the original hard carbon constraint is never relaxed.
- Cost, service and emissions are each reported with point estimates, intervals (when the sample allows) and guardrails.

### Metrics and computation records

- **Realized metrics**: total cost (freight, carbon price, holding, per-period backlog and final backlog), immediate fill rate, backlog unit-periods, emissions, final stock and backlog, and first-action audit counts.
- **Computation records**:
  - Per solve: purpose, status, incumbent objective, dual bound, gap, node count, variable count, wall time and process CPU time.
  - Per decision: time for scenario generation, model building and solving, tie handling and checks.
  - Run environment: hardware, parallel setting and software versions.
  - Solve counts never stand in for time.

### Small development pilot (the only run in this version)

- **Paths**: the `volatile` and `upshift` paths for new development seed 72001. The budget covers two complete paths, so the pilot looks first at the two processes where the mechanism is most likely. This choice favors detecting the mechanism and does not represent the four-process average. `stable` and `downshift` are left for an expanded development batch.
- **Fitting data**: 16 paths from fitting seeds 71001, 71011, 71023 and 71039, used only to estimate v_fit; no policy runs on them.
- **Sampler seed**: one, 913337; permutation seed 917351.
- **Order**: B1 trajectories with per-state audits on both paths, then LB → B4 calibration → M1, M2*, B3 and B4 trajectories.
- **Budget**:
  - At most 300 solves or 60 minutes of wall time, whichever comes first; audits and retries count.
  - No new solve starts with less than 30 seconds of wall time remaining.
  - Period 11 admits no arriving dispatch: new methods record a zero action without solving, while the original B1 code solves and is counted.
- **Failure handling**:
  - Timeouts and nonoptimal results **count as failures**. Status, incumbent, bound and gap are saved, and there is no retry.
  - A failed trajectory stops at that period and is marked incomplete with no realized cost; a failed audit state is recorded as unresolved.
  - If the budget runs out, every unfinished item is listed; nothing is dropped silently.
- **Reading** (a development diagnostic, not a hypothesis test):
  - Materially different actions in the audit mean "a mechanism signal worth further testing".
  - Only ties or identical actions mean "no mechanism signal in the pilot".
  - Audits left incomplete by failures or budget mean "inconclusive".
  - Realized costs on two paths are descriptive only.
  - No outcome expands the budget automatically, trains BC/PPO or changes the research goal.

### Correctness tests (must pass before the pilot)

[`tests/test_rolling_tree.py`](../tests/test_rolling_tree.py) covers:

- a hand-calculated ledger matching the original event order;
- identical observed histories receiving identical decisions, with branch indices unable to separate observationally identical histories;
- shuffled pairing preserving each SKU's marginal tree, constraints and information;
- open-loop invariance to pairing;
- reduction of b=1 trees to open loop;
- MILP versus enumeration, and tie-robust selection versus enumeration, on small instances;
- pathwise carbon accumulation;
- current and earlier decisions unchanged when future demand changes;
- no hidden fields in policy inputs;
- independent ledger replay with tamper detection.

### Artifacts and reproduction

- Pilot evidence: `benchmark_results/rolling_tree_pilot/`, containing configuration, tasks, per-solve records, per-state audits, trajectories, outcomes, run environment and a SHA256 manifest.
- `python -m semiconductor_logistics rolling-tree pilot --output <empty directory>` reruns the pilot in an empty directory and consumes solve budget again.
- `python -m semiconductor_logistics rolling-tree verify` does not solve: it regenerates tasks and trees, recomputes ledgers and summaries independently, and checks hashes.

### Version history

| Version | Content |
|---|---|
| v1 (development) | Corrected question (execution already replans; one optimization lacks recourse); tie rules for B3 and M2*, and B4; time-independent common shocks in this version; limited to minimal implementation, tests and a bounded pilot |
