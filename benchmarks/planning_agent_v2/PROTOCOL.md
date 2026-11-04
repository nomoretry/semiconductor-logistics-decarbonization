# 规划 Agent 评测 v2：事前协议 / Planning agent evaluation v2: pre-specified protocol

本文提供中英文版本，中文在前，英文在后。题目、评分器和配置在任何 Agent 运行之前提交，哈希记录在 `freeze.json`。
This document provides Chinese first and English second. Tasks, scorer and configuration were committed before any agent ran on them; their hashes are in `freeze.json`.

## 中文

### 问题

在没有用来调整过提示词或规则的业务表述上，大模型 Agent 相对同信息的规则 Agent，是否能更准确地理解业务问题、选择工具、提取参数、处理缺失信息，并完成整个任务？代价（token、费用、时间）是多少？

### 比较对象

| | 大模型 Agent | 规则 Agent |
|---|---|---|
| 实现 | `planning_agent/graph.py` 的 LangGraph 流程，提示词 `agent.py`，工具 `tools.py`，数字审查 `guardrails.py`，均不修改 | `planning_agent/rules.py` |
| 模型 | `gpt-6.1-sol`，Responses API，`reasoning.effort=max`，`reasoning.mode=standard`，`service_tier=default` | 不使用模型 |
| 重复 | 每题独立运行 3 次 | 每题运行 3 次（确定性，用来核对） |

两者看到完全相同的问题文字，使用同一套工具和求解器（HiGHS，默认 12 个 SKU、16 周、种子 7）。每次运行都新建工具会话和模型客户端，不带任何上次的状态。

### 题目（`cases.json`）

20 题是 20 个不同的问题，60 次运行不是 60 个独立问题。题目由项目作者编写，**不是独立评测**。

| 组 | 题数 | 内容 | 参考答案 |
|---|---|---|---|
| A | 8 | 7 条可执行的公告或假设（中英文、数字写法、单位换算、两条扰动、需求变化、未说明字段）；1 条缺关键信息 | 每个字段的值；引擎算出的数字 |
| B | 6 | 查网络、预设场景、碳前沿、对冲、解释加备忘录、无关请求 | 必须成功调用的工具和关键参数；引擎算出的数字 |
| C | 6 | 真实船公司公告摘录，只给原文，并追问成本和排放 | 公告本身不能给出可执行参数。参考答案是助手标注，**未经人工复核** |

C 组抽取规则：`real_notices_v1` 的 16 条按参考答案是否含数量分层，用 `random.Random(20261104)` 打乱，每层取 3 条，事件组不重复。结果：R009、R015、R016（含数量），R011、R003、R008（不含数量）。

### 评分（`planning_agent/eval_v2.py` 的 `score_run`，确定性）

- **scenario 类（A01–A07）**：必需的工具都成功调用；某次成功的 `create_scenario` 与参考参数逐字段一致（周次和延误周数完全相同；运力、运费变化误差不超过 1 个百分点；距离系数误差不超过 0.01；按线路展开后比较，多出来的扰动算错）；回答含全部引擎数字（`evaluate._has_number` 的容差）；数字审查通过；没有错误；A07 还要写明假设。
- **tool 类（B01–B05）**：必需工具和关键参数；引擎数字；数字审查；没有错误。
- **refuse 类（B06）**：不调用工具并拒绝。
- **clarify、notice 类（A08、C 组）**：回答说明缺什么（路线映射、周次、幅度三类信息至少说到两类，并有表示缺失或提问的字眼）；如果仍然建了场景或求解，必须明确标为假设；数字审查通过；没有错误。是否引用公告里的数量单独统计，不计入成败。

失败标签：`param_error`、`tool_selection_error`、`assumption_not_flagged`、`wrong_assumption`、`unnecessary_clarification`、`missing_info_not_stated`、`gold_number_missing`、`unsupported_number`、`refusal_failed`、`timeout`、`budget_limit`、`output_cap`、`max_steps`、`api_error`。

