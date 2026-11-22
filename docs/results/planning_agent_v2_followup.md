# 评测 v2 后续：A04 修复与复测、修正评分、C03 / Evaluation v2 follow-up: the A04 fix and retest, corrected scoring, C03

本文提供中英文版本，中文在前，英文在后。60 次原始运行、冻结配置、原始评分和来源身份都没有改动；52/60 仍是原协议下的结果。
This document provides Chinese first and English second. The 60 original runs, the frozen configuration, the original scores and the source identity are unchanged; 52/60 remains the result under the original protocol.

## 中文

### 结论

| 成绩 | 来源与条件 | 模型 | 规则 | 模型减规则 |
|---|---|---:|---:|---:|
| **官方** | 60 次原始运行，事前冻结的评分器 | 52/60，86.7% [71.7, 100.0] | 6/60，10.0% [0.0, 25.0] | +76.7 [+53.3, +95.0] |
| **修正评分** | 同一批保存的回答，用评分器 v2.1 离线重评，**没有调用模型** | 54/60，90.0% [75.0, 100.0] | 6/60，10.0% [0.0, 25.0] | +80.0 [+60.0, +95.0] |
| **A04 修复后开发复测** | 修复后只重跑 A04 三次，单独保存，**不并入 60 次** | 3/3（原 0/3） | 未重跑 | — |

百分比是按题平均，方括号是按题重抽样的 95% 区间。

- 这三行不能相加。54/60 没有包含 A04 复测；A04 复测的 3/3 不能加到 54/60 上。报告里的 57/60 是另一回事：它是看到失败后，把 B06 和 C03 都按人工阅读判为成功的事后读法（`analysis/sensitivity.json`），也不包含 A04 复测，并且 C03 还没有人工复核，所以它不是成绩。
- A04 的根因已从服务端保存的原始请求确认，修复后 3 次都按预期完成。这是开发复测：作者看过失败才修工具，也只跑了这一题，另外 19 题没有在修复后重跑。
- B06 是评分器的错误，修正后模型 3/3。规则的成绩不变。
- C03 待人工复核，官方和修正评分下都是 0/3，不计为已验证的成功。
- 结论只限于**本题集上优于当前冻结规则**。

### 1. A04：工具接口缺陷

**从实际请求确认的根因。** 用 `GET /responses/{id}` 读回 3 次原始运行第一个请求的记录（`a04_retest/original_response_evidence.json`，读取不是模型运行）：

- 8 个工具全部是 `strict: true`。请求里没有设这个字段，是服务按默认值尝试严格模式。原报告把这一点写成推断，现在有了服务端记录。
- `create_scenario` 的 Schema 变成：`mode`、`lanes` 和所有可选字段都在 `required` 里，`additionalProperties` 为 `false`，`mode` 是不含空值的枚举。
- 工具代码把 `mode` 下的全部线路加到 `lanes` 上。

这三点合起来，在 Marvell 网络上无法表达“只影响 `TW_air`”：`mode` 必须有值，而 `air` 又会带上 `MY_air`。

**修复后的语义（`planning_agent/tools.py` 的 `disruption_lanes`）：**

| 传入 | 结果 |
|---|---|
| 只有 `lanes` | 只影响这些线路 |
| 只有 `mode` | 影响这种运输方式的全部线路 |
| 两者都有，并且一致 | `lanes` 决定范围，`mode` 只作核对 |
| 两者都有，但有线路不属于该 `mode` | 报错并指出冲突的线路，不建场景 |
| 缺省、`null` 或空列表 | 视为没有给；两者都没有时报错 |
| 未知线路、网络里没有的运输方式、`lanes` 不是列表 | 报错，不建场景 |

其他改动：Responses 请求明确写 `strict: false`，因为这些工具的可选字段缺省时有含义（没有给，并作为假设报告）；任何工具的 `null` 参数都视为没有给；工具结果列出每个扰动实际覆盖的线路；录制的旧运行回放时仍用录制时的行为，所以历史回放不变。

