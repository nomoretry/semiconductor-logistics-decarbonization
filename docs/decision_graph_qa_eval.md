# 决策图问答离线评测与信息价值 / Decision graph QA offline evaluation and information value

本文先中文、后英文。The Chinese report precedes its English version.

## 中文

### 问题与实现

研究问题是滚动补货与运输中，拿掉一类库存、需求或共享资源信息会如何改变本期发运及其成本、即时满足率和排放。DQ-2 使用 DQ-1 的单一合成环境，覆盖 40 条需求路径、80 条行为轨迹和 880 张图。train、dev、test 分别有 352、176、352 张图，每图 31 题。评测框架用公开状态和当前题目生成 `None` 输入，`Chain` 加直接父节点问答，`Graph` 加全部祖先问答。有上游答案时可用 `gold` 标准答案或 `own` 前序作答。回答文件按图记录 `id` 和 `answers`。[事前协议](decision_graph_qa_eval_protocol.md) · [DQ-1 数据](decision_graph_qa.md) · [评测实现](../decision_graph_qa/evaluation.py)

B 的计划超额是固定动作后七情景求解的目标值减参照最优值。实际后果从核对过的同一历史状态分支，比较执行该动作或已存参照动作后在同一真实需求路径上的余期账本。两支从下一期起使用同一 `mpc_scenarios` 续行策略。真实约束下的违约动作不执行。成本差、即时满足率差和排放差均为测试动作减参照动作，成本与排放使用合成环境的单位，即时满足率用百分点。[逐期执行与复核](../decision_graph_qa/consequence.py)

### 运行与复算

| 运行 | 图 | 需求路径 | 行为轨迹 | 记录墙钟（秒） | 单图 p95（秒） | 求解次数 | 失败调用 | 实际后果缓存命中 |
|---|---|---|---|---|---|---|---|---|
| 试算 | 66 | 3 | 6 | 50.90 | 1.432 | 4,080 | 0 | 1,295 |
| 正式 | 880 | 40 | 80 | 794.57 | 2.028 | 55,195 | 0 | 17,317 |

独立复算验证了 880 张图和 12 个清单文件的 SHA256，并从原始证据重算结果与区间。正式运行结束后，DQ-1 的 `verify` 再次通过，核对 880 张图、8 个文件的 SHA256 和 JSON Schema 2020-12。两项核验均为零求解。[评测复算实现](../decision_graph_qa/eval_run.py) · [DQ-1 清单](../benchmark_results/decision_graph_qa_v1/manifest.json)

试算在每个划分各取一条 stable 需求路径，保留两种历史策略。按 p95 × 880 + 60 秒估计正式墙钟为 1,320.04 秒，通过 5,400 秒门槛。试算证据保存在本地运行记录，正式配置登记了该清单的 SHA256。正式运行以单进程顺序执行，每次求解上限 30 秒。金标准各组合均为 27,280/27,280 题正确，880 张图的三项实际差均为零，计划超额在 DQ-1 容差内。[正式配置](../benchmark_results/decision_graph_qa_eval_v1/config.json) · [逐图与逐期证据](../benchmark_results/decision_graph_qa_eval_v1/attempts.jsonl.gz) · [12 个文件的 SHA256 清单](../benchmark_results/decision_graph_qa_eval_v1/manifest.json)

### 离线基线

`gold` 读取标准答案，`perturbed` 使用固定扰动，`rule` 用 z=1.0 的补货规则推导当期动作和 P3，后续计划为零，`file` 读取序列化后再载入的标准答案。三种上下文与两种来源共六组，每个答题方都执行这六组。下表每行使用该答题方六组共有的结果。上下文文本改变了输入长度，离线答题方忽略文本，因此相同分数只用于核对框架。独立题目总数为 27,280，组合重复使用这些题目。[逐题汇总](../benchmark_results/decision_graph_qa_eval_v1/summary.json) · [文件答题输入](../benchmark_results/decision_graph_qa_eval_v1/file_responses.jsonl)

