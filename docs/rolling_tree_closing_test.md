本文先列中文，后列英文。 / Chinese first, English second.

# 需求关联与滚动发运的闭环配对结果 / Paired closed-loop results for demand dependence in rolling dispatch

## 中文

### 研究问题与样本

同样的历史和逐 SKU 边际情景下，保留跨 SKU 的同期需求配对，能否改变有限运力的分配，并改善后续成本、即时满足率或排放？本次按事前协议执行一次。40 个需求种子各生成四类过程，共 160 条新合成路径，每条 12 期。每条路径上，M1、M2 和 M2* 共用一个采样种子。M1 保留配对，M2 置换配对并直接执行自身最优动作，两者每期各自重规划。M2* 用 M1 目标在 M2 最优面上选解。平局求解超时时退回本期 M2 自身动作。B1 是七情景 EWMA 滚动规划器，B0 是 z=1 的 base-stock，LB 是全期预知的成本下界。[原协议](rolling_tree_closing_protocol.md) · [预算修订](rolling_tree_closing_protocol_amendment.md) · [配置](../benchmark_results/rolling_tree_closing/config.json) · [路径索引](../benchmark_results/rolling_tree_closing/tasks.json)

### 主要比较与预注册判定

M1 与 M2 在全部 160 条路径上形成完整配对。记每条路径的实际总成本差为 D = cost(M1) − cost(M2)。总成本包括运费、碳价、持有、逐期积压及末期积压费用。各比较均以前者减后者，成本与排放采用合成环境单位。相对差用同一配对组的对照均值作分母。即时满足率为需求当期直接满足的比例，表中绝对差以百分点表示。t 区间以路径为单位，bootstrap 用同一路径索引同时重抽三个指标，重复 10,000 次，种子 979301。

| 比较 | 路径 | 指标 | 平均差 | 占对照均值 | 配对 t 95% 区间 | bootstrap 95% 区间 |
|---|---|---|---|---|---|---|
| `M1-M2` | 160 | 总成本 | +0.205 | 0.08% | [−1.662, +2.071] | [−1.610, +2.107] |
| `M1-M2` | 160 | 即时满足率（百分点） | +0.192 | 0.22% | [−0.00026, +0.38373] | [−0.00071, +0.38042] |
| `M1-M2` | 160 | 排放 | −0.281 | -0.28% | [−0.685, +0.123] | [−0.681, +0.113] |

M2 平均成本 255.095，2% 实用界值为 ±5.102。按主要成本 t 区间，四类判定结果为 **没有实用价值（成本等效）**。满足率护栏为平均差至少 −0.5 个百分点，排放护栏为相对增加不超过 2%。三个指标的两种区间均包含零。成本区间整体落在等效界内。即时满足率和排放均未测出方向明确的改善。[配对汇总与全部区间](../benchmark_results/rolling_tree_closing/summary.json) · [逐路径结果](../benchmark_results/rolling_tree_closing/results.jsonl)

### 次要比较

下列比较均按各自的完整配对统计，只作描述。LB 的下界性质仅针对总成本。M2* 平局超时退回 16 次，该比较包含这些按协议执行的动作。逐路径核对台账，M2 和 M2* 的 1,920 个动作中有 1 个不同，160 条路径的总成本、即时满足率和排放逐条相同。相对于现行 B1，M1 平均贵 7.255（+2.93%），即时满足率低 3.972 个百分点，排放少 7.606。