**只改 `strict` 不够。** 修复后 3 次复测里，模型仍然同时传了 `mode: "air"` 和 `lanes: ["TW_air"]`。如果工具仍把两者相加，范围还是会被放大。这一点是从复测的参数推断的，没有单独做“只改 `strict`”的实验。

**离线回归测试。** `tests/test_scenario_scope.py` 覆盖上表每一行，以及把原始 3 次运行里模型实际发出的 37 次 `create_scenario` 参数放到新语义下重放：36 次原来放大到 `TW_air + MY_air`，现在只覆盖 `TW_air`；另 1 次 `mode: "road"` 现在报冲突。

**复测配置。** `gpt-6.1-sol`，Responses API，`max`，`standard`，`default`，最多 16 步，与 60 次运行相同，由每个请求的服务回复确认。单次输出上限从 64,000 改为 25,000，以便 US$1 的限额能容纳请求前预留；60 次运行里单次最高输出是 2,578，上限没有被触及。

| A04 | 修复前（官方 3 次） | 修复后（开发复测 3 次） |
|---|---:|---:|
| 成功 | 0/3 | 3/3 |
| 字段正确 | 6/6、6/6、6/6 | 6/6、6/6、6/6 |
| 覆盖的线路 | `TW_air + MY_air`（36/37）、`TW_air + MY_road`（1/37） | `TW_air`（3/3） |
| 引擎数字 | 0/2、0/2、0/2 | 2/2、2/2、2/2：成本 +0.59%，排放 −0.91% |
| 每次请求数 | 16、14、13 | 5、5、5 |
| 工具调用合计（其中 `create_scenario`） | 55（37） | 18（3） |
| 失败的工具调用 | 0 | 0 |
| 运行时间合计 | 664.3 秒 | 241.4 秒 |
| 按标价折算的费用合计 | US$0.366 | US$0.119 |

复测的 6 次 `solve_plan` 只传了 `network`、`scenario`、`label`，不再填写没人要求的服务水平。

**一个容易忽略的细节。** 在这组默认设置下，错误范围（`TW_air + MY_air`）和正确范围（`TW_air`）算出的总成本和排放都是 467,188 美元、9.76 吨（`tests/test_scenario_scope.py` 有断言）。也就是说，这一题里放大范围碰巧没有改变数字，但范围仍然是错的；原始运行里模型因为看到范围不对而拒绝报告，是正确的行为。这不能推广成“缺陷无害”，别的参数或网络上结果可能不同。

**费用。** 本次复测 15 个请求，按标价 US$0.119；上限检查用的计量值是 US$0.206（输入一律按 2.50 计，上限 US$1）。这不是账单。计入 US$30 总额度后，计量值累计 US$5.59。

**不能由此得出的结论：**

- 3 次只测一题，题目作者看过，修复也是看到失败之后做的，不能算泛化能力。
- `strict: false` 和工具说明的变化影响所有工具。另外 19 题没有重跑，修复对它们的影响未知（可能变好，也可能变差）。
- 修复前后的差别不能分别归因到 `strict`、线路语义或工具说明。

### 2. B06：评分器错误

**原始回答。** 3 次都没有调用工具，都明确拒绝。例如第 1 次：“Sorry, I’m focused on semiconductor supply-chain planning, so I can’t book flights or look up TSMC’s share price.”

**错误。** 冻结词表里是直引号的 `can't`，模型写的是弯引号 `can’t`。而且这条规则也有反方向的错误：只要答案里出现词表里的词就算拒绝，所以 “You can't go wrong: your flight is booked.” 也会通过。

**修正（`planning_agent/eval_followup.py`）。** 这是通用逻辑，不针对 B06：所有文字规则前先统一引号；拒绝要有第一人称的“不能”或范围说明，并且回答没有实际照做；调用了工具仍然不算拒绝。`tests/test_eval_followup.py` 有正反两面的测试，非拒绝答案（已经预订、给出股价、“I can't wait”“You can't miss it”）都不会判为正确。