| 答题方 | 模式 / 来源 | P1 / P2 / P3 / B / M 正确率（%） | P3/B/M 违约 | B 违约 | 计划超额 | 相对超额（%） | 实际成本差 | 即时满足率差（百分点） | 排放差 | 各 B 后果的 n |
|---|---|---|---|---|---|---|---|---|---|---|
| `gold` | `None/gold`, `None/own`, `Chain/gold`, `Chain/own`, `Graph/gold`, `Graph/own` | 100.00 / 100.00 / 100.00 / 100.00 / 100.00 | 0/7,040 (0.00%) | 0/880 (0.00%) | 0.00 | 0.00 | 0.00 | 0.000 | 0.00 | 880 |
| `perturbed` | `None/gold`, `None/own`, `Chain/gold`, `Chain/own`, `Graph/gold`, `Graph/own` | 91.67 / 90.91 / 83.33 / 0.00 / 0.00 | 2,640/7,040 (37.50%) | 880/880 (100.00%) | — | — | — | — | — | 0 |
| `rule` | `None/gold`, `None/own`, `Chain/gold`, `Chain/own`, `Graph/gold`, `Graph/own` | 100.00 / 100.00 / 62.29 / 14.32 / 8.07 | 0/7,040 (0.00%) | 0/880 (0.00%) | 12.46 | 9.07 | 7.73 | -1.813 | -1.40 | 880 |
| `file` | `None/gold`, `None/own`, `Chain/gold`, `Chain/own`, `Graph/gold`, `Graph/own` | 100.00 / 100.00 / 100.00 / 100.00 / 100.00 | 0/7,040 (0.00%) | 0/880 (0.00%) | 0.00 | 0.00 | 0.00 | 0.000 | 0.00 | 880 |

阶段顺序为 P1 感知、P2 预测、P3 规划、B 行为、M 窗口计划。全阶段违约率按已提交的 P3、B、M 回答计算。B 指标为每张图动作的均值，违约或无结果时该指标缺失。计划超额比例以各图的参照目标为分母。`—` 表示无可用值。

### 上下文输入长度

各份导出均采用 test 划分和 `gold` 来源。长度按单题文本字符计，含状态、当前题目和模式允许的前序问答。独立核验确认每份文件有 10,912 个不同的图与节点组合，字符数全部与记录一致。

| 语言 | 模式 | 题数 | 最小 | 均值 | p95 | 最大 | 文件 |
|---|---|---|---|---|---|---|---|
| `zh` | `None` | 10,912 | 1,045 | 1313.4 | 1,565 | 1,589 | [JSONL](../benchmark_results/decision_graph_qa_eval_v1/prompts_test_None_zh.jsonl) |
| `zh` | `Chain` | 10,912 | 1,045 | 1379.0 | 1,668 | 1,800 | [JSONL](../benchmark_results/decision_graph_qa_eval_v1/prompts_test_Chain_zh.jsonl) |
| `zh` | `Graph` | 10,912 | 1,045 | 1519.5 | 2,160 | 2,550 | [JSONL](../benchmark_results/decision_graph_qa_eval_v1/prompts_test_Graph_zh.jsonl) |
| `en` | `None` | 10,912 | 1,208 | 1497.1 | 1,746 | 1,790 | [JSONL](../benchmark_results/decision_graph_qa_eval_v1/prompts_test_None_en.jsonl) |
| `en` | `Chain` | 10,912 | 1,208 | 1651.1 | 2,089 | 2,245 | [JSONL](../benchmark_results/decision_graph_qa_eval_v1/prompts_test_Chain_en.jsonl) |
| `en` | `Graph` | 10,912 | 1,208 | 1996.2 | 3,499 | 3,985 | [JSONL](../benchmark_results/decision_graph_qa_eval_v1/prompts_test_Graph_en.jsonl) |

### 信息价值

消融每次替换一类信息。I1 将在途量置零，I2 将未清积压置零，I3 使用长期均值替换滚动预测，I4 以满额周期预算乘剩余期比例替换剩余预算，I5 按 `base_mean × mass` 划分运力和碳额度并按 SKU 独立规划。H 直接取已存的事后已知需求首期动作。所有动作回到真实观测和真实路径评价。[消融实现](../decision_graph_qa/ablation.py)