| 比较 | 路径 | 指标 | 平均差 | 占对照均值 | 配对 t 95% 区间 | bootstrap 95% 区间 |
|---|---|---|---|---|---|---|
| `M1-M2*` | 160 | 总成本 | +0.205 | 0.08% | [−1.662, +2.071] | [−1.610, +2.107] |
| `M1-M2*` | 160 | 即时满足率（百分点） | +0.192 | 0.22% | [−0.00026, +0.38373] | [−0.00071, +0.38042] |
| `M1-M2*` | 160 | 排放 | −0.281 | -0.28% | [−0.685, +0.123] | [−0.681, +0.113] |
| `M1-B1` | 160 | 总成本 | +7.255 | 2.93% | [+0.987, +13.523] | [+1.184, +13.694] |
| `M1-B1` | 160 | 即时满足率（百分点） | −3.972 | -4.38% | [−4.65296, −3.29050] | [−4.65969, −3.28957] |
| `M1-B1` | 160 | 排放 | −7.606 | -7.10% | [−8.971, −6.241] | [−8.944, −6.263] |
| `M2-B1` | 160 | 总成本 | +7.051 | 2.84% | [+0.884, +13.217] | [+1.162, +13.370] |
| `M2-B1` | 160 | 即时满足率（百分点） | −4.163 | -4.59% | [−4.87222, −3.45470] | [−4.87517, −3.46140] |
| `M2-B1` | 160 | 排放 | −7.325 | -6.84% | [−8.632, −6.018] | [−8.613, −6.019] |
| `B1-B0` | 160 | 总成本 | −40.607 | -14.07% | [−54.890, −26.324] | [−55.423, −26.858] |
| `B1-B0` | 160 | 即时满足率（百分点） | +6.656 | 7.92% | [+5.57419, +7.73689] | [+5.59159, +7.73412] |
| `B1-B0` | 160 | 排放 | +14.969 | 16.25% | [+13.155, +16.782] | [+13.162, +16.744] |
| `M1-LB` | 160 | 总成本 | +154.529 | 153.35% | [+140.509, +168.550] | [+141.106, +168.983] |
| `M1-LB` | 160 | 即时满足率（百分点） | −12.021 | -12.18% | [−13.47693, −10.56443] | [−13.49854, −10.60595] |
| `M1-LB` | 160 | 排放 | +36.744 | 58.58% | [+34.352, +39.135] | [+34.393, +39.050] |
| `M2-LB` | 160 | 总成本 | +154.324 | 153.14% | [+140.958, +167.690] | [+141.381, +168.273] |
| `M2-LB` | 160 | 即时满足率（百分点） | −12.212 | -12.37% | [−13.66434, −10.76049] | [−13.68512, −10.79421] |
| `M2-LB` | 160 | 排放 | +37.025 | 59.03% | [+34.629, +39.421] | [+34.650, +39.350] |
| `M2*-LB` | 160 | 总成本 | +154.324 | 153.14% | [+140.958, +167.690] | [+141.381, +168.273] |
| `M2*-LB` | 160 | 即时满足率（百分点） | −12.212 | -12.37% | [−13.66434, −10.76049] | [−13.68512, −10.79421] |
| `M2*-LB` | 160 | 排放 | +37.025 | 59.03% | [+34.629, +39.421] | [+34.650, +39.350] |
| `B1-LB` | 160 | 总成本 | +147.274 | 146.15% | [+135.712, +158.835] | [+136.238, +159.171] |
| `B1-LB` | 160 | 即时满足率（百分点） | −8.049 | -8.16% | [−9.24598, −6.85192] | [−9.27053, −6.88318] |
| `B1-LB` | 160 | 排放 | +44.350 | 70.71% | [+41.818, +46.882] | [+41.756, +46.756] |
| `B0-LB` | 160 | 总成本 | +187.881 | 186.44% | [+166.379, +209.383] | [+167.489, +210.021] |
| `B0-LB` | 160 | 即时满足率（百分点） | −14.704 | -14.90% | [−16.38795, −13.02103] | [−16.40176, −13.05842] |
| `B0-LB` | 160 | 排放 | +29.381 | 46.85% | [+27.021, +31.742] | [+27.006, +31.669] |

### 四类需求过程

每种过程分配 40 条路径。upshift 的平均成本差为 +3.763，其余三组为负。四组成本 t 区间均跨零。第一张表为主要比较。第二张表每格依次列出完整配对数、成本差、即时满足率百分点差、排放差。机器可读汇总给出每个过程、每个对照、每个指标的相对量和两种区间。[配对汇总与全部区间](../benchmark_results/rolling_tree_closing/summary.json) · [逐路径结果](../benchmark_results/rolling_tree_closing/results.jsonl)

