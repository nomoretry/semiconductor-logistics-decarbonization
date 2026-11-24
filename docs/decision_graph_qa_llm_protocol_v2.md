# 决策图问答真实模型评测协议 v2 / Decision graph QA model evaluation protocol v2

本文先中文、后英文。The Chinese protocol precedes its English version.

Protocol config SHA256: f3fe6a36b377ebf5c685b3a871ddd5019db55ff35a7c6923b47ae593da53f60f

[协议配置 / Protocol configuration](../benchmark_results/decision_graph_qa_llm_v2/protocol_config.json)

## 中文

### 问题

问题同 v1：在同一个合成滚动库存与运输环境里，让大模型回答本期发运矩阵（B）和规划题（P3），给它哪些上游信息，答得怎么样，每个决定花多少钱和时间。v2 只换题目文字，把规则和标准答案用到的需求情景写进题目。图、问题、标准答案、判分、抽样种子、请求参数和系统提示都不变。[v1 协议](decision_graph_qa_llm_protocol.md) · [DQ-1 数据](decision_graph_qa.md) · [DQ-2 评测](decision_graph_qa_eval.md)

### v1 停止的原因

v1 使用 DQ-2 导出的英文题目，每条只有状态、前面的问答和问题本身。题目没有写目标、各项费用怎样计、事件顺序、约束和窗口排放额度的分摊。标准答案还依赖由随机种子生成的 7 组需求情景，题目只给出种子和组数，模型不能运行程序。因此 B 和 P3 的标准答案不能由 v1 的题目推出。

下表是登记 v2 之前完成的离线核算。答题方知道全部规则、能精确求解，只是看不到那 7 组情景，在 352 张 test 图上按 DQ-1 判分。

| 答题方 | B 判对 | 判对率 | 计划超额均值 | 相对超额中位数 |
|---|---:|---:|---:|---:|
| 自己抽 200 组需求，种子 20261125 | 128 | 36.4% | 1.65 | 1.02% |
| 自己抽 200 组需求，种子 7 | 134 | 38.1% | 1.56 | 0.91% |
| 抽 200 组并给 P3 标准答案，种子 20261125 | 256 | 72.7% | 0.60 | 0 |
| 抽 200 组并给 P3 标准答案，种子 7 | 251 | 71.3% | 0.60 | 0 |
| 只用均值预测 | 81 | 23.0% | 7.83 | 7.80% |

给出 P3 标准答案后，判对率高出约 35 个百分点。这些答案由那 7 组情景算出，所以这个差来自答案透露的情景，与答题能力无关。v1 的 `Chain`、`Graph` 与 `None` 之差包含这一部分，无法分开。

v1 已运行冒烟 7 题和试点前 12 次，记录原样保留，作为探索性证据，不与 v2 合并，也不用来回答上面的问题。v1 不再发送新请求，见 v1 协议的修订 3。DQ-1 的图、标准答案和判分以及 DQ-2 的离线结论不使用这些题目文字，不受影响。

### 题目

每条题目依次由五部分组成，各部分之间空一行：

1. 规则。全部题目相同，原文见文末，译文见下一节。
2. 状态。DQ-1 图中的英文 `state_text`，逐字不变。
3. 需求情景。一行 `Demand scenarios (scenario, offset, SKU) = …`，内容是 `planner.scenarios` 给出的 7 × h × 3 个整数，h 为窗口长度。
4. 已答的问题，只在 `Chain` 和 `Graph` 里出现。先是一行说明（原文见文末），再是冻结的 `graph.context` 选出的问答，逐字不变。
5. 问题。DQ-1 的英文问题，逐字不变。

去掉第 1、3 部分和第 4 部分的说明行，得到的文字与 DQ-2 导出的 v1 题目逐字相同。题目只导出 test 划分的 P3 六题和 B，每种上下文 352 × 7 = 2,464 条，共 7,392 条，存为 gzip 的 JSONL，清单记录文件和解压内容的 SHA256。

### 规则译文

带 `public.` 的名字是公开参数的字段，其它名字是状态字段或在规则里定义。下标从 0 起，i 是 SKU，j 是路线。