表中为图均值及 95% 整群 bootstrap 区间。按 `(split, profile, seed)` 抽整条需求路径，每次保留组内的时点和行为轨迹，在组内有放回抽样 10,000 次，种子 984301。动作未变的图照常计入。`n` 顺序是动作变化、计划超额、相对计划超额、实际成本差、即时满足率差和排放差的有效图数。最右列以有违约判定的动作数为分母。[统计实现](../decision_graph_qa/eval_statistics.py) · [按划分、需求过程和行为策略交叉分组的完整结果](../benchmark_results/decision_graph_qa_eval_v1/summary.json)

#### Test · 352 图、16 条需求路径

| 项 | 动作变化（%） | 计划超额 | 相对超额（%） | 实际成本差 | 即时满足率差（百分点） | 排放差 | n | 违约 |
|---|---|---|---|---|---|---|---|---|
| I1 | 74.15 [68.75, 79.83] | 4.17 [3.66, 4.67] | 5.83 [4.62, 7.27] | 2.02 [-0.46, 4.37] | 0.138 [-0.284, 0.609] | 1.33 [0.68, 2.05] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| I2 | 22.16 [17.05, 28.69] | 0.28 [0.14, 0.47] | 0.14 [0.08, 0.21] | 0.31 [-0.55, 1.27] | 0.085 [0.003, 0.172] | 0.03 [-0.05, 0.13] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| I3 | 82.95 [79.55, 86.36] | 6.90 [5.64, 8.32] | 9.01 [7.37, 10.85] | -3.05 [-7.75, 0.39] | 0.255 [-0.165, 0.725] | 0.10 [-0.30, 0.53] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| I4 | 27.27 [19.03, 36.36] | 2.29 [0.48, 4.60] | 1.10 [0.24, 2.14] | 2.52 [0.12, 5.81] | -0.074 [-0.277, 0.078] | 0.13 [0.02, 0.25] | 352 / 330 / 330 / 330 / 330 / 330 | 22/352 |
| I5 | 88.07 [84.94, 90.91] | 16.51 [12.71, 20.65] | 11.82 [10.59, 13.03] | 9.45 [4.19, 15.65] | -2.288 [-3.000, -1.624] | -0.17 [-0.66, 0.32] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| H | 86.36 [83.24, 89.49] | 16.65 [14.63, 18.63] | 17.82 [14.89, 20.49] | -11.05 [-16.96, -6.46] | 1.670 [1.054, 2.258] | 0.61 [0.11, 1.15] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |

在 I1–I5 中，I5 的平均计划超额最高，实际成本增加也最大，为 9.45 [4.19, 15.65]。即时满足率下降 2.288 [1.624, 3.000] 个百分点，排放差的区间跨零。I1 的排放增幅点估计最大，为 1.33 [0.68, 2.05]。I4 有 22/352 个动作违反真实配额，其成本差 2.52 [0.12, 5.81] 仅来自其余 330 图。I3 的计划超额为 6.90 [5.64, 8.32]，实际成本差为 -3.05 [-7.75, 0.39]。这两个评价指标给出了不同的排序。事后参照 H 的计划超额为 16.65 [14.63, 18.63]，实际成本差为 -11.05 [-16.96, -6.46]。

#### Train · 352 图、16 条需求路径

| 项 | 动作变化（%） | 计划超额 | 相对超额（%） | 实际成本差 | 即时满足率差（百分点） | 排放差 | n | 违约 |
|---|---|---|---|---|---|---|---|---|
| I1 | 75.28 [70.17, 80.40] | 3.83 [3.34, 4.35] | 7.15 [5.50, 8.80] | 3.91 [1.36, 6.56] | 0.044 [-0.249, 0.320] | 1.74 [0.89, 2.61] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| I2 | 15.91 [11.36, 21.02] | 0.33 [0.06, 0.72] | 0.12 [0.04, 0.22] | -0.53 [-1.31, 0.20] | -0.027 [-0.132, 0.091] | -0.13 [-0.20, -0.07] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| I3 | 80.97 [76.70, 85.23] | 5.84 [4.79, 6.92] | 8.68 [6.62, 10.76] | 2.42 [-0.64, 6.45] | -0.399 [-0.792, -0.026] | -0.14 [-0.90, 0.65] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| I4 | 16.48 [11.36, 22.73] | 1.51 [0.07, 3.83] | 0.52 [0.05, 1.16] | 3.37 [0.03, 9.13] | -0.086 [-0.226, 0.036] | -0.06 [-0.15, 0.03] | 352 / 342 / 342 / 342 / 342 / 342 | 10/352 |
| I5 | 86.93 [83.24, 90.63] | 14.18 [10.04, 19.70] | 11.07 [9.65, 12.46] | 13.92 [4.67, 25.45] | -2.402 [-3.163, -1.712] | -0.85 [-1.34, -0.34] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| H | 86.65 [83.52, 89.49] | 19.23 [16.41, 22.70] | 19.31 [16.75, 21.49] | -6.56 [-9.94, -3.74] | 1.280 [0.848, 1.743] | 0.46 [-0.20, 1.11] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |

