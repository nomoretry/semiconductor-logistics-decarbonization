# 历史条件情景树：小规模开发试跑 / History-conditioned scenario trees: small development pilot

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

### 范围

按 [开发协议 v1](rolling_tree_protocol.md) 执行一次。这是**开发诊断，不是确认结论**：

- 2 条新开发路径（种子 72001 的 `volatile` 和 `upshift`），1 个采样种子；
- 拟合用 16 条路径，只估计共同因子方差，不运行策略；
- 确认数据没有生成、查看或运行；没有训练任何学习策略，没有调用 API。

代码版本为本地分支提交 `f53e078`，证据在 [`benchmark_results/rolling_tree_pilot/`](../benchmark_results/rolling_tree_pilot/)。

### 预算与计算

- **用量**：280 次求解（上限 300），墙钟 71.8 秒，进程 CPU 80.1 秒；没有触发预算停止。
- **求解结果**：280 次全部证明最优，最大 MIP gap 为 1.1×10⁻⁸；没有超时、失败或重试。
- **求解分配**：B1 共 24 次，LB 2 次，逐状态审计 110 次，B4 校准 12 次；M1、M2*、B3、B4 轨迹分别 22、44、44、22 次。
- **硬件与软件**：Intel Core i7-10870H（2.20 GHz，16 个逻辑处理器），Windows 10 19045；Python 3.12.10、NumPy 2.3.5、SciPy 1.17.0。单进程顺序运行，HiGHS 用默认线程。
- 原 B1 规划器不返回对偶界和节点数，只记录了状态、gap 和目标值。

| 方法 | 每次决策在线时间：平均（秒） | p95（秒） |
|---|---:|---:|
| B0 | 0.0004 | 0.0007 |
| B1 | 0.0126 | 0.0257 |
| M1 | 0.1452 | 0.6765 |
| M2* | 0.7915 | 3.1513 |
| B3 | 0.5369 | 1.9742 |
| B4 | 0.0790 | 0.2423 |

在线时间包括情景生成、建模、求解、平局处理和独立核对。单次求解最长 4.76 秒（M2* 的平局求解）。

- **B4 等时间校准**：在前 3 个审计状态上，M1 平均在线时间 0.0976 秒；候选 27、54、108、216 条路径的平均在线时间分别为 0.0618、0.1693、0.5169、0.7525 秒，按规则选 27。在完整轨迹中，B4 平均 0.0790 秒，仍比 M1 的 0.1452 秒快。
- **共同因子方差**：拟合 16 条路径、576 个乘积，v_fit=0.0766；试跑中历史条件的 v 在 0.024 到 0.520 之间。

### 首期动作审计（B1 轨迹上的 24 个状态）

| 比较 | 实质不同 | 相同 | 平局 | 末期强制为零 |
|---|---:|---:|---:|---:|
| 相关性：M1 对 M2（经 M2*） | 3 | 19 | 0 | 2 |
| 追索：M1 对 B2（经 B3） | 4 | 18 | 0 | 2 |

实质不同的状态如下（超额 = M2* 或 B3 的首期动作在 M1 目标下比 M1 最优值高出的部分）：

| 路径 | t | 比较 | 超额 | 占 M1 窗口目标 |
|---|---:|---|---:|---:|
| volatile | 0 | 相关性 | 0.0444 | 0.044% |
| volatile | 0 | 追索 | 0.1815 | 0.178% |
| volatile | 2 | 追索 | 0.3333 | 0.383% |
| volatile | 7 | 追索 | 0.6593 | 1.105% |
| upshift | 0 | 追索 | 0.7648 | 0.729% |
| upshift | 3 | 相关性 | 0.0926 | 0.174% |
| upshift | 8 | 相关性 | 1.6481 | 0.871% |

- 超额都远大于数值容差（相对 1e-6），而且所有求解都证明最优，所以这些差异不是求解误差或平局选择造成的。
- 在 3 个相关性实质不同的状态上，M1 树和 M2 树的各阶段节点数相同，差异也不来自“观测历史巧合合并”造成的信息结构差别。另有 5 个状态的节点数因巧合合并而不同，这些状态的相关性审计结果都是“相同”。

### 实际运行结果（单条路径，单个采样种子，只作描述）

