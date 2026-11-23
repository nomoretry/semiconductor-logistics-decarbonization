# 决策图问答真实模型评测事前协议 / Decision graph QA model evaluation protocol

本文先中文、后英文。The Chinese protocol precedes its English version.

Protocol config SHA256: ec4f3a4ed681cc646195195a1f7bf11f1b540263517e9dc73cbe3efaaf83c09a

[协议配置 / Protocol configuration](../benchmark_results/decision_graph_qa_llm_v1/protocol_config.json)

## 中文

### 问题和证据

在同一个合成滚动库存与运输环境中比较三种英文输入。 `None` 给出状态和当前问题，`Chain` 加直接父节点的标准问答，`Graph` 加全部祖先节点的标准问答。比较回答正确率、违约和本期发运动作的实际后果，记录每次调用和每项发运决定的计算代价。匹配的发运题 B 输入中，`Chain` 和 `Graph` 均包含 P3 标准答案，涉及各 SKU 是否发货、分线路公斤数和排放。此时 B 部分检验模型能否将中间答案组装成合法发运矩阵。推论限于该合成环境、题目和标准上游答案。[DQ-1 数据](decision_graph_qa.md) · [DQ-2 评测](decision_graph_qa_eval.md)

评测直接读取 DQ-2 test 划分、`gold` 来源的三份英文提示文件。按协议配置核对来源清单 SHA256，再核对清单中待使用文件的原始字节。每条请求对应一个配置、上下文、图和题的组合。详见 [DQ-2 文件清单](../benchmark_results/decision_graph_qa_eval_v1/manifest.json) 和 [DQ-1 文件清单](../benchmark_results/decision_graph_qa_v1/manifest.json)。

| 配置 | 模型 | 推理强度 | 推理模式 | 范围 |
|---|---|---|---|---|
| S | `gpt-6.2-sol` | `max` | `standard` | B 主评测、P3 扩展和冒烟 |
| A | `gpt-6.2-astra` | `high` | `standard` | B，仅登记，真实运行需另行批准 |

两配置均使用 `max_output_tokens=64000`、`store=false` 和默认服务档（`service_tier="default"`，见修订 1）。请求体只有 `model`、`instructions`、`input`、`reasoning`、`max_output_tokens`、`store`、`service_tier`。启动时核对协议配置哈希，按键名排序、无多余空白的 UTF-8 JSON 计算请求体 SHA256。记录返回的模型快照、推理参数和服务档，报告标出同一配置内的快照变化。S 与 A 的比较针对整体配置。

### 作答和状态

固定系统提示如下。输入仅提供题目和相应上下文。

> Answer only the question at the end of the message. Output exactly one JSON value without explanation. Use true or false for yes-or-no questions, numbers for quantities, and two-dimensional arrays of integers for matrices (rows are SKUs and columns are routes). Use null when the question permits no answer.

合并 Responses 消息中的 `output_text`，去掉首尾空白。如果整段恰好是一个带或不带 `json` 标记的 Markdown 反引号代码块，取其内容。用 `json.loads` 解析单个 JSON 值，拒绝非 JSON 数值，包括 `NaN` 与 `Infinity`。DQ-1 判分器核对类型、取值和约束。

| 状态 | 含义 |
|---|---|
| `ok` | 成功解析，交给 DQ-1 判分 |
| `parse_failure` | 响应完成，解析失败 |
| `truncated` | `status=incomplete`，且 `incomplete_details.reason=max_output_tokens` |
| `error` | 请求失败或其它未完成响应 |

前三类为终态并进入正确率分母。解析失败与截断计作答错。其它未完成响应记为错误且当次不自动重试。记录错误与未作答数。主评测只复用请求哈希相同的试点终态，保留原传输方式。

### 分档与顺序

| 档 | 取样 | S 调用数 | 判读 |
|---|---|---|---|
| 冒烟 | 试点第一图，`None` 下 P3 六题与 B | 7 | 接口、解析与记账 |
| 试点 | 16 条需求路径 × 2 种行为策略，各抽一个时点，B × 3 上下文 | 96 | 用量、费用、用时和失败率 |
| 主评测完整版 | test 352 图，B × 3 上下文 | 1,056，试点全复用时新增 960 | 正式比较 |
| 主评测半量版 | 32 组各取试点时点及另外五个时点，B × 3 上下文 | 576，试点全复用时新增 480 | 正式比较 |
| P3 扩展 | 试点 32 图，P3 六题 × 3 上下文 | 576 | 预算允许时做描述性比较 |

按 `None` 文件中图的首次出现顺序排列图和组。对每组用同一随机流（984311）无放回抽取一个试点时点，另用 984314 从本组余下图抽五个时点。主评测从导出顺序的所选图开始，以 984313 打乱。试点和 P3 保留试点抽样顺序。每图以配置中的上下文顺序和导出中的题序构造组合，用该档独立初始化的 984312 随机流打乱。

