# 公告影响范围读错的后果与事先确认的价值 / What misreading a notice's scope costs, and what confirming it is worth

本文提供中英文版本，中文在前，英文在后。数字来自 [`benchmark_results/scope_misread_v1/`](../../benchmark_results/scope_misread_v1) 和 [`benchmark_results/scope_value_v1/`](../../benchmark_results/scope_value_v1)，不调用模型，只用本地求解器。所有订单、运力和费率都是合成假设。
This document provides Chinese first and English second. Numbers come from [`benchmark_results/scope_misread_v1/`](../../benchmark_results/scope_misread_v1) and [`benchmark_results/scope_value_v1/`](../../benchmark_results/scope_value_v1); no model is called and everything is solved locally. All orders, capacities and rates are synthetic assumptions.

## 中文

### 问题

评测题 A04 的公告只影响台湾空运（`TW_air`）。旧工具接口会把范围扩大到全部空运（`TW_air` 和 `MY_air`），而两种范围算出的总成本和排放相同（[后续报告](planning_agent_v2_followup.md)）。这里回答三件事：为什么相同；按错误范围做的计划放回真实情景后，在什么条件下才有后果；计划员拿不准范围时，事先确认值多少。

### 方法

- **网络**：Marvell 启发网络，12 个 SKU、16 周、种子 7。扰动取 A04 的参数：第 7–9 周，现货舱位 −33.33%，现货运价 +15%。
- **两种计算分开**：
  - 两个情景各自最优值之差：计划员以为的情景的最优成本减真实情景的最优成本。这是两个不同情景的比较，不是损失。
  - 遗憾：按错误范围做的计划在真实情景中执行。得知真相之前的发运和整季空运预留保持不变，之后的发运重新优化（`solve(fixed_first_stage=...)`，模型原有的调整）。遗憾等于这个结果的成本减真实情景的最优成本。
- **得知真相的时点**：第 1 周（只有预留已定）、第 7 周（窗口打开时）、第 10 周（窗口过后），以及始终不重排。
- **只改一个条件**：`MY_road` 每周舱位，用马来西亚平均周需求的倍数表示，原值 1.5。需求、服务条款和其他输入不变。取值范围在求解之前提交；0.2 到 0.1 之间的加密取值是看到结果后加的，只用来定位分界点。
- **多个同样好的方案**：另算一个“有利平局”遗憾：在错误读法下几乎同样好的计划里，取真实情景中表现最好的那个。
- 求解器 HiGHS，`mip_gap=1e-7`；代码 `network_planning/misread.py`。

### 结果一：原案例里两种范围为什么相同

- 用保存的 A04 工具参数重放：修复后的接口覆盖 `TW_air`，旧接口覆盖 `TW_air + MY_air`，两者都是 467,188 美元、9.76 吨、服务水平 100%。
- 发运方案本身也相同：158 个发运变量逐项一致，线路启用和预留也一致。
- 原因：
  1. 台湾货只能走 `TW_air` 和 `TW_ocean`，马来西亚货只能走 `MY_air` 和 `MY_road`，两地没有共用线路。多出来的 `MY_air` 扰动只可能影响马来西亚货。
  2. 第 7–9 周马来西亚货全部走公路：同样 1 周到，运价 0.7 对 5.5 美元/kg，公路每周 276.6 kg，这三周最多用 199 kg。`MY_air` 在窗口内闲置，扰动加在它上面不改变任何约束和成本。

### 结果二：实际只有 `TW_air` 受扰，计划员按全部空运做计划