| 过程 | 路径 | 指标 | 平均差 | 占对照均值 | 配对 t 95% 区间 | bootstrap 95% 区间 |
|---|---|---|---|---|---|---|
| stable | 40 | 总成本 | −1.386 | -0.65% | [−4.162, +1.389] | [−4.318, +0.953] |
| stable | 40 | 即时满足率（百分点） | +0.289 | 0.32% | [−0.03236, +0.61114] | [+0.00337, +0.60593] |
| stable | 40 | 排放 | −0.125 | -0.12% | [−1.172, +0.922] | [−1.125, +0.900] |
| volatile | 40 | 总成本 | −0.259 | -0.11% | [−1.754, +1.237] | [−1.713, +1.157] |
| volatile | 40 | 即时满足率（百分点） | +0.162 | 0.19% | [−0.22357, +0.54753] | [−0.21933, +0.51922] |
| volatile | 40 | 排放 | −0.375 | -0.39% | [−1.123, +0.373] | [−1.100, +0.325] |
| upshift | 40 | 总成本 | +3.763 | 0.93% | [−2.802, +10.327] | [−2.200, +10.266] |
| upshift | 40 | 即时满足率（百分点） | +0.060 | 0.08% | [−0.36934, +0.48942] | [−0.35776, +0.46734] |
| upshift | 40 | 排放 | +0.050 | 0.04% | [−0.547, +0.647] | [−0.500, +0.650] |
| downshift | 40 | 总成本 | −1.299 | -0.75% | [−3.466, +0.868] | [−3.424, +0.785] |
| downshift | 40 | 即时满足率（百分点） | +0.256 | 0.28% | [−0.18110, +0.69216] | [−0.15515, +0.67799] |
| downshift | 40 | 排放 | −0.675 | -0.82% | [−1.539, +0.189] | [−1.550, +0.100] |

| 比较 | stable | volatile | upshift | downshift |
|---|---|---|---|---|
| `M1-M2*` | 40 / −1.39 / +0.29 / −0.13 | 40 / −0.26 / +0.16 / −0.38 | 40 / +3.76 / +0.06 / +0.05 | 40 / −1.30 / +0.26 / −0.68 |
| `M1-B1` | 40 / +5.31 / −3.91 / −7.33 | 40 / +0.63 / −3.35 / −6.05 | 40 / +39.98 / −7.20 / −3.85 | 40 / −16.90 / −1.43 / −13.20 |
| `M2-B1` | 40 / +6.69 / −4.20 / −7.20 | 40 / +0.89 / −3.52 / −5.67 | 40 / +36.22 / −7.26 / −3.90 | 40 / −15.60 / −1.68 / −12.53 |
| `B1-B0` | 40 / −20.60 / +6.63 / +13.10 | 40 / −47.49 / +7.41 / +10.82 | 40 / −93.13 / +7.71 / +15.50 | 40 / −1.21 / +4.88 / +20.45 |
| `M1-LB` | 40 / +129.54 / −9.90 / +41.60 | 40 / +134.24 / −10.17 / +35.60 | 40 / +246.70 / −21.91 / +33.30 | 40 / +107.64 / −6.11 / +36.48 |
| `M2-LB` | 40 / +130.92 / −10.19 / +41.73 | 40 / +134.50 / −10.33 / +35.98 | 40 / +242.94 / −21.97 / +33.25 | 40 / +108.94 / −6.36 / +37.15 |
| `M2*-LB` | 40 / +130.92 / −10.19 / +41.73 | 40 / +134.50 / −10.33 / +35.98 | 40 / +242.94 / −21.97 / +33.25 | 40 / +108.94 / −6.36 / +37.15 |
| `B1-LB` | 40 / +124.23 / −6.00 / +48.92 | 40 / +133.61 / −6.82 / +41.65 | 40 / +206.72 / −14.71 / +37.15 | 40 / +124.54 / −4.68 / +49.67 |
| `B0-LB` | 40 / +144.83 / −12.62 / +35.83 | 40 / +181.09 / −14.23 / +30.82 | 40 / +299.85 / −22.42 / +21.65 | 40 / +125.75 / −9.55 / +29.23 |

### 哪一期、哪种备件改变了发运