#### Dev · 176 图、8 条需求路径

| 项 | 动作变化（%） | 计划超额 | 相对超额（%） | 实际成本差 | 即时满足率差（百分点） | 排放差 | n | 违约 |
|---|---|---|---|---|---|---|---|---|
| I1 | 80.11 [75.00, 84.66] | 3.57 [3.29, 3.93] | 6.73 [4.55, 9.06] | 2.16 [-0.78, 5.10] | 0.096 [-0.494, 0.718] | 2.15 [1.08, 3.22] | 176 / 176 / 176 / 176 / 176 / 176 | 0/176 |
| I2 | 18.75 [12.50, 24.43] | 0.05 [0.01, 0.12] | 0.01 [0.00, 0.03] | 0.26 [-1.47, 1.71] | -0.117 [-0.309, 0.066] | -0.01 [-0.25, 0.18] | 176 / 176 / 176 / 176 / 176 / 176 | 0/176 |
| I3 | 89.77 [86.36, 93.18] | 6.76 [5.52, 8.06] | 11.34 [8.13, 14.73] | -2.78 [-6.65, 0.59] | 0.477 [-0.056, 1.089] | 0.57 [-0.28, 1.51] | 176 / 176 / 176 / 176 / 176 / 176 | 0/176 |
| I4 | 22.16 [13.64, 30.68] | 2.24 [0.00, 6.19] | 0.52 [0.00, 1.29] | 1.30 [-0.40, 3.92] | -0.181 [-0.412, 0.036] | -0.07 [-0.46, 0.18] | 176 / 172 / 172 / 172 / 172 / 172 | 4/176 |
| I5 | 86.93 [81.82, 90.91] | 14.60 [9.66, 20.37] | 10.79 [9.86, 11.87] | 17.78 [5.35, 34.17] | -2.794 [-3.632, -2.016] | -0.26 [-1.35, 0.83] | 176 / 176 / 176 / 176 / 176 / 176 | 0/176 |
| H | 86.93 [85.23, 88.64] | 14.63 [12.13, 16.76] | 16.72 [12.91, 19.99] | -7.67 [-13.77, -2.34] | 1.390 [0.428, 2.301] | 0.95 [-0.35, 2.24] | 176 / 176 / 176 / 176 / 176 / 176 | 0/176 |

### 局限和下一项验收

这些量化结果来自一个合成滚动库存与运输环境，以及事前指定的一组信息代替值。I5 的效果包括固定分配和将每条路线的 SKU 配额向下取整造成的运力损失。DQ-1 的 215/880 张图存在容差内的其它最优首期动作。动作变化率、实际后果也受到所存参照动作与消融方案择优方式的影响。H 是同一窗口内已知需求的单情景事后参照，H 的优化目标只覆盖已知需求窗口。固定滚动续行的实际成本差采用单独的模拟比较。[DQ-1 并列解审计](../benchmark_results/decision_graph_qa_v1/summary.json)

下一项验收是按已导出的题目、既定三种上下文和两种上游答案来源运行真实大模型评测，检查上下文是否改变回答、违约和 B 的实际后果。真实大模型评测需单独批准预算。用 `export-prompts` 生成题目后，将结果以 `id` 和 `answers` 写入 JSONL 交给 `evaluate --answers`，沿用同一评分和后果定义。

## English

### Research question and implementation

