# M1 首期动作的实质性与三树选择 / M1 first-action materiality and three-tree selection

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

### 问题与输入

[单树检查](rolling_tree_stability.md)中，3→12 档有 44/132 对首期动作不同，12 档换种子有 53/132 对不同。本实验先判断不同动作在相同规划问题中是否等价，再检验三树选择能否降低首期动作改变率。研究范围是四条既有合成开发路径的 44 个 B1 非强制观测。仅比较情景树内的目标值用于选择动作和判定实质性，研究范围不含轨迹、实现成本、需求相关性的价值及确认集。

重用 [v2](rolling_tree_pilot_v2.md) 的条件方差、τ=192、9×3 分支、原 MILP、逐次 30 秒上限与相对 MIP gap 0。动作按 SKU×路线整数发运矩阵逐项比较。3 和 12 档分别为 81 和 324 条抽样叶路径。甲组固定为 924601、924611、924617，乙组固定为 924623、924629、924631。输入由[冻结的单树逐状态证据](../benchmark_results/rolling_tree_stability/states.jsonl)和 [B1 观测](../benchmark_results/rolling_tree_v2_pilot/traces.jsonl)确定。

### A：单树改变的实质性

- 使用原记录的首期动作和对应情景树，仅审计 3→12 档改变的 44 对和 12 档跨种子改变的 53 对。每对在两个方向上固定一侧的动作，求另一侧树下的最优值。单树档案未保存目标值，在同一树上重新求无首期固定约束的最优值作为参照。同一观测中相同的树和固定条件仅计算一次。
- 方向超额为固定动作目标减目标树的最优值。容差沿用 v2，即 `1e-6 × max(1, |参照目标|) + 1e-7`。3→12 以 12 档方向超额严格超过容差为实质，逆向只报参照。种子对至少一个方向超限即为实质。缺失的方向及无法判定的配对单列。
- 按方向报超额的中位数、p90、最大值及其相对参照目标的比例，同档种子按列表先后确定两个方向。参照为零时相对比例留空。额外统计相对超额严格超过 0.5% 的次数。该描述性阈值不参与判定。

### B：三树选择

- 各观测分别运行甲组 3 档、甲组 12 档、乙组 3 档、乙组 12 档，共 176 次决策。组内独立求解三棵树，对不同首期动作去重，并在其余树中固定该动作求值。同一动作已是某棵树的最优解时复用该值。选择在三棵树上平均目标最低的动作，均值相同取首次产生该动作的种子在列表中靠前者。缺少任一必需值时本组该档决策缺失。
- 在同一观测下比较甲组 12 档→乙组 12 档和甲组 3 档→甲组 12 档。各对任一数量不同即记为改变。两个原始改变率均 ≤10% 才判为稳定。分母为两侧均有动作的观测数，并报告缺失数。无可比对或全程中断时不下结论。
- 对改变的动作，在目标组三棵树中求源动作的平均目标，减目标组选中动作的平均目标。沿用 A 的容差公式，参照值为目标组的平均目标。只计实质改变的比率以有判定的观测为分母，动作相同的观测计为未改变。该比率作描述，有符号超额可为负。
- 在线用时覆盖每次三树决策的建树、求解、物理重放和组内固定动作评估。比较用的跨组和跨档求解计入正式总墙钟。按档报告在线均值、p95，并与保存的单树时间比较。

### 试算、预算与复算

- 四个需求过程各取零基期次 `t=0,5,6`，共 12 个固定观测。三期均有完整六期规划窗口，既有单树结果在这些期次记录到动作改变。试算 A、B 使用与正式阶段相同的计算，保存试算原始记录。按观测计入全部相关计算，包括 B 的比较审计。
- 用 `44 × (A 的单观测用时 p95 + B 的单观测用时 p95) + 45 秒` 估计正式 A+B 墙钟。分位数采用线性插值。估计超过 5,400 秒时结束在试算阶段。该估计只用时间。所有种子和档位预先固定。
- 单进程顺序执行，整理观测顺序沿用冻结的 B1 路径顺序与期次顺序。正式 A 后接 B，两部分共享 5,400 秒预算，余量不足 45 秒不发起新的求解。正式期间累计失败/已尝试求解严格超过 5% 时结束，保留已取得的证据。每阶段相同计算只尝试一次。计划上界 A 为 388 次，B 为 1,848 次，去重后实测可能更少。
- `python -m rolling_tree consensus4 --output <空目录>` 运行试算及通过时间门槛后的 A、B。默认在 `benchmark_results` 下生成 `rolling_tree_materiality` 与 `rolling_tree_consensus`。用 `python -m rolling_tree verify4` 离线核对两个证据包的清单、重建记录的情景树，并按原始记录复算判定、分布和汇总。