完整配对中 133 条（83.1%）出现动作分歧，27 条全程动作相同。有分歧组的 D 均值为 0.246、p95 为 15.470。全程相同组的 D 恰为 0。下表计数均按路径，涉及多个 SKU 或路线的同一条路径可进入多列。慢线共涉及 126 条，快线涉及 24 条。

| 首次分歧期次（第 1–12 期） | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 路径数 | 26 | 17 | 25 | 18 | 10 | 6 | 13 | 6 | 6 | 6 | 0 | 0 |

| 备件 | 慢线件数改变的路径 | 快线件数改变的路径 | 任一路线改变的路径 |
|---|---|---|---|
| SKU1 | 73 | 7 | 74 |
| SKU2 | 66 | 10 | 71 |
| SKU3 | 66 | 9 | 67 |

按登记路径顺序取首个有分歧的例子。`closing-stable-75011` 的第 1 期，M1 减 M2 的发运件数矩阵为 `[[0, 0], [0, -1], [0, 0]]`（行对应 SKU1–3，列为慢线、快线）。M1 在快线上少发 1 件 SKU2，慢线分配相同。两者装载率（慢 / 快）分别为 100.00% / 0.00%、100.00% / 50.00%，当期发运分别消耗窗口碳配额的 12.12%、24.24%。该路径最终 D 为 −0.600。 [逐条首次分歧](../benchmark_results/rolling_tree_closing/divergences.json) · [逐期轨迹](../benchmark_results/rolling_tree_closing/traces.jsonl)

下表的分母为 133 条首次分歧路径。装载率按发运质量除以该路线容量计算。碳约束取紧指所选计划至少一条叶路径用满窗口碳配额，其含义是用满资源，不能据此推断因果效应。

| 方法 | 慢线满载 | 规划窗口碳约束取紧 |
|---|---|---|
| `M1` | 60.90% | 15.04% |
| `M2` | 57.14% | 11.28% |

### 计算与复算

计时在共享机器上测得。第二次试算估计 7930.677 秒，正式运行 4064.738 秒，归档 960 条轨迹、9120 次求解。表中 M1 至 B0 按在线决策尝试计时，LB 按每条路径一次离线求解计时。超时已包含在非最优数内。[求解记录](../benchmark_results/rolling_tree_closing/solves.jsonl) · [用量](../benchmark_results/rolling_tree_closing/execution.json) · [运行环境](../benchmark_results/rolling_tree_closing/runtime.json)

| 方法 | 计时次数 | 平均秒 | p95 秒 | 求解数 | 非最优 | 其中超时 | 退回 | 不完整轨迹 |
|---|---|---|---|---|---|---|---|---|
| `M1` | 1920 | 0.25131 | 0.72977 | 1760 | 0 | 0 | 0 | 0 |
| `M2` | 1920 | 0.27088 | 0.79474 | 1760 | 0 | 0 | 0 | 0 |
| `M2*` | 1920 | 1.57451 | 8.25564 | 3520 | 16 | 16 | 16 | 0 |
| `B1` | 1920 | 0.01096 | 0.02067 | 1920 | 0 | 0 | 0 | 0 |
| `B0` | 1920 | 0.00038 | 0.00078 | 0 | 0 | 0 | 0 | 0 |
| `LB` | 160 | 0.01031 | 0.01841 | 160 | 0 | 0 | 0 | 0 |

在仓库根目录运行 `python -m rolling_tree verify5` 可无求解核对 SHA256、重建任务和情景、按动作重放台账并复算全部区间。此次复算重建 160 条路径、10720 组情景，重放 11520 条逐期台账，求解 0 次。完整重跑命令为 `python -m rolling_tree closing --output <空目录> --max-wall-seconds 14400`。[SHA256 清单](../benchmark_results/rolling_tree_closing/manifest.json) · [执行代码](../rolling_tree/closing.py) · [复算代码](../rolling_tree/closing_replay.py)

### 局限与下一项验收