**已知局限**：缺失信息的判断靠关键词，可能漏判或误判；保存的完整回答可以人工复核。

### 统计

先在每题内平均，再在 20 题上平均。95% 区间用按题重抽样的百分位自助法（10,000 次，种子 20261104），所以同一题的重复不当作独立样本；模型减规则的差值用同一方法配对。同时报告逐题胜负数和每题三次的一致性。不报 p 值。

### 预算与停止

上限 US$30。按官方标准价（输入 2、缓存读取 0.10、缓存写入 2.50、输出 10，单位美元/百万 token，2026-11-04 读取）。请求发出前按输入 2.50、输出 10 预留。其他上限：请求 1,500 次，每次输出 64,000 token，单次超时 1,800 秒，每次运行最多 16 步。

**事前估计**：24 题 xhigh 记录平均每题 13,100 输入、1,750 输出（其中推理 940）。60 次相同用量约 US$2.6；`max` 的推理量未知，按推理 token 增加 10 倍估约 US$9，增加 30 倍估约 US$25。

只有预算不足、凭据或模型不可用、实际配置与本协议不符、严重实现错误时才停止。已完成的结果保留，可以从断点继续。临时错误由客户端重试，并可重跑该次运行（共 3 次机会），所有重试都计入请求、token 和费用。

### 不做的事

运行开始后不修改题目、评分规则、提示词或优化约束。发现确实需要修复的实现错误时，保存原始结果，另存新版本并说明差异。

### 运行前的修改记录

第一次启动时只发出 1 个请求，服务返回内容为空的 HTTP 400，没有模型回复，0 token（记录在结果目录的 `attempts.jsonl`、`ledger.jsonl`）。原因是 Windows 控制台的隐藏输入不支持 Ctrl+V，把控制字符当成了密钥（用占位密钥和控制字符分别请求，复现了 401 和这个 400）。修复：发送前检查密钥格式，提示用鼠标右键粘贴。题目、评分规则、提示词和优化约束都没有改，重新记录了 `freeze.json`。

第二次启动时，第一个请求遇到网络错误（`URLError`，11 秒），重试后返回 HTTP 401（密钥不正确），同样没有模型回复。网络错误的那次预留按规则保留在账本里（0.66 美元，实际没有计费），所以这次运行实际可用的额度略低于 30 美元。之后改用一个带遮罩的本地对话框输入密钥，它先用不收费的模型查询核对密钥，再以环境变量启动同一命令，不改变评测代码。

## English

### Question

On business wording that was not used to tune prompts or rules, does the LLM agent understand the request, choose tools, extract parameters, handle missing information and finish the task more accurately than a rule agent with the same information? At what cost in tokens, money and time?

### Compared

| | LLM agent | Rule agent |
|---|---|---|
| Implementation | The LangGraph flow in `planning_agent/graph.py`, prompt in `agent.py`, tools in `tools.py`, numeric review in `guardrails.py`, all unchanged | `planning_agent/rules.py` |
| Model | `gpt-6.1-sol`, Responses API, `reasoning.effort=max`, `reasoning.mode=standard`, `service_tier=default` | None |
| Repeats | Three independent runs per task | Three runs per task (deterministic, as a check) |

Both see the same text and use the same tools and solver (HiGHS, default 12 SKUs, 16 weeks, seed 7). Each run gets a new tool session and model client with no state from earlier runs.

### Tasks (`cases.json`)

Twenty tasks are twenty questions; sixty runs are not sixty independent questions. The project author wrote the tasks, so this is **not an independent evaluation**.

| Group | Tasks | Content | Reference |
|---|---|---|---|
| A | 8 | Seven executable notices or what-ifs (Chinese and English, numbers in words, unit conversion, two disruptions, demand change, unstated fields); one with key information missing | Value of each field; engine numbers |
| B | 6 | Network lookup, preset scenario, carbon frontier, hedge, explanation with memo, an unrelated request | Tools that must succeed and key arguments; engine numbers |
| C | 6 | Real carrier notice excerpts, text only, with a question about cost and emissions | The notice alone gives no executable parameters. Assistant-written references, **not reviewed by a person** |