| 路径 | 方法 | 总成本 | 即时满足率 | 排放 | 积压单位期 | 期末库存 / 积压 |
|---|---|---:|---:|---:|---:|---:|
| volatile | B0 | 353.10 | 0.8704 | 76 | 7 | 3 / 6 |
| volatile | B1 | 301.10 | 0.9259 | 84 | 4 | 3 / 4 |
| volatile | M1 | 356.05 | 0.9074 | 83 | 6 | 4 / 5 |
| volatile | M2* | 356.35 | 0.9074 | 83 | 6 | 4 / 5 |
| volatile | B3 | 359.15 | 0.9074 | 83 | 6 | 4 / 5 |
| volatile | B4 | 231.90 | 0.9630 | 86 | 2 | 4 / 2 |
| volatile | LB | 84.85 | 1.0000 | 59 | 0 | 0 / 0 |
| upshift | B0 | 856.20 | 0.5570 | 116 | 54 | 3 / 9 |
| upshift | B1 | 680.80 | 0.7089 | 132 | 34 | 5 / 7 |
| upshift | M1 | 662.20 | 0.7089 | 132 | 34 | 1 / 7 |
| upshift | M2* | 674.75 | 0.6835 | 131 | 37 | 0 / 7 |
| upshift | B3 | 665.95 | 0.6962 | 131 | 35 | 0 / 7 |
| upshift | B4 | 585.15 | 0.7595 | 131 | 26 | 2 / 6 |
| upshift | LB | 385.40 | 0.8861 | 132 | 13 | 0 / 6 |

| 比较 | 回答的问题 | volatile | upshift |
|---|---|---:|---:|
| M1−M2* | 相关性价值 | −0.30（−0.08%） | −12.55（−1.86%） |
| M1−B3 | 平局之外的追索价值 | −3.10（−0.86%） | −3.75（−0.56%） |
| M1−B4 | 等时间开环 | +124.15（+53.54%） | +77.05（+13.17%） |
| M1−B1 | 现行锚点 | +54.95（+18.25%） | −18.60（−2.73%） |

- M1−M2* 和 M1−B3 在两条路径上都是负值，但都没有达到 2% 的实用参考。满足率和排放的护栏都成立。
- 样本只有 2 条路径、1 个采样种子，**不给区间，也不判定假设**。
- 最大的差距来自 B4：等时间的开环 MPC 在两条路径上都明显好于所有基于树的方法（M1、M2*、B3），在 volatile 上 B1 也好于 M1。M1−B4 在两条路径上、M1−B1 在 volatile 上，满足率护栏都不成立。

### 事后诊断（看过结果后补做，属于探索）

在相同的 B1 状态上，只生成情景、不求解：

- 情景树第一期只有 2–3 个不同的需求向量，B4 有 18–27 个，B1 有 5–7 个。
- 第一期情景样本均值与预测之差（3 个 SKU 绝对值之和）平均为：情景树 1.70，B4 0.59，B1 1.21。

基于树的方法（M1、M2*、B3 共用同一组 27 条叶路径）的计划，受第一期采样误差影响更大。这能解释它们为什么落后于 B4，以及在 volatile 上落后于 B1。这个差距来自情景集的构造，而不是追索或相关性。

### 判读

- **按协议预设的读法**：审计中出现了实质不同的动作，属于“存在值得继续检验的机制信号”。但信号很小：超额只占窗口目标的 0.04%–1.1%，实际成本差也没有达到实用参考。
- **可能的解释**：
  - 真实的相关性或追索作用；
  - 单个采样种子下 3 个首期分支的抽样噪声；
  - 一次实质不同的决策之后轨迹分叉带来的累积差异；
  - 情景模型族与合成生成器在结构上匹配。
- **更大的问题**：当前情景树的首期采样太粗，使“追索与相关性的价值”和“情景集质量”混在一起。在这种设计下，扩大开发批次会主要测到情景集质量的差别。

### 下一项验收条件

先另立版本修订情景生成，使树与开环对照在第一期的样本质量可比。例如：首期分支数与开环情景数对齐；或者对每个节点的子节点做矩匹配，使其均值等于预测。之后在不超过 4 条新开发路径上，再做一次同样有预算的试跑。

只有当 M1−B4 不再由情景集质量主导、M1−M2* 的方向在多个采样种子下保持时，才考虑扩大开发批次。按本次实测计时，32 条路径×3 个采样种子约需 1.3 万次求解、约 1 小时墙钟时间（估计值）。确认集仍不生成。

### 复现