依据试点单次费用与剩余预算选择主评测规模，可分批或跨月，账本累计。若试点截断率超过 5%，须先记录修订并将输出上限增至 128,000。若解析失败率超过 10%，须先复查系统提示并记录修订再运行主评测。发生任一修订时，试点记录须重新取得。当前协议登记 `own`（按图顺序回答全部 31 题，使用自己的上游回答）和中文输入，规模与费用另行批准。

### 判分、比较和计时

用 `scoring.grade_graph` 判分，只提供解析成功的回答。B 主口径在已解析且动作可执行时，调用 `consequence.Consequences.compare`。缺失、错误和违约分别计数。次口径对有记录的非 `ok` B 用 DQ-2 规则动作兜底。已解析但违约的 B 保留违约，未尝试的 B 保留缺失。计划超额沿用 DQ-1，实际结果用测试动作减去参考动作，续行均使用 `mpc_scenarios`。实际成本差、即时满足率差（百分点）和排放差沿用 DQ-2 定义。[判分实现](../decision_graph_qa/scoring.py) · [后果实现](../decision_graph_qa/consequence.py)

逐配置报告 Chain − None、Graph − None、Graph − Chain。报告 B 正确率、违约率、截断率、解析失败率、计划超额和三项实际差。B 违约率以有违约判定的回答为分母，截断与解析失败以终态为分母。P3 在扩展档报告六题平均及各题结果。每项配对差使用两边均有该指标的图，P3 同图中的题也匹配。沿用 `eval_statistics.py`，按需求路径整群 bootstrap 10,000 次，种子 984301，报告 95% 区间和样本数。主评测支持正式比较，试点用于运行评估，P3 扩展用于描述。若 A 获准运行，按共同的 B 图和上下文比较 A 与 S。[统计实现](../decision_graph_qa/eval_statistics.py)

报告每次调用和每个 B 决定的平均费用、平均和 p95 用时以及平均输入、输出和推理 token。批处理没有单次用时的记录保持缺失。用试点 32 图在同一台机器上重测参考规划器（含情景构造）和规则动作的本地用时中位数。结果一并列出相同图范围的 DQ-2 标准答案和规则基线。[DQ-2 逐图证据](../benchmark_results/decision_graph_qa_eval_v1/attempts.jsonl.gz)

### 预算、记录和验收

每百万 token 的预演单价如下。缓存写按 30 分钟档计。实际运行明确传入全部四个单价与累计 `--max-usd`；按月分批时同时核对账户可用额度。

| 配置 | 输入 | 缓存读 | 缓存写 | 输出 |
|---|---:|---:|---:|---:|
| S | 2.00 | 0.10 | 2.50 | 10.00 |
| A | 8.00 | 0.40 | 10.00 | 40.00 |

费用为（未缓存输入 × 输入单价 + 缓存读 × 缓存读单价 + 缓存写 × 缓存写单价 + 输出 × 输出单价）÷ 1,000,000。推理 token 包含在输出中。逐条发送前用提示和系统说明字符数 ÷ 3 估算输入，加上最大输出按单价预留。已结算、进行中预留和新预留之和必须在额度内。每次发送含重试计入调用上限，每请求至多 3 次尝试。401、403、花费上限和额度错误停止派发。其他 429、5xx 和网络错误按 `Retry-After` 或指数退避重试。无法判断实际消耗的请求按预留金额计费。费用预留基于字符估算与给定单价。

Batch 可用于主评测和 P3 扩展，预演单价为逐条的一半。导出记录相同请求体和哈希，并用试点平均输出估计费用。提交前用试点用量按 Batch 单价重算单次费用 p95，并按块内请求数预留。p95 预留是预算估计，可能低于最终费用。Batch 结果使用实际用量结算，可离线重复导入。账本和回答逐条追加，续跑优先使用相同请求的终态。分析输出写入答案、逐图结果、汇总、双语表和 SHA256 清单。

当前验收是离线预演、预算和续跑测试、判分等价验证。真实评测在这些验收后另行运行，先验证七条冒烟请求的接口和记账，再执行试点。所有数据和离线参照来自单个合成环境。

### 修订 1：请求写明默认服务档

本修订在任何真实请求之前做出。原配置的请求体没有 `service_tier`。按 OpenAI 文档，不写这个参数的请求按项目设置的服务档处理；项目设为 Fast 时按 Fast 计价，是标准价的 2 倍，而账本和 `--max-usd` 按标准价计算。修订后两个配置的请求体都写明 `service_tier="default"`，即标准价，配置哈希随之更新。逐条运行记录响应返回的 `service_tier`。返回值与请求不同时停止派发新请求，这次调用按标准价算出的费用乘 6 记账（价目表所列的最高倍数），作为上界。Batch 结果按 Batch 单价结算，不适用这条停止规则；Batch 沿用同一请求体，如果 Batch 接口不接受这个字段，先记录新的修订再提交。题目、抽样、判分和比较都不变。