## English

### Question and inputs

The [single-tree check](rolling_tree_stability.md) found first-action differences in 44/132 pairs from tier 3 to tier 12 and 53/132 seed pairs at tier 12. This experiment checks equivalence within the same planning problem, then tests whether three-tree selection reduces first-action changes. It uses the 44 non-forced B1 observations of four existing synthetic development paths. Objectives inside the trees are used for action selection and materiality. The scope excludes rollouts, realized costs, the value of dependence and confirmation data.

Reuse [v2](rolling_tree_pilot_v2.md) conditional variance, τ=192, 9×3 branching, the original MILP, a 30-second solve limit and relative MIP gap 0. Compare the integer shipment matrices by SKU and route. Tiers 3 and 12 have 81 and 324 sampled leaf paths, respectively. Seed group A is 924601, 924611, 924617 and group B is 924623, 924629, 924631. Use the [frozen single-tree records](../benchmark_results/rolling_tree_stability/states.jsonl) and [B1 observations](../benchmark_results/rolling_tree_v2_pilot/traces.jsonl) as inputs.

### A. Materiality of single-tree changes

- Use the archived first actions and corresponding trees. Audit the 44 changed tier pairs from 3 to 12 and the 53 changed seed pairs at tier 12. In both directions fix one action and optimize on the other tree. The single-tree archive stores no objective, so solve each target tree without the fixed first stage to obtain its reference optimum. Within an observation, reuse an identical tree and fixed-action evaluation.
- The directed excess is the fixed-action objective minus the target tree optimum. Use the v2 tolerance `1e-6 × max(1, |reference objective|) + 1e-7`. A tier change is material when the excess on tier 12 strictly exceeds tolerance. The reverse direction is descriptive. A seed change is material when either direction exceeds tolerance. Report missing directions and unresolved pairs separately.
- Report median, p90 and maximum directed excess in objective units and relative to the reference. Order seed-pair directions by the listed seeds. Leave the relative value missing for a zero reference. Count relative excesses strictly above 0.5% for description.

### B. Three-tree selection

- Run group A tier 3, group A tier 12, group B tier 3 and group B tier 12 at each observation, giving 176 decisions. Solve each of the three trees independently. Deduplicate their first actions and evaluate each on the other trees under a fixed first stage. Reuse the objective where the action is already optimal on a tree. Select the action with lowest mean objective across the three trees. Break exact ties by the earliest seed producing the action. A group-tier decision is missing if any required value is missing.
- For the same observation, compare group A tier 12→group B tier 12 and group A tier 3→group A tier 12. Any difference in shipment counts is a change. Stability requires both raw change rates to be ≤10%. Divide by observations with two available actions and report missing pairs. Leave the conclusion unassessed if a comparison has no pairs or the run is interrupted.
- For changes, compare the mean objective of the source action on the target group's three trees with the mean of the target selection. Apply the A tolerance formula using the target mean as reference. The material-change rate uses observations with a determination and counts identical actions as unchanged. This rate is descriptive and signed excess can be negative.
- Measure online time for building the trees, solving, physical replay and within-group evaluation. Cross-group and cross-tier audits count toward formal wall time. Report online mean and p95 by tier against archived single-tree timing.

### Trial, budget and replay

- Use periods `t=0,5,6` under each of the four demand processes, for 12 fixed observations. All three periods have a full six-period planning window and showed changes in the archived single-tree evidence. Run the same computations as in the formal phases and preserve trial records. Time all associated work per observation, including B's comparison audits.
- Estimate formal A+B wall time as `44 × (A p95 per observation + B p95 per observation) + 45 seconds`. Use linearly interpolated quantiles. Finish at the trial phase if the estimate exceeds 5,400 seconds. The estimate uses timing alone. The seed groups and tiers are fixed in advance.
- Run sequentially in a single process in the frozen B1 path and period order. Run A before B with a shared formal cap of 5,400 seconds. Reserve 45 seconds before starting any solve. End the formal run immediately if cumulative failures strictly exceed 5% of attempts and retain captured evidence. Attempt each evaluation once per phase. The formal upper bounds are 388 solves for A and 1,848 for B, with reuse reducing the realized counts.
- Run `python -m rolling_tree consensus4 --output <empty directory>` for the timing trial and formal A and B when the time gate passes. Defaults place `rolling_tree_materiality` and `rolling_tree_consensus` under `benchmark_results`. Run `python -m rolling_tree verify4` to check both manifests offline, rebuild the recorded scenario trees and recompute decisions, distributions and summaries from saved records.