数据来自一个合成环境，每条路径只用一个规划采样种子。原 v2 开发门槛未通过，本轮只回答已登记的收尾问题，尚待独立验证。HiGHS 预处理在项目另一模块出现过错误最优与误报不可行。这里保留原求解设置，个别首期动作及基于最优值的超额可能受影响。给定已执行动作后的实际成本由环境独立记账。求解改变动作时，策略仍可能走出不同轨迹。若重启，可先在独立校准的环境中事前登记相同的路径配对和成本、服务、排放门槛，再检验结果能否复现。

## English

### Question and sample

With identical information and marginal SKU scenarios at a shared state, does preserving contemporaneous cross-SKU pairing change allocation of limited freight capacity and improve realized cost, immediate fill or emissions? The preregistered test ran once on 160 fresh synthetic paths using 40 demand seeds across four profiles, 12 periods each, with M1, M2 and M2* sharing one planning seed per path. M1 preserves pairing. M2 permutes pairing and takes its own optimal first action. Both replan each period from their own realized state. M2* minimizes the M1 objective on the M2 optimal face, falling back to its own action after a tie-solve timeout. B1 uses the seven-scenario rolling EWMA planner, B0 uses base-stock with z=1, and LB is the full-foresight cost bound. [Protocol](rolling_tree_closing_protocol.md) · [Budget amendment](rolling_tree_closing_protocol_amendment.md) · [Configuration](../benchmark_results/rolling_tree_closing/config.json) · [Path index](../benchmark_results/rolling_tree_closing/tasks.json)

### Primary comparison and decision

M1 and M2 completed all 160 path pairs. On each path D = cost(M1) − cost(M2), using freight, carbon price, holding, periodic backlog and terminal backlog costs. All differences subtract the second policy from the first. Cost and emissions use synthetic environment units. Relative differences use the comparator mean for those same pairs. Immediate fill is the share of demand served in its arrival period. Absolute fill differences are in percentage points. The t interval uses paths as observations. The bootstrap resamples the same path indices across all three outcomes, with 10,000 draws and seed 979301.

| Contrast | Paths | Outcome | Mean difference | Relative to comparator | Paired t 95% CI | Bootstrap 95% CI |
|---|---|---|---|---|---|---|
| `M1-M2` | 160 | Total cost | +0.205 | 0.08% | [−1.662, +2.071] | [−1.610, +2.107] |
| `M1-M2` | 160 | Immediate fill (pp) | +0.192 | 0.22% | [−0.00026, +0.38373] | [−0.00071, +0.38042] |
| `M1-M2` | 160 | Emissions | −0.281 | -0.28% | [−0.685, +0.123] | [−0.681, +0.113] |

Mean M2 cost was 255.095, giving a practical 2% margin of ±5.102. The primary cost t interval gave the preregistered classification **equivalent within the practical cost margin**. Guardrails allow a mean fill decline of up to 0.5 percentage points and a relative emissions increase of up to 2%. Both intervals included zero for all three outcomes. The entire cost interval was inside the equivalence margin. Immediate fill and emissions did not show a clear directional improvement. [All contrasts and intervals](../benchmark_results/rolling_tree_closing/summary.json) · [Path outcomes](../benchmark_results/rolling_tree_closing/results.jsonl)

### Secondary comparisons

Each descriptive contrast uses its own complete pairs. LB bounds total cost only. The M2* comparison includes the 16 prescribed tie-timeout fallbacks. A descriptive ledger check found one difference among 1,920 M2 and M2* actions, with identical total cost, fill and emissions on each of the 160 paths. Against B1, M1 cost 7.255 more on average (+2.93%), delivered 3.972 percentage points less immediate fill and emitted 7.606 less.