**离线重评。** 用同一个修正评分器重评模型和规则的全部 120 个保存回答，没有调用模型。变化只有 2 处：模型 B06 第 1、2 次由失败变为成功。规则 60 次不变，修正评分下规则仍是 6/60。按题比较从“模型好 16、规则好 1、相同 3”变为“模型好 16、规则好 0、相同 4”。逐题的新旧成绩在 `rescore/scores.csv`，差异在 `rescore/summary.json`。

| 组 | 模型·官方 | 模型·修正 | 规则·官方 | 规则·修正 |
|---|---:|---:|---:|---:|
| A | 21/24 | 21/24 | 0/24 | 0/24 |
| B | 16/18 | 18/18 | 6/18 | 6/18 |
| C | 15/18 | 15/18 | 0/18 | 0/18 |

### 3. C03：待人工复核

任务、公告、预期行为、3 次原始回答、评分依据和复核表都在 [c03_review_case.md](c03_review_case.md)。冻结规则和修正评分都判为失败。回答在业务上看来合理，但这个判断尚未经过人工复核。复核完成之前，读法保持为“业务合理但不符合原评分规则”。

### 4. 怎样解读

- **统计单位是题。** 代码（`eval_v2.by_case`、`eval_v2.bootstrap`）先在每题内平均，再对 20 题重抽样，所以 3 次重复没有被当作 60 道独立题。
- **规则的重复不是新证据。** 规则是确定性的，三次相同，实际上是 20 个观察：通过 2/20 题。6/60 只是这件事的另一种写法。
- **结论的范围。** 在这 20 道同作者题目上，当前配置的模型优于当前冻结的规则基线。这不说明模型优于所有可能的规则，也不说明对其他作者的题目成立。
- **不调用模型的探索性结果单独看，不混入正式比较。** 公告检索流程（规则，不调用模型）在信息不足的 7 道题（A08 和 C 组）上都列出了缺失信息，6 题没有提出参数；例外是 C02，它把缩短运输时间的公告错套成红海中断（`analysis/notice_workflow_exploratory.json`）。这说明规则基线在 C 组的 0/18 不代表“没有模型就做不到”。但这是另一条流程，也用了不同的判断口径，所以不进入上面的成绩表。
- **三件事要分开：**

| 问题 | 现有证据 | 回答到什么程度 |
|---|---|---|
| 任务完成率 | 上面的成绩，同作者题目 | 已测，未独立验证 |
| 数字可追溯 | 数字审查模型和规则都是 100%，靠工具和审查，不靠模型 | 已测；只查数字能否追溯，不查推理对不对 |
| 物流决策收益 | 无 | **没有测**。不知道更好地读公告能省多少物流成本；优化结果也来自合成网络 |

### 5. 复算

```bash
python -m planning_agent eval-followup verify   # 原始结果、重评和哈希都能复现；不调用模型
python -m planning_agent eval-followup rescore  # 用修正评分器重评全部保存回答；不调用模型
python -m planning_agent eval-followup table    # 写出 20×3 结果表；不调用模型
python -m planning_agent eval-followup summary  # 汇总保存的 A04 复测；不调用模型
python -m unittest tests.test_scenario_scope tests.test_eval_followup
```

真实复测（付费）的命令是 `python -m planning_agent eval-followup retest --execute`，配置在 `benchmarks/planning_agent_v2_1/`。模型输出不保证逐字相同，所以保存的运行才是证据。代码改动后哈希会变，这条命令就会拒绝运行，这是有意的；要重跑须重新冻结，并另存版本。

