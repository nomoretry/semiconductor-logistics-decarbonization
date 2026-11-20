# M1 首期动作稳定性 / M1 first-action stability

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

### 问题与实现

**不稳定。** 延续路径从 3 增至 12，首期发运矩阵在 132 对中改变 44 对（33.3%）。12 档仅换采样种子时改变 53 对（40.2%）。两项都超过事前规定的 10%。本次执行只检验四条合成开发路径上的 M1 首期动作稳定性。 [事前协议](rolling_tree_stability_protocol.md) · [完整汇总](../benchmark_results/rolling_tree_stability/summary.json)

沿用 v2 的 B1 轨迹中 44 个非强制观测，覆盖 4 种需求过程和期次 `t=0…10`。每个观测使用 3 个既有规划器种子，共 132 个观测与种子组合。采用 v2 的条件方差、τ=192、9×3 分支和 MILP。对同一观测和种子，各档位共用前两层需求抽样，改变的是第二层以下的延续路径数及对应的分层抽样。 [v2 B1 轨迹](../benchmark_results/rolling_tree_v2_pilot/traces.jsonl) · [运行配置](../benchmark_results/rolling_tree_stability/config.json) · [实现](../rolling_tree/stability.py)

### 档位与计算

每档在 12 个固定状态试算，共 60 次，墙钟 77.886 秒，失败 0 次。按在线 p95 ≤10 秒的最大档规则选出 L=12。估计正式墙钟 975.641 秒。 [逐次试算](../benchmark_results/rolling_tree_stability/timing.jsonl)

| 延续路径数 | 试算次数 | 在线 p95（秒） |
|---:|---:|---:|
| 1 | 12 | 0.747 |
| 3 | 12 | 0.942 |
| 6 | 12 | 2.697 |
| 9 | 12 | 2.677 |
| 12 | 12 | 5.360 |

正式运行 396 次，墙钟 283.387 秒。求解器均报告最优，失败和超时各 0 次。最长单次 MILP 用时 28.613 秒，最大报告 MIP gap 约 1.34e-15。在线时间含条件方差计算、情景生成、模型构建、求解及物理重放。 [逐状态记录](../benchmark_results/rolling_tree_stability/states.jsonl) · [运行环境](../benchmark_results/rolling_tree_stability/runtime.json)

| 延续路径数 | 抽样叶路径数 | 正式求解 | 失败 | 在线均值（秒） | 在线 p95（秒） |
|---:|---:|---:|---:|---:|---:|
| 1 | 27 | 132 | 0 | 0.215 | 0.638 |
| 3 | 81 | 132 | 0 | 0.485 | 1.090 |
| 12 | 324 | 132 | 0 | 1.446 | 4.484 |

### 首期动作改变

任一 SKU×路线的整数发运量不同即计为改变。每项有 132 个可比对，缺失 0 对。种子参照在同一观测下两两比较。各对共享合成路径，结果作描述性解读。求解器返回的不同最优动作也可能计入改变。

| 同观测、同种子换延续档位 | 改变 / 可比（率） |
|---|---:|
| 1 → 3 | 66/132 (50.0%) |
| 3 → 12 | 44/132 (33.3%) |
| 1 → 12 | 74/132 (56.1%) |

| 同观测、同档位换种子 | 改变 / 可比（率） |
|---:|---:|
| 1 | 62/132 (47.0%) |
| 3 | 66/132 (50.0%) |
| 12 | 53/132 (40.2%) |

| 零基期次 `t` | 3 → 12 | 12 档换种子 |
|---:|---:|---:|
| 0 | 6/12 (50.0%) | 9/12 (75.0%) |
| 1 | 5/12 (41.7%) | 4/12 (33.3%) |
| 2 | 3/12 (25.0%) | 2/12 (16.7%) |
| 3 | 2/12 (16.7%) | 4/12 (33.3%) |
| 4 | 5/12 (41.7%) | 8/12 (66.7%) |
| 5 | 7/12 (58.3%) | 10/12 (83.3%) |
| 6 | 8/12 (66.7%) | 4/12 (33.3%) |
| 7 | 4/12 (33.3%) | 4/12 (33.3%) |
| 8 | 2/12 (16.7%) | 0/12 (0.0%) |
| 9 | 2/12 (16.7%) | 6/12 (50.0%) |
| 10 | 0/12 (0.0%) | 2/12 (16.7%) |

| 需求过程 | 3 → 12 | 12 档换种子 |
|---|---:|---:|
| stable | 13/33 (39.4%) | 14/33 (42.4%) |
| volatile | 9/33 (27.3%) | 15/33 (45.5%) |
| upshift | 9/33 (27.3%) | 13/33 (39.4%) |
| downshift | 13/33 (39.4%) | 11/33 (33.3%) |

