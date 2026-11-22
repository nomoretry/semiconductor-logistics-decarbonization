# 决策图问答协议修订：不可行状态复核 / Decision graph QA protocol amendment for infeasibility checks

本文先中文、后英文。The Chinese amendment precedes its English version.

## 中文

### 试算诊断

首轮试算尝试 264 张图，完成 263 张。第 198 张图 `test-stable-5171/base_stock/10` 在快线用量最大值核验中报错。该图只有快线能在两期窗口内到达。参照计划为 `[[[0,0],[0,0],[0,4]],[[0,0],[0,0],[0,0]]]`，物理复算成本为 218.4，最优面约束上界为 218.4002185。

在 SciPy 1.17.0 中重放该观测，HiGHS 开启预处理时对快线用量最大值和发运排放最大值均返回状态 2（不可行）。参照计划是这两个问题的可行解，行约束最大违约约为 2.8×10⁻¹⁴。关闭预处理后，两次求解均返回最优，分别为 4 kg 和 16，与各自的最小值相同。同一观测的三项反向发货标志和首期动作排除检查在预处理开关两种设置下结果一致。首轮试算由此识别了一个误报不可行的状态。其他状态的误报也可能影响并列统计，因此所有受影响类型的不可行状态均须复核。

### 求解与验收规则

1. 新规划器返回状态 2 时，用相同的问题关闭预处理（`presolve=False`）再求解一次。第二次返回最优时，用其解完成整数性、可行性和物理复算检查，按求解标签计入 `presolve_retry_recovered`。两次均返回状态 2 时才确认不可行，按标签计入 `presolve_retry_confirmed`。其他求解状态沿用原错误处理。
2. 参照计划在构造上属于最优面。任一端点确认不可行或物理成本超过上界，均作为核验错误处理。失败记录包含各次调用的求解状态、计划、模型目标值（端点问题中为带符号的运量或排放）、物理成本和上界。对不可得的值记录空值。端点核验失败、规划器目标值不一致或排除首期动作核验失败时立即中止，记录图编号与原因。逐图记录与汇总均按求解标签保存两类复核计数，实际求解次数含复核调用。
3. 按原划分和顺序重新试算 24 条策略轨迹、264 张图，任一试算失败即中止。正式生成要求试算零失败，且线性插值单图 p95×880+60 秒不超过 3,600 秒。保留首轮试算及哈希，按图编号比较两轮共有图中的 `opposite_flags`、`load_ranges`、`emission_range` 和 `other_action`。逐项记录差异及对应的复核证据。有差异且无法由纠正误报解释时中止。正式生成单进程顺序执行，正式阶段的其他失败或超时沿用失败数/已尝试图数 >1% 的中止线，并保留原始失败记录。

[原协议](decision_graph_qa_protocol.md)继续规定数据划分、种子、行为策略、模板、答案计算、容差、判分、复算和运行预算。每次求解仍限时 30 秒，整轮上限四小时。试算和正式生成的计时均按共享机器上的实际墙钟报告。实现见[扩展规划器](../decision_graph_qa/planner.py)、[生成与计数](../decision_graph_qa/dataset.py)和[回归测试](../tests/test_decision_graph_qa.py)。

## English

### Pilot diagnosis

The initial pilot attempted 264 graphs and completed 263. Graph 198, `test-stable-5171/base_stock/10`, raised an error while checking the maximum fast-route load. Only the fast route can arrive within its two-period window. The reference schedule is `[[[0,0],[0,0],[0,4]],[[0,0],[0,0],[0,0]]]`, its replayed physical cost is 218.4, and the optimal-face ceiling is 218.4002185.

Replaying the observation in SciPy 1.17.0 with HiGHS presolve enabled returned status 2 (infeasible) for both the maximum fast-route load and maximum dispatch emissions. The reference schedule is feasible for both problems, with a maximum row violation of approximately 2.8×10⁻¹⁴. Disabling presolve yielded optimal values of 4 kg and 16 respectively, equal to their minima. The three opposite dispatch flag checks and the first-action exclusion check for the same observation agreed under both presolve settings. The pilot identified a false infeasibility result in this state. Such results in other states could affect tie counts, so infeasibility requires confirmation across the affected solve types.

### Solver and acceptance rules

1. When the extended planner returns status 2, re-solve the identical problem once with `presolve=False`. If the second solve returns an optimum, check integrality, feasibility and physical replay and count it by solve label under `presolve_retry_recovered`. Confirm infeasibility only after two status-2 results and count it by label under `presolve_retry_confirmed`. Keep the existing error handling for other solver statuses.
2. The reference schedule belongs to the optimal face by construction. Confirmed infeasibility or replayed physical cost above the ceiling constitutes an endpoint audit error. Failure records include each solver status, the schedule, the model objective (the signed load or emissions for an endpoint), the physical cost and the ceiling, using null for unavailable values. Halt immediately on an endpoint audit failure, a planner objective mismatch or a first-action exclusion audit failure, recording the reason and graph ID. Per-graph records and summaries retain both retry counts by solve label. Solve counts include retry calls.
3. Repeat the pilot with the original splits and order for 24 policy trajectories and 264 graphs, halting on any pilot failure. The formal build requires zero pilot failures and a linearly interpolated per-graph p95×880+60 seconds of at most 3,600 seconds. Preserve the initial pilot and its hashes. Join the two pilots on graph ID and compare `opposite_flags`, `load_ranges`, `emission_range` and `other_action` on all shared graphs. Record every difference and its retry evidence. Halt on any difference that the correction of false infeasibility cannot explain. Run the formal build sequentially in one process. For other formal failures or timeouts, retain the >1% failures-to-attempts halt threshold and preserve the original failure records.