| Contrast | Paths | Outcome | Mean difference | Relative to comparator | Paired t 95% CI | Bootstrap 95% CI |
|---|---|---|---|---|---|---|
| `M1-M2*` | 160 | Total cost | +0.205 | 0.08% | [−1.662, +2.071] | [−1.610, +2.107] |
| `M1-M2*` | 160 | Immediate fill (pp) | +0.192 | 0.22% | [−0.00026, +0.38373] | [−0.00071, +0.38042] |
| `M1-M2*` | 160 | Emissions | −0.281 | -0.28% | [−0.685, +0.123] | [−0.681, +0.113] |
| `M1-B1` | 160 | Total cost | +7.255 | 2.93% | [+0.987, +13.523] | [+1.184, +13.694] |
| `M1-B1` | 160 | Immediate fill (pp) | −3.972 | -4.38% | [−4.65296, −3.29050] | [−4.65969, −3.28957] |
| `M1-B1` | 160 | Emissions | −7.606 | -7.10% | [−8.971, −6.241] | [−8.944, −6.263] |
| `M2-B1` | 160 | Total cost | +7.051 | 2.84% | [+0.884, +13.217] | [+1.162, +13.370] |
| `M2-B1` | 160 | Immediate fill (pp) | −4.163 | -4.59% | [−4.87222, −3.45470] | [−4.87517, −3.46140] |
| `M2-B1` | 160 | Emissions | −7.325 | -6.84% | [−8.632, −6.018] | [−8.613, −6.019] |
| `B1-B0` | 160 | Total cost | −40.607 | -14.07% | [−54.890, −26.324] | [−55.423, −26.858] |
| `B1-B0` | 160 | Immediate fill (pp) | +6.656 | 7.92% | [+5.57419, +7.73689] | [+5.59159, +7.73412] |
| `B1-B0` | 160 | Emissions | +14.969 | 16.25% | [+13.155, +16.782] | [+13.162, +16.744] |
| `M1-LB` | 160 | Total cost | +154.529 | 153.35% | [+140.509, +168.550] | [+141.106, +168.983] |
| `M1-LB` | 160 | Immediate fill (pp) | −12.021 | -12.18% | [−13.47693, −10.56443] | [−13.49854, −10.60595] |
| `M1-LB` | 160 | Emissions | +36.744 | 58.58% | [+34.352, +39.135] | [+34.393, +39.050] |
| `M2-LB` | 160 | Total cost | +154.324 | 153.14% | [+140.958, +167.690] | [+141.381, +168.273] |
| `M2-LB` | 160 | Immediate fill (pp) | −12.212 | -12.37% | [−13.66434, −10.76049] | [−13.68512, −10.79421] |
| `M2-LB` | 160 | Emissions | +37.025 | 59.03% | [+34.629, +39.421] | [+34.650, +39.350] |
| `M2*-LB` | 160 | Total cost | +154.324 | 153.14% | [+140.958, +167.690] | [+141.381, +168.273] |
| `M2*-LB` | 160 | Immediate fill (pp) | −12.212 | -12.37% | [−13.66434, −10.76049] | [−13.68512, −10.79421] |
| `M2*-LB` | 160 | Emissions | +37.025 | 59.03% | [+34.629, +39.421] | [+34.650, +39.350] |
| `B1-LB` | 160 | Total cost | +147.274 | 146.15% | [+135.712, +158.835] | [+136.238, +159.171] |
| `B1-LB` | 160 | Immediate fill (pp) | −8.049 | -8.16% | [−9.24598, −6.85192] | [−9.27053, −6.88318] |
| `B1-LB` | 160 | Emissions | +44.350 | 70.71% | [+41.818, +46.882] | [+41.756, +46.756] |
| `B0-LB` | 160 | Total cost | +187.881 | 186.44% | [+166.379, +209.383] | [+167.489, +210.021] |
| `B0-LB` | 160 | Immediate fill (pp) | −14.704 | -14.90% | [−16.38795, −13.02103] | [−16.40176, −13.05842] |
| `B0-LB` | 160 | Emissions | +29.381 | 46.85% | [+27.021, +31.742] | [+27.006, +31.669] |

### Demand profiles

Each profile has 40 assigned paths. Mean cost difference was +3.763 for upshift and negative in each other profile. All four cost t intervals included zero. The first table gives the primary contrast. Each cell of the second table lists complete pairs / cost difference / fill difference in percentage points / emissions difference. The machine-readable summary includes relative differences and both intervals for all metrics, profiles and contrasts. [All contrasts and intervals](../benchmark_results/rolling_tree_closing/summary.json) · [Path outcomes](../benchmark_results/rolling_tree_closing/results.jsonl)