| SKU | 路线 | 3 → 12（改变对数 / 绝对件数差之和） | 12 档换种子（改变对数 / 绝对件数差之和） |
|---|---|---:|---:|
| SKU1 | 慢线 | 26 / 31 | 25 / 30 |
| SKU1 | 快线 | 2 / 2 | 2 / 2 |
| SKU2 | 慢线 | 18 / 18 | 22 / 22 |
| SKU2 | 快线 | 0 / 0 | 12 / 12 |
| SKU3 | 慢线 | 16 / 16 | 16 / 18 |
| SKU3 | 快线 | 0 / 0 | 4 / 4 |

- 延续档位的改变率在 `t=6`（8/12）和 `t=5`（7/12）最高，`stable` 与 `downshift` 均为 13/33。44 个改变对中有 42 对只涉及慢线，慢线 SKU1 涉及 26 对，绝对件数差合计 31 件。
- 换种子的改变率在 `t=5`（10/12）和 `t=0`（9/12）最高，`volatile` 有 15/33 对。最常变的是慢线 SKU1（25 对）和 SKU2（22 对），快线 SKU2 也有 12 对变化。单对可以涉及多个单元。
- `t=10` 的规划窗口只有两期，各延续档位没有第二层以下的需求抽样。该期 3→12 为 0/12，对应的 12 档换种子为 2/12。其他比较的完整分解见 [汇总](../benchmark_results/rolling_tree_stability/summary.json)。

### 下一项验收条件与复算

在相同 44 个观测上先规定改进的情景近似和复验用种子，再检验相邻精度档的首期动作改变率及高档种子两两改变率。两率均须 ≤10%，沿用高档试算在线 p95 ≤10 秒、单次求解 30 秒和正式墙钟 60 分钟预算。两项通过后再检验需求相关性的价值。

`python -m rolling_tree verify3` 核对 SHA256、重新生成 456 棵试算和正式情景树，并从保存的记录复算汇总，求解次数为 0。重做计时及求解用 `python -m rolling_tree stability3 --output <空目录>`。 [SHA256 清单](../benchmark_results/rolling_tree_stability/manifest.json)

## English

### Question and implementation

**Unstable.** Increasing the continuation count from 3 to 12 changes the first shipment matrix in 44/132 (33.3%) of pairs. Changing only the sampler seed at tier 12 changes it in 53/132 (40.2%) of pairs. Both exceed the pre-specified 10% limit. The single run assesses M1's first-action stability on four synthetic development paths. [Protocol](rolling_tree_stability_protocol.md) · [Full summary](../benchmark_results/rolling_tree_stability/summary.json)

The experiment uses 44 non-forced observations from the v2 B1 trajectories across four demand processes and periods `t=0…10`. Each observation uses three existing sampler seeds, giving 132 observation–seed combinations. It uses the v2 conditional variance, τ=192, 9×3 branching and MILP. At a fixed observation and seed the tiers share demand draws at the first two levels. The continuation count and the corresponding stratified draws change below that depth. [v2 B1 trajectories](../benchmark_results/rolling_tree_v2_pilot/traces.jsonl) · [Run configuration](../benchmark_results/rolling_tree_stability/config.json) · [Implementation](../rolling_tree/stability.py)

### Tiers and computation

There were 60 timing attempts, 12 fixed states per tier, with 77.886 seconds of wall time and zero failures. The largest tier with online p95 ≤10 seconds was L=12. The estimated formal wall time was 975.641 seconds. [Timing ledger](../benchmark_results/rolling_tree_stability/timing.jsonl)

| Continuation paths | Timing attempts | Online p95 (s) |
|---:|---:|---:|
| 1 | 12 | 0.747 |
| 3 | 12 | 0.942 |
| 6 | 12 | 2.697 |
| 9 | 12 | 2.677 |
| 12 | 12 | 5.360 |

The formal run completed 396 solves in 283.387 wall seconds. The solver reported optimal solutions for all attempts, with zero failures and zero timeouts. The longest MILP took 28.613 seconds and the maximum reported MIP gap was about 1.34e-15. Online time includes conditioning the variance, scenario generation, model construction, solving and physical replay. [Formal ledger](../benchmark_results/rolling_tree_stability/states.jsonl) · [Runtime environment](../benchmark_results/rolling_tree_stability/runtime.json)

