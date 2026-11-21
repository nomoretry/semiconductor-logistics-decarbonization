# 首期动作实质性与三树选择结果 / First-action materiality and three-tree selection results

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

### 问题与方法

在四条合成开发路径上沿用 44 个 B1 非强制观测，复核单树首期发运量的改变是否超过目标值容差，并检验三树选择是否将两项首期动作改变率降到 10% 或以下。动作改变指任一 SKU×路线的整数发运量不同。使用原定的两组种子、3 和 12 两档情景树及原 MILP。目标值来自各自的规划窗口。 [原协议](rolling_tree_consensus_protocol.md) · [实现](../rolling_tree/consensus.py) · [冻结的单树动作](../benchmark_results/rolling_tree_stability/states.jsonl) · [正式配置](../benchmark_results/rolling_tree_consensus/config.json)

### A. 单树动作改变的实质性

对冻结记录中动作不同的配对，在对方情景树上固定本方首期动作并重新求解。带符号超额等于固定动作的最优目标减去目标树的无约束首期最优目标。相对超额以目标树最优值的绝对值为分母。超额严格大于原定容差即为实质改变。档位比较以 3 档动作放入 12 档为准，逆向作描述。换种子比较以任一方向超出容差为准，正向按种子列表顺序从较早到较晚的种子。全部配对均可判定。[A 汇总](../benchmark_results/rolling_tree_materiality/summary.json) · [A 逐观测记录](../benchmark_results/rolling_tree_materiality/formal.jsonl)

| 固定动作来自→评估所在树 | 实质 / 复核数 | 带符号超额（中位数 / p90 / 最大值） | 相对超额（中位数 / p90 / 最大值） | 相对超额严格大于 0.5% |
|---|---:|---:|---:|---:|
| 3 档→12 档 | 44/44 | +0.164815 / +0.485586 / +0.811420 | 0.276938% / 0.763298% / 2.133291% | 12/44 |
| 12 档→3 档 | 44/44 | +0.173457 / +0.572346 / +0.984568 | 0.372858% / 1.331813% / 1.903366% | 16/44 |
| 12 档，种子先→后 | 53/53 | +0.271605 / +1.189877 / +2.585185 | 0.500618% / 1.651951% / 9.181794% | 28/53 |
| 12 档，种子后→先 | 53/53 | +0.256173 / +0.880062 / +2.585185 | 0.517137% / 1.246025% / 9.181794% | 27/53 |

3 档→12 档的 **44/44** 个记录改变均为实质改变，占全部 132 个档位配对的 **33.33%**。12 档换种子的 **53/53** 个记录改变均为实质改变，占全部 132 个种子配对的 **40.15%**。其中 **37/53** 个换种子配对至少有一个方向的相对超额严格大于 0.5%。0.5% 是描述性统计门槛。 [A 汇总](../benchmark_results/rolling_tree_materiality/summary.json)

### B. 三树选择的稳定性

对每个观测、种子组和档位，分别求解三棵树，去重得到的首期动作，并在三棵树上评估每个动作。取平均目标最低的动作，平局按种子顺序取先者。共完成 **176 次决策**。跨组和跨档的实质改变按目标组三树下的平均目标超额及同一容差评估。每项比较均有 44 个可比较观测。[B 汇总](../benchmark_results/rolling_tree_consensus/summary.json) · [B 逐观测记录](../benchmark_results/rolling_tree_consensus/formal.jsonl)

| 比较 | 动作改变数及比例 | 实质改变数及比例 | 原始改变率 ≤10% |
|---|---:|---:|---|
| 12 档，甲组→乙组 | 17/44 (38.64%) | 17/44 (38.64%) | 未达标 |
| 甲组，3 档→12 档 | 20/44 (45.45%) | 19/44 (43.18%) | 未达标 |

两项原始改变率均超过 10%，因此三树选择在本次实验中**不稳定**。甲组的 20 个跨档动作改变中，19 个超过实质性容差。两项实质改变率也均超过 10%。[B 汇总](../benchmark_results/rolling_tree_consensus/summary.json)

| 档位 | 三树决策数（两组合计） | 三树在线均值（秒） | 三树在线 p95（秒） | 归档单树在线均值（秒） | 归档单树在线 p95（秒） |
|---|---:|---:|---:|---:|---:|
| 3 | 88 | 1.649 | 2.592 | 0.485 | 1.090 |
| 12 | 88 | 4.441 | 12.676 | 1.446 | 4.484 |