| `MY_road` 舱位倍数 | 窗口内 `MY_air` 用量（最优计划） | 两个最优值之差（美元） | 发运是否不同 | 遗憾（美元）：第 1 周 / 第 7 周 / 第 10 周得知 / 不重排 |
|---|---|---:|---|---|
| 1.5、1.25、1.1 | 0 | 0 | 相同 | 0 / 0 / 0 / 0 |
| 1.0–0.7 | 27–142 kg，都在预留舱位内 | 0 | 线路周货量相同 | 0 / 0 / 0 / 0 |
| 0.6–0.2 | 198–423 kg，用到现货，不超过削减后的上限 | 28–209 | 线路周货量相同 | 0 / 0 / 0 / 0 |
| 0.19–0.15（事后加密） | 441–506 kg | 393–3,213 | 窗口内各周的分配不同 | 0 / 0 / 166–2,919 / 166–2,919 |
| 0.14–0.11（事后加密） | 523–573 kg | 3,843–5,948 | 开窗前也不同 | 0 / 200–1,600 / 3,538–5,644 / 3,538–5,644 |
| 0.1 | 590 kg | 6,421 | 第 6 周多空运 74 kg | 0 / 2,125 / 6,117 / 6,117 |
| 0.0 | 664 kg | 17,184 | 第 3–5 周多空运 147 kg | 0 / 13,396 / 16,880 / 16,880 |

- **什么时候才有后果**：模型里公告只改现货舱位和现货价格，预留舱位不受影响。所以 `MY_air` 开始被使用（倍数 1.0 以下）和用到现货（0.6 以下）时，发运都不变；计划员只是以为要多付附加费，这正是“两个最优值之差”，它不是损失。只有削减后的现货上限真正卡住（某周 `MY_air` 超过 172 kg，倍数 0.19 以下，即公路只能运平均需求的不到五分之一）时，发运才改变。
- **代价是什么**：全部是提前备货多出来的库存持有成本。服务水平始终 100%，没有积压和期末缺口；排放最多增加 0.016 吨。
- **可行性**：没有出现不可行。误读的计划以为的舱位比实际少，放回真实情景总能执行。
- **平局**：倍数 0.9 和 0.2 处两个计划有 4 个和 60 个变量不同，但线路周货量相同、成本相同，是 SKU 之间同样好的方案。有遗憾的情形里，“有利平局”遗憾与原值相同，所以不是求解器任选最优解造成的。
- 第 1 周就得知真相时遗憾为 0，因为两种读法的空运预留相同。

### 结果三：反方向，实际全部空运受扰，计划员只按 `TW_air` 做计划

| `MY_road` 舱位倍数 | 遗憾（美元）：第 1 周 / 第 7 周得知 | 第 10 周得知，或不重排 |
|---|---|---|
| 1.5–0.2（12 个取值） | 0 / 0 | 可行，遗憾 0 |
| 0.1 | 0 / 8,595，期末库存缺口 48 件 | 不可行：`MY_air` 第 8、9 周的现货发运超过实际舱位 |
| 0.0 | 0 / 10,433，期末库存缺口 80 件 | 不可行：`MY_air` 第 7–9 周的现货发运超过实际舱位 |

- 读窄和读宽的后果性质不同。读宽只多付持有成本；读窄时，开窗才知道已经来不及提前备货，期末库存目标达不到（缺口罚金 31,526 和 65,874 美元，扣掉少付的持有成本等之后是上表的净遗憾）。
- 按积压计算的服务水平仍是 100%：缺口落在计划期末的库存目标上，这是模型期末条款的结果，不代表现实中客户不受影响。
- 窗口过后才发现，或始终照原计划执行：原计划在窗口内的 `MY_air` 现货发运超过实际存在的舱位，违反现货舱位约束，计划无法执行，所以不报遗憾。

### 结果四：拿不准范围时，事先确认值多少

计划员不知道公告是窄（只有 `TW_air`）还是宽（全部空运），宽的概率是 p。不确认时，范围在第 4 周或第 7 周自己显现，计划员可以按窄做、按宽做，或用两阶段随机规划对冲。确认指第 1 周之前就知道。确认的价值 = 对冲方案的期望成本 − 知情后的期望成本。

| `MY_road` 舱位倍数 | 第 4 周显现（p = 0.1 / 0.25 / 0.5 / 0.75 / 0.9） | 第 7 周显现（同样的 p） |
|---|---|---|
| 1.5–0.2（12 个取值） | 0 | 0 |
| 0.1 | 0 | 860 / 1,540 / 1,030 / 520 / 212 美元 |
| 0.0 | 228 / 571 / 985 / 520 / 229 美元 | 1,043 / 2,608 / 3,487 / 3,031 / 1,340 美元 |

