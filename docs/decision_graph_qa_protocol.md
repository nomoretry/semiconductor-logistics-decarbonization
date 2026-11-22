# 滚动库存决策图问答协议 / Rolling inventory decision graph QA protocol

本文先中文、后英文。The Chinese protocol precedes its English version.

## 中文

### 问题与抽样

哪些库存、需求和共享资源信息会通过问题之间的依赖改变发运决定及其成本、交付与排放？DQ-1 固定数据和判分；上下文干预与物流后果属于 DQ-2。图的组织借鉴 *DriveLM: Driving with Graph Visual Question Answering*（ECCV 2024）的阶段、逻辑依赖与离散行为接口。代码、物流数据和评分均来自本项目。

数据源为 [环境](../rolling_inventory/environment.py)、[参数](../rolling_inventory/config.json)与[参照规划器](../rolling_inventory/planning.py)，起点 `fe8d27c`。用 `generate` 分别生成 train（5101、5209、5119、5147）、dev（5153、5167）、test（5171、5179、5189、5227）。这十个整数在起点的 Python、JSON、Markdown 文件中均无整词冲突。每个种子对应 stable、volatile、upshift、downshift 四种过程。每条真实需求路径分别按 `mpc_scenarios` 和 `base_stock`（z=0）从头运行，两个策略共享需求路径。取 t=0…10，t=10 只有快线可到，t=11 没有可到路线。目标为 40 条路径、80 条策略轨迹、880 张图（352/176/352）；同一路径上的图相互关联。

12 期，三个 SKU 的质量为 [1,2,1] kg，持有、积压、期末附加积压单价为 [0.4,0.6,0.3]、[7,10,5]、[21,30,15]。慢/快线提前期 [2,1]，每期运力 [8,4] kg，每 kg 运价 [1,3]、排放 [1,4]；碳价 0.25，初始排放预算 132。发运后才揭示当期需求。`observe()` 包括当期到达并清偿旧积压后的库存和积压、逐期在途量、历史、剩余预算、公开参数和 EWMA 预测。窗口 H=min(6,12−t)，窗口排放额度 C=剩余额度×H/(12−t)。用观测预测均值、`default_rng(scenario_seed+t).poisson` 和原数组维序生成 7 条需求情景。所有情景共享**整个** H×3×2 整数计划。发运必须在窗口内到达；目标为七条路径的平均运输、碳、持有、积压与实际期末附加积压费用。相对 MIP gap 为 0，每次求解限时 30 秒。

### 状态、题目和边

逐图保存原观测及中英文结构化文本。输入只展示公开状态、当前问题和指定上下文。种子、过程、策略、求解记录和事后值留在输入外。以下模板按 SKU i、路线 r 展开。窗口偏移 u 从 0 开始。每图 31 个节点（12/11/6/1/1）。

| 阶段 | 问题（单位及结构） |
|---|---|
| P1 | SKU i 的可用库存、未清积压、各窗口期在途到达各多少？（分别为两个整数与整数序列；当前到达已计入库存。）全局：剩余排放预算、本窗口额度、现在发运能在整个周期结束前到达的路线编号，各是什么？ |
| P2 | SKU i 的未来 min(3,H) 期需求总量？不再发货时，首次缺口在哪个窗口偏移（空表示无缺口）？窗口最大累计缺口多少件？将最大缺口按质量加总，是否超过慢线可在窗口内到达的总运力？若全部走慢线，排放是否超窗口额度？ |
| P3 | SKU i 本期是否发货？每条路线本期用多少 kg？本期总排放多少？分别回答布尔或非负整数。 |
| B、M | 本期 3×2 发运矩阵是什么？整个窗口的 H×3×2 发运计划是什么？数量均为整数件。 |