| Profile | Paths | Outcome | Mean difference | Relative to comparator | Paired t 95% CI | Bootstrap 95% CI |
|---|---|---|---|---|---|---|
| stable | 40 | Total cost | −1.386 | -0.65% | [−4.162, +1.389] | [−4.318, +0.953] |
| stable | 40 | Immediate fill (pp) | +0.289 | 0.32% | [−0.03236, +0.61114] | [+0.00337, +0.60593] |
| stable | 40 | Emissions | −0.125 | -0.12% | [−1.172, +0.922] | [−1.125, +0.900] |
| volatile | 40 | Total cost | −0.259 | -0.11% | [−1.754, +1.237] | [−1.713, +1.157] |
| volatile | 40 | Immediate fill (pp) | +0.162 | 0.19% | [−0.22357, +0.54753] | [−0.21933, +0.51922] |
| volatile | 40 | Emissions | −0.375 | -0.39% | [−1.123, +0.373] | [−1.100, +0.325] |
| upshift | 40 | Total cost | +3.763 | 0.93% | [−2.802, +10.327] | [−2.200, +10.266] |
| upshift | 40 | Immediate fill (pp) | +0.060 | 0.08% | [−0.36934, +0.48942] | [−0.35776, +0.46734] |
| upshift | 40 | Emissions | +0.050 | 0.04% | [−0.547, +0.647] | [−0.500, +0.650] |
| downshift | 40 | Total cost | −1.299 | -0.75% | [−3.466, +0.868] | [−3.424, +0.785] |
| downshift | 40 | Immediate fill (pp) | +0.256 | 0.28% | [−0.18110, +0.69216] | [−0.15515, +0.67799] |
| downshift | 40 | Emissions | −0.675 | -0.82% | [−1.539, +0.189] | [−1.550, +0.100] |

| Contrast | stable | volatile | upshift | downshift |
|---|---|---|---|---|
| `M1-M2*` | 40 / −1.39 / +0.29 / −0.13 | 40 / −0.26 / +0.16 / −0.38 | 40 / +3.76 / +0.06 / +0.05 | 40 / −1.30 / +0.26 / −0.68 |
| `M1-B1` | 40 / +5.31 / −3.91 / −7.33 | 40 / +0.63 / −3.35 / −6.05 | 40 / +39.98 / −7.20 / −3.85 | 40 / −16.90 / −1.43 / −13.20 |
| `M2-B1` | 40 / +6.69 / −4.20 / −7.20 | 40 / +0.89 / −3.52 / −5.67 | 40 / +36.22 / −7.26 / −3.90 | 40 / −15.60 / −1.68 / −12.53 |
| `B1-B0` | 40 / −20.60 / +6.63 / +13.10 | 40 / −47.49 / +7.41 / +10.82 | 40 / −93.13 / +7.71 / +15.50 | 40 / −1.21 / +4.88 / +20.45 |
| `M1-LB` | 40 / +129.54 / −9.90 / +41.60 | 40 / +134.24 / −10.17 / +35.60 | 40 / +246.70 / −21.91 / +33.30 | 40 / +107.64 / −6.11 / +36.48 |
| `M2-LB` | 40 / +130.92 / −10.19 / +41.73 | 40 / +134.50 / −10.33 / +35.98 | 40 / +242.94 / −21.97 / +33.25 | 40 / +108.94 / −6.36 / +37.15 |
| `M2*-LB` | 40 / +130.92 / −10.19 / +41.73 | 40 / +134.50 / −10.33 / +35.98 | 40 / +242.94 / −21.97 / +33.25 | 40 / +108.94 / −6.36 / +37.15 |
| `B1-LB` | 40 / +124.23 / −6.00 / +48.92 | 40 / +133.61 / −6.82 / +41.65 | 40 / +206.72 / −14.71 / +37.15 | 40 / +124.54 / −4.68 / +49.67 |
| `B0-LB` | 40 / +144.83 / −12.62 / +35.83 | 40 / +181.09 / −14.23 / +30.82 | 40 / +299.85 / −22.42 / +21.65 | 40 / +125.75 / −9.55 / +29.23 |

### First changes in dispatch