- 14 个取值里的 12 个（包括原案例），确认范围的价值是 0：两种读法给出同一个计划。这时为确认花的时间或费用不改变任何物流决策。
- 只有公路几乎关闭、而且范围要到窗口打开才显现时，确认才有价值，数百到约 3,500 美元。倍数 0.1 时提前三周显现（第 4 周）就已经够用，价值为 0。
- 不确认时的简单做法：按窄做的期望损失是 p × 读窄的遗憾，按宽做是 (1 − p) × 读宽的遗憾。倍数 0.1、第 7 周显现时，读窄 8,595 美元，读宽 2,125 美元；p = 0.25 时按窄做损失 2,149，按宽做 1,594，对冲 1,540。倍数 0.0 时两边接近（10,433 对 13,396）。
- 与信息处理成本对照：评测中模型读一条公告的中位成本是 0.034 美元、73 秒（按标价折算）。这只说明读公告本身便宜。向承运人确认范围要花计划员的时间，这个成本项目里没有测量。

### 能说和不能说的

- 能说：在这个合成网络里，范围读错只在替代线路几乎消失时才改变发运；读宽的代价是持有成本，读窄的代价是期末缺口，发现得太晚计划就无法执行；“两个情景的最优值之差”会高估读宽的损失；其余条件下确认范围不改变物流决策。
- 不能说：这是企业实测；对别的网络、别的扰动幅度同样成立；预留舱位在现实中一定不受公告影响（这是模型假设）。
- 评测成绩的三种口径不变：官方 52/60，修正评分 54/60，A04 修复后复测 3/3；C03 待人工复核。

### 复算

```bash
python scripts/run_scope_misread.py --check
python scripts/run_scope_misread.py --refinement --check
python scripts/run_scope_value.py --workers 6 --check
python -m unittest tests.test_scope_misread
```

### 下一项验收条件

现有结论只限这个网络和这组参数。要推广，需要先满足下面任一条件，并且协议先于结果提交、保留零差异和不可行结果：

1. 网络里有两地共用的运力。现在台湾和马来西亚的货没有共用线路，所以读错范围只影响被多算或少算的那一地。
2. 公告也影响预留舱位的模型变体。现在预留舱位不受影响，这是误读在大部分取值下没有后果的直接原因。
3. 换需求随机种子后，分界点和遗憾的量级是否稳定。

## English

### Question

The notice in evaluation task A04 affects Taiwan air (`TW_air`) only. The old tool interface widened the scope to every air lane (`TW_air` and `MY_air`), yet both scopes gave the same total cost and emissions ([follow-up report](planning_agent_v2_followup.md)). This document answers three things: why they were the same; under which conditions a plan made for the wrong scope has consequences once it meets what occurs; and what confirming the scope in advance is worth to a planner who is unsure.

### Method

- **Network**: the Marvell-inspired network, 12 SKUs, 16 weeks, seed 7. The disruption uses A04's parameters: weeks 7–9, spot space −33.33%, spot rate +15%.
- **Two computations kept apart**:
  - The difference between two optima: the optimum of the scenario the planner believed minus the optimum of the scenario that occurred. This compares two different scenarios and is not a loss.
  - Regret: the plan made for the wrong scope is carried out in the scenario that occurred. Dispatches before the planner learns the truth, and the season's air reservation, stay as planned; later dispatches are re-optimised (`solve(fixed_first_stage=...)`, an adjustment the model already allows). Regret is the cost of that outcome minus the optimum of the scenario that occurred.
- **When the truth is learnt**: week 1 (only the reservation is committed), week 7 (when the window opens), week 10 (after the window), and never re-planning.
- **One condition changed**: weekly space on `MY_road`, as a multiple of mean weekly Malaysia demand; the original value is 1.5. Demand, service terms and every other input stay fixed. The grid was committed before solving; the finer values between 0.2 and 0.1 were added after seeing the results, only to locate the threshold.
- **Several equally good plans**: a "favourable tie-break" regret is also computed: among the plans that are almost equally good under the wrong reading, the one that does best in what occurred.
- Solver HiGHS, `mip_gap=1e-7`; code in `network_planning/misread.py`.