How does removing one source of inventory, demand or shared-resource information change current dispatch and its cost, immediate fulfillment and emissions? DQ-2 uses the single DQ-1 synthetic environment, with 40 demand paths, 80 behavior trajectories and 880 graphs. Train, dev and test contain 352, 176 and 352 graphs, each with 31 questions. The framework renders the public state and question in `None`, adds direct-parent QA in `Chain`, and adds all ancestor QA in `Graph`. Upstream answers use the stored `gold` or the responder's `own` preceding answers. Response files use per-graph `id` and `answers` fields. [Registered protocol](decision_graph_qa_eval_protocol.md) · [DQ-1 dataset](decision_graph_qa.md) · [Evaluation implementation](../decision_graph_qa/evaluation.py)

Planning excess for B is the seven-scenario objective after fixing the action minus the reference optimum. The realized comparison forks from the same checked historical state and runs the submitted and stored reference actions on the same realized demand path. Both branches use the same `mpc_scenarios` continuation from the next period. Actions violating the real constraints are skipped. Realized cost, immediate fulfillment and emissions differences are action minus reference. Cost and emissions use the synthetic environment's units. Immediate fulfillment differences use percentage points. [Period-level execution and verification](../decision_graph_qa/consequence.py)

### Runs and verification

| Run | Graphs | Demand paths | Behavior trajectories | Recorded wall time (s) | Per-graph p95 (s) | Solves | Failed calls | Realized consequence cache hits |
|---|---|---|---|---|---|---|---|---|
| Pilot | 66 | 3 | 6 | 50.90 | 1.432 | 4,080 | 0 | 1,295 |
| Formal | 880 | 40 | 80 | 794.57 | 2.028 | 55,195 | 0 | 17,317 |

Independent verification checked 880 graphs and 12 manifest file hashes and recomputed the summaries and intervals from raw evidence. After the formal run, DQ-1 `verify` passed again with 880 graphs, eight SHA256 file hashes and JSON Schema 2020-12. Both checks used zero solver calls. [Evaluation verification implementation](../decision_graph_qa/eval_run.py) · [DQ-1 manifest](../benchmark_results/decision_graph_qa_v1/manifest.json)

The pilot used one stable demand path per split with both history policies. The p95 × 880 + 60 s estimate was 1,320.04 s, within the 5,400 s gate. Pilot evidence is retained in local run records, and the formal configuration records the SHA256 of its manifest. Formal execution used one sequential process and a 30 s limit per solve. Every gold combination received full credit on 27,280 of 27,280 answers. All three realized differences were zero across 880 graphs and planning excess was within the DQ-1 tolerance. [Formal configuration](../benchmark_results/decision_graph_qa_eval_v1/config.json) · [Per-graph and period-level evidence](../benchmark_results/decision_graph_qa_eval_v1/attempts.jsonl.gz) · [SHA256 manifest for 12 files](../benchmark_results/decision_graph_qa_eval_v1/manifest.json)

### Offline baselines

`gold` reads the stored answers. `perturbed` uses the fixed perturbation. `rule` derives the current action and P3 from the z=1.0 replenishment rule and sets the later plan to zero. `file` reads back the serialized gold responses. Each responder runs all six combinations of three contexts and two sources. Each row reports the result shared by that responder's six combinations. Rendering changes the input lengths. The offline responders ignore the contents, so equal scores exercise the framework. The 27,280 distinct questions are reused across combinations. [Per-stage summary](../benchmark_results/decision_graph_qa_eval_v1/summary.json) · [File responder inputs](../benchmark_results/decision_graph_qa_eval_v1/file_responses.jsonl)

| Responder | Mode / source | P1 / P2 / P3 / B / M accuracy (%) | P3/B/M violations | B violations | Planning excess | Relative excess (%) | Realized cost Δ | Immediate fulfillment Δ (pp) | Emissions Δ | n per B outcome |
|---|---|---|---|---|---|---|---|---|---|---|
| `gold` | `None/gold`, `None/own`, `Chain/gold`, `Chain/own`, `Graph/gold`, `Graph/own` | 100.00 / 100.00 / 100.00 / 100.00 / 100.00 | 0/7,040 (0.00%) | 0/880 (0.00%) | 0.00 | 0.00 | 0.00 | 0.000 | 0.00 | 880 |
| `perturbed` | `None/gold`, `None/own`, `Chain/gold`, `Chain/own`, `Graph/gold`, `Graph/own` | 91.67 / 90.91 / 83.33 / 0.00 / 0.00 | 2,640/7,040 (37.50%) | 880/880 (100.00%) | — | — | — | — | — | 0 |
| `rule` | `None/gold`, `None/own`, `Chain/gold`, `Chain/own`, `Graph/gold`, `Graph/own` | 100.00 / 100.00 / 62.29 / 14.32 / 8.07 | 0/7,040 (0.00%) | 0/880 (0.00%) | 12.46 | 9.07 | 7.73 | -1.813 | -1.40 | 880 |
| `file` | `None/gold`, `None/own`, `Chain/gold`, `Chain/own`, `Graph/gold`, `Graph/own` | 100.00 / 100.00 / 100.00 / 100.00 / 100.00 | 0/7,040 (0.00%) | 0/880 (0.00%) | 0.00 | 0.00 | 0.00 | 0.000 | 0.00 | 880 |

