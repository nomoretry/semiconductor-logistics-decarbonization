# M1 首期动作稳定性协议 / M1 first-action stability protocol

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

### 问题与证据

在 T3 的多 SKU 滚动库存问题中，各 SKU 争用运力和累计碳预算。这里先检验 M1 在同一观测下的首期发运量是否对情景树近似稳定。全部证据限于既有合成开发观测。本轮仅求解 M1，范围不含相关性价值、成本比较、其他方法、轨迹重跑、新需求路径和确认集。

[v2 试跑](rolling_tree_pilot_v2.md)选定先验强度 τ=192、前两层分支数 9 和 3、每个第二层节点 1 条延续路径。其[审计记录](../benchmark_results/rolling_tree_v2_pilot/audit.jsonl)中，同一观测下三个采样种子两两比较有 62/132 对首期动作不同。[追加的探索检查](../benchmark_results/rolling_tree_v2_continuation_check/states.jsonl)中，由 1 条增至 3 条有 66/132 对不同。

### 观测与模型

- 从 v2 [轨迹证据](../benchmark_results/rolling_tree_v2_pilot/traces.jsonl)的 B1 行取 `observation`，与审计记录按路径、期次和规划器种子对齐。仅用 72019 下的 stable、volatile、upshift、downshift 四条路径，每条 11 个非强制期次（`t=0…10`），共 44 个观测。每个观测与 924601、924611、924617 组合，得到既有的 132 个审计状态。
- 沿用[冻结配置](../benchmark_results/rolling_tree_v2_pilot/config.json)与[拟合方差](../benchmark_results/rolling_tree_v2_pilot/summary.json)，以及 v2 [抽样](../rolling_tree/scenarios.py)和 [MILP](../rolling_tree/planning.py)。同一观测与种子下，前两层需求抽样保持相同。延续路径数改变时，该层以下的分层抽样随之改变。决策按前两期可观测需求历史共享，同一历史下各条延续路径共享后续发运决策。
- 用 B1 证据中的路径顺序，其下按 `t`、冻结配置中的种子顺序、延续档位从小到大顺序求解。正式档位为 1、3、L，对应 27、81、27×L 条叶路径。每个审计状态在每档求解一次，共 396 次。

### 计时选择与预算

- 试算观测在求解前固定。每条路径的首个非强制期次（`t=0`）各配三个种子，共 12 个审计状态。每个状态各运行 1、3、6、9、12 档，最多 60 次，单独记录。1、3 档供正式运行墙钟估算。
- 在线墙钟含条件方差计算、情景生成、模型构建、求解和求解器解的物理重放。p95 用 12 次尝试的在线秒数线性插值计算，包含失败尝试的实际用时。只看时间，从 6、9、12 中选 p95 ≤ 10 秒的最大档 L。若三档均超过 10 秒，停止。
- 正式运行墙钟估计为 `132 × (p95_1 + p95_3 + p95_L) + 45 秒`。该估计以固定试算状态为依据，其他期次可能用时更长。估计超过 3,600 秒则停止，报告估计和缩小方案。
- 单进程顺序运行，每次 MILP 限 30 秒，`mip_rel_gap=0`。保留非最优/超时的求解状态、MIP gap（求解器提供时）和时间。每个组合只尝试一次。正式运行最多 396 次、墙钟最多 3,600 秒。剩余不足 45 秒时停止发起求解，为单次求解与前后处理留时。每次尝试后检查累计失败数占已尝试数的比例，严格超过 5% 时立即停止。预算或失败门槛导致正式运行未完成时保留已完成的记录，不出稳定性结论。

### 比较与判据

- 动作是三个 SKU × 慢线、快线的整数发运矩阵。任意单元的件数不同即计为一次首期动作改变。比较同一观测及种子的 1→3、3→L、1→L。在每个档位内，对同一观测的三个种子两两比较，作为采样噪声参照。每项计划比较 132 对，改变率分母为两侧均有最优动作的对数，并同时报告缺失对数。这里比较求解器返回的动作，等价最优动作也可能导致改变。
- **稳定**要求 3→L 和 L 档采样噪声的改变率均 ≤10%。正式运行完成但任一改变率超过 10% 即为**不稳定**。按期次和需求过程报告改变数、可比较对数与改变率，按 SKU×路线报告涉及的改变对数与绝对件数差之和。单对可同时改变多个单元。四条开发路径上的描述性统计不提供置信区间。
- [证据目录](../benchmark_results/rolling_tree_stability/)保存配置和来源校验值、逐次试算及正式记录、运行环境、汇总和 SHA256 清单。复跑命令为 `python -m rolling_tree stability3 --output <空目录>`。离线复算为 `python -m rolling_tree verify3`，核对清单、重建情景树并从逐次记录复算汇总。

## English

