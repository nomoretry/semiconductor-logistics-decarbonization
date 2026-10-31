# 研究问题、设计与验收 / Research questions, design and acceptance

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

### 项目要回答什么

**在运输容量、交付和碳约束下，哪些信息值得获取，预测误差如何改变库存与运输决策，信息处理和优化计算的成本是否值得付出？**

研究对象是物流决策。公告抽取、付费查询、概率预测、整数规划和学习策略分别服务于上述问题。项目的难度来自信息不完整、多SKU资源竞争、运输提前期、在途库存、逐期需求和跨期碳预算；项目的完成度由可运行实现、有效对照、独立评测和证据复算判断。

### 三条研究线及实际连接

| 研究问题 | 决策及方法 | 主要比较 | 输出与边界 |
|---|---|---|---|
| 公告能提供哪些可执行事实？ | 有限字段抽取、来源证据、澄清、参数校验、已知订单MILP | 固定LLM与冻结规则；错误更新与正确澄清分别统计 | 合成测试成立；真实参考未人工复核，内部路线映射尚缺 |
| 信息值不值得付费？ | 公开延误先验、付费查询、停止查询、共享容量运输分配；精确DP、受限搜索、BC/PPO | 相同可见信息；区分决策成本与实际计算代价 | 五种子千题没有稳定PPO优势；减少求解次数不等于实测加速 |
| 预测分布何时改变滚动决策？ | 过去需求与在途状态、情景MPC、累计碳约束、非预知历史追索诊断 | 强规则、均值/情景优化、固定均值下的分布变化、平局稳健对照 | 预测指标与决策指标分别报告；尚无有效的滚动学习教师 |

目前三条线分别验证。公告抽取没有在实验中接入查询策略训练或未知需求控制；不能将各部分分数拼成端到端性能。ASML和Marvell提供问题背景，模拟订单、价格和容量不是企业运营数据。

### 本项目已有的工作与贡献范围

- 实现运输、库存、在途、积压、容量和碳的物理台账，把信息处理的效果传递到明确的物流费用与服务指标。
- 构造有查询成本与共享资源约束的物流决策问题，比较规则、搜索、精确规划及小型学习策略，并保存查询和最终运输决策的证据。
- 在另行划分的需求路径上检验均值预测与分布误差，保留预测评分改善但决策不改善的结果。
- 分析当前MPC对完整SKU路径配对的不变性；用有限追索、最优平局和跨模型评估排查表面收益。

这些是本项目已经实现并可复算的建模、实验和分析工作。尚不声称提出了新的通用BC/PPO算法、首次发现了上述数学性质、验证了企业节省，或完成了真实场景泛化。是否具有可发表的新颖性仍需针对具体研究问题做系统文献定位和外部验证。

### 方法的选择依据