Stage order is P1 perception, P2 prediction, P3 planning, B behavior and M window schedule. The all-stage violation denominator includes supplied P3, B and M replies. The B metrics are graph-level means over available results. Relative planning excess divides by the reference objective for each graph. An em dash indicates no available value.

### Context input lengths

Each export uses test and the `gold` source. Length counts characters per question, including the state, current question and preceding QA permitted by the mode. An independent check found 10,912 distinct graph and node pairs in each file and verified every recorded character count.

| Language | Mode | Questions | Min | Mean | p95 | Max | File |
|---|---|---|---|---|---|---|---|
| `zh` | `None` | 10,912 | 1,045 | 1313.4 | 1,565 | 1,589 | [JSONL](../benchmark_results/decision_graph_qa_eval_v1/prompts_test_None_zh.jsonl) |
| `zh` | `Chain` | 10,912 | 1,045 | 1379.0 | 1,668 | 1,800 | [JSONL](../benchmark_results/decision_graph_qa_eval_v1/prompts_test_Chain_zh.jsonl) |
| `zh` | `Graph` | 10,912 | 1,045 | 1519.5 | 2,160 | 2,550 | [JSONL](../benchmark_results/decision_graph_qa_eval_v1/prompts_test_Graph_zh.jsonl) |
| `en` | `None` | 10,912 | 1,208 | 1497.1 | 1,746 | 1,790 | [JSONL](../benchmark_results/decision_graph_qa_eval_v1/prompts_test_None_en.jsonl) |
| `en` | `Chain` | 10,912 | 1,208 | 1651.1 | 2,089 | 2,245 | [JSONL](../benchmark_results/decision_graph_qa_eval_v1/prompts_test_Chain_en.jsonl) |
| `en` | `Graph` | 10,912 | 1,208 | 1996.2 | 3,499 | 3,985 | [JSONL](../benchmark_results/decision_graph_qa_eval_v1/prompts_test_Graph_en.jsonl) |

### Information value

Each ablation replaces one information category. I1 sets pipeline arrivals to zero. I2 sets outstanding backlog to zero. I3 replaces the rolling forecast with the long-run mean. I4 replaces remaining budget with the full-episode budget times the fraction of periods remaining. I5 allocates capacity and emissions allowance by `base_mean × mass` and plans each SKU separately. H uses the stored first action with known demand. Evaluate every action under the real observation and realized demand path. [Ablation implementation](../decision_graph_qa/ablation.py)

The tables report graph-level means and 95% cluster bootstrap intervals. Clusters are `(split, profile, seed)` demand paths, resampled with replacement 10,000 times within each group with seed 984301, keeping the times and behavior trajectories in the group. Graphs with unchanged actions remain in the calculations. The six `n` values are the available graph counts in metric order. The last column uses the number of actions assessed for violations as its denominator. [Statistics implementation](../decision_graph_qa/eval_statistics.py) · [Full split by demand-profile by behavior-policy breakdown](../benchmark_results/decision_graph_qa_eval_v1/summary.json)

#### Test · 352 graphs, 16 demand paths

