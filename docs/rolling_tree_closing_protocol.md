本文先列中文，后列英文。 / Chinese first, English second.

# 需求关联与滚动发运的闭环配对检验 / Paired closed-loop test of demand dependence in rolling dispatch

## 中文

### 问题与证据范围

三个 SKU 共用慢线和快线时，保留同期需求关联是否改变发运，并改善完整 12 期的成本、即时满足率或排放？本检验事前登记，使用一个合成环境中新划分的路径。v2 的第一期误差和 M1−M2* 方向一致性门槛未通过。此前有 4 条开发路径、12 个路径与采样种子组合、10 个完整的 M1−M2* 配对。首期动作对抽样的敏感性已另行测量。本轮以策略的闭环表现收尾，原确认集保持封存。[v1 方法](rolling_tree_protocol.md) · [v2 协议](rolling_tree_protocol_v2.md) · [开发结果](rolling_tree_pilot_v2.md) · [稳定性](rolling_tree_stability.md) · [三树比较](rolling_tree_consensus.md)

### 共同设置与路径

使用[环境](../rolling_inventory/environment.py)、[环境配置](../rolling_inventory/config.json)、[v2 规划器](../rolling_tree/experiment_v2.py)、[情景生成器](../rolling_tree/scenarios.py)及[冻结设置](../rolling_tree/config_v2.json)。先验强度为 192，拟合种子为 71001、71011、71023、71039，方差为 0.07659418132480351。前两层分别有 9 和 3 个分支，每个末端有 1 条延续路径，完整窗口有 27 叶。窗口最多 6 期，路线容量按质量为 8、4，提前期为 2、1。剩余碳预算按窗口占剩余期数的比例分配，每条叶路径分别受限。[选参](../benchmark_results/rolling_tree_v2_tuning/selection.json) · [拟合](../benchmark_results/rolling_tree_v2_tuning/fit.json)

每条路径按 M1、M2、M2*、B1、B0、LB 顺序执行。前五项每期根据自身已实现的历史重新决策。M1 保留共同冲击配对。M2 对同一棵树按种子 917351 逐层置换 SKU 子树，保持各 SKU 的边际路径多重集合，直接执行自身最优首期动作。M2* 先解 M2，再在其目标不超过最优值加既有容差的最优面内按 M1 选解。仅第二次求解超时时退回本期自身最优动作，每次记录。容差为 1e−6 × max(1, |最优值|) + 1e−7。B1 使用原 EWMA、Poisson 开环 7 情景和种子 901337。B0 使用原 base-stock，z=1。LB 全期预知，仅作下界。此轮排除 B3、B4。

调用 `generate(base, 'closing', seeds)`。下表是两种语言共用的路径种子，按从左到右、从上到下排序。每个种子对应四类过程，序号依次为 stable=0、volatile=1、upshift=2、downshift=3。以种子下标 i（从 0 起）和过程序号 j 定义 k=4i+j。按 k 递增执行；每条路径的 M1、M2、M2* 共用采样种子 925101+k。每类 40 条，共 160 条，每条只用一个采样种子。配对重抽种子 979301。

| 路径种子 / Path seeds |||||
|---:|---:|---:|---:|---:|
|75011|75023|75037|75041|75053|
|75067|75079|75083|75097|75109|
|75113|75127|75139|75151|75163|
|75173|75187|75193|75209|75217|
|75223|75239|75247|75253|75269|
|75277|75289|75307|75323|75337|
|75347|75353|75367|75377|75389|
|75391|75401|75407|75431|75437|

### 配对统计与判定

主要比较为每条路径 D = M1 总成本 − M2 总成本，沿用 `metrics` 的运费、碳价、持有、逐期积压及末期积压之和。只使用两条轨迹均完整的路径，逐条列出缺失项。报告路径差均值、均值除以同组对照均值的比例，及均值的两个双侧 95% 区间。主区间为样本标准差、n−1 自由度的配对 t 区间。核对区间为按路径有放回等概率抽取 n 条，重复 10,000 次所得均值的 2.5、97.5 百分位数（线性插值）。每组内按 k 排序，用 NumPy default_rng(979301) 重置，三个指标共用索引。以同法报告即时满足率差和排放差，满足率另用百分点表示。零分母的相对量留空。