运输分配使用整数规划以表达守恒、容量和碳约束；已知小型查询问题用精确DP提供强基线；学习查询策略只检验是否能替代部分在线计算。PPO使用[原论文](https://arxiv.org/abs/1707.06347v2)的策略目标和[GAE](https://arxiv.org/abs/1506.02438v6)优势估计，不作为项目创新声明。预测评估与追索建模的论文依据分别保存在[预测协议](rolling_forecast_protocol.md)、[分布协议](rolling_distribution_protocol.md)和[追索协议](rolling_recourse_protocol.md)。

后续模块必须由一个未解决的物流问题和可检验假设驱动。若强优化基线已解释收益，就保留该结果；不为了拥有某种算法、达到某个训练规模或对应别人的模块而增加训练。

### 验收标准

| 条件 | 具体检查 | 当前状态 |
|---|---|---|
| 问题与信息边界 | 状态、动作、事件顺序、单位和隐藏信息可定位到代码；不把预知未来下界当教师 | 各实验已定义；尚缺整体端到端验证 |
| 决策价值 | 同信息强基线、成本/服务/排放取舍、最优平局审计；不只看预测准确率 | 已完成多轮；滚动学习教师仍未通过 |
| 实验可信度 | 训练/选参/测试隔离，报告独立情境数；按研究问题选择种子和规模 | 查询五种子千题完成；追索36模型仅机制诊断 |
| 计算价值 | 测量实际运行时间、硬件与允许质量损失，不能用调用数直接代替速度 | 已有计时，尚无部署时限或可接受质量损失定义 |
| 可复算交付 | 源码、配置、原始结果、哈希、重执行与CI对应同一版本 | 已实现；本次补齐35份已授权分布证据 |
| 可发布工程 | 完整依赖锁、静态检查、跨平台验收、固定Release及完整双语文档 | 仍有工作待完成，见[进度](progress.md) |

### 下一项研究

在原12期库存时序下建立历史条件情景树，保留共享容量与累计碳约束，先比较精确或受控求解预算下的优化策略。检查共同需求冲击是否改变可执行动作，以及改变是否有成本、服务或排放价值；平局、仅预测评分变化和不可部署的预知需求优势不能替代此证据。开发结果支持明确假设后，再另行固定新确认路径。BC/PPO只有在有效教师或明确计算瓶颈出现后才进入下一阶段。

早期文档定位的修正与来源保留见[来源历史](source_history.md)。当前研究设计、模块和验收均以本页的问题为准。

## English

### Research question

**Under transport-capacity, delivery and carbon constraints, which information is worth acquiring, how do forecast errors change inventory and transport decisions, and when are information processing and optimization computation worth their cost?**

The object of study is logistics decision-making. Notice extraction, paid queries, probabilistic forecasts, integer optimization and learned policies serve this question. Difficulty comes from incomplete information, shared multi-SKU resources, lead times, pipeline inventory, sequential demand and intertemporal carbon budgets. Completion means executable implementations, meaningful controls, independent evaluation and reproducible evidence.

### Research lines and implemented connections

| Question | Decisions and methods | Main comparison | Evidence and limits |
|---|---|---|---|
| Which notice facts support executable updates? | Bounded extraction, supporting evidence, clarification, parameter checks, known-order MILP | Fixed LLM versus frozen rules; incorrect updates separate from correct abstention | Synthetic results available; real references lack human review and internal-route mapping |
| Is information worth purchasing? | Public delay priors, paid queries, stopping and shared-capacity transport; exact DP, bounded search, BC/PPO | Equal visible information; separate decision costs from computation | No stable PPO gain in five-seed final evaluation; fewer solves are not measured speedups |
| When do forecast distributions change rolling decisions? | Past demand, pipeline, scenario MPC, cumulative carbon and nonanticipative recourse diagnostics | Strong rules and optimization; fixed-mean distribution changes; robust treatment of ties | Prediction and decision scores reported separately; no validated rolling-policy teacher |

These lines are evaluated separately. Extraction has not been experimentally connected to query-policy training or unknown-demand control. Component scores cannot be combined into an end-to-end claim. ASML and Marvell motivate the problems; simulated orders, prices and capacities are not company operating records.

### Implemented work and contribution scope

- Physical accounting for shipments, stock, pipeline, backlog, capacity and carbon links information handling to explicit logistics costs and service metrics.
- Paid-query logistics problems with shared resources support comparisons among rules, search, exact planning and small learned policies, with query and transport evidence.
- Separate demand paths test mean forecasts and distribution errors, retaining cases where better prediction scores do not improve decisions.
- Analysis of the current MPC's whole-SKU-path pairing invariance, together with finite recourse, optimal-tie and cross-model audits, examines apparent gains.

These are implemented, replayable modeling, experimental and analytical contributions within this project. They do not establish a new general BC/PPO algorithm, first discovery of the mathematical properties, company savings or real-world generalization. Publication-level novelty still needs systematic literature positioning around a specific question and external validation.

### Why these methods

Integer optimization represents conservation, capacity and carbon constraints. Exact DP supplies strong comparisons on small query problems. Query-policy learning tests substitution for part of online computation. PPO uses the [original policy objective](https://arxiv.org/abs/1707.06347v2) and [GAE](https://arxiv.org/abs/1506.02438v6); these are not claimed as project inventions. Forecasting, distribution and recourse protocols retain their primary literature sources.

Every new module must address an unresolved logistics question with a testable hypothesis. If strong optimization explains a gain, retain that finding. Do not add training merely to include an algorithm, match a training scale or reproduce another repository's module list.

### Acceptance criteria

| Condition | Check | Current status |
|---|---|---|
| Problem and information boundary | Code-defined states, actions, event ordering, units and hidden information; clairvoyance is only a bound | Defined per study; integrated end-to-end validation remains absent |
| Decision value | Equal-information strong baselines, cost/service/emission tradeoffs and optimal-tie audits, beyond forecast accuracy | Multiple studies completed; rolling teacher screen remains unmet |
| Evaluation validity | Training/tuning/test separation and distinct-case counts; seeds and scale justified by the question | Five-seed query final complete; 36 recourse models are mechanism diagnostics |
| Computation value | Actual timings, hardware and allowed quality loss; solve counts alone are insufficient | Timing evidence exists; deployment deadline and acceptable loss remain unspecified |
| Reproducibility | Source, configuration, raw results, hashes, replay and CI for one version | Implemented; this change completes the 35 authorized distribution evidence files |
| Release engineering | Full lockfile, static checks, cross-platform acceptance, fixed Release and complete bilingual documentation | Still unfinished; see [progress](progress.md) |

### Next study

Build history-conditioned scenario trees under the original 12-period timing, shared capacity and cumulative carbon constraints. Start with exact or controlled-budget optimization. Test whether common demand shocks alter feasible actions and whether those changes matter for cost, service or emissions. Ties, forecast-score-only changes and clairvoyant advantages are insufficient. Fix fresh confirmation paths only after development supports a clear hypothesis. Rolling BC/PPO waits for a useful teacher or an explicit computation bottleneck.

See [source history](source_history.md) for the correction to earlier framing and retained provenance. Current design, modules and acceptance follow this project's questions.