## English

### Question and evidence

Compare three English inputs in one synthetic environment for rolling inventory and transport. `None` provides state and the current question, `Chain` adds the direct parents' reference question–answer pairs, and `Graph` adds all ancestors' reference question–answer pairs. Compare accuracy, violations, and the realized consequences of current dispatch actions. Track the computational cost per call and per dispatch decision. For B, both `Chain` and `Graph` include reference P3 answers about whether to ship each SKU, kilograms by route, and emissions. Part of the B task in these conditions is assembling those intermediate answers into a valid dispatch matrix. Inference is limited to the synthetic environment, questions, and reference upstream answers. [DQ-1 dataset](decision_graph_qa.md) · [DQ-2 evaluation](decision_graph_qa_eval.md)

Read the three frozen English prompt files for the DQ-2 test split and `gold` source. Verify the source manifest SHA256 hashes from the protocol configuration, then check the bytes of the files used against the manifests. Each request corresponds to one configuration, context, graph, and question. [DQ-2 manifest](../benchmark_results/decision_graph_qa_eval_v1/manifest.json) · [DQ-1 manifest](../benchmark_results/decision_graph_qa_v1/manifest.json)

| Configuration | Model | Reasoning effort | Reasoning mode | Scope |
|---|---|---|---|---|
| S | `gpt-6.2-sol` | `max` | `standard` | B main evaluation, P3 extension, and smoke run |
| A | `gpt-6.2-astra` | `high` | `standard` | B upon separate approval for a live run |

Both configurations use `max_output_tokens=64000`, `store=false`, and the default service tier (`service_tier="default"`, Amendment 1). The request body contains `model`, `instructions`, `input`, `reasoning`, `max_output_tokens`, `store`, and `service_tier`. Verify the configuration hash on startup. Hash each request body as compact, key-sorted UTF-8 JSON. Record returned model snapshots, reasoning parameters, and service tiers, and flag snapshot changes within each configuration. Compare S and A as entire configurations.

### Responses and states

Use the fixed system prompt below. The input supplies the question and its context.

> Answer only the question at the end of the message. Output exactly one JSON value without explanation. Use true or false for yes-or-no questions, numbers for quantities, and two-dimensional arrays of integers for matrices (rows are SKUs and columns are routes). Use null when the question permits no answer.

Concatenate Responses message `output_text` parts and trim outer whitespace. If the entire reply is a Markdown backtick block with an optional `json` tag, take the block contents. Parse one JSON value with `json.loads` and reject non-JSON numbers including `NaN` and `Infinity`. The DQ-1 scorer checks types, values, and constraints.

| State | Meaning |
|---|---|
| `ok` | Parsed successfully and graded with the DQ-1 scorer |
| `parse_failure` | Completed response that failed parsing |
| `truncated` | `status=incomplete` with `incomplete_details.reason=max_output_tokens` |
| `error` | Request failure or another incomplete response |

The first three are terminal and enter the accuracy denominator. Parse failures and truncations count as incorrect. Other incomplete responses are errors without an automatic retry on that invocation. Count errors and missing answers. The main evaluation reuses terminal pilot records with matching body hashes and retains each record's original transport.

### Phases and order

| Phase | Sample | S calls | Interpretation |
|---|---|---|---|
| Smoke | First pilot graph, six P3 questions and B under `None` | 7 | Interface, parsing, and accounting |
| Pilot | 16 demand paths × 2 behavior policies, one time per group, B × 3 contexts | 96 | Usage, cost, latency, and failure rates |
| Main full | All 352 test graphs, B × 3 contexts | 1,056, with 960 new calls if all pilot records are reused | Formal comparison |
| Main half | Pilot time and five additional times per group, B × 3 contexts | 576, with 480 new calls if all pilot records are reused | Formal comparison |
| P3 extension | 32 pilot graphs, six P3 questions × 3 contexts | 576 | Descriptive comparison if budget permits |

Use first graph appearance in the `None` export to order graphs and groups. Use one random stream (984311) to sample one pilot time per group without replacement. Sample five from the remaining graphs in each group using 984314. For main, shuffle the selected graphs from export order with 984313. Keep the pilot sampling order for pilot and P3. Within each graph, start with the configured context order and exported question order and shuffle the combinations using a separate stream initialized to 984312 for each phase.

