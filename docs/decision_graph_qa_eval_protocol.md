# 决策图问答评测协议 / Decision graph QA evaluation protocol

本文先中文、后英文。The Chinese protocol precedes its English version.

## 中文

### 问题与证据范围

在滚动补货与运输中，哪些库存、需求与共享资源信息会改变本期发运，以及这种改变如何影响成本、即时交付和排放？用 [DQ-1 数据](../benchmark_results/decision_graph_qa_v1/manifest.json)中的 40 条合成需求路径、80 条行为轨迹和 880 张图。每图 31 题、63 条边，train、dev、test 分别为 352、176、352 张图。沿用 [DQ-1 原协议](decision_graph_qa_protocol.md)及[求解修订](decision_graph_qa_protocol_amendment.md)。用离线答题方检查评测框架，信息价值的证据来自规划器消融。

### 答题与上下文

| 答题方 | 规则 |
|---|---|
| `gold` | 返回图中的标准答案，检查满分与 B 后果为零。 |
| `perturbed` | 使用 `answer_map(graph, perturb=True)` 的固定扰动，检查错误与违约能被识别。 |
| `rule` | P1 从观测读取，P2 用观测的均值预测调用 `predictions`。以 `base_stock(obs, 1.0)` 的首期动作回答 B，由它得到 P3 的发货标志、路线用量和排放。M 的首期为 B，其后各期为零。 |
| `file` | 读取逐图 JSONL 对象 `{"id":…, "answers":{node_id: answer}}`。默认离线运行将金标准序列化为文件并读回，用于检查文件接口。另可指定外部回答。 |

每个答题方执行 `None`、`Chain`、`Graph` 三种上下文。三者均提供公开观测和当前题目。`Chain` 增加直接父节点问答，`Graph` 增加全部不同祖先的问答，遵循冻结的拓扑顺序。每种上下文用 `gold` 与 `own` 两种来源，分别提供标准和该答题方已作答的上游答案。缺答仍计入应答分母，作为下游上下文时显式标识为缺答。评测输入使用英文，离线答题方忽略输入文本。六个组合的结果一致是框架检查。相同答案映射复用判分。将 test 的三种模式以 `gold` 来源分别导出中英 JSONL，记录字符数。`export-prompts` 也可用回答文件导出 `own` 上下文。题目输入不含实际未来需求、当前答案或求解证据。

### 判分与实际后果

用冻结的 `grade_graph` 判阶段正确率。违约率的分母为已提交的 P3、B、M 回答数。B 的计划超额是固定该动作后重解的目标值减去数据中的参照最优值。计划超额比例除以参照最优值，零分母记为空。扩展规划器的求解关闭预处理。

从真实路径的第 0 期开始重放。`mpc_scenarios` 历史行为使用各先前时点保存的 B，`base_stock` 历史行为按 `base_stock(obs, 0.0)` 回放，与数据生成一致。每个时点在分支前逐字段核对保存的观测。按真实观测检查 B 的整数结构、运力、窗口内到达及 DQ-1 窗口排放额度。违约动作不执行，后果记为空。

对可行动作复制环境，在一支执行作答的 B，在另一支执行保存的 B。两支共享实际需求路径。从下一期起都用冻结的 `decide(obs, "mpc_scenarios")` 执行到第 12 期末，沿用其默认预处理。累计从分支期开始的运费、碳价、持有、逐期积压和追加末期积压成本。即时满足率为余期即时满足的新增需求件数除以余期新增需求件数，零需求时为 1。排放为余期发运排放之和。三项差均为回答减参照。每张图每种可行首期动作只做一次实际回放，两支动作相同时复用同一轨迹。记录库存环境的逐期执行证据和缓存命中数。

### 规划器信息消融

每次只替换下表中的一类信息。I1–I5 用扩展规划器、七条情景和按剩余期数分摊的碳额度。I1、I2、I4、I5 共享真实观测生成的需求样本。I3 用同一生成规则和时点种子对替换后的预测采样。所有行动均回到真实观测判计划超额和在真实路径上评实际后果。

| 项 | 信息与代替值 | 关联题目 |
|---|---|---|
| I1 | 将在途矩阵全部置零。 | `P1.pipeline.*` |
| I2 | 将未清积压向量全部置零。 | `P1.backlog.*` |
| I3 | 将每个剩余期的均值预测换成公开的 `base_mean`。 | `P2.*` |
| I4 | 将剩余排放预算设为 `carbon_budget × (12 − t) / 12`。替换后的窗口额度可高于真实额度，超真实额度的动作记违约。 | `P1.remaining`、`P1.allowance`、`P2.carbon` |
| I5 | 各 SKU 分开规划。按 `base_mean × mass` 的比例分配每条路线的 kg 运力并向下取整，按同一比例分配碳额度。各子问题保留真实输入的 SKU 部分和原七条联合样本中该 SKU 的需求列。合并计划须通过真实共享约束核验。 | 物体层边、`P2.capacity` |
| H | 直接取 `hindsight.first_action_with_known_demand`。该动作来自同窗口的一条已知需求路径，用作事后参照。固定滚动续行策略下的实际总成本差没有由此建立上下界。 | 事后字段 |

