# 需求分布与决策协议 / Demand distribution and decision protocol

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

### 问题与结构边界

固定原EWMA均值、物理环境和MPC，仅从过去误差估计额外需求波动，能否降低新路径上的实际成本？唯一主要比较是`residual_nb − poisson`的每路径总成本。旧预测开发路径不再使用。

当前目标为`c(q) + Σ_i (1/S) Σ_s L_i(q_i,D_si)`。共享容量和碳约束与情景无关，全部情景共享整段发运计划。每个SKU完整多期路径的独立置换保留任意可行计划的目标和最优值。最优解不唯一时动作可能不同，不能解释为相关性收益。本轮不添加联合服务约束或情景追索。

### 划分和估计

[配置](../rolling_distribution/config.json)指定原四类合成过程各4个拟合、4个选参、16个确认种子，即16/16/64条独立路径，每条12期、3SKU。烟雾测试使用另一命名空间和缩小环境；与既有滚动种子隔离。协议、配置和实现先提交，再生成正式数据；先保存拟合及选择，再生成确认路径。策略不接收未来需求、过程或路径标签。公开基础均值和季节规律仍是仿真假设。

均值固定EWMA α=0.35。拟合库逐期先预测后读取需求。每SKU额外离散系数为`clip(Σ[(y−μ)^2−y]/Σμ²,0,2)`。负二项均值μ、方差`μ+κμ²`；κ≤1e-8时用Poisson。这是基准矩估计，不声称无偏或最优。在线将拟合库平均分子/分母视为τ条伪观测，加上当前路径过去的一步残差。不得汇入其他确认路径。

τ候选12/48/192，仅按16条选参路径的一步边际负二项NLL选择；同分取候选列表首项。保存所有候选分数，不按确认成本选参。

### 方法和共同冲击审计

部署方法为原独立Poisson和残差负二项独立情景MPC；均用7情景、6期窗口、均匀碳分配、零期末抵扣、3个相同采样种子。另保留base-stock和预知需求下界，各路径一次。共512条策略轨迹、6,144期，仍只有64条独立确认需求路径。

联合诊断按总需求排列每SKU整段情景路径，再按拟合/已观察标准化残差的跨SKU秩重新配对。这是经验copula启发的聚合路径秩模型，不是完整时间依赖模型。每SKU完整路径多重集合必须精确保留；仅保留逐期边际却改变单SKU时间依赖，不算有效对照。

在第一个采样种子的NB策略逐期状态上，额外求解重排情景，比较最优值，并交叉评分两个计划在原/重排情景的目标。保存最大偏差、不同动作次数及原始情景。诊断耗时不计入部署延迟；不把多最优解差异作为第三种策略收益。

### 评分与判定

精确Poisson/NB NLL衡量一步边际。128成员预测集合计算一步边际CRPS、三SKU energy score、p=0.5 variogram score、80%区间覆盖/宽度，另计算规划窗口总量的energy/variogram。经验集合公式含对角项，不称为底层分布评分的无偏估计。联合重排和独立NB的边际评分应相同。保存全部预测集合；不调用LLM API。

主要指标为实际总成本，另有当期新需求满足率、积压单位期、期末库存/积压、排放及求解次数。路径内平均3个采样种子，再按4类过程分层路径bootstrap 4,000次，给主差值95%区间、各采样种子/过程差值。一次主要比较，不按结果挑选方法。确认结论限于该合成生成器均衡混合及固定MPC。

质量教师筛选预先要求：成本平均降幅≥2%、主差值区间上界<0、各采样种子成本均改善、满足率下降≤0.005、排放增幅≤2%。这是研究筛选而非业务SLA；通过也不证明BC/PPO有收益。计算替代需要真实p95时限与允许质量损失，当前均为null。本地逐步计时不等于部署基准。PPO还需要同信息强教师之后可测的顺序决策损失；预知未来下界差距不是学习可回收收益。本轮不训练滚动BC/PPO。

### 依据与复现