### Result 1: why the two scopes agree on the original case

- Replaying the saved A04 tool arguments: the fixed interface covers `TW_air`, the old one `TW_air + MY_air`, and both give US$467,188, 9.76 t and a 100% service level.
- The dispatch plans themselves are the same: all 158 shipment variables agree, as do lane activations and reservations.
- Reasons:
  1. Taiwan cargo can only use `TW_air` and `TW_ocean`, and Malaysia cargo only `MY_air` and `MY_road`; the two origins share no lane. The extra disruption on `MY_air` can only affect Malaysia cargo.
  2. In weeks 7–9 all Malaysia cargo goes by road: the same one-week lead time, US$0.7 against US$5.5 per kg, and 276.6 kg of weekly road space of which at most 199 kg is used in those weeks. `MY_air` is idle in the window, so a disruption on it changes no constraint and no cost.

### Result 2: only `TW_air` is affected, and the planner plans for every air lane

| `MY_road` space multiple | `MY_air` use in the window (best plan) | Difference between the two optima (USD) | Do dispatches differ | Regret (USD): learnt in week 1 / week 7 / week 10 / never re-planned |
|---|---|---:|---|---|
| 1.5, 1.25, 1.1 | 0 | 0 | Same | 0 / 0 / 0 / 0 |
| 1.0–0.7 | 27–142 kg, all within reserved space | 0 | Same lane-week loads | 0 / 0 / 0 / 0 |
| 0.6–0.2 | 198–423 kg, uses spot space, within the reduced limit | 28–209 | Same lane-week loads | 0 / 0 / 0 / 0 |
| 0.19–0.15 (post hoc) | 441–506 kg | 393–3,213 | Weeks within the window differ | 0 / 0 / 166–2,919 / 166–2,919 |
| 0.14–0.11 (post hoc) | 523–573 kg | 3,843–5,948 | Weeks before the window differ too | 0 / 200–1,600 / 3,538–5,644 / 3,538–5,644 |
| 0.1 | 590 kg | 6,421 | 74 kg more by air in week 6 | 0 / 2,125 / 6,117 / 6,117 |
| 0.0 | 664 kg | 17,184 | 147 kg more by air in weeks 3–5 | 0 / 13,396 / 16,880 / 16,880 |

- **When there are consequences**: in the model a notice changes spot space and the spot price only; reserved space is untouched. So dispatches stay the same when `MY_air` starts to be used (multiple below 1.0) and when it uses spot space (below 0.6); the planner merely expects to pay a surcharge, which is exactly the difference between the two optima and is not a loss. Dispatches change only when the reduced spot limit really binds (`MY_air` above 172 kg in some week, at a multiple of 0.19 or less, that is when the road can carry less than a fifth of mean demand).
- **What the cost is**: all of it is extra inventory holding from stocking up early. The service level stays at 100%, with no backlog and no shortfall at the end; emissions rise by at most 0.016 t.
- **Feasibility**: nothing was infeasible. The misread plan assumes less space than exists, so it can always be carried out in what occurs.
- **Ties**: at multiples 0.9 and 0.2 the two plans differ in 4 and 60 variables, but lane-week loads and cost are the same; these are equally good choices among SKUs. Where there is regret, the favourable tie-break regret equals it, so it is not an accident of which optimum the solver returned.
- Regret is 0 when the truth is learnt in week 1, because both readings reserve the same air space.

### Result 3: the reverse, every air lane is affected and the planner plans for `TW_air` only

| `MY_road` space multiple | Regret (USD): learnt in week 1 / week 7 | Learnt in week 10, or never re-planned |
|---|---|---|
| 1.5–0.2 (12 values) | 0 / 0 | Feasible, regret 0 |
| 0.1 | 0 / 8,595, with 48 units short of the closing stock target | Infeasible: spot dispatches on `MY_air` in weeks 8 and 9 exceed the space that exists |
| 0.0 | 0 / 10,433, with 80 units short of the closing stock target | Infeasible: spot dispatches on `MY_air` in weeks 7–9 exceed the space that exists |