动作未变的样本照常计入。计划超额和实际成本差可因目标及续行的区别给出不同排序。I5 测量在此固定分配规则下去掉共享资源调配的后果。

### 统计及运行门槛

- 报告每项的动作改变率、计划超额及相对超额、实际成本差、即时满足率差、排放差及违约数。列出划分汇总和各划分内需求过程与行为策略的交叉分组，正文以 test 为主。均值按图计算。动作变化使用得到动作的图，超额与实际差只使用该指标有值的图。给出分母及缺失/违约数，不给违约补零。
- 以 `(split, profile, seed)` 为整群，在组内有放回抽取等数量的需求路径，保留所抽路径的全部入组时点与行为轨迹，再计算按图均值。使用 `default_rng(984301)` 生成 10,000 次抽样，报告线性插值的 2.5 与 97.5 百分位；无可用值的复样不进入区间。只有一条路径的组无法从重采样估计跨路径变异。不做假设检验，报告所有项。
- 试算按冻结生成顺序在每个划分取第一条需求路径（`stable` 的 5101、5153、5171），保留两种历史策略及 11 个时点，合计 6 条轨迹、66 张图。跑全部离线答题方、上下文和消融。以线性插值单图用时 p95 × 880 + 60 秒估计正式墙钟。估计超过 5,400 秒则停在试算。正式运行顺序单进程，每次求解 30 秒上限，无重试，整轮以四小时为限。保留原始失败，实际出错求解数超过累计实际求解次数的 1% 即中止。固定答案的无效动作及求解证实的回答不可行计作违约。
- 开工核对冻结数据。回放不一致、金标准判分未满分、金标准 B 两类后果超出 DQ-1 容差时立即中止。冻结模块的已知可行点或物理目标复核出错也中止。正式产物保留逐图证据、试算门槛、输入长度和 SHA256 清单。`verify-eval` 不求解，核对清单并由原始证据重算汇总和区间。真实大模型评测需单独批准预算。

## English

### Question and evidence scope

Which inventory, demand and shared-resource information changes current dispatch in rolling replenishment and transport, and how do the resulting decisions affect cost, immediate fulfillment and emissions? Use the [DQ-1 dataset](../benchmark_results/decision_graph_qa_v1/manifest.json) with 40 synthetic demand paths, 80 behavior trajectories and 880 graphs. Each graph has 31 questions and 63 edges. Train, dev and test contain 352, 176 and 352 graphs. Follow the [DQ-1 protocol](decision_graph_qa_protocol.md) and [solver amendments](decision_graph_qa_protocol_amendment.md). Offline responders exercise the evaluation framework. The planner ablations supply the evidence about information value.

### Responders and contexts

| Responder | Rule |
|---|---|
| `gold` | Return the stored answers to check full credit and zero B consequence differences. |
| `perturbed` | Use the fixed `answer_map(graph, perturb=True)` perturbations to check detection of errors and violations. |
| `rule` | Read P1 from the observation and compute P2 with `predictions` on the observed mean forecast. Answer B with the first dispatch from `base_stock(obs, 1.0)`. Derive P3 dispatch flags, route loads and emissions from B. Put B first in M and set later dispatches to zero. |
| `file` | Read one JSONL object per graph with `{"id":…, "answers":{node_id: answer}}`. The default offline run writes then reads back the gold answers to exercise file ingestion. External answers can be supplied separately. |

Run every responder with `None`, `Chain` and `Graph` contexts. All three show the public observation and current question. `Chain` adds direct-parent QA. `Graph` adds distinct ancestor QA in the frozen topological order. Each mode uses `gold` and `own` sources for stored and previously submitted upstream answers, respectively. Missing responses count in the expected-answer denominator and are marked explicitly when shown upstream. Evaluation renders English inputs. Offline responders ignore the text, so identical results across the six combinations exercise the framework. Identical answer maps reuse grades. Export the test inputs for every mode in both languages with `gold` upstream answers and count characters. `export-prompts` can also export `own` with an answer file. Inputs exclude realized future demand, the current answer and solver evidence.

### Grading and realized consequences