Choose the main scope from observed pilot cost per call and remaining budget. The ledger accumulates across batches and months. A pilot truncation rate above 5% requires a recorded amendment and an increase to 128,000 output tokens. A parse failure rate above 10% requires a system prompt review and recorded amendment before main. Either amendment requires new pilot records. Register `own` (answer all 31 questions in graph order using the model's upstream replies) and Chinese inputs for separate approval of scope and cost.

### Scoring, comparison, and timing

Use `scoring.grade_graph` with only parsed answers. The primary B analysis calls `consequence.Consequences.compare` for parsed, executable actions. Count missing records, errors, and violations separately. The secondary analysis falls back to the DQ-2 rule action for a recorded non-`ok` B response. Preserve violations for parsed invalid actions and absence for unattempted actions. Planned excess uses the DQ-1 definition. Realized differences are the evaluated action minus the reference action, with `mpc_scenarios` continuation. Realized cost, immediate fill rate in percentage points, and emissions follow the DQ-2 definitions. [Scoring](../decision_graph_qa/scoring.py) · [Consequences](../decision_graph_qa/consequence.py)

Report Chain − None, Graph − None, and Graph − Chain within each configuration. Report B accuracy, violation, truncation, parse failure, planned excess, and the three realized differences. Use adjudicated responses for the B violation denominator and terminal records for truncation and parse failure denominators. Report the six-question P3 average and per-question results in the extension. Pair on graphs with values on both sides and match P3 questions within each paired graph. Reuse `eval_statistics.py` for 10,000 demand-path cluster bootstrap draws with seed 984301. Report all 95% intervals and sample sizes. Main supports formal comparisons, pilot evaluates operations, and P3 is descriptive. If approved and run, compare A and S on shared B graphs and contexts. [Statistics](../decision_graph_qa/eval_statistics.py)

Report mean cost per call and per B decision, mean and p95 latency, and mean input, output, and reasoning tokens. Keep per-call Batch latency missing when unrecorded. On the same machine, time the reference planner including scenario construction and the rule action on the 32 pilot graphs, and report medians. Include the DQ-2 reference answer and rule baselines on the same graph scope. [DQ-2 per-graph evidence](../benchmark_results/decision_graph_qa_eval_v1/attempts.jsonl.gz)

### Budget, records, and acceptance

The following are the USD per million token prices for the dry run. Cache writes use the 30-minute rate. A live run specifies all four rates and cumulative `--max-usd`. Check available account credits when spreading work across months.

| Configuration | Input | Cache read | Cache write | Output |
|---|---:|---:|---:|---:|
| S | 2.00 | 0.10 | 2.50 | 10.00 |
| A | 8.00 | 0.40 | 10.00 | 40.00 |

Cost is (uncached input × input rate + cache reads × cache read rate + cache writes × cache write rate + output × output rate) ÷ 1,000,000. Reasoning tokens are included in output. Before each synchronous send, estimate input from the prompt and instruction characters divided by 3 and reserve the cost of that input and the maximum output. Settled costs, open reservations, and the new reservation must fit the budget. Each send including retries counts toward the call limit, up to three attempts per request. Stop dispatch on 401, 403, spend limits, and quota errors. Retry other 429, 5xx, and network errors with `Retry-After` or exponential backoff. An attempt with unknown consumption is charged at its reserved amount. Reservations depend on character estimates and provided prices.

Batch supports main and the P3 extension. Dry-run Batch prices are half of synchronous prices. Export the same request bodies and hashes and estimate cost using mean pilot output. Before submitting a chunk, reprice pilot usage at the provided Batch rates and reserve the pilot p95 per-call cost times the chunk size. The p95 reservation is a budget estimate and final charges may exceed it. Settle Batch results from actual usage and support idempotent offline imports. Append ledger and reply records and reuse terminal records for unchanged requests on resume. Analysis writes answers, per-graph results, summaries, bilingual tables, and a SHA256 manifest.

Current acceptance covers offline dry runs, budget and resume tests, and grading equivalence checks. A separate live evaluation starts with seven smoke requests to verify the interface and ledger, followed by pilot. All data and offline baselines come from one synthetic environment.

### Amendment 1: request the default service tier explicitly

This amendment was made before any live request. The original request body omitted `service_tier`. According to the OpenAI documentation, a request without this parameter uses the service tier set for the project, and a project set to Fast is billed at Fast rates, twice the Standard rate, while the ledger and `--max-usd` use Standard rates. Both configurations now send `service_tier="default"`, the Standard tier, and the configuration hash changes accordingly. Synchronous runs record the returned `service_tier`. If it differs from the request, dispatch stops and that call is booked at six times its Standard cost, the highest multiplier in the price list, as an upper bound. Batch results are settled at Batch rates and are not subject to this stop rule. Batch uses the same request body; if the Batch endpoint rejects this field, a further amendment is recorded before submission. Questions, sampling, scoring, and comparisons are unchanged.