令 m=0.02 × 配对样本的 M2 平均成本。按上述成本 t 区间 [L,U] 判定。U < −m，且满足率均值差 ≥ −0.005、排放均值差 ≤ 0.02 × M2 平均排放时，为“有实用价值”。L > −m 且 U < m 时为“没有实用价值（等效）”。L > m 时为“有害”。其他情况为“不确定”，包括碰到等效边界。另列区间是否包含零。次要比较 M1−M2*、M1−B1、M2−B1、B1−B0 和五个策略各自减 LB，按各自完整配对重复上述统计。对全部比较另按四类过程分组，只作描述，不做多重显著性判定。

### 首次分歧与计算代价

对完整 M1/M2 配对，找任一 SKU×路线的整数动作首次不同的期次（t=0 对应第 1 期）。记录两侧动作、M1 减 M2 的件数矩阵、各路线发运质量/容量，以及全路径 D。记录首期发运排放占当前窗口碳配额的比例，并用所选最优窗口计划中各叶的实际碳耗识别规划约束：只要任一叶碳耗达到窗口配额（绝对容差 1e−7），该策略的窗口碳约束即取紧；这只表示资源用满。分策略报告慢线满载和碳约束取紧的比例，分母为有分歧的完整配对。汇总首次期次和涉及各 SKU、路线的路径数，有、无分歧分别统计 D；无分歧须有 D=0。记录每种在线策略的所有决策尝试（含失败、强制零和退回）的墙钟均值及 p95，LB 单列每路径一次离线求解。另报总求解数、非最优、超时、轨迹失败及退回次数。计时在共享机器上测得。

### 预算、证据与终止

协议提交后只用开发种子 72019 的四条既有路径试算，规划采样沿用 v2 的首个种子 924601，跑全部六项，只输出逐路径墙钟。估计为 160 × 四条中最慢的整条路径秒数 + 60 秒；超过 7,200 秒即结束，不开正式运行。正式单进程顺序执行，上限 7,200 秒，HiGHS 每次 30 秒、相对 gap 为 0，预留完整求解时限才启动求解。每条轨迹遇到非最优或超时即记录中断，不重试，唯一例外是 M2* 的平局超时退回。M1 或 M2 任一策略累计超过 8 条不完整轨迹即终止。墙钟、复算不符、种子冲突、需要变更冻结材料或安装依赖同样终止。保存已得记录和未完成范围。整轮目标四小时以内。

完整证据包括配置、任务摘要、逐次求解、逐期动作与台账、结果、运行环境、汇总和 SHA256 清单。用 `python -m rolling_tree closing --output <空目录> --max-wall-seconds 7200` 从计时门槛开始执行，用 `python -m rolling_tree verify5` 无求解重建任务和情景、重放动作并核对区间与全部汇总。若试算未过，只报告计时、公式和缩小方案，正式效应无估计。

## English

### Question and scope

When three SKUs share two routes, does preserving contemporaneous dependence change shipments and improve 12-period realized cost, immediate fill or emissions? This preregistered closing test uses fresh paths in one synthetic environment. The v2 first-period error and M1−M2* direction gates failed. Development had four paths, 12 path–sampler combinations and ten complete M1−M2* pairs. Earlier work measured first-action sensitivity. The original confirmation split stays sealed. [v1 methods](rolling_tree_protocol.md) · [v2 protocol](rolling_tree_protocol_v2.md) · [pilot](rolling_tree_pilot_v2.md) · [stability](rolling_tree_stability.md) · [three-tree comparison](rolling_tree_consensus.md)

### Policies and paths

Use the [environment](../rolling_inventory/environment.py), [base configuration](../rolling_inventory/config.json), [v2 planner](../rolling_tree/experiment_v2.py), [sampler](../rolling_tree/scenarios.py) and [frozen settings](../rolling_tree/config_v2.json). Prior strength is 192. Fitting seeds 71001, 71011, 71023 and 71039 give variance 0.07659418132480351. Branching (9,3) with one continuation gives 27 leaves at full horizon. The window covers up to six periods. Slow/fast capacities are 8/4 mass units and leads are 2/1 periods. Each leaf has a carbon allowance equal to remaining carbon times the fraction of remaining periods covered by the window. [Selection](../benchmark_results/rolling_tree_v2_tuning/selection.json) · [Fit](../benchmark_results/rolling_tree_v2_tuning/fit.json)