Actions diverged on 133 complete pairs (83.1%), and remained identical on 27. The divergent group had mean D 0.246 and p95 15.470. Identical trajectories had D exactly zero. Tables count paths. A path can change multiple SKUs or routes. The slow route changed on 126 paths and the fast route on 24.

| First divergent period (1–12) | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Paths | 26 | 17 | 25 | 18 | 10 | 6 | 13 | 6 | 6 | 6 | 0 | 0 |

| Part | Paths with a slow-route change | Paths with a fast-route change | Paths with either route changing |
|---|---|---|---|
| SKU1 | 73 | 7 | 74 |
| SKU2 | 66 | 10 | 71 |
| SKU3 | 66 | 9 | 67 |

The first divergent example in registered path order is `closing-stable-75011`, period 1. Its M1 minus M2 unit matrix was `[[0, 0], [0, -1], [0, 0]]` (rows SKU1–3, columns slow and fast). M1 sent one fewer SKU2 unit on the fast route, with identical slow-route allocations. Slow/fast loads were 100.00% / 0.00% for M1 and 100.00% / 50.00% for M2. Dispatch used 12.12% and 24.24% of the window allowance, respectively. Final path D was −0.600. [First divergence by path](../benchmark_results/rolling_tree_closing/divergences.json) · [Period ledgers](../benchmark_results/rolling_tree_closing/traces.jsonl)

Denominators below are the 133 divergent pairs. Load is shipped mass divided by route capacity. Binding planned carbon means at least one leaf used the entire window allowance. This measures resource use and does not identify a causal effect.

| Method | Slow route full | Planned window carbon binding |
|---|---|---|
| `M1` | 60.90% | 15.04% |
| `M2` | 57.14% | 11.28% |

### Computation and replay

Times were measured on a shared machine. Retiming estimated 7930.677 s. Formal execution took 4064.738 s and recorded 960 trajectories and 9120 solves. M1 through B0 time each online decision attempt. LB times one offline solve per path. Timeouts are included in nonoptimal returns. [Solve records](../benchmark_results/rolling_tree_closing/solves.jsonl) · [Execution](../benchmark_results/rolling_tree_closing/execution.json) · [Runtime](../benchmark_results/rolling_tree_closing/runtime.json)

| Method | Timed attempts | Mean s | p95 s | Solves | Nonoptimal | Timeouts | Fallbacks | Incomplete trajectories |
|---|---|---|---|---|---|---|---|---|
| `M1` | 1920 | 0.25131 | 0.72977 | 1760 | 0 | 0 | 0 | 0 |
| `M2` | 1920 | 0.27088 | 0.79474 | 1760 | 0 | 0 | 0 | 0 |
| `M2*` | 1920 | 1.57451 | 8.25564 | 3520 | 16 | 16 | 16 | 0 |
| `B1` | 1920 | 0.01096 | 0.02067 | 1920 | 0 | 0 | 0 | 0 |
| `B0` | 1920 | 0.00038 | 0.00078 | 0 | 0 | 0 | 0 | 0 |
| `LB` | 160 | 0.01031 | 0.01841 | 160 | 0 | 0 | 0 | 0 |

From the repository root, `python -m rolling_tree verify5` checks SHA256, regenerates tasks and scenarios, replays recorded actions and recomputes all intervals. The replay regenerated 160 paths and 10720 scenario sets, checked 11520 period ledger entries and ran zero solves. To repeat the entire study use `python -m rolling_tree closing --output <empty-directory> --max-wall-seconds 14400`. [SHA256 manifest](../benchmark_results/rolling_tree_closing/manifest.json) · [Execution](../rolling_tree/closing.py) · [Replay](../rolling_tree/closing_replay.py)

### Limitations and next acceptance condition

The data come from one synthetic environment with one planning seed per path. Two original v2 development gates failed. This registered closing test addresses the stated question and awaits independent validation. Elsewhere in the project HiGHS presolve returned incorrect optima and false infeasibility. The retained settings could affect some selected first actions and objective excesses. The environment independently accounts for the realized cost of the actions taken. A solver-induced change in actions can still change a trajectory. A follow-up could preregister the same pairing and cost, fill and emissions criteria in an independently calibrated environment, then test replication.