P2 用原浮点数预测，不取整。无发运时净库存为初始库存减积压，加截至 u 的在途到达，减截至 u 的需求。首次严格为负的偏移即首次缺口；最大累计缺口为 max(0, −min 净库存)，避免把持续积压重复计数。总缺口 kg 与 8×max(H−2,0) 比较，再把 kg 乘慢线排放因子与 C 比较，均为严格大于。两项压力指示量只描述总量，不保证各期可达。每道 P2 都在独立的 `hindsight` 中以相同公式代入当期及以后真实需求。`hindsight.first_action_with_known_demand` 是相同窗口、相同额度、单一真实路径下的原规划器动作；预知解只作该路径的费用下界参照。

依赖以下列规则生成，同一边只标一层。每个 SKU 的首次缺口与最大缺口分别连自本 SKU 三道 P1（任务层）；三期需求和直接读取状态预测。两道全局压力题分别连自所有 SKU 的最大缺口（物体层）；运力压力另连可达路线，排放压力另连窗口额度（任务层）。窗口额度连自剩余预算（任务层）。各 SKU 发运题连自自身三道 P2（任务层）及两道全局压力题（物体层）。各路线用量与总排放连自两道全局压力题（任务层）。B 连自六道 P3 与两道全局压力题，M 连自 B 和六道 P3（任务层）。窗口额度、运力压力等上下文是决策解释信息，规划器始终可读完整观测。

None 给状态文本和当前问题；Chain 再给直接父问题及答案；Graph 给去重的全部祖先问答。按节点的固定拓扑顺序排列，默认使用记录的答案，函数支持调用方显式传入前序回答。任何模式均不展示当前答案或事后信息。

### 判分、可复算性与预算

- P1/P2 用类型敏感匹配。整数、布尔、空值与数组结构严格一致；浮点误差限 δ(x)=1e−7+1e−6×|x|，x 为参照值。P3/B 将回答作为单独约束重解。不满足资源、整数、形状、到达等可行性条件计违约；可行但成本高于原最优值加 δ 的答案只判错。每个 SKU 约束首期数量和为 0 或至少 1，每条线约束质量和，排放约束加权质量和，B 固定六个整数。金标准取原规划器返回的计划；逐状态与新规划器的无约束最优值比较，超 δ 即中止。
- 生成时逐 SKU 重解相反布尔值。在目标值 ≤ 原最优值+δ 的面上，分别最小化与最大化两条线用量及排放（端点不能判定区间中所有整数都可实现）。排除金标准首期动作重解：对每个格子用二元选择指示其 ≤ 金标准−1 或 ≥ 金标准+1，以该格的上界构造大 M；至少选一个差异。不可行即不存在该差异，求解超时不作不可行解释。
- M 验证整数、非负、共享容量、窗口内到达与累计排放，用 `path_cost` 计算七情景平均费用，超额 ≤ δ 判对。另报与已存计划的逐格绝对差之和。B 的可行性和已保存延续计划的费用可不求解复算；替代动作的最优延续须重解。以全部预期节点作准确率分母，缺答判错；另报各阶段准确率、P3/B/M 作答违约数与分母。固定扰动仅检验判分。
- 试算以各划分首个种子、全部过程及策略，共 24 条轨迹、264 图。每图计时包括参照、约束审计、事后解和行为推进，串行执行。用线性插值 p95×880+60 秒估计正式墙钟，超过 3600 秒即停；正式生成从头单进程顺序运行。逐图保留用时、求解调用与故障。正式阶段故障或超时数/已尝试图数 >1% 即停，不重试。原规划器与新规划器偏差超 δ 在任何阶段均立即停下。整轮上限四小时。因门槛未到正式阶段时，试算不替代发布集。
- 文件按划分 JSONL，SHA256 清单、配置、环境、统计与 JSON Schema 一并发布。`python -m decision_graph_qa build --pilot DIR` 做试算；`build --pilot-evidence DIR --out DATA` 在门槛内正式生成。`verify --data DATA` 不求解，核对清单、结构、观测与轨迹、P1/P2、B/M 和费用；有 jsonschema 时执行完整 Schema，否则执行内置基本结构检查。`recheck --data DATA --sample 0.1` 用固定随机种子 901337 抽取向上取整的 10%，重做最优值与全部并列审计。`score --data DATA --answers FILE` 读 JSONL，每行含图编号及节点编号到回答的映射。DQ-2 的验收是以三种上下文运行规则基线与离线模式，评估成本、交付与排放后果。