| Item | Action changed (%) | Planning excess | Relative excess (%) | Realized cost Δ | Immediate fulfillment Δ (pp) | Emissions Δ | n | Violations |
|---|---|---|---|---|---|---|---|---|
| I1 | 74.15 [68.75, 79.83] | 4.17 [3.66, 4.67] | 5.83 [4.62, 7.27] | 2.02 [-0.46, 4.37] | 0.138 [-0.284, 0.609] | 1.33 [0.68, 2.05] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| I2 | 22.16 [17.05, 28.69] | 0.28 [0.14, 0.47] | 0.14 [0.08, 0.21] | 0.31 [-0.55, 1.27] | 0.085 [0.003, 0.172] | 0.03 [-0.05, 0.13] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| I3 | 82.95 [79.55, 86.36] | 6.90 [5.64, 8.32] | 9.01 [7.37, 10.85] | -3.05 [-7.75, 0.39] | 0.255 [-0.165, 0.725] | 0.10 [-0.30, 0.53] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| I4 | 27.27 [19.03, 36.36] | 2.29 [0.48, 4.60] | 1.10 [0.24, 2.14] | 2.52 [0.12, 5.81] | -0.074 [-0.277, 0.078] | 0.13 [0.02, 0.25] | 352 / 330 / 330 / 330 / 330 / 330 | 22/352 |
| I5 | 88.07 [84.94, 90.91] | 16.51 [12.71, 20.65] | 11.82 [10.59, 13.03] | 9.45 [4.19, 15.65] | -2.288 [-3.000, -1.624] | -0.17 [-0.66, 0.32] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| H | 86.36 [83.24, 89.49] | 16.65 [14.63, 18.63] | 17.82 [14.89, 20.49] | -11.05 [-16.96, -6.46] | 1.670 [1.054, 2.258] | 0.61 [0.11, 1.15] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |

Among I1–I5, I5 had the largest mean planning excess and the largest realized cost increase, 9.45 [4.19, 15.65]. Immediate fulfillment fell by 2.288 [1.624, 3.000] percentage points, and its emissions interval crossed zero. I1 had the largest estimated increase in emissions, 1.33 [0.68, 2.05]. I4 violated the true allowance in 22 of 352 graphs. Its cost difference of 2.52 [0.12, 5.81] uses the remaining 330 graphs. I3 had planning excess of 6.90 [5.64, 8.32] and a realized cost difference of -3.05 [-7.75, 0.39]. These two metrics yielded different rankings. For hindsight H, planning excess was 16.65 [14.63, 18.63] and the realized cost difference was -11.05 [-16.96, -6.46].

#### Train · 352 graphs, 16 demand paths

| Item | Action changed (%) | Planning excess | Relative excess (%) | Realized cost Δ | Immediate fulfillment Δ (pp) | Emissions Δ | n | Violations |
|---|---|---|---|---|---|---|---|---|
| I1 | 75.28 [70.17, 80.40] | 3.83 [3.34, 4.35] | 7.15 [5.50, 8.80] | 3.91 [1.36, 6.56] | 0.044 [-0.249, 0.320] | 1.74 [0.89, 2.61] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| I2 | 15.91 [11.36, 21.02] | 0.33 [0.06, 0.72] | 0.12 [0.04, 0.22] | -0.53 [-1.31, 0.20] | -0.027 [-0.132, 0.091] | -0.13 [-0.20, -0.07] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| I3 | 80.97 [76.70, 85.23] | 5.84 [4.79, 6.92] | 8.68 [6.62, 10.76] | 2.42 [-0.64, 6.45] | -0.399 [-0.792, -0.026] | -0.14 [-0.90, 0.65] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| I4 | 16.48 [11.36, 22.73] | 1.51 [0.07, 3.83] | 0.52 [0.05, 1.16] | 3.37 [0.03, 9.13] | -0.086 [-0.226, 0.036] | -0.06 [-0.15, 0.03] | 352 / 342 / 342 / 342 / 342 / 342 | 10/352 |
| I5 | 86.93 [83.24, 90.63] | 14.18 [10.04, 19.70] | 11.07 [9.65, 12.46] | 13.92 [4.67, 25.45] | -2.402 [-3.163, -1.712] | -0.85 [-1.34, -0.34] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |
| H | 86.65 [83.52, 89.49] | 19.23 [16.41, 22.70] | 19.31 [16.75, 21.49] | -6.56 [-9.94, -3.74] | 1.280 [0.848, 1.743] | 0.46 [-0.20, 1.11] | 352 / 352 / 352 / 352 / 352 / 352 | 0/352 |