Use the frozen `grade_graph` for stage accuracy. The violation denominator is the supplied P3, B and M replies. Planning excess for B is the objective after re-optimization with the action fixed minus the stored reference optimum. Relative excess divides by the stored optimum and is undefined at zero. The extended planner uses presolve off.

Replay the realized path from period 0. Use earlier stored B actions for the `mpc_scenarios` history and `base_stock(obs, 0.0)` for the `base_stock` history, as in dataset generation. Compare the full replayed observation to the saved observation before branching. Check B for integer structure, route capacity, arrival in the window and the DQ-1 paced window emissions allowance under the real observation. Violating actions are skipped and have missing consequences.

Fork the environment for each feasible action. Apply the submitted B in one branch and the stored B in the other. Both experience the same realized demand. From the following period to the end of period 12, both use the frozen `decide(obs, "mpc_scenarios")` with its default presolve setting. Accumulate freight, carbon charges, holding, period backlog and additional terminal backlog costs from the branch point. Immediate fulfillment divides immediately filled new units by new demand units over the remaining periods and is 1 at zero demand. Emissions sum dispatch emissions over those periods. The three differences are submitted minus reference. Replay each feasible first action once per graph and share the trajectory when both actions match. Record period-level execution evidence and cache hits.

### Planner information ablations

Replace one information category at a time. I1–I5 use the extended planner, seven scenarios and a carbon allowance paced by the remaining periods. I1, I2, I4 and I5 use the demand samples from the true observation. I3 samples from the substituted forecast through the same generator and period seed. Evaluate planning excess under the true observation and realized consequences on the real demand path.

| Item | Information and substitute | Related questions |
|---|---|---|
| I1 | Set all entries of the pipeline matrix to zero. | `P1.pipeline.*` |
| I2 | Set all entries of the outstanding backlog vector to zero. | `P1.backlog.*` |
| I3 | Use the public `base_mean` as the mean forecast at every remaining period. | `P2.*` |
| I4 | Set remaining emissions budget to `carbon_budget × (12 − t) / 12`. This can exceed the true window allowance. Actions above the true allowance are violations. | `P1.remaining`, `P1.allowance`, `P2.carbon` |
| I5 | Plan each SKU separately. Divide each route's kg capacity in proportion to `base_mean × mass` and round down. Divide the carbon allowance by the same proportions. Retain the SKU's true inputs and its demand column in the seven original joint samples. Check the combined schedule against the true shared constraints. | Object edges, `P2.capacity` |
| H | Use the stored `hindsight.first_action_with_known_demand`. It comes from a single known demand path over the same window and serves as a hindsight reference. It supplies no bound on realized total cost differences under the fixed rolling continuation. | Hindsight field |

Include observations with unchanged actions. Planning excess and realized cost may rank interventions differently because the objective and continuation differ. I5 measures the consequence of dropping shared-resource allocation under this particular fixed allocation rule.

### Statistics and run gates

- Report action-change rate, absolute and relative planning excess, realized cost, immediate fulfillment and emissions differences, and violations for every item. Include split totals and demand-profile by behavior-policy groups within each split, with test as the primary split. Compute graph-level means. Use graphs with an action for action changes, and graphs with an available metric for excess and realized differences. Report counts and missing or violated answers without substituting zeros for violations.
- Resample `(split, profile, seed)` clusters within each group with replacement, keeping the original number of paths. Retain all in-group times and policy trajectories for sampled paths, and recompute the graph-level mean. Use `default_rng(984301)` for 10,000 draws and linear 2.5th and 97.5th percentiles. Exclude draws without an available metric from the interval. A group with one path cannot estimate between-path variation by resampling. Report every item and run no hypothesis tests.
- Select the first demand path in the frozen generation order within each split (`stable` seeds 5101, 5153 and 5171) for the pilot. Keep both historical policies and 11 times, giving 6 trajectories and 66 graphs. Run all offline responders, contexts and ablations. Estimate formal wall time as linearly interpolated per-graph p95 × 880 + 60 seconds. Stop at the pilot if the estimate exceeds 5,400 seconds. Run formal evaluation sequentially in one process. Limit each solve to 30 seconds with no retries and the full round to four hours. Preserve solver errors and stop if failed calls exceed 1% of actual calls attempted. Invalid replies and proven answer infeasibility count as violations.
- Verify the frozen dataset before starting. Stop on observation mismatch, incomplete gold credit, or a nonzero gold B difference in either evaluation beyond DQ-1 tolerance. Stop on a frozen planner known-feasible-point or physical-objective audit failure. Formal artifacts retain per-graph evidence, the timing gate, input lengths and a SHA256 manifest. `verify-eval` checks hashes and recomputes summaries and intervals from raw evidence without solving. Evaluation with live LLMs requires separate budget approval.