| Continuation paths | Sampled leaf paths | Formal solves | Failures | Online mean (s) | Online p95 (s) |
|---:|---:|---:|---:|---:|---:|
| 1 | 27 | 132 | 0 | 0.215 | 0.638 |
| 3 | 81 | 132 | 0 | 0.485 | 1.090 |
| 12 | 324 | 132 | 0 | 1.446 | 4.484 |

### First-action changes

A difference in integer shipments in any SKU×route cell counts as one change. Each contrast has 132 comparable pairs and zero missing pairs. Seed comparisons are pairwise at the same observation. These pairs share synthetic paths, so the results are descriptive. Alternative optimal actions returned by the solver can contribute changes.

| Change tier at the same observation and seed | Changed / comparable (rate) |
|---|---:|
| 1 → 3 | 66/132 (50.0%) |
| 3 → 12 | 44/132 (33.3%) |
| 1 → 12 | 74/132 (56.1%) |

| Change seed at the same observation and tier | Changed / comparable (rate) |
|---:|---:|
| 1 | 62/132 (47.0%) |
| 3 | 66/132 (50.0%) |
| 12 | 53/132 (40.2%) |

| Zero-based period `t` | 3 → 12 | Seed changes at tier 12 |
|---:|---:|---:|
| 0 | 6/12 (50.0%) | 9/12 (75.0%) |
| 1 | 5/12 (41.7%) | 4/12 (33.3%) |
| 2 | 3/12 (25.0%) | 2/12 (16.7%) |
| 3 | 2/12 (16.7%) | 4/12 (33.3%) |
| 4 | 5/12 (41.7%) | 8/12 (66.7%) |
| 5 | 7/12 (58.3%) | 10/12 (83.3%) |
| 6 | 8/12 (66.7%) | 4/12 (33.3%) |
| 7 | 4/12 (33.3%) | 4/12 (33.3%) |
| 8 | 2/12 (16.7%) | 0/12 (0.0%) |
| 9 | 2/12 (16.7%) | 6/12 (50.0%) |
| 10 | 0/12 (0.0%) | 2/12 (16.7%) |

| Demand process | 3 → 12 | Seed changes at tier 12 |
|---|---:|---:|
| stable | 13/33 (39.4%) | 14/33 (42.4%) |
| volatile | 9/33 (27.3%) | 15/33 (45.5%) |
| upshift | 9/33 (27.3%) | 13/33 (39.4%) |
| downshift | 13/33 (39.4%) | 11/33 (33.3%) |

| SKU | Route | 3 → 12 (changed pairs / total absolute units) | Seed changes at tier 12 (changed pairs / total absolute units) |
|---|---|---:|---:|
| SKU1 | Slow | 26 / 31 | 25 / 30 |
| SKU1 | Fast | 2 / 2 | 2 / 2 |
| SKU2 | Slow | 18 / 18 | 22 / 22 |
| SKU2 | Fast | 0 / 0 | 12 / 12 |
| SKU3 | Slow | 16 / 16 | 16 / 18 |
| SKU3 | Fast | 0 / 0 | 4 / 4 |

- Continuation-tier sensitivity peaks at `t=6` (8/12) and `t=5` (7/12). The `stable` and `downshift` paths each have 13/33 changes. Of the 44 changed pairs, 42 involve the slow route only. Slow-route SKU1 changes in 26 pairs, totaling 31 absolute units.
- Sampler-seed sensitivity peaks at `t=5` (10/12) and `t=0` (9/12). The `volatile` path has 15/33 changes. Slow-route SKU1 (25 pairs) and SKU2 (22 pairs) change most often, and fast-route SKU2 changes in 12 pairs. A pair can affect multiple cells.
- The window at `t=10` has two periods, so there are no draws below the second level at any tier. There are 0/12 changes from 3 to 12 in that period and 2/12 seed changes at tier 12. Full breakdowns for the other contrasts are in the [summary](../benchmark_results/rolling_tree_stability/summary.json).

### Next acceptance condition and reproduction

Pre-specify an improved scenario approximation and the seeds for a repeat test on the same 44 observations. Test the first-action change rate between adjacent precision tiers and the pairwise seed change rate at the higher tier. Both must be ≤10%, with the same 10-second online p95 limit for tier selection, 30-second solve limit and 60-minute formal wall budget. Test the value of demand dependence after both gates pass.

`python -m rolling_tree verify3` checks the SHA256 manifest, regenerates 456 timing and formal scenario trees and recomputes the summary from saved records, with zero solves. Repeat timing and solving with `python -m rolling_tree stability3 --output <empty directory>`. [SHA256 manifest](../benchmark_results/rolling_tree_stability/manifest.json)