The [original protocol](decision_graph_qa_protocol.md) governs splits, seeds, behavior policies, templates, answer computation, tolerance, scoring, replay and timing budgets. Each solve has a 30-second limit and the full run has a four-hour limit. Report actual pilot and formal wall times measured on a shared machine. See the [extended planner](../decision_graph_qa/planner.py), [generation and counts](../decision_graph_qa/dataset.py) and [regression tests](../tests/test_decision_graph_qa.py).

## 修订 2 / Amendment 2

### 中文

修订 1 后，正式生成完成 880 张图，无求解复算与 10% 抽样重解均通过。全量金标准判分为 27,279/27,280，在 `train-volatile-5101/base_stock/5` 的 `P3.load.1` 出现一处错判，正式数据停在金标准验收。

在该图的六期窗口，参照最优费用为 108.328571，首期动作是 `[[2,3],[2,0],[2,0]]`，快线用量恰为 3 kg。用 SciPy 1.17.0 重放快线用量固定为 3 kg 的约束模型。HiGHS 开启预处理时返回状态 0 和 gap 0，目标值与对偶界均为 109.407143，首期动作为 `[[2,3],[3,0],[0,0]]`。物理重放费用超额 1.078571。参照计划满足新增约束，最大行违约约为 1.8×10⁻¹⁵。关闭预处理后重解得到参照计划与 108.328571 的费用。这次错误最优出现在状态 0，修订 1 只对状态 2 触发复核。

1. 扩展规划器的无约束、反向发货标志、最优面端点、首期动作排除和判分约束求解一律使用 `presolve=False`。保留修订 1 的防御分支与计数，实际启用预处理且返回状态 2 才会进入该分支。本协议的正常运行中两类复核计数均为零。汇总注明扩展规划器的预处理关闭、冻结的参照规划器预处理开启。
2. 对判分约束，若已存参照计划满足新增约束，重解必须得到可行计划且物理费用不超过参照最优值加协议容差。确认不可行或费用超限作为核验错误并中止，记录图编号、题号、参照费用和重解费用，费用不可得时记录空值。反向发货标志与排除首期动作的约束主动排除参照计划。最优面端点沿用物理重放检查。冻结的 `rolling_inventory.planning.solve` 继续按原设置运行。生成时逐图比较两个规划器的无约束最优值，超容差即中止。
3. 保留首次正式生成的原始记录。按相同划分和顺序重新试算 264 张图，按图比较并列字段及 P3/B/M 答案。通过零失败与耗时门槛后重新正式生成。新正式集须通过无求解复算、10% 抽样重解、金标准满分且零违约及固定扰动检查。逐图比较两份正式集的参照最优值、P3/B 答案和并列字段，并记录每项差异的依据与归因。场景、种子、题目、判分容差、预算及其余验收条件沿用原协议及上述修订。

### English

After Amendment 1, formal generation completed 880 graphs. Solver-free verification and the 10% re-solving check passed. The full gold score was 27,279/27,280. The sole rejected gold answer was `P3.load.1` on `train-volatile-5101/base_stock/5`, which held the release at the gold-scoring check.

The six-period window has a reference optimum of 108.328571. Its first action `[[2,3],[2,0],[2,0]]` uses exactly 3 kg of fast-route capacity. The scoring model with fast-route utilization fixed at 3 kg was replayed in SciPy 1.17.0. With presolve enabled, HiGHS returned status 0 and gap 0, with objective and dual bound both 109.407143 and first action `[[2,3],[3,0],[0,0]]`. The replayed physical cost excess was 1.078571. The reference schedule satisfies the added constraint, with a maximum row violation of approximately 1.8×10⁻¹⁵. Disabling presolve returned the reference schedule and its cost of 108.328571. This incorrect optimum returned status 0. Amendment 1 triggers its confirmation solve only on status 2.

1. Use `presolve=False` for every solve in the extended planner, including unrestricted, opposite dispatch flag, optimal-face endpoint, first-action exclusion and constrained scoring solves. Retain the defensive branch and counts from Amendment 1 for status-2 results from solves with presolve enabled. Both retry counts are zero in normal operation under this protocol. Summaries record presolve disabled for the extended planner and enabled for the frozen reference planner.
2. When the stored reference schedule satisfies the scoring constraints, re-solving must return a feasible plan whose physical cost is at most the reference optimum plus the protocol tolerance. Confirmed infeasibility or excess above tolerance constitutes an audit error and halts the run. Record the graph ID, question ID, reference cost and re-solved cost, using null for an unavailable cost. Opposite flag and first-action exclusion constraints deliberately exclude the reference plan. Optimal-face endpoints retain their physical replay check. The frozen `rolling_inventory.planning.solve` uses its original settings. Compare the planners' unrestricted optima on each graph and halt on discrepancies beyond tolerance.
3. Preserve the first formal generation output. Repeat the 264-graph pilot with identical splits and order, comparing tie fields and P3/B/M answers graph by graph. Rebuild the formal release after the zero-failure and time gates pass. Require solver-free verification, a 10% re-solving check, full gold credit with zero violations and the fixed perturbation check. Compare the reference objectives, P3/B answers and tie fields graph by graph between both formal outputs and record evidence and attribution for each difference. The scenarios, seeds, questions, scoring tolerance, budgets and other acceptance conditions follow the original protocol and Amendment 1.