- 窗口：h = min(public.horizon, public.periods − t)，窗口偏移 u = 0, …, h−1 对应第 t+u 期。
- 计划：x[u][i][j] 是非负整数，即偏移 u 用路线 j 发运 SKU i 的件数。计划现在定下，对所有需求情景相同，不随需求调整。本期发运是 x[0]。
- 每个偏移 u 的次序：先到货，包括 pipeline[t+u][i] 和所有 v + public.lead[j] = u 的 x[v][i][j]，其中本期（偏移 0）的到货已计入 stock 和 backlog；再发出 x[u]；然后发生该偏移的需求。
- 净库存：每个情景里 SKU i 从 stock[i] − backlog[i] 开始，逐偏移加到货、减需求。负值是未满足的需求，由以后的到货补上。N[u][i] 是偏移 u 的需求发生后的净库存。
- 公斤数和排放：x[u] 在路线 j 上的公斤数是 public.mass[i] × x[u][i][j] 对 i 求和；排放是 public.mass[i] × public.emissions[j] × x[u][i][j] 对 i、j 求和。两者都是整数。
- 计划的费用 = 发运费用 + 各情景库存费用的平均。发运费用是 x[u][i][j] × public.mass[i] ×（public.freight[j] + public.carbon_price × public.emissions[j]）对 u、i、j 求和。一个情景的库存费用是 public.holding[i] × max(N[u][i], 0) + public.backlog[i] × max(−N[u][i], 0) 对 u、i 求和；若 t+u = public.periods − 1，再加 public.terminal_backlog[i] × max(−N[u][i], 0)。此外不计任何费用，窗口之后的库存、积压和在途到货没有费用也没有价值。
- 约束：每个偏移 u、每条路线 j 的公斤数不超过 public.capacity[j]；u + public.lead[j] ≥ h 时 x[u][i][j] = 0；窗口内全部发运的排放合计不超过 carbon_remaining × h ÷（public.periods − t）。
- 最优计划是满足约束的计划中费用最低的；并列最低的都算最优。题目列出的需求情景是费用里唯一的需求，概率相同，代替用 public.scenario_seed 抽样。预测和历史需求不进入费用。

### 三种上下文给了什么

`None` 给规则、状态、情景和问题，信息足以算出标准答案。`Chain` 加直接父节点的标准问答，`Graph` 加全部祖先的标准问答。B 的直接父节点是六道 P3 题和两道 P2 压力题，所以 `Chain` 和 `Graph` 的 B 题都给出每种货发不发、各线装多少公斤和本期排放，全部取自同一个最优计划。

`Chain` − `None` 和 `Graph` − `None` 衡量规划这一步由优化程序代做之后模型能多对多少，不是物流信息的价值，也不能说明省下了优化计算，因为给出 P3 的程序同时给出 B。`Graph` − `Chain` 衡量再给感知和预测答案的作用，这些答案都能从状态直接算出。物流信息的价值以 DQ-2 的规划器消融为准。

### 离线验收

以下各项在任何付费请求之前完成，任何一项不通过就停下修改题目，全部重做。

1. 文字：7,392 条题目由代码重新生成，与保存的文件逐字相同；去掉新增部分后与 v1 题目逐字相同。
2. 只读题目文字的程序：只解析题目文字，不导入参照规划器、模拟器和数据，用自己的变量列出整数规划并求解。352 张图的目标值与 DQ-1 保存的最优值相差不超过 DQ-1 容差，用精确分数复算的费用也相同；由它得到的六道 P3、B 和整窗计划 M 用冻结的 `grade_graph` 判分，全部判对。
3. 对照：同一程序读 v1 题目必须全部拒绝。另按十种误读（不分摊排放额度、不计碳价、不计期末追加积压费用、忽略积压、忽略在途、按件计运费、到货晚一期、用均值预测、用情景平均、只用第一组情景）分别求解，报告 B 判对率、违约和相对超额，不设门槛，用来说明每条规则是否影响答案。
4. 参照：在 352 张图上计算 v1 的离线上限（上表）、与 P3 标准答案一致的全部发运矩阵中随机取一个的判对率。
5. 运行器：v1 试点已记录的 12 条请求哈希仍能由代码重现；v2 请求体与 v1 相比只有 `input` 不同；v1 不能再发出真实请求；全部离线测试通过。

验收通过后生成协议配置，把它的 SHA256 写进本文，之后才允许真实请求。

### 运行阶段

试点的 32 张图、上下文和顺序与 v1 相同，所以前 12 次就是 v1 已运行的 4 张图 × 3 种上下文，用新题目重新提问。

