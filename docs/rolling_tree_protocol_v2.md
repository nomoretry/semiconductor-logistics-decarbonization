# 历史条件情景树：开发协议 v2 / History-conditioned scenario trees: development protocol v2

本文提供中英文版本，中文在前，英文在后。本协议在 v2 选参和第二次试跑**之前**提交；[v1 协议](rolling_tree_protocol.md)和[第一次试跑](rolling_tree_pilot.md)保持原样。
This document provides Chinese first and English second. It is committed **before** v2 tuning and the second pilot; the [v1 protocol](rolling_tree_protocol.md) and the [first pilot](rolling_tree_pilot.md) stay unchanged.

## 中文

### 为什么要 v2

问题不变：多个 SKU 同期出现需求冲击、争用共享运力和累计碳预算时，规划器掌握跨 SKU 的需求关联（共同冲击），是否会改变本期的补货量、运输方式或运力分配，并在没参与选参的需求路径上改善成本、交付或排放。

第一次试跑发现，情景树第一期只有 2–3 个不同的需求向量，第一期样本均值与预测之差平均 1.70，B4 为 0.59，B1 为 1.21。树方法（M1、M2\*、B3）落后等时间开环 B4 13%–54%，主要可由这一采样误差解释。在这种设计下比较“相关性”和“追索”，测到的主要是情景集的质量差别。v2 只修改规划器自己的情景抽样，使树与开环对照在第一期的样本质量可比。

### 改了什么

1. **逐层分支数**：第一层分支数与开环对照的情景数相当，候选形状见“选参”。
2. **节点内分层抽样**：同一节点的子节点共用共同因子的等概率分位点（同 v1）；每个 SKU 的 Poisson 部分对每个子节点取一个分层均匀数（拉丁超立方），各 SKU 独立。因此共同因子是跨 SKU 的唯一联系。延续路径在每期对共同因子和 Poisson 部分都跨路径分层。
3. **B4 用同样的分层抽样**：否则树与开环的比较又会混进采样方法的差别。
4. **新增对现行滚动基线的审计（anchor）**：在 B1 的状态上，先求出 B1 自身情景下的全部最优首期动作中、在 M1 目标下最好的一个（B1\*），再与 M1 的最优值比较。“实质不同”表示排除 B1 自身的并列方案以后，B1 的动作在 M1 目标下仍非最优。
5. **只换一个决策的反事实**：在 B1 的实际轨迹上，对每个比较的第一个“实质不同”状态，只把那一期的动作换成 M1 的，或换成对照的最好平局动作（M2\* 或 B1\*），其余各期照常由 B1 重新规划，再在同一条真实需求路径上计算成本、交付和排放。这样能给出“这一笔决定改了以后值多少”。

不变的部分：物理环境、事件顺序、可见信息、MILP 写法、平局稳健的定义（M2\*、B3）、容差（相对 1e-6 加绝对 1e-7）、求解器设置（`mip_rel_gap=0`，单次 30 秒）、拟合种子与拟合方差、B1 的原代码与原情景种子。

### 选参（只用选参划分，不看任何成本）

- **先验强度 τ**：候选 12、48、192。在 16 条选参路径的每一期（t≥1）上，计算一步 3-SKU 联合预测的 energy score（500 个样本，种子 977201），取均值最低者；同分取列表首项。
- **树形**：按以下顺序取第一个满足全部条件的：(9, 3) 加 3 条延续路径（81 叶）→ (9, 3) 加 1 条（27 叶）→ (7, 3) 加 1 条（21 叶）。
  - 测量状态：选参种子 71101 的 4 类过程，在 B1 轨迹上各取前 3 个非强制状态，共 12 个。
  - 条件：0 次失败；第一期样本误差的均值不高于 B1 自身 7 个情景；M1 在线时间 p95 ≤ 2 秒；平局稳健 M2\* 的在线时间 p95 ≤ 10 秒。
  - 都不满足就停止，不降低精度硬跑。
- **B4 情景数 S′**：候选 27、54、108、216，取平均在线时间最接近 M1 的一个。

### 第二次开发试跑

- **路径**：开发种子 72019 的 4 类过程（stable、volatile、upshift、downshift），都是新路径；第一次试跑用过的 72001 不再使用。
- **规划器采样种子**：924601、924611、924617。B0、B1、LB 不依赖采样种子，每条路径运行一次。
- **运行顺序**：
  1. B0；
  2. B1 轨迹；
  3. 每个采样种子在 B1 的全部状态上审计 dependence（M1 对 M2\*）、recourse（M1 对 B3）、anchor（M1 对 B1\*）；
  4. 只换一个决策的反事实；
  5. LB；
  6. 每个采样种子的 M1、M2\*、B3、B4 完整轨迹。
- **预算**：选参 ≤600 次求解或 30 分钟；试跑 ≤3,500 次求解或 90 分钟；单次 30 秒；求解失败和超时如实记录，不重试。
- **不做的事**：不生成、不查看、不运行确认数据；不训练学习策略；不调用 API 或 LLM。

### 读法（事先写定）

- **第一笔实际改变的决策**：对每条路径、每个采样种子、每种比较，报告最早的“实质不同”状态。内容包括：期次；M1 与对照最好平局动作逐 SKU、逐路线的件数差；超额及其占 M1 窗口目标的比例；当时的历史条件共同因子方差。
- **这笔决策值多少**：只换一个决策的反事实，与对照动作的反事实比较，报告实际总成本、即时满足率和排放的差。这是单条真实路径上的一次实现，只作描述。
- **策略层面**：报告 M1−M2\*、M1−B3、M1−B4、M1−B1、B4−B1 的成本差均值、每个采样种子的方向、更好/更差/相同的个数，以及满足率与排放的护栏。12 个“路径×种子”只来自 4 条独立路径，**不给区间，也不判定假设**。
- **扩大到 32 条开发路径的门槛**（全部满足才考虑，且另需确认预算）：
  - 树的第一期样本误差均值不高于 B4 加 0.1，也不高于 B1；
  - M1−B4 的平均相对成本差在 ±5% 以内，即不再由情景集质量主导；
  - M1−M2\* 在 3 个采样种子下方向一致。