Execute M1, M2, M2*, B1, B0 and LB in this order on each path. The first five policies replan from their own realized histories. M1 preserves common-shock pairing. M2 permutes SKU subtrees on that same tree with seed 917351, preserving each SKU's marginal path multiset, and dispatches its own optimal first action. M2* solves M2, then minimizes the M1 objective within the M2 optimum plus tolerance, 1e−6 × max(1, |optimum|) + 1e−7. Only a timeout of this second solve triggers use of that period's own optimal action and a counted fallback. B1 uses the original EWMA, seven open-loop Poisson scenarios and seed 901337. B0 is the original base-stock rule with z=1. LB uses full foresight solely as an offline bound. B3 and B4 are excluded.

Use `generate(base, 'closing', seeds)` with the shared seed table above in row-major order. Index profiles stable=0, volatile=1, upshift=2, downshift=3. For zero-based seed position i and profile j, execute in increasing k=4i+j and share sampler seed 925101+k across M1, M2 and M2*. There are 40 paths per profile, 160 overall and one sampler per path. The bootstrap seed is 979301.

### Paired statistics and decision

The primary difference D is M1 minus M2 total cost on a path, using freight, carbon price, holding, periodic backlog and terminal backlog in `metrics`. Use complete pairs and list all omissions individually. Report the mean difference, its ratio to the paired comparator mean and two two-sided 95% intervals for the mean. The primary paired t interval uses the sample standard deviation and n−1 degrees of freedom. The percentile check draws n paths uniformly with replacement 10,000 times and uses linearly interpolated 2.5th and 97.5th percentiles of the means. Within each group, order paths by k, reset NumPy default_rng(979301) and share indices across the three metrics. Apply the same statistics to immediate fill and emissions. Also express fill differences in percentage points. Leave relative results undefined for a zero denominator.

Let m=0.02 times the paired mean M2 cost and [L,U] be the primary cost t interval. A practical benefit requires U < −m, mean fill difference ≥ −0.005 and mean emissions difference ≤ 0.02 times mean M2 emissions. Equivalence requires L > −m and U < m. Harm requires L > m. All remaining cases, including contact with an equivalence boundary, are uncertain. Separately report inclusion of zero. Repeat descriptive statistics on each comparison's own complete pairs for M1−M2*, M1−B1, M2−B1, B1−B0 and each of the five policies minus LB. Report every contrast separately by profile. Only the overall primary contrast receives a decision.

### First divergence and computation

For each complete M1/M2 pair identify the first integer action difference by SKU and route (t=0 is period 1). Save both actions, the M1 minus M2 unit matrix, shipped mass/capacity on each route and final path D. Report first-dispatch emissions divided by the current window allowance. Identify binding planned carbon when at least one leaf of the selected optimal window plan attains its allowance within absolute tolerance 1e−7. This measures resource use. For each policy report the shares with full slow route and binding carbon among divergent complete pairs. Summarize first periods, counts by affected SKU and route, and D separately for divergent and identical paths. Identical paths must have D=0. Report mean and p95 wall time across all online decision attempts including failures, forced zeros and fallbacks. Separately time LB once per path. Count solves, nonoptimal returns, timeouts, trajectory failures and fallbacks. Times are measured on a shared machine.

### Budget, evidence and stopping

After protocol commit, time all six methods on the four existing development paths from seed 72019 with the first v2 sampler, 924601. Retain only per-path wall times. Estimate = 160 times the maximum full-path seconds plus 60 seconds. End at timing if the estimate exceeds 7,200 seconds. Formal execution is sequential in one process with a 7,200-second cap, 30 seconds per HiGHS solve and zero relative gap. Reserve the full solve limit before starting another solve. Nonoptimal results and timeouts end the trajectory immediately without retry, except for the M2* tie-timeout fallback. End if either M1 or M2 exceeds eight incomplete trajectories. Also end on budget exhaustion, a replay mismatch, seed reuse, or a need to change frozen materials or install dependencies. Preserve available evidence and the outstanding scope. The total work target is four hours.

The archive contains configuration, task digests, solve records, period actions and ledgers, outcomes, runtime, summary and a SHA256 manifest. Run `python -m rolling_tree closing --output <empty-directory> --max-wall-seconds 7200` starting with the timing gate. Run `python -m rolling_tree verify5` to regenerate tasks and trees, replay recorded actions, and check intervals and all summaries without optimization. If timing fails, report timings, formula and a smaller design for consideration. The formal effects remain unestimated.