- Reading too narrowly and too broadly differ in kind. Too broad only adds holding cost. Too narrow means that when the window opens it is too late to stock up, and the closing stock target is missed (shortfall penalties of US$31,526 and US$65,874; after the holding cost and other costs not paid, the net regret is as in the table).
- The service level measured on backlog stays at 100%: the gap lands on the stock target at the end of the horizon. That follows from the model's closing terms and does not mean customers would be unaffected in reality.
- Learnt after the window, or never re-planned: the plan's spot dispatches on `MY_air` in the window exceed the space that exists, which violates the spot space constraint. The plan cannot be carried out, so no regret is reported.

### Result 4: what confirming the scope is worth to a planner who is unsure

The planner does not know whether the notice is narrow (`TW_air` only) or broad (every air lane); the probability of broad is p. Without confirmation the scope shows by itself in week 4 or week 7, and the planner can plan for narrow, plan for broad, or hedge with a two-stage stochastic plan. Confirmation means knowing before week 1. Its value is the expected cost of the hedge minus the expected cost when informed.

| `MY_road` space multiple | Shows in week 4 (p = 0.1 / 0.25 / 0.5 / 0.75 / 0.9) | Shows in week 7 (same p) |
|---|---|---|
| 1.5–0.2 (12 values) | 0 | 0 |
| 0.1 | 0 | US$860 / 1,540 / 1,030 / 520 / 212 |
| 0.0 | US$228 / 571 / 985 / 520 / 229 | US$1,043 / 2,608 / 3,487 / 3,031 / 1,340 |

- At 12 of the 14 values, the original case among them, confirming the scope is worth 0: both readings give the same plan. Time or money spent on confirming then changes no logistics decision.
- Confirmation has value only when the road is almost closed and the scope would not show until the window opens: a few hundred to about US$3,500. At a multiple of 0.1, three weeks of warning (week 4) is already enough and the value is 0.
- Simple policies without confirmation: planning for narrow loses p × the regret of reading too narrowly in expectation, and planning for broad loses (1 − p) × the regret of reading too broadly. At a multiple of 0.1 with the scope showing in week 7, too narrow costs US$8,595 and too broad US$2,125; at p = 0.25 planning for narrow loses 2,149, planning for broad 1,594 and the hedge 1,540. At 0.0 the two sides are close (10,433 against 13,396).
- Against the cost of information processing: in the evaluation the model read a notice at a median of US$0.034 and 73 seconds (at list prices). This only says that reading a notice is cheap. Confirming the scope with a carrier costs planner time, which this project has not measured.

### What can and cannot be said

- Can be said: in this synthetic network, a misread scope changes dispatches only when the substitute lane has almost vanished; reading too broadly costs holding cost, reading too narrowly costs a closing shortfall, and a plan found out too late cannot be carried out; the difference between two optima overstates the loss from reading too broadly; under the other conditions confirming the scope changes no logistics decision.
- Cannot be said: that this is a company measurement; that it holds for other networks or other disruption sizes; that reserved space is untouched by notices in reality (this is a model assumption).
- The three evaluation scores are unchanged: official 52/60, corrected scoring 54/60, A04 retest after the fix 3/3; C03 is pending human review.

### Reproduction

```bash
python scripts/run_scope_misread.py --check
python scripts/run_scope_misread.py --refinement --check
python scripts/run_scope_value.py --workers 6 --check
python -m unittest tests.test_scope_misread
```

### Next acceptance condition

These conclusions hold for this network and these parameters only. Generalising needs one of the following first, with the protocol committed before the results and zero-difference and infeasible results kept:

1. A network in which two origins share space. Taiwan and Malaysia cargo share no lane here, so a misread scope affects only the origin that was wrongly added or left out.
2. A model variant in which a notice also affects reserved space. Reserved space is untouched here, which is the direct reason a misreading has no consequence at most values.
3. Other demand seeds, to see whether the threshold and the size of the regret are stable.