## English

### Question and sample

Which dependencies between inventory, demand and shared resources change a dispatch decision and its cost, delivery and emissions? DQ-1 fixes the dataset and scoring rules. DQ-2 tests context interventions and logistics consequences. The stage ordering, logical edges and discrete action interface draw on *DriveLM: Driving with Graph Visual Question Answering* (ECCV 2024). The implementation, logistics data and scoring are project-specific.

Use the [environment](../rolling_inventory/environment.py), [configuration](../rolling_inventory/config.json) and [reference planner](../rolling_inventory/planning.py) at `fe8d27c`. Call `generate` with train seeds 5101, 5209, 5119, 5147; dev 5153, 5167; test 5171, 5179, 5189, 5227. None of the ten integers occurred as a whole word in the starting Python, JSON or Markdown files. Generate stable, volatile, upshift and downshift demand for each seed. Replay each realized path with both `mpc_scenarios` and `base_stock` (z=0). Collect t=0…10. At t=10 only the fast route can arrive; at t=11 neither can. Target 40 demand paths, 80 policy trajectories and 880 dependent graphs (352/176/352).

There are 12 periods. SKU masses are [1,2,1] kg. Holding, backlog and additional terminal backlog prices are [0.4,0.6,0.3], [7,10,5] and [21,30,15]. Slow/fast lead times are [2,1], capacity [8,4] kg per period, freight per kg [1,3] and emissions per kg [1,4]. Carbon price is 0.25 and the initial emissions budget is 132. Demand is revealed after dispatch. The observation includes stock and backlog after current arrivals settle old backlog, pipeline, history, remaining budget, public parameters and EWMA forecast. H=min(6,12−t), C=remaining budget×H/(12−t). Use the observed means and the reference array order with `default_rng(scenario_seed+t).poisson` for seven paths. All paths share the **entire** H×3×2 integer schedule, with arrivals inside the window. Minimize average freight, carbon, holding, backlog and the additional backlog cost at the true terminal period. Set relative MIP gap to 0 and allow 30 seconds per solve.

### State, questions and dependencies

Store the observation and two structured state texts. Model inputs expose only public state, the question and its selected context. Metadata, solver evidence and hindsight stay outside inputs. Expand the templates for each SKU i and route r. Window offsets start at zero. Each graph has 31 nodes (12/11/6/1/1).

| Stage | Question and answer |
|---|---|
| P1 | What are SKU i's available inventory, outstanding backlog and arrivals in each window period? Two integers and a sequence. Current arrivals are already credited. What are the remaining budget, window allowance and route indices that can still arrive before episode end? |
| P2 | What is SKU i's total demand over min(3,H) periods? With no new dispatch, what is the first shortage offset (null if none)? What is the peak cumulative shortage in units? Does total shortage mass exceed slow capacity deliverable within the window? Would slow-only emissions exceed C? |
| P3 | Is SKU i shipped now? How many kg use each route now? What are total current emissions? Answer each with a boolean or nonnegative integer as appropriate. |
| B, M | What is the current 3×2 dispatch? What is the full H×3×2 schedule? Entries are integer units. |