Group C selection: the 16 `real_notices_v1` items were split by whether the reference lists a quantity, shuffled with `random.Random(20261104)`, and three were taken from each stratum without repeating an event group: R009, R015, R016 (quantity); R011, R003, R008 (none).

### Scoring (`score_run` in `planning_agent/eval_v2.py`, deterministic)

- **scenario (A01–A07)**: required tools succeed; one successful `create_scenario` matches the reference field by field (weeks and delay weeks exactly; capacity and rate changes within 1 percentage point; distance factor within 0.01; compared per lane, and extra disruptions count as wrong); the answer contains every engine number (tolerance of `evaluate._has_number`); numeric review passes; no error; A07 must also state its assumption.
- **tool (B01–B05)**: required tools and key arguments; engine numbers; numeric review; no error.
- **refuse (B06)**: declines and calls no tool.
- **clarify, notice (A08, group C)**: the answer says what is missing (at least two of route mapping, weeks, magnitude, with a word signalling a gap or a question); if it still built a scenario or solved, it must label that as an assumption; numeric review passes; no error. Whether the notice's quantity is cited is reported separately and does not decide success.

Failure labels: `param_error`, `tool_selection_error`, `assumption_not_flagged`, `wrong_assumption`, `unnecessary_clarification`, `missing_info_not_stated`, `gold_number_missing`, `unsupported_number`, `refusal_failed`, `timeout`, `budget_limit`, `output_cap`, `max_steps`, `api_error`.

**Known limitation**: missing information is judged by keywords, which can err either way; the saved answers can be reviewed by hand.

### Statistics

Average within each task, then over the 20 tasks. 95% intervals are percentile bootstraps over tasks (10,000 resamples, seed 20261104), so repeats of a task are not treated as independent; model minus rule is paired the same way. Task-level wins and the agreement of the three runs are also reported. No p-values.

### Budget and stopping

Limit US$30. Official Standard prices (input 2, cached read 0.10, cache write 2.50, output 10, USD per million tokens, read 2026-11-04). Before a request is sent it reserves at input 2.50 and output 10. Other limits: 1,500 requests, 64,000 output tokens per request, 1,800 seconds per request, 16 steps per run.

**Estimate before running**: the 24-question xhigh record averaged 13,100 input and 1,750 output tokens per task (940 reasoning). Sixty runs at that use cost about US$2.6; the use at `max` is unknown, and ten or thirty times the reasoning tokens gives about US$9 or US$25.

The run stops only for an exhausted budget, an unavailable key or model, an actual configuration that differs from this protocol, or a serious implementation error. Saved results stay, and the run can continue from where it stopped. Transient errors are retried by the client and a run may be repeated (three chances in all); every retry counts towards requests, tokens and cost.

### Not done

Once running, tasks, scoring rules, prompts and optimisation constraints do not change. If a real implementation error needs fixing, the original results stay, a new version is saved separately and the difference is explained.

### Changes before the run

The first start sent one request and received an HTTP 400 with an empty body: no model reply and 0 tokens (recorded in `attempts.jsonl` and `ledger.jsonl` in the results folder). The cause was that hidden input in a Windows console does not paste with Ctrl+V and took a control character as the key (requests with a placeholder key and with a control character reproduced the 401 and this 400). The fix checks the key's format before sending and tells the user to paste with a right-click. Tasks, scoring rules, prompts and optimisation constraints did not change; `freeze.json` was recorded again.

On the second start the first request hit a network error (`URLError`, 11 seconds), and the retry returned HTTP 401 (wrong key), again with no model reply. The reservation of the network error stays in the ledger under the rules (USD 0.66, not actually billed), so the budget available to this run is slightly below USD 30. After that, the key was entered in a masked local dialog, which checks it with a free model lookup and then starts the same command with an environment variable; the evaluation code did not change.