| 阶段 | 内容 | 放行条件 |
|---|---|---|
| 0 | 离线验收，不发请求 | 上一节全部通过 |
| 1 | 试点前 12 次，累计上限 8 美元 | 12 次都有终态；截断和解析失败合计不超过 1 次；返回的服务档都是 `default`；复核答案没有发现题目写错或有歧义 |
| 2 | 试点其余 84 次 | 另行批准上限 |
| 3 | 主评测或 P3 扩展 | 看过阶段 2 的结果后另行批准 |

复核时把没判对的答案与十种误读的最优动作比较，用来发现写得有歧义的规则。阶段 1 截断 2 次以上时，先记录修订，把输出上限提到 128,000，再重做这 12 次。发现题目问题时停下，另立新版本。阶段 1 的 12 次不用于得出结论。阶段 2 完成后，试点 96 次用于描述三种上下文的判对率、相对超额、费用和用时，主评测规模不预先确定。截断和解析失败的门槛、`own` 来源和中文题目的登记沿用 v1。

### 判分、统计和参照

判分、实际后果、配对差、整群 bootstrap 和计时沿用 v1。另报 B 的相对计划超额，即固定该动作重解后的目标值比参照最优值高百分之几；违约、截断、解析失败和没有记录的回答单列，不补零。

同一批图上给出五个参照：只读题目文字的程序、DQ-2 的规则动作、只用均值预测的规划、参照规划器的用时，以及与 P3 标准答案一致的矩阵中随机取一个（`Chain`、`Graph` 判对率的对照）。

### 请求和预算

请求体、单价、记账、停发条件、重试规则和逐条等待 3,600 秒沿用 v1（含修订 1、2）。v2 使用新的结果目录和账本 `benchmark_results/decision_graph_qa_llm_v2/`，`--max-usd` 按这个目录累计。

### 局限

- 一个合成环境，规模很小（窗口 6 期、3 种 SKU、2 条路线），参照规划器在毫秒级算出答案。
- 题目文字和只读文字的程序由同一作者编写，尚未由他人独立阅读题目重写求解程序。题目文字待人工复核。
- 情景列表是参照规划器的内部输入，真实业务里不会列在题目中。
- `Chain` 和 `Graph` 使用标准上游答案，不代表模型自己作答的上游。
- 只考英文题目和单一配置，模型快照变化时结果可能不同。

## English

### Question

The question is the same as in v1. In one synthetic environment for rolling inventory and transport, a language model answers the current dispatch matrix (B) and the planning questions (P3). Which upstream information is it given, how well does it answer, and what does each decision cost in money and time? v2 changes only the text of the questions. The rules and the demand scenarios behind the reference answers are now stated. The graphs, questions, reference answers, grading, sampling seeds, request parameters and system prompt are unchanged. [v1 protocol](decision_graph_qa_llm_protocol.md) · [DQ-1 dataset](decision_graph_qa.md) · [DQ-2 evaluation](decision_graph_qa_eval.md)

### Why v1 was closed

v1 used the English prompts exported by DQ-2. Each prompt contains the state, earlier questions and answers, and the question. No prompt states the objective, how each cost is counted, the order of events, the constraints, or how the emissions allowance is paced over the window. The reference answers also depend on seven demand scenarios drawn from a random seed. The prompts give the seed and the number of scenarios, and the model cannot run code. The reference answers to B and P3 therefore do not follow from the v1 prompts.

The table shows offline results obtained before v2 was registered. The responder knows all rules and solves exactly but does not see the seven scenarios. It is graded on 352 test graphs with the DQ-1 rules.

| Responder | B correct | Share | Mean planning excess | Median relative excess |
|---|---:|---:|---:|---:|
| Own 200 demand draws, seed 20261125 | 128 | 36.4% | 1.65 | 1.02% |
| Own 200 demand draws, seed 7 | 134 | 38.1% | 1.56 | 0.91% |
| 200 draws plus P3 reference answers, seed 20261125 | 256 | 72.7% | 0.60 | 0 |
| 200 draws plus P3 reference answers, seed 7 | 251 | 71.3% | 0.60 | 0 |
| Mean forecast only | 81 | 23.0% | 7.83 | 7.80% |

With the P3 reference answers, the share of correct answers is about 35 percentage points higher. These answers are computed from the seven scenarios, so this difference comes from the scenarios they reveal and not from the ability to answer. The v1 differences between `Chain` or `Graph` and `None` contain this part and cannot be separated from it.