#### Dev · 176 graphs, 8 demand paths

| Item | Action changed (%) | Planning excess | Relative excess (%) | Realized cost Δ | Immediate fulfillment Δ (pp) | Emissions Δ | n | Violations |
|---|---|---|---|---|---|---|---|---|
| I1 | 80.11 [75.00, 84.66] | 3.57 [3.29, 3.93] | 6.73 [4.55, 9.06] | 2.16 [-0.78, 5.10] | 0.096 [-0.494, 0.718] | 2.15 [1.08, 3.22] | 176 / 176 / 176 / 176 / 176 / 176 | 0/176 |
| I2 | 18.75 [12.50, 24.43] | 0.05 [0.01, 0.12] | 0.01 [0.00, 0.03] | 0.26 [-1.47, 1.71] | -0.117 [-0.309, 0.066] | -0.01 [-0.25, 0.18] | 176 / 176 / 176 / 176 / 176 / 176 | 0/176 |
| I3 | 89.77 [86.36, 93.18] | 6.76 [5.52, 8.06] | 11.34 [8.13, 14.73] | -2.78 [-6.65, 0.59] | 0.477 [-0.056, 1.089] | 0.57 [-0.28, 1.51] | 176 / 176 / 176 / 176 / 176 / 176 | 0/176 |
| I4 | 22.16 [13.64, 30.68] | 2.24 [0.00, 6.19] | 0.52 [0.00, 1.29] | 1.30 [-0.40, 3.92] | -0.181 [-0.412, 0.036] | -0.07 [-0.46, 0.18] | 176 / 172 / 172 / 172 / 172 / 172 | 4/176 |
| I5 | 86.93 [81.82, 90.91] | 14.60 [9.66, 20.37] | 10.79 [9.86, 11.87] | 17.78 [5.35, 34.17] | -2.794 [-3.632, -2.016] | -0.26 [-1.35, 0.83] | 176 / 176 / 176 / 176 / 176 / 176 | 0/176 |
| H | 86.93 [85.23, 88.64] | 14.63 [12.13, 16.76] | 16.72 [12.91, 19.99] | -7.67 [-13.77, -2.34] | 1.390 [0.428, 2.301] | 0.95 [-0.35, 2.24] | 176 / 176 / 176 / 176 / 176 / 176 | 0/176 |

### Limitations and next acceptance condition

These estimates come from one synthetic rolling inventory and transport environment and one prespecified set of substitutions. I5 includes the effects of fixed allocation and capacity lost by rounding down each SKU's route allocation. DQ-1 found other first actions within the optimum tolerance in 215 of 880 graphs. Action changes and realized effects depend on the stored reference action and the way the ablated model selects among optima. H uses one known demand path over the same window as a hindsight reference. Its optimization scope is the known-demand window. The realized cost difference comes from the separate simulation under the fixed rolling continuation. [DQ-1 tie audit](../benchmark_results/decision_graph_qa_v1/summary.json)

The next acceptance condition is to evaluate live LLMs with the exported questions, three context modes and two upstream answer sources, then check whether context changes answers, violations and realized B consequences. Live evaluation requires separate budget approval. Use `export-prompts` for the questions, write responses to JSONL with `id` and `answers`, and pass them to `evaluate --answers` to reuse the scoring and consequence definitions.

## 复算命令 / Replay commands

在仓库根目录用已配置的 Python 环境运行。前两条核对已发布产物，求解次数为零。复现试算和正式运行时使用新目录。Run from the repository root in the configured Python environment. The first two commands verify the released artifacts without solving. Use fresh paths for the pilot and formal replay.

```text
python -m decision_graph_qa verify-eval --out benchmark_results/decision_graph_qa_eval_v1
python -m decision_graph_qa verify --data benchmark_results/decision_graph_qa_v1
python -m decision_graph_qa evaluate --data benchmark_results/decision_graph_qa_v1 --pilot --out dq2-replay-pilot
python -m decision_graph_qa evaluate --data benchmark_results/decision_graph_qa_v1 --pilot-evidence dq2-replay-pilot --out dq2-replay-formal
python -m decision_graph_qa export-prompts --data benchmark_results/decision_graph_qa_v1 --split test --mode Graph --source gold --lang zh --out dq2-test-graph-zh.jsonl
```