三树在线用时包含建树、求解、物理重放和组内动作评估。跨组及跨档审计记入正式总墙钟。计时在共享机器上进行。[B 汇总](../benchmark_results/rolling_tree_consensus/summary.json) · [单树计时归档](../benchmark_results/rolling_tree_stability/summary.json) · [运行环境](../benchmark_results/rolling_tree_consensus/runtime.json)

### 预算与运行范围

按原公式，用 12 个固定观测（四条路径各取 `t=0,5,6`）的单观测用时估计正式墙钟 `44 × (A p95 + B p95) + 45 秒`。初次试算估计 **6066.942 秒**，超过 **5,400 秒**门槛，正式求解为 **0 次**。预算修订将估计门槛与 A+B 共享墙钟上限均调至 **10,800 秒**。重做同样 12 个观测的试算后，估计 **5061.510 秒**，通过修订门槛。[预算修订](rolling_tree_consensus_protocol_amendment.md) · [A 初次试算](../benchmark_results/rolling_tree_materiality_gate1/summary.json) · [B 初次试算](../benchmark_results/rolling_tree_consensus_gate1/summary.json)

一次正式运行覆盖原定全部 44 个观测，单进程顺序执行，实测共享墙钟 **707.178 秒**。A 求解 **289 次**，B 求解 **957 次**，合计 **1,246 次**，失败和超时均为 **0 次**。 [A 清单](../benchmark_results/rolling_tree_materiality/manifest.json) · [B 清单](../benchmark_results/rolling_tree_consensus/manifest.json)

### 下一项验收与复算

先降低首期动作对种子组和档位的敏感性。下一轮在同一批 44 个观测上复验，在事先规定的时间上限内确认两项原始改变率均 ≤10%，再研究需求相关性的价值。

```sh
python -m rolling_tree consensus4 --max-wall-seconds 10800 --output <空目录>
python -m rolling_tree verify4
python -m rolling_tree verify4 --gate1
```

复跑命令将阶段记录写入指定的空目录。默认位置的续跑证据可用 `verify4` 复算，初次试算归档可用 `verify4 --gate1` 复算，两者均为离线复算。

## English

### Question and method

Reuse 44 non-forced B1 observations from four synthetic development paths to test whether archived single-tree shipment changes exceed the objective tolerance and whether three-tree selection brings both first-action change rates to 10% or below. An action changes when any integer shipment quantity differs by SKU and route. Use the original MILP, both predeclared seed groups, and scenario-tree tiers 3 and 12. Objective values refer to their planning windows. [Original protocol](rolling_tree_consensus_protocol.md) · [Implementation](../rolling_tree/consensus.py) · [Frozen single-tree actions](../benchmark_results/rolling_tree_stability/states.jsonl) · [Formal configuration](../benchmark_results/rolling_tree_consensus/config.json)

### A. Materiality of single-tree action changes

For pairs with a change in the archive, fix each first action in the other tree and solve again. Signed excess is the optimum with the first action fixed minus the target tree optimum with the first action free. Relative excess divides this difference by the absolute target optimum. An excess strictly above the original tolerance is material. Tier-pair materiality uses the tier-3 action evaluated on tier 12. The reverse direction is descriptive. For a seed pair, excess above tolerance in either direction establishes materiality. The forward direction goes from the earlier seed in the list to the later one. Every pair was resolved. [A summary](../benchmark_results/rolling_tree_materiality/summary.json) · [A observation records](../benchmark_results/rolling_tree_materiality/formal.jsonl)

| Fixed action source→evaluation tree | Material / evaluated | Signed excess (median / p90 / max) | Relative excess (median / p90 / max) | Relative excess strictly above 0.5% |
|---|---:|---:|---:|---:|
| Tier 3→tier 12 | 44/44 | +0.164815 / +0.485586 / +0.811420 | 0.276938% / 0.763298% / 2.133291% | 12/44 |
| Tier 12→tier 3 | 44/44 | +0.173457 / +0.572346 / +0.984568 | 0.372858% / 1.331813% / 1.903366% | 16/44 |
| Tier 12, earlier→later seed | 53/53 | +0.271605 / +1.189877 / +2.585185 | 0.500618% / 1.651951% / 9.181794% | 28/53 |
| Tier 12, later→earlier seed | 53/53 | +0.256173 / +0.880062 / +2.585185 | 0.517137% / 1.246025% / 9.181794% | 27/53 |