- Gneiting与Raftery，*Strictly Proper Scoring Rules, Prediction, and Estimation*，[作者出版记录](https://sites.stat.washington.edu/raftery/Research/publications.html)：分布评分与点误差的区别。
- Schefzik等，*Uncertainty Quantification in Complex Simulation Models Using Ensemble Copula Coupling*，[全文§3.4、§4、§5.2](https://arxiv.org/html/1302.7149v2)：分离边际样本与联合秩；不复现其天气实验。
- Scheuerer与Hamill，*Variogram-Based Proper Scoring Rules for Probabilistic Forecasts of Multivariate Quantities*，[DOI](https://doi.org/10.1175/MWR-D-14-00269.1)：依赖诊断；出版社全文受限，公式通过[后续原始研究§2](https://ascmo.copernicus.org/articles/11/23/2025/index.html)核对（对无序SKU对取权重1）。

运行`python -m semiconductor_logistics rolling-distribution run --output artifacts/distribution-new`。`make verify-distribution`重建全部划分、重选参数、重执行策略和相关性审计，从动作独立核对库存、在途、容量、碳和费用。源码身份和输出SHA256归档；即便篡改者重算哈希，动作修改仍应被重执行拒绝。旧研究字节不变。

## English

### Question and structural boundary

With the original EWMA mean, physical system and MPC fixed, can past-error dispersion estimates reduce realized cost on new paths? The sole primary contrast is per-path `residual_nb − poisson` total cost. Previously inspected forecast paths are excluded.

The objective is `c(q) + Σ_i (1/S) Σ_s L_i(q_i,D_si)`. Capacity/carbon constraints are scenario-independent; scenarios share the whole dispatch schedule. Independently permuting complete SKU paths preserves every feasible plan's objective and the optimum. Multiple optima may yield different actions, which is not dependence value. No joint service constraint or scenario recourse is added.

### Splits and estimates

The [config](../rolling_distribution/config.json) specifies 4 fitting, 4 tuning and 16 confirmation seeds per original profile: 16/16/64 distinct paths, each with 12 periods and three SKUs. Smoke has a separate namespace and reduced environment. Seeds are disjoint from previous rolling studies. Commit protocol, config and implementation before formal generation; save fit/selection before generating confirmation. Policies receive no future demand or profile/path labels. Public base means and seasonality remain simulation assumptions.

Keep EWMA alpha=0.35. Build fitting residuals prequentially, predicting before observing each outcome. Per-SKU excess dispersion is `clip(Σ[(y−μ)^2−y]/Σμ²,0,2)`. NB mean is μ, variance `μ+κμ²`; use Poisson for κ≤1e-8. This benchmark moment estimator is not claimed unbiased or optimal. Online estimates combine τ pseudo-observations from the fitting library's mean numerator/denominator with the current path's observed one-step residuals. Never pool other confirmation paths.

Select τ from 12/48/192 by mean one-step marginal NB NLL on 16 tuning paths, breaking ties by candidate order. Retain all scores; do not select by confirmation costs.

### Methods and common-shock audit

Deployable methods are original independent-Poisson and independent residual-NB scenario MPC, both with seven scenarios, horizon six, uniform carbon allocation, zero terminal credit and three shared sampler seeds. Include base-stock and the clairvoyant bound once per path. There are 512 trajectories and 6,144 periods, but only 64 independent confirmation demand paths.

The joint diagnostic sorts complete SKU scenario paths by total demand, then pairs them by cross-SKU ranks from fitted/observed standardized residuals. This empirical-copula-inspired aggregate-rank construction is not a full temporal dependence model. Preserve each SKU's complete path multiset exactly; changing within-SKU temporal dependence while preserving individual-period marginals is not a valid control.

At every first-sampler NB policy state, solve the rearranged ensemble, compare optima and cross-evaluate both schedules on both ensembles. Save discrepancies, action differences and raw scenarios. Exclude diagnostic time from deployment timing. Do not treat tie-breaking differences as a third policy's benefit.

### Scores and decisions

Use exact one-step Poisson/NB marginal NLL. With 128 forecast members, score one-step marginal CRPS, three-SKU energy, p=0.5 variogram, 80% coverage/width, plus energy/variogram of horizon totals. Empirical-ensemble formulas include diagonal terms and are not claimed unbiased for the underlying distribution score. Joint and independent NB must have equal marginal scores. Archive all forecast ensembles; no LLM API is used.

Primary outcome is realized total cost; also report new-demand fill rate, backlog-unit-periods, final stock/backlog, emissions and calls. Average three sampler repeats within each path and use 4,000 profile-stratified path-bootstrap replicates for the primary 95% interval. Retain sampler/profile differences. One primary comparison; no outcome-based method selection. Confirmation is limited to the balanced synthetic generator mixture and fixed MPC.

The quality-teacher screen requires ≥2% lower mean cost, a negative upper confidence endpoint, lower costs at every sampler seed, fill loss≤0.005 and emissions increase≤2%. These are research thresholds, not business SLAs; passing does not prove a BC/PPO benefit. Compute substitution requires a real p95 deadline and tolerable quality loss, both currently null. Local timing is not a deployment benchmark. PPO additionally needs measurable sequential loss beyond same-information strong teachers; a clairvoyant gap is not recoverable learning benefit. No rolling BC/PPO is trained.

### Sources and reproduction

Gneiting and Raftery's [publication record](https://sites.stat.washington.edu/raftery/Research/publications.html) motivates distribution scoring. Schefzik et al.'s [full text §§3.4, 4, 5.2](https://arxiv.org/html/1302.7149v2) motivates marginal/rank separation, not a reproduction of their weather experiment. Scheuerer and Hamill's [variogram paper](https://doi.org/10.1175/MWR-D-14-00269.1) motivates dependence diagnostics; publisher full text was restricted, with formulas checked in [subsequent original research §2](https://ascmo.copernicus.org/articles/11/23/2025/index.html), using weight one per unordered SKU pair.

Run `python -m semiconductor_logistics rolling-distribution run --output artifacts/distribution-new`. `make verify-distribution` regenerates splits, repeats selection and policies/dependence audits, independently auditing stock, pipeline, capacity, carbon and costs from actions. Bind source identities and output SHA256; replay must reject changed actions even after hashes are recomputed. Prior research bytes remain unchanged.