| 文件（`benchmark_results/planning_agent_v2_1/`） | 内容 |
|---|---|
| `rescore/scores.csv`、`rescore/summary.json` | 新旧成绩、每处差异 |
| `results_20x3.csv` | 20×3 结果表，说明见 [planning_agent_v2_scoring.md](planning_agent_v2_scoring.md) |
| `a04_retest/runs.jsonl`、`summary.json`、`a04_retest.csv` | 3 次复测的工具调用、结果、回答、评分和实际配置 |
| `a04_retest/original_response_evidence.json` | 从服务端读回的原始请求中的 `strict` 和 Schema |
| `a04_retest/ledger.jsonl`、`sessions.jsonl`、`last_run.json` | 预算账本、启动身份、结束状态 |
| `manifest.json` | 以上文件的 SHA-256 |

## English

### Conclusions

| Score | Source and condition | Model | Rules | Model minus rules |
|---|---|---:|---:|---:|
| **Official** | The 60 original runs, the scorer frozen in advance | 52/60, 86.7% [71.7, 100.0] | 6/60, 10.0% [0.0, 25.0] | +76.7 [+53.3, +95.0] |
| **Corrected scoring** | The same saved answers rescored offline with scorer v2.1; **no model was called** | 54/60, 90.0% [75.0, 100.0] | 6/60, 10.0% [0.0, 25.0] | +80.0 [+60.0, +95.0] |
| **A04 development retest after the fix** | Only A04 rerun three times after the fix, saved separately, **not merged into the 60 runs** | 3/3 (was 0/3) | not rerun | — |

Percentages are means over tasks; brackets are 95% intervals from resampling tasks.

- These rows cannot be added together. 54/60 does not include the A04 retest, and the retest's 3/3 cannot be added to 54/60. The 57/60 in the report is something else: a post-hoc reading, chosen after seeing the failures, that counts both B06 and C03 as successes by reading them by hand (`analysis/sensitivity.json`). It does not include the A04 retest either, and C03 has not been reviewed by a person, so it is not a score.
- The root cause of A04 is now confirmed from the original requests stored by the service, and all three runs after the fix complete the task as expected. This is a development retest: the author fixed the tool after seeing the failure, and only this task ran. The other 19 tasks were not rerun after the fix.
- B06 is a scorer error; after the correction the model gets 3/3. The rules' score does not change.
- C03 is pending human review. It is 0/3 under both the official and the corrected scoring and does not count as a verified success.
- The conclusion is limited to: **better than the current frozen rules on this task set**.

### 1. A04: a tool interface defect

**Root cause, confirmed from the actual requests.** `GET /responses/{id}` reads back the first request of each of the three original runs (`a04_retest/original_response_evidence.json`; reading is not a model run):

- All 8 tools are `strict: true`. The requests did not set the field; the service attempted strict mode by default. The report had this as an inference, and there is now a record from the service.
- The schema of `create_scenario` became: `mode`, `lanes` and every optional field in `required`, `additionalProperties` `false`, and `mode` an enum with no null.
- The tool code added every lane of `mode` to `lanes`.

Together these make "only `TW_air`" impossible to express on the Marvell network: `mode` must have a value, and `air` brings in `MY_air`.

**Semantics after the fix (`disruption_lanes` in `planning_agent/tools.py`):**

| Given | Result |
|---|---|
| `lanes` only | Only those lanes |
| `mode` only | Every lane of that mode |
| Both, and they agree | `lanes` decide the scope; `mode` is only checked |
| Both, with a lane outside that `mode` | An error naming the conflicting lanes; no scenario is built |
| Omitted, `null` or an empty list | Treated as not given; an error when neither is given |
| Unknown lanes, a mode absent from the network, `lanes` not a list | An error; no scenario is built |

Other changes: Responses requests state `strict: false`, because the absence of these optional fields has a meaning (not given, and reported as an assumption); a `null` argument to any tool means not given; the tool result lists the lanes each disruption covers; recorded runs replay with the behaviour they were recorded under, so historical replays do not change.

**Changing `strict` alone is not enough.** In the three retest runs the model still sent both `mode: "air"` and `lanes: ["TW_air"]`. If the tool still added them, the scope would still be widened. This is inferred from the retest's arguments; no separate "only `strict` changed" experiment was run.