All **44/44** archived tier 3→12 changes were material, representing **33.33%** of all 132 tier pairs. All **53/53** archived seed changes at tier 12 were material, representing **40.15%** of all 132 seed pairs. For **37/53** changed seed pairs, relative excess strictly exceeded 0.5% in at least one direction. The 0.5% cutoff is descriptive. [A summary](../benchmark_results/rolling_tree_materiality/summary.json)

### B. Stability of three-tree selection

For each observation, seed group and tier, solve three trees separately, deduplicate their first actions, and evaluate each action on all three trees. Choose the action with the lowest mean objective, breaking ties by seed order. The formal run completed **176 decisions**. For cross-group and cross-tier materiality, evaluate the mean excess on the target group's three trees using the same tolerance. Each comparison had 44 comparable observations. [B summary](../benchmark_results/rolling_tree_consensus/summary.json) · [B observation records](../benchmark_results/rolling_tree_consensus/formal.jsonl)

| Comparison | Changed / comparable (%) | Material / comparable (%) | Raw change rate ≤10% |
|---|---:|---:|---|
| Tier 12, group A→group B | 17/44 (38.64%) | 17/44 (38.64%) | Fail |
| Group A, tier 3→tier 12 | 20/44 (45.45%) | 19/44 (43.18%) | Fail |

Both raw change rates exceeded 10%, so three-tree selection was **unstable** in this experiment. Of the 20 tier changes in group A, 19 exceeded the materiality tolerance. Both material change rates also exceeded 10%. [B summary](../benchmark_results/rolling_tree_consensus/summary.json)

| Tier | Three-tree decisions (both groups) | Three-tree online mean (s) | Three-tree online p95 (s) | Archived single-tree online mean (s) | Archived single-tree online p95 (s) |
|---|---:|---:|---:|---:|---:|
| 3 | 88 | 1.649 | 2.592 | 0.485 | 1.090 |
| 12 | 88 | 4.441 | 12.676 | 1.446 | 4.484 |

Three-tree online time includes tree construction, solving, physical replay and within-group action evaluation. Cross-group and cross-tier audits count toward total formal wall time. Timings were measured on a shared machine. [B summary](../benchmark_results/rolling_tree_consensus/summary.json) · [Archived single-tree timings](../benchmark_results/rolling_tree_stability/summary.json) · [Runtime environment](../benchmark_results/rolling_tree_consensus/runtime.json)

### Budget and run coverage

The original formula used per-observation times on 12 fixed observations (`t=0,5,6` for each of four paths) to estimate formal wall time as `44 × (A p95 + B p95) + 45 seconds`. The initial trial estimated **6066.942 seconds**, above the **5,400-second** gate, and the formal solve count was **zero**. The budget amendment raised both the estimated wall-time gate and the shared A+B cap to **10,800 seconds**. Repeating the trial on the same 12 observations produced an estimate of **5061.510 seconds**, within the amended gate. [Budget amendment](rolling_tree_consensus_protocol_amendment.md) · [Initial A trial](../benchmark_results/rolling_tree_materiality_gate1/summary.json) · [Initial B trial](../benchmark_results/rolling_tree_consensus_gate1/summary.json)

One formal run kept all 44 observations and ran sequentially in one process. It used **707.178 seconds** of shared wall time for **289 A solves** and **957 B solves**, totaling **1,246 solves** with **zero failures and zero timeouts**. [A manifest](../benchmark_results/rolling_tree_materiality/manifest.json) · [B manifest](../benchmark_results/rolling_tree_consensus/manifest.json)

### Next acceptance condition and replay

First reduce first-action sensitivity to the seed group and tier. Test again on the same 44 observations and verify that both raw change rates are 10% or below under a predeclared timing limit before studying the value of demand dependence.

```sh
python -m rolling_tree consensus4 --max-wall-seconds 10800 --output <empty directory>
python -m rolling_tree verify4
python -m rolling_tree verify4 --gate1
```

The rerun command writes phase records to the specified empty directory. Use `verify4` to verify the continuation evidence in its default location and `verify4 --gate1` to verify the original trial archives. Both verification commands run offline.