### Question and evidence

In the T3 rolling inventory problem, multiple SKUs compete for transport capacity and a cumulative carbon budget. This study checks whether M1's first-period shipment quantities are stable across scenario-tree approximations of the same observation. All evidence comes from existing synthetic development observations. The study solves M1 only. Its scope excludes the value of demand dependence, cost comparisons, other methods, trajectory reruns, new demand paths and the confirmation set.

The [v2 pilot](rolling_tree_pilot_v2.md) selected prior strength τ=192, branching of 9 and 3 at the first two levels, and one continuation path per depth-2 node. In its [audit records](../benchmark_results/rolling_tree_v2_pilot/audit.jsonl), first actions differ in 62/132 pairwise comparisons of three sampler seeds at the same observation. In the [exploratory follow-up](../benchmark_results/rolling_tree_v2_continuation_check/states.jsonl), they differ in 66/132 pairs when the continuation count rises from one to three.

### Observations and model

- Take `observation` from the B1 rows in the v2 [trajectory evidence](../benchmark_results/rolling_tree_v2_pilot/traces.jsonl) and align them with the audit by path, period and planner seed. Use only the stable, volatile, upshift and downshift paths under seed 72019. Each contributes 11 non-forced periods (`t=0…10`), giving 44 observations. Pair each with 924601, 924611 and 924617 to obtain the 132 existing audit states.
- Reuse the [frozen configuration](../benchmark_results/rolling_tree_v2_pilot/config.json), [fitted variance](../benchmark_results/rolling_tree_v2_pilot/summary.json), v2 [sampling](../rolling_tree/scenarios.py) and [MILP](../rolling_tree/planning.py). At a fixed observation and seed the first two demand draws are the same across tiers. The stratified draws below that depth change with the continuation count. Decisions are shared by observed demand history from the first two periods. Continuations with the same history share later shipment decisions.
- Follow the B1 path order in the evidence and, within each path, increasing `t`, the seed order from the frozen configuration, and increasing continuation count. The formal tiers are 1, 3 and L, giving 27, 81 and 27×L leaf paths. Solve each audit state once per tier, for 396 solves.

### Timing selection and budget

- Fix the timing observations before solving. Use the first non-forced period (`t=0`) of each path with each of the three seeds, for 12 audit states. Run each state at tiers 1, 3, 6, 9 and 12, for at most 60 attempts in a separate ledger. Tiers 1 and 3 inform the formal wall-time estimate.
- Online wall time includes conditioning the variance, scenario generation, model construction, solving and physical replay of the solver's solution. Compute p95 in seconds by linear interpolation of the 12 attempt times, including actual times for failed attempts. Use timing alone to select the largest tier L among 6, 9 and 12 with p95 ≤ 10 seconds. Stop if all three exceed 10 seconds.
- Estimate formal wall time as `132 × (p95_1 + p95_3 + p95_L) + 45 seconds`. The estimate uses the specified timing states. Other periods may take longer. Stop if the estimate exceeds 3,600 seconds and report the estimate and a reduced scope.
- Run in one sequential process with a 30-second MILP limit and `mip_rel_gap=0`. Retain solver status, MIP gap when available, and timing for nonoptimal or timed-out attempts. Make one attempt per combination. The formal run is capped at 396 attempts and 3,600 wall seconds. Stop starting solves when less than 45 seconds remain, reserving time for one solve and its surrounding work. After each attempt, stop immediately if cumulative failures strictly exceed 5% of attempts so far. If the budget or failure rule interrupts the formal run, retain the recorded attempts and leave stability unassessed.

### Comparisons and decision rule

- An action is an integer shipment matrix for three SKUs and the slow and fast routes. A quantity difference in any cell counts as one first-action change. Compare 1→3, 3→L and 1→L at the same observation and seed. Within each tier, compare the three seeds pairwise at the same observation to measure sampling noise. Each contrast has 132 planned pairs. Divide changes by the number with an optimal action on both sides and report the missing pairs as well. Comparisons use the returned actions, so alternative optima can contribute changes.
- **Stable** requires both the 3→L change rate and the L-tier seed comparison rate to be ≤10%. A completed formal run that exceeds either limit is **unstable**. Report changes, comparable pairs and rates by period and demand process. For each SKU×route cell report the number of pairs changing it and the sum of absolute unit differences. A single pair can change multiple cells. The four development paths support descriptive statistics without confidence intervals.
- The [evidence directory](../benchmark_results/rolling_tree_stability/) stores the configuration and source checksums, timing and formal attempt records, runtime environment, summary and SHA256 manifest. Replay with `python -m rolling_tree stability3 --output <empty directory>`. Verify offline with `python -m rolling_tree verify3`, which checks hashes, regenerates scenario trees and recomputes the summary from the attempt records.