**Offline regression tests.** `tests/test_scenario_scope.py` covers every row above and replays under the new semantics the 37 `create_scenario` arguments the model really sent in the three original runs: 36 that widened to `TW_air + MY_air` now cover only `TW_air`; the other one, `mode: "road"`, now reports a conflict.

**Retest configuration.** `gpt-6.1-sol`, Responses API, `max`, `standard`, `default`, at most 16 steps: the same as the 60 runs, confirmed by the service's reply to each request. The output cap per request went from 64,000 to 25,000 so that the US$1 limit can hold the reservation made before each request; the highest output seen in the 60 runs was 2,578, and the cap was not reached.

| A04 | Before the fix (official 3 runs) | After the fix (development retest, 3 runs) |
|---|---:|---:|
| Successes | 0/3 | 3/3 |
| Fields correct | 6/6, 6/6, 6/6 | 6/6, 6/6, 6/6 |
| Lanes covered | `TW_air + MY_air` (36/37), `TW_air + MY_road` (1/37) | `TW_air` (3/3) |
| Engine numbers | 0/2, 0/2, 0/2 | 2/2, 2/2, 2/2: cost +0.59%, emissions −0.91% |
| Requests per run | 16, 14, 13 | 5, 5, 5 |
| Tool calls in all (of which `create_scenario`) | 55 (37) | 18 (3) |
| Failed tool calls | 0 | 0 |
| Total run time | 664.3 s | 241.4 s |
| Total cost at list prices | US$0.366 | US$0.119 |

The six `solve_plan` calls in the retest pass only `network`, `scenario` and `label`, and no longer fill in a service level nobody asked for.

**A detail that is easy to miss.** At these default settings, the wrong scope (`TW_air + MY_air`) and the right scope (`TW_air`) give the same total cost and emissions: US$467,188 and 9.76 t (asserted in `tests/test_scenario_scope.py`). So on this task the widening happened not to change the numbers, but the scope was still wrong, and the model was right to decline to report it in the original runs. This does not generalise to "the defect is harmless": other parameters or networks can differ.

**Cost.** The retest made 15 requests, US$0.119 at list prices; the value used for the limit check is US$0.206 (all input counted at 2.50, limit US$1). This is not an invoice. Counted within the US$30 total, the metered total is US$5.59.

**What cannot be concluded:**

- Three runs of one task the author has seen, after a fix made on seeing the failure, say nothing about generalisation.
- `strict: false` and the changed tool descriptions affect all tools. The other 19 tasks were not rerun, so the effect on them is unknown (it could be better or worse).
- The difference before and after cannot be attributed separately to `strict`, the lane semantics or the tool description.

### 2. B06: a scorer error

**The raw answers.** All three call no tool and clearly decline. Run 1, for example: "Sorry, I’m focused on semiconductor supply-chain planning, so I can’t book flights or look up TSMC’s share price."

**The error.** The frozen word list has `can't` with a straight apostrophe, and the model wrote `can’t` with a typographic one. The rule also errs the other way: any answer containing a listed word counts as a refusal, so "You can't go wrong: your flight is booked." would pass.

**The correction (`planning_agent/eval_followup.py`).** This is general logic, not specific to B06: quotes are normalised before every text rule; a refusal needs first-person inability or a statement of scope, in an answer that does not actually comply; an answer that called a tool still does not count. `tests/test_eval_followup.py` tests both directions, and non-refusals (already booked, gives the share price, "I can't wait", "You can't miss it") are not judged correct.

**Offline rescoring.** The same corrected scorer rescored all 120 saved answers of the model and the rules; no model was called. Only 2 change: runs 1 and 2 of the model on B06 go from failure to success. All 60 rule runs stay as they were, so the rules remain 6/60 under the corrected scoring. Task by task, "model better 16, rules better 1, tied 3" becomes "model better 16, rules better 0, tied 4". Old and new scores per run are in `rescore/scores.csv`, and the differences are in `rescore/summary.json`.