v1 had run seven smoke questions and the first 12 pilot calls. Those records are kept unchanged as exploratory evidence. They are not merged with v2 and are not used to answer the question above. v1 sends no further requests (Amendment 3 of the v1 protocol). The DQ-1 graphs, reference answers and grading and the DQ-2 offline findings do not use these prompt texts and are unaffected.

### Statement

Each prompt has five parts separated by blank lines:

1. The rules. They are identical in all prompts and reproduced at the end of this document.
2. The state, the English `state_text` of the DQ-1 graph, unchanged.
3. The demand scenarios, one line `Demand scenarios (scenario, offset, SKU) = …` with the 7 × h × 3 integers from `planner.scenarios`, where h is the window length.
4. Already answered questions, only in `Chain` and `Graph`. One introductory line (reproduced at the end) precedes the questions and answers selected by the frozen `graph.context`, unchanged.
5. The question, the English DQ-1 question, unchanged.

Without parts 1 and 3 and the introductory line of part 4, the text is identical to the v1 prompt exported by DQ-2. Only the six P3 questions and B of the test split are exported, 352 × 7 = 2,464 prompts per context and 7,392 in total. They are stored as gzip JSONL with SHA256 hashes of the files and of their contents.

### What the three contexts give

`None` gives the rules, the state, the scenarios and the question, which is enough to compute the reference answer. `Chain` adds the reference answers of the direct parents and `Graph` those of all ancestors. The direct parents of B are the six P3 questions and two P2 pressure questions, so for B both `Chain` and `Graph` state which SKUs are dispatched, the kilograms on each route and the current emissions, all from one optimal plan.

`Chain` − `None` and `Graph` − `None` measure how much more the model gets right once the optimizer has done the planning step. They are not the value of logistics information, and they do not show that optimization was saved, because the program that supplies P3 also supplies B. `Graph` − `Chain` measures the effect of adding the perception and prediction answers, which follow directly from the state. The value of logistics information remains the subject of the DQ-2 planner ablations.

### Offline acceptance

All items are completed before any paid request. If an item fails, stop, correct the statement and repeat everything.

1. Text. All 7,392 prompts are rendered again and match the stored files exactly. Without the additions they match the v1 prompts exactly.
2. Text-only program. It parses the prompt text only, does not import the reference planner, the simulator or the data, and states and solves the integer program in its own variables. On 352 graphs its objective equals the stored DQ-1 optimum within the DQ-1 tolerance, and so does its cost recomputed in exact fractions. Its six P3 answers, its B and its full-window plan M are graded with the frozen `grade_graph` and are all correct.
3. Controls. The same program must reject every v1 prompt. Ten misreadings are solved as well (emissions limit not paced, no emissions charge, no extra terminal backlog cost, outstanding backlog ignored, scheduled receipts ignored, freight per unit, receipts one offset late, mean forecast, average of the scenarios, first scenario only). Report B accuracy, violations and relative excess without a threshold, to show whether each rule affects the answer.
4. References. On 352 graphs compute the v1 ceilings (table above) and the accuracy of a dispatch picked at random among all matrices that agree with the P3 reference answers.
5. Runner. The 12 recorded v1 pilot request hashes are still reproduced. v2 request bodies differ from v1 only in `input`. v1 can no longer send live requests. All offline tests pass.

After acceptance, generate the protocol configuration and record its SHA256 in this document. Live requests are allowed only afterwards.

### Stages

The 32 pilot graphs, the contexts and their order are the same as in v1. The first 12 calls therefore ask the new questions on the four graphs × three contexts that v1 already ran.

| Stage | Content | Condition to proceed |
|---|---|---|
| 0 | Offline acceptance, no requests | Everything in the previous section passes |
| 1 | First 12 pilot calls, cumulative cap US$8 | All 12 are terminal, at most one truncation or parse failure in total, every returned service tier is `default`, and a review of the answers finds no error or ambiguity in the statement |
| 2 | Remaining 84 pilot calls | A cap is approved separately |
| 3 | Main evaluation or P3 extension | Approved separately after stage 2 |