- `python -m semiconductor_logistics rolling-tree verify` 不求解，重新生成任务和情景树，独立复算台账和汇总，并核对哈希。
- `python -m semiconductor_logistics rolling-tree pilot --output <空目录>` 重新运行试跑，会再次消耗求解预算。
- 测试：`python -m unittest tests.test_rolling_tree`。

## English

### Scope

One run under [development protocol v1](rolling_tree_protocol.md). It is a **development diagnostic, not a confirmatory result**:

- two new development paths (`volatile` and `upshift` for seed 72001) and one sampler seed;
- 16 fitting paths used only to estimate the common-factor variance, with no policy runs;
- no confirmation data generated, inspected or run; no learned policy trained; no API calls.

The code version is local branch commit `f53e078`; the evidence is in [`benchmark_results/rolling_tree_pilot/`](../benchmark_results/rolling_tree_pilot/).

### Budget and computation

- **Usage**: 280 solves (limit 300), 71.8 s wall time and 80.1 s process CPU; the budget did not stop the run.
- **Solve outcomes**: all 280 solves were proven optimal, with a maximum MIP gap of 1.1×10⁻⁸; there were no timeouts, failures or retries.
- **Allocation**: B1 24 solves, LB 2, per-state audits 110 and B4 calibration 12; the M1, M2*, B3 and B4 trajectories used 22, 44, 44 and 22.
- **Hardware and software**: Intel Core i7-10870H (2.20 GHz, 16 logical processors), Windows 10 19045; Python 3.12.10, NumPy 2.3.5 and SciPy 1.17.0. One sequential process; HiGHS with default threads.
- The archived B1 planner does not return dual bounds or node counts; only status, gap and objective were recorded for it.

| Method | Online seconds per decision: mean | p95 |
|---|---:|---:|
| B0 | 0.0004 | 0.0007 |
| B1 | 0.0126 | 0.0257 |
| M1 | 0.1452 | 0.6765 |
| M2* | 0.7915 | 3.1513 |
| B3 | 0.5369 | 1.9742 |
| B4 | 0.0790 | 0.2423 |

Online time covers scenario generation, model building, solving, tie handling and independent checks. The longest single solve took 4.76 s (an M2* tie solve).

- **B4 equal-time calibration**: on the first three audit states, M1 averaged 0.0976 s online; the 27, 54, 108 and 216 path candidates averaged 0.0618, 0.1693, 0.5169 and 0.7525 s, so the rule selected 27. Over full trajectories B4 averaged 0.0790 s, still faster than M1's 0.1452 s.
- **Common-factor variance**: from 16 fitting paths and 576 products, v_fit=0.0766; the history-conditioned v ranged from 0.024 to 0.520 during the pilot.

### First-action audit (24 states on the B1 trajectories)

| Comparison | Material | Identical | Tie | Forced zero (last period) |
|---|---:|---:|---:|---:|
| Dependence: M1 vs M2 (via M2*) | 3 | 19 | 0 | 2 |
| Recourse: M1 vs B2 (via B3) | 4 | 18 | 0 | 2 |

Material states (excess = how much worse M2*'s or B3's first action is than M1's optimum under M1's objective):

| Path | t | Comparison | Excess | Share of M1 window objective |
|---|---:|---|---:|---:|
| volatile | 0 | dependence | 0.0444 | 0.044% |
| volatile | 0 | recourse | 0.1815 | 0.178% |
| volatile | 2 | recourse | 0.3333 | 0.383% |
| volatile | 7 | recourse | 0.6593 | 1.105% |
| upshift | 0 | recourse | 0.7648 | 0.729% |
| upshift | 3 | dependence | 0.0926 | 0.174% |
| upshift | 8 | dependence | 1.6481 | 0.871% |

- Every excess is far above the numerical tolerance (relative 1e-6), and every solve was proven optimal, so these differences are not solver error or tie selection.
- At the three dependence-material states, the M1 and M2 trees have identical node counts at every stage, so the difference does not come from coincidental merging of observed histories. Five other states had different node counts because of such merging, and all five audited as identical for dependence.

### Realized results (single path, single sampler seed; descriptive only)