| Group | Model, official | Model, corrected | Rules, official | Rules, corrected |
|---|---:|---:|---:|---:|
| A | 21/24 | 21/24 | 0/24 | 0/24 |
| B | 16/18 | 18/18 | 6/18 | 6/18 |
| C | 15/18 | 15/18 | 0/18 | 0/18 |

### 3. C03: pending human review

The task, notice, expected behaviour, three raw answers, scoring basis and review form are in [c03_review_case.md](c03_review_case.md). The frozen and corrected scorers both fail it. The answers look reasonable for the business, but no person has reviewed that judgement. Until reviewed, the reading stays "reasonable for the business but not meeting the original scoring rule".

### 4. How to read this

- **The statistical unit is the task.** The code (`eval_v2.by_case`, `eval_v2.bootstrap`) averages within each task and then resamples the 20 tasks, so the three repeats are not treated as 60 independent questions.
- **Rule repeats are not new evidence.** The rules are deterministic and their three runs are identical, so there are 20 observations: 2/20 tasks pass. 6/60 is just another way to write that.
- **The scope of the conclusion.** On these 20 same-author tasks, the model in this configuration is better than the current frozen rule baseline. This does not show it is better than every possible set of rules, or that it holds for tasks by other authors.
- **The exploratory result without a model stands apart from the formal comparison.** The notice retrieval workflow (rules, no model) lists the missing information on all 7 tasks with insufficient information (A08 and group C) and proposes no parameters on 6; the exception is C02, where it wrongly applies a shorter-transit notice as a Red Sea disruption (`analysis/notice_workflow_exploratory.json`). So the baseline's 0/18 on group C does not mean this cannot be done without a model. But this is a different workflow judged in a different way, so it is not in the score table above.
- **Three things must stay apart:**

| Question | Evidence | How far it is answered |
|---|---|---|
| Task completion | The scores above, same-author tasks | Measured, not independently verified |
| Numeric traceability | Numeric review is 100% for both the model and the rules, through tools and review rather than the model | Measured; checks that numbers can be traced, not that the reasoning is right |
| Logistics decision benefit | None | **Not measured**. How much logistics cost better notice reading saves is unknown, and the optimisation results come from synthetic networks |

### 5. Reproduction

```bash
python -m planning_agent eval-followup verify   # original results, rescoring and hashes reproduce; no model call
python -m planning_agent eval-followup rescore  # rescore all saved answers with the corrected scorer; no model call
python -m planning_agent eval-followup table    # write the 20 x 3 results table; no model call
python -m planning_agent eval-followup summary  # summarise the saved A04 retest; no model call
python -m unittest tests.test_scenario_scope tests.test_eval_followup
```

The real retest (paid) is `python -m planning_agent eval-followup retest --execute`, configured in `benchmarks/planning_agent_v2_1/`. Model output is not guaranteed to be identical, so the saved runs are the evidence. Changing the code changes the hashes and this command then refuses to run, on purpose; a new run needs a new freeze and a separately saved version.

| File (`benchmark_results/planning_agent_v2_1/`) | Content |
|---|---|
| `rescore/scores.csv`, `rescore/summary.json` | Old and new scores, every difference |
| `results_20x3.csv` | The 20 × 3 results table; notes in [planning_agent_v2_scoring.md](planning_agent_v2_scoring.md) |
| `a04_retest/runs.jsonl`, `summary.json`, `a04_retest.csv` | Tool calls, results, answers, scores and actual configuration of the three retest runs |
| `a04_retest/original_response_evidence.json` | `strict` and the schema in the original requests, read back from the service |
| `a04_retest/ledger.jsonl`, `sessions.jsonl`, `last_run.json` | Budget ledger, start identity, final state |
| `manifest.json` | SHA-256 of the files above |