The review compares answers that are not correct with the optimal dispatch of each misreading, to find rules that are stated ambiguously. Two or more truncations in stage 1 require a recorded amendment that raises the output limit to 128,000, and the 12 calls are repeated. If a statement problem is found, stop and register a new version. The 12 calls of stage 1 support no conclusions. After stage 2, the 96 pilot calls describe accuracy, relative excess, cost and time in the three contexts. The scope of a main evaluation is not fixed in advance. The truncation and parse failure gates, the `own` source and the Chinese questions follow v1.

### Scoring, statistics and references

Scoring, realized consequences, paired differences, the cluster bootstrap and timing follow v1. The relative planning excess of B is reported as well, the percentage by which the objective after fixing the action exceeds the reference optimum. Violations, truncations, parse failures and missing answers are listed separately and are not filled with zeros.

Five references use the same graphs: the text-only program, the DQ-2 rule action, the plan on the mean forecast, the time of the reference planner, and a dispatch picked at random among the matrices that agree with the P3 reference answers (a reference for the `Chain` and `Graph` accuracies).

### Requests and budget

Request bodies, prices, accounting, stop conditions, retry rules and the 3,600-second wait per request follow v1, including Amendments 1 and 2. v2 uses its own results directory and ledger, `benchmark_results/decision_graph_qa_llm_v2/`, and `--max-usd` accumulates over this directory.

### Limitations

- One synthetic environment of small scale (a six-period window, three SKUs, two routes). The reference planner answers within milliseconds.
- The statement and the text-only program have the same author. Nobody else has yet read the statement and written an independent solver from it. The statement awaits human review.
- The scenario list is an internal input of the reference planner and would not be printed in a real business question.
- `Chain` and `Graph` use reference upstream answers, not the model's own.
- Only English questions and one configuration are evaluated, and results may change with the model snapshot.

## 题目规则原文 / Planning rules as sent

```text
Planning rules

Names starting with "public." are fields of the public parameters. The other names are state fields listed below or are defined here. Every index starts at 0. i is a SKU and j is a route.

Window: h = min(public.horizon, public.periods - t). Offset u = 0, ..., h-1 stands for period t+u.

Plan: x[u][i][j] is a nonnegative integer, the units of SKU i dispatched on route j at offset u. One plan is fixed now for all demand scenarios and does not react to demand. The current dispatch is x[0].

Order of events at offset u:
1. Receipts arrive: pipeline[t+u][i] plus every x[v][i][j] with v + public.lead[j] = u. Receipts due in the current period (offset 0) are already counted in stock and backlog.
2. The dispatch x[u] leaves.
3. The demand of offset u occurs.

Net inventory: in each scenario, SKU i starts at stock[i] - backlog[i]. Receipts add to it and demand subtracts from it, offset by offset. A negative value is unfilled demand that later receipts fill. N[u][i] is the net inventory after the demand of offset u.

Kilograms and emissions: the dispatch x[u] puts the sum over i of public.mass[i] * x[u][i][j] kilograms on route j, and emits the sum over i and j of public.mass[i] * public.emissions[j] * x[u][i][j]. Both are whole numbers.

Cost of a plan = dispatch cost + mean inventory cost over the scenarios.
- Dispatch cost: sum over u, i and j of x[u][i][j] * public.mass[i] * (public.freight[j] + public.carbon_price * public.emissions[j]).
- Inventory cost of a scenario: sum over u and i of public.holding[i] * max(N[u][i], 0) + public.backlog[i] * max(-N[u][i], 0). In the last period of the episode (t+u = public.periods - 1), add public.terminal_backlog[i] * max(-N[u][i], 0).
Nothing else is charged. Inventory, backlog and pipeline arrivals after the window have no further cost or value.

Constraints:
- The kilograms on route j at offset u are at most public.capacity[j], for every u and j.
- x[u][i][j] = 0 whenever u + public.lead[j] >= h, so every dispatch arrives inside the window.
- The emissions of all dispatches in the window add up to at most carbon_remaining * h / (public.periods - t).

An optimal plan has the lowest cost among all plans that satisfy the constraints. If several plans share the lowest cost, each of them is optimal.

The demand scenarios listed below are the only demand in this cost, and they are equally likely. They replace any draw with public.scenario_seed. The forecast and the past demand do not enter the cost.
```

`Chain` 和 `Graph` 里已答问题之前的说明行 / The line before the answered questions in `Chain` and `Graph`:

```text
Questions already answered about this decision. The answers are correct, and those about an optimal plan describe one and the same optimal plan.
```
