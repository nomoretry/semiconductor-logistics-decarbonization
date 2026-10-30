# 预测与滚动决策协议 / Forecast and rolling-decision protocol

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

### 问题和依据

检验更准确的历史需求预测能否改善同一滚动优化器的实际决策。过去的开发结果已被查看，不再当作未知测试。本实验是合成开发研究，不是企业校准、正式最终检验或学习策略结果。

Gneiting与Raftery的[概率评分研究](https://stat.uw.edu/research/tech-reports/strictly-proper-scoring-rules-prediction-and-estimation)支持使用适当概率评分；Bertsimas与Kallus的[预测到决策研究](https://dspace.mit.edu/entities/publication/a7a1f90f-cb44-498d-ba81-bda4d028f608)说明预测输出需要在决策目标中检验。本研究借鉴这两个评测原则，不复现其算法，也不据此保证改进。

### 预先固定的设计

- 沿用12期、3 SKU、2路线的物理环境，4类合成需求过程。新的12条校准路径使用种子3001/3109/3203；32条开发路径使用4001/4103/4201/4303/4409/4507/4603/4703，各种子与4类过程交叉。与既有路径不重合。烟雾检查采用另外的种子和缩短环境。
- 原EWMA的α=0.35不变；快速EWMA候选α为0.55/0.70/0.85；季节调整移动均值候选窗口为2/4/6。均从公开base_mean开始，已观察需求除以已知4期季节因子，再估计需求水平；短窗仅使用已有数据，无历史时用base_mean。所有预测均截断至至少0.05。
- 每个新预测家族只按12条校准路径的一步、逐SKU Poisson负对数似然均值选参数；完全相同时选择候选表前项。不按开发成本再选择或修改候选。
- 各预测器使用相同的独立Poisson情景假设，7条情景、6期规划、uniform碳分配、期末价值ρ=0。采样种子固定为901337/902347/903359。保留原采样器；相同种子不意味着不同均值下逐次随机数完全配对。不新增过度离散或共同冲击模型。
- 3预测器×3采样种子，以及原base-stock(z=1)、全时域预知需求下界：每条路径11轨迹，共352轨迹、4,224期。原base-stock预测不替换。只在离线下界计算中读取未来需求；任何可部署决策输入都不包含过程标签、任务ID、未来需求或未来冲击。

### 评分、比较和结论规则

逐预测起点保存已知历史生成的预测均值、未来实际需求及误差；未来实际需求仅传入评分器。分别报告1至6期提前量的MAE、RMSE、预测减实际的bias及逐SKU Poisson NLL。NLL是边际分布评分，不是共同冲击下联合分布评分；不把7条抽样本身当作精确预测分布。

成本使用实际运费、碳成本、持有、积压及期末积压成本，无库存信用。还报告即时履约、排放、期末库存/积压、积压单位期、逐步规划时间和求解调用。三种预测均接入同一既有求解器；保存完整动作和可独立核算的物理台账。计时包含预测及优化；离线下界只规划一次，其计时单列。

主要对照是两个校准选定的新预测器分别减原EWMA。先在同一路径内平均三个采样种子，再汇总32条路径，不能称96个独立样本。列出每个采样种子与每类过程的方向；2000次、固定种子的按过程分层路径bootstrap给出描述性95%区间，不用于确认性显著性、多次检验或外推。由于4类过程为人为均衡组成，这些区间仅描述当前混合。

计算预测NLL改善与成本改善的路径数交叉表，保留方向不一致的案例。预先设定的描述性教师稳定条件为：相对原EWMA平均成本下降、差值区间上界<0、三个采样种子均下降，且即时履约下降不超过0.01。该条件只检查两个候选，不能自动批准训练。

滚动BC还需要独立的新路径确认、可部署同信息教师、明确在线时限和允许质量损失；本轮没有给定部署时限，因此无论结果如何均不启动BC/PPO。预知需求下界不是教师，差距不能解释为可被RL回收的收益。保留未达条件和负结果。

### 证据与复算

先提交本协议和配置，再执行校准及开发。保存配置、独立划分、全部候选校准分数、选参结果、逐预测评分、轨迹、计时、结果及源码/文件SHA256。`rolling-forecast verify`重新生成数据、重新选参、重新求解所有策略，逐项比较动作/台账/结果并重新汇总计时；重测耗时只验证有限非负，不要求与原计时相等。旧冻结包和协议保持原字节。

## English

### Question and sources

Test whether more accurate history-only forecasts improve realized decisions under the same rolling optimizer. Previously inspected development paths are not unseen tests. This is synthetic development research, not company calibration, a final test, or a learned-policy result.

[Gneiting and Raftery](https://stat.uw.edu/research/tech-reports/strictly-proper-scoring-rules-prediction-and-estimation) motivate proper probabilistic scoring; [Bertsimas and Kallus](https://dspace.mit.edu/entities/publication/a7a1f90f-cb44-498d-ba81-bda4d028f608) motivate assessing predictions through decisions. We adopt these evaluation principles without reproducing their algorithms or assuming improvement.

### Fixed design

- Retain the 12-period, 3-SKU, 2-route physical environment and four synthetic demand profiles. Use 12 new calibration paths (seeds 3001/3109/3203) and 32 development paths (4001/4103/4201/4303/4409/4507/4603/4703), crossed with all profiles. They do not overlap prior paths. Smoke checks use separate seeds and a shorter environment.
- Keep original EWMA alpha=0.35. Fast EWMA candidates are 0.55/0.70/0.85; seasonally adjusted moving-average windows are 2/4/6. Start from public base_mean; divide observed demand by the known four-period seasonal factor before level estimation. The window uses available history only and base_mean when empty. Floor predicted means at 0.05.
- Select each new family's parameter using mean one-step per-SKU Poisson negative log likelihood on calibration paths only; exact ties select the first candidate. No development-cost selection or candidate revision.
- Use independent Poisson scenarios for every predictor: seven scenarios, six-period horizon, uniform carbon allocation, zero terminal credit. Fix sampling seeds 901337/902347/903359 and retain the original sampler. Equal seeds do not imply identical random draws across different means. No overdispersion/common-shock extension is added.
- Evaluate three predictors by three sampling seeds, original base-stock(z=1), and the full-horizon clairvoyant bound: 11 trajectories/path, 352 trajectories and 4,224 periods. Do not replace the base-stock forecast. Only the explicit offline bound may read future demand. Deployable policy inputs exclude profile labels, task IDs, future demand and shocks.

### Scores, comparisons and decision rules

Save history-derived forecast means and later observed demands/errors at each origin; future demand goes only to the scorer. Report MAE, RMSE, forecast-minus-actual bias and per-SKU Poisson NLL by lead 1–6. NLL scores marginal distributions, not the joint distribution under common shocks. Seven sampled paths are not treated as the exact predictive distribution.

Use realized freight, carbon, holding, backlog and terminal-backlog cost without inventory credit. Report immediate fill, emissions, final inventory/backlog, backlog unit-periods, per-step planning time and solver calls. Every predictor uses the same existing solver. Preserve actions and independently auditable physical ledgers. Timing includes forecasting and planning; the offline bound is planned once and timed separately.

Primary contrasts subtract original EWMA from each calibration-selected alternative. Average three sampling seeds within each path before aggregating 32 paths, never treating them as 96 independent samples. Report every sampler and demand profile. A fixed-seed, 2,000-replicate profile-stratified path bootstrap provides descriptive 95% intervals, not confirmatory significance, multiplicity adjustment or extrapolation. Intervals describe only this artificially balanced mixture.

Cross-tabulate paths by forecast-NLL and decision-cost improvement, retaining disagreement cases. A descriptive teacher stability condition requires lower mean cost than original EWMA, a cost-difference interval upper bound below zero, improvement for all three sampling seeds, and an immediate-fill decline no worse than 0.01. This screens only two candidates and does not authorize training by itself.

Rolling BC additionally requires confirmation on new paths, a deployable same-information teacher, a specified online deadline and acceptable quality loss. No deployment deadline is supplied; therefore this study starts no BC/PPO regardless of its result. The clairvoyant bound is not a teacher and its gap is not recoverable RL benefit. Preserve failures and negative results.

### Evidence and replay

Commit protocol/config before calibration and development. Save configuration, splits, all candidate calibration scores, selection, forecast scores, trajectories, timing, summaries, and source/artifact SHA256. `rolling-forecast verify` regenerates data, repeats selection, resolves all policies, compares actions/ledgers/results and recomputes timing summaries. Fresh timings must be finite and nonnegative but need not equal archived measurements. Keep all earlier frozen packages and protocols byte-identical.