- 不满足门槛时如实报告，指出是哪项约束或哪种已有策略解释了结果。

## English

### Why v2

The question is unchanged: when several SKUs face a demand shock in the same period and compete for shared transport capacity and a cumulative carbon budget, does a planner that knows the cross-SKU dependence (a common shock) change this period's replenishment quantity, transport mode or capacity allocation, and does that improve cost, delivery or emissions on demand paths not used for tuning?

The first pilot found that the tree's first period had only 2–3 distinct demand vectors. Its first-period sample mean missed the forecast by 1.70 on average, against 0.59 for B4 and 1.21 for B1. Tree methods (M1, M2\*, B3) trailed the equal-time open-loop B4 by 13%–54%, mostly explained by that sampling error. Comparisons of dependence and recourse under that design would mostly measure scenario-set quality. v2 changes only the planner's own scenario sampling, so that trees and open-loop comparators have comparable first-period sample quality.

### Changes

1. **Branching per depth**: the first level branches about as widely as the open-loop comparator has scenarios; the candidate shapes are listed under tuning.
2. **Stratified draws within a node**: children of one node share the common factor's equal-probability quantiles (as in v1). Each SKU's Poisson component takes one stratified uniform per child (Latin hypercube), independently across SKUs, so the common factor is the only cross-SKU link. Continuation paths stratify both the factor and the Poisson draws across paths, period by period.
3. **B4 uses the same stratified sampling**, so that tree against open loop is not confounded by the sampling method again.
4. **A new audit of the rolling baseline (anchor)**: on B1's states, B1\* is the action that, among all first actions optimal under B1's own scenarios, is best under M1's objective. It is compared with M1's optimum. "Material" means that even after excluding B1's own ties, B1's action is suboptimal under M1.
5. **One-decision counterfactuals**: on B1's actual trajectory, at the first material state of each comparison, only that period's action is replaced, by M1's or by the comparator's best tie (M2\* or B1\*). B1 re-plans every other period as usual, and cost, delivery and emissions are computed on the same real demand path. This prices "what changing this one decision is worth".

Unchanged: physical environment, event order, visible information, MILP formulation, the tie-robust definitions (M2\*, B3), tolerances (relative 1e-6 plus absolute 1e-7), solver settings (`mip_rel_gap=0`, 30 s per solve), fitting seeds and fitted variance, and B1's original code and scenario seed.

### Tuning (tuning split only; no cost is consulted)

- **Prior strength τ**: candidates 12, 48 and 192. Over every period t≥1 of the 16 tuning paths, compute the one-step 3-SKU joint energy score (500 samples, seed 977201); take the lowest mean, first in list order on ties.
- **Tree shape**: the first of (9, 3) with 3 continuation paths (81 leaves) → (9, 3) with 1 (27 leaves) → (7, 3) with 1 (21 leaves) that meets every condition.
  - Measured on the first three non-forced B1 states of each process of tuning seed 71101, 12 states in all.
  - Conditions: zero failures; mean first-period error not above B1's own seven scenarios; M1 online p95 ≤ 2 s; tie-robust M2\* online p95 ≤ 10 s.
  - If none qualifies, stop rather than loosen accuracy.
- **B4 scenario count S′**: candidates 27, 54, 108 and 216; the one whose mean online time is closest to M1's.

### Second development pilot

- **Paths**: development seed 72019 under all four processes (stable, volatile, upshift, downshift), all new; seed 72001 of the first pilot is not reused.
- **Planner sampling seeds**: 924601, 924611 and 924617. B0, B1 and LB do not use them and run once per path.
- **Order**:
  1. B0;
  2. the B1 trajectory;
  3. for each sampling seed, audits on all of B1's states of dependence (M1 against M2\*), recourse (M1 against B3) and anchor (M1 against B1\*);
  4. one-decision counterfactuals;
  5. LB;
  6. full M1, M2\*, B3 and B4 trajectories for each sampling seed.
- **Budget**: tuning ≤600 solves or 30 minutes; pilot ≤3,500 solves or 90 minutes; 30 s per solve; failures and timeouts are recorded and never retried.
- **Not done**: no confirmation data generated, viewed or run; no learned policy; no API or LLM call.

### Readouts (fixed in advance)

- **The first decision that actually changes**: for each path, sampling seed and comparison, the earliest material state. Reported: its period; the per-SKU, per-route units by which M1 differs from the comparator's best tie; the excess and its share of M1's window objective; and the history-conditioned common-factor variance at that time.
- **What that decision is worth**: the one-decision counterfactual against the comparator's counterfactual, as differences in realized total cost, immediate fill rate and emissions. This is one realization on one real path and is descriptive only.
- **Policies**: mean cost differences M1−M2\*, M1−B3, M1−B4, M1−B1 and B4−B1, the direction under each sampling seed, counts of better, worse and same, and the fill and emission guardrails. The 12 path×seed cases come from 4 independent paths: **no intervals and no hypothesis decision**.
- **Gate for the 32-path development batch** (all must hold, and the budget needs separate agreement):
  - the tree's mean first-period error is no higher than B4's plus 0.1 and no higher than B1's;
  - the mean relative cost difference M1−B4 is within ±5%, so it is no longer dominated by scenario quality;
  - M1−M2\* has the same direction under all three sampling seeds.
- If the gate fails, the result is reported as it is, naming the constraint or existing policy that explains it.