Keep floating forecasts unrounded. At offset u compute initial stock less backlog plus arrivals through u less demand through u. Use the first strictly negative balance and max(0, −minimum balance). The peak avoids repeated counting of outstanding shortages. Sum peaks weighted by mass. Compare strictly against 8×max(H−2,0) for capacity and compare slow-only emissions against C. These aggregate indicators do not guarantee timely deliveries. For every P2 question, store the same statistic from current and future realized demand under `hindsight`. `hindsight.first_action_with_known_demand` uses the reference planner, the same horizon and allowance, and one realized path. Its perfect-information optimum is a cost bound for that path.

Assign one layer per edge. Each SKU's first shortage and peak depend on its three P1 nodes (task). Three-period demand reads the forecast directly. Each global pressure depends on all SKU peaks (object). Capacity pressure also depends on eligible routes, emissions pressure on the window allowance, and the allowance on remaining budget (task). Each SKU dispatch flag depends on its three P2 questions (task) and both global pressures (object). Both route loads and emissions depend on both pressures (task). B has all six P3 nodes and both global pressures as parents; M has B and all six P3 nodes (task). These dependencies organize explanatory context. The planner uses the entire observation.

None supplies state text and the current question. Chain adds direct parent QA. Graph adds all distinct ancestor QA. Order by fixed topological node order. Use recorded answers by default and accept explicit upstream responses. No mode exposes the current answer or hindsight.

### Scoring, replay and budget

- Match P1/P2 with strict integers, booleans, nulls and array structure. For floats use δ(x)=1e−7+1e−6×|x| at the reference value. For each P3/B response independently constrain the reference-equivalent model and re-solve. Shape, integrality, timing or resource infeasibility counts as a violation. A feasible response above optimum+δ is incorrect. Fix the SKU sum to zero or at least one, fix a route's mass, fix emission-weighted mass, or fix all six B cells. Take the canonical plan from the original solver. At every state compare its optimum to the new unrestricted solver and halt immediately on a difference above δ.
- Re-solve each opposite dispatch flag. On the face with objective ≤ optimum+δ minimize and maximize each of the two loads and emissions. Endpoints do not certify every intermediate integer. Exclude the canonical first action and re-solve. A binary selector can enforce ≤ stored−1 or ≥ stored+1 per cell using its bound for big M. Require at least one difference. Proven infeasibility rules out that difference. A timeout does not.
- Validate M for nonnegative integers, capacity, within-window arrivals and total emissions. Average `path_cost` over seven scenarios and accept excess ≤ δ. Report cellwise L1 sum separately. Replay B's feasibility and its stored continuation cost without solving. An alternative action's best continuation requires a solve. Accuracy counts all expected nodes and missing responses are incorrect. Report per-stage accuracy and violation counts and denominators for supplied P3/B/M answers. Fixed perturbations exercise the scorer.
- Pilot the first seed in each split across all profiles and policies (24 trajectories, 264 graphs). Sequential per-graph timing includes reference planning, constraint audits, hindsight and policy advancement. Estimate formal wall time as linearly interpolated p95×880+60 seconds. Stop if above 3,600 seconds. Start the formal build afresh in one sequential process. Retain per-graph timing, solve counts and failures. Halt when formal failed/timed-out graphs divided by attempted graphs exceeds 1%, without retries. Halt on any planner discrepancy above δ. The full run is limited to four hours. Pilot evidence cannot substitute for the release.
- Publish split JSONL, a SHA256 manifest, configuration, environment, counts and JSON Schema. Use `python -m decision_graph_qa build --pilot DIR`, then `build --pilot-evidence DIR --out DATA` only within budget. `verify --data DATA` checks hashes, structure, observations and trajectories, P1/P2, B/M and cost without solving. Use full JSON Schema when jsonschema is present, otherwise the built-in basic structure checks. `recheck --data DATA --sample 0.1` samples a ceiling-rounded 10% with fixed seed 901337 and repeats objective and tie audits. `score --data DATA --answers FILE` reads one JSONL object per graph with its ID and a node-ID-to-answer map. DQ-2 requires running three context modes with rule and offline baselines and measuring cost, delivery and emissions consequences.