| Path | Method | Total cost | Immediate fill | Emissions | Backlog unit-periods | Final stock / backlog |
|---|---|---:|---:|---:|---:|---:|
| volatile | B0 | 353.10 | 0.8704 | 76 | 7 | 3 / 6 |
| volatile | B1 | 301.10 | 0.9259 | 84 | 4 | 3 / 4 |
| volatile | M1 | 356.05 | 0.9074 | 83 | 6 | 4 / 5 |
| volatile | M2* | 356.35 | 0.9074 | 83 | 6 | 4 / 5 |
| volatile | B3 | 359.15 | 0.9074 | 83 | 6 | 4 / 5 |
| volatile | B4 | 231.90 | 0.9630 | 86 | 2 | 4 / 2 |
| volatile | LB | 84.85 | 1.0000 | 59 | 0 | 0 / 0 |
| upshift | B0 | 856.20 | 0.5570 | 116 | 54 | 3 / 9 |
| upshift | B1 | 680.80 | 0.7089 | 132 | 34 | 5 / 7 |
| upshift | M1 | 662.20 | 0.7089 | 132 | 34 | 1 / 7 |
| upshift | M2* | 674.75 | 0.6835 | 131 | 37 | 0 / 7 |
| upshift | B3 | 665.95 | 0.6962 | 131 | 35 | 0 / 7 |
| upshift | B4 | 585.15 | 0.7595 | 131 | 26 | 2 / 6 |
| upshift | LB | 385.40 | 0.8861 | 132 | 13 | 0 / 6 |

| Contrast | Question | volatile | upshift |
|---|---|---:|---:|
| M1−M2* | dependence value | −0.30 (−0.08%) | −12.55 (−1.86%) |
| M1−B3 | recourse beyond ties | −3.10 (−0.86%) | −3.75 (−0.56%) |
| M1−B4 | equal-time open loop | +124.15 (+53.54%) | +77.05 (+13.17%) |
| M1−B1 | current anchor | +54.95 (+18.25%) | −18.60 (−2.73%) |

- M1−M2* and M1−B3 are negative on both paths but below the 2% practical reference. The fill and emission guardrails hold.
- With two paths and one sampler seed, **no interval is reported and no hypothesis is decided**.
- The largest gap comes from B4: equal-time open-loop MPC is clearly better than every tree-based method (M1, M2*, B3) on both paths, and B1 beats M1 on `volatile`. The fill guardrail fails for M1−B4 on both paths and for M1−B1 on `volatile`.

### Post-hoc diagnostic (added after viewing results; exploratory)

On the same B1 states, generating scenarios without solving:

- Trees contain only 2–3 distinct first-period demand vectors, against 18–27 for B4 and 5–7 for B1.
- The gap between the first-period scenario sample mean and the forecast (absolute values summed over 3 SKUs) averages 1.70 for trees, 0.59 for B4 and 1.21 for B1.

Plans from tree-based methods (M1, M2* and B3 share the same 27 leaf paths) suffer more first-period sampling error. This explains why they trail B4, and B1 on `volatile`. The gap comes from how the scenario set is constructed, not from recourse or dependence.

### Reading

- **Under the protocol's preset reading**: materially different actions appeared in the audit, which counts as "a mechanism signal worth further testing". The signal is small: excesses are 0.04%–1.1% of the window objective, and realized cost differences stay below the practical reference.
- **Possible explanations**:
  - genuine dependence or recourse effects;
  - sampling noise in three first-stage branches under one sampler seed;
  - divergence accumulating after a single material decision;
  - the structural match between the scenario model family and the synthetic generator.
- **The larger problem**: the current trees sample the first period too coarsely, so the value of recourse and dependence is confounded with scenario-set quality. With this design, a larger development batch would mainly measure differences in scenario-set quality.

### Next acceptance condition

First revise scenario generation in a new version so that trees and open-loop controls have comparable first-period sample quality. For example, align the number of first-stage branches with the open-loop scenario count, or moment-match each node's children to the forecast mean. Then rerun an equally bounded pilot on at most four new development paths.

Only when M1−B4 is no longer dominated by scenario-set quality, and the direction of M1−M2* holds across several sampler seeds, should a larger development batch be considered. At the measured timings, 32 paths×3 sampler seeds would need about 13,000 solves and roughly one hour of wall time (an estimate). Confirmation data remain ungenerated.

### Reproduction

- `python -m semiconductor_logistics rolling-tree verify` runs no solver: it regenerates tasks and scenario trees, recomputes ledgers and summaries independently, and checks hashes.
- `python -m semiconductor_logistics rolling-tree pilot --output <empty directory>` reruns the pilot and consumes solve budget again.
- Tests: `python -m unittest tests.test_rolling_tree`.
