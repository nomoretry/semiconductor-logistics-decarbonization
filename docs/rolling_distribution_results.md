# 需求分布与滚动决策结果 / Demand distribution and rolling-decision results

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

**公开归档待批准：** 本地实验和复算已完成，35份新证据尚未完整公开，PR保持草稿。清单、审批原因和操作见[归档状态](rolling_distribution_publication.md)。

### 结论

残差负二项模型略微改善一步边际NLL，但没有降低总体滚动成本。相对原独立Poisson，平均成本增加2.06%，配对差值区间跨零；未通过预先固定的质量教师筛选。继续保留原EWMA＋Poisson情景MPC作为比较基线，不训练滚动BC/PPO。

另一个结果是模型结构边界：当前MPC对跨SKU情景配对不敏感。768次审计保留每SKU完整需求路径，仅重排跨SKU配对，最大最优目标偏差为1.14×10⁻¹³。13次完整计划、其中5次首期动作不同，属于多最优解选择，不能解释为相关性收益。

### 设计与证据

[协议、配置和实现](https://github.com/nomoretry/semiconductor-logistics-decarbonization/commit/e71d68d7a822508e2b574c61d97b9b2d356a6d9c)先于正式数据生成提交。16条拟合、16条选参、64条独立确认路径来自原四类合成过程；后64条此前未查看。拟合与选参结果先保存，再生成确认路径。均值EWMA α=0.35、7情景、6期窗口、碳分配和期末价值保持不变。选参按一步边际NLL选τ=12，候选为12/48/192，不根据确认成本重选。

64路径×两部署方法×3采样种子，加每路径base-stock和预知需求下界，共512轨迹、6,144期。采样重复不是新需求路径。另有768次联合重排求解审计，不计入512条部署轨迹或部署时延。原始35文件证据包（[清单](../data_sources/rolling_distribution_artifact_audit.json)，待公开）包含拟合残差、所有候选分数、预测集合、动作轨迹、重排审计、计时、汇总及SHA256清单。

### 决策结果

成本是合成配置的单位，非公司货币收益。满足率为当期新需求的即时满足率。

| 方法 | 平均总成本 | 满足率 | 平均排放 | 期末库存 |
|---|---:|---:|---:|---:|
| 原Poisson情景MPC | 270.2820 | 89.6693% | 106.7240 | 10.5052 |
| 残差NB情景MPC | 275.8435 | 90.4631% | 107.7344 | 11.2917 |
| base-stock | 313.2336 | 83.3888% | 92.0781 | 9.8438 |
| 预知需求下界 | 118.7883 | 98.3985% | 67.2656 | 0.0000 |

主差值NB−Poisson为+5.5615，95%分层路径bootstrap区间[−0.9259,+12.7341]。点估计更贵，但不能据此断言统计上确定更差。31路径成本改善、33路径变差；3个采样种子差值为+10.8273、−2.2969、+8.1539。各过程差值：stable +3.5188、volatile −7.6083、upshift +24.5083、downshift +1.8271。volatile的子组改善是诊断，不能用于在确认集上选择部署规则。

满足率提高0.7938个百分点，同时排放和期末库存上升。对比没有改变服务目标或优化约束，因此保留这些取舍，不将单独满足率改善称为整体优越。

### 预测与相关性

| 方法 | 一步边际NLL | 一步边际CRPS | 窗口总量energy | 窗口总量variogram |
|---|---:|---:|---:|---:|
| Poisson | 1.588357 | 0.711166 | 4.576435 | 2.477484 |
| 独立NB | 1.582202 | 0.711919 | 4.529341 | 2.498033 |
| NB联合重排诊断 | 1.582202 | 0.711919 | 4.540171 | 2.491267 |

指标越小越好；各指标方向不完全一致。NB改善NLL及窗口总量energy，一步CRPS却略差，不能概括为所有预测指标改善。联合重排精确保留每SKU完整路径，因此边际NLL/CRPS相同；联合评分可以变化，当前规划目标却不变。这个结论来自可分目标结构及数值复核，不是“物流中相关性没有价值”。联合服务风险、随机共享容量或情景相关未来追索可能改变它，但本轮没有实现这些新问题。

128成员经验集合的80%一步覆盖为Poisson89.24%、NB91.32%，窗口总量覆盖为68.06%/72.01%。离散区间、均值偏差与窗口误差都影响覆盖，不将覆盖更高自动当作校准更好。完整指标和逐值样本在本地汇总及`forecasts-*.jsonl.gz`。

### 学习策略判断与复现

质量教师的成本降幅、区间上界和跨采样种子方向三项均未通过；满足率与排放阈值通过。当前没有新的稳定教师。部署时限与允许损失仍未指定，不能把本地计时称为计算瓶颈。本轮既不启动滚动BC，也不启动PPO；预知未来下界不能作为可实现教师。

下一项有意义的建模工作是明确联合风险或非预知未来的追索决策是否属于实际业务目标，并单独固定新协议。不能修改本轮确认集、阈值或损失函数来制造成功；已查看的64路径不再是新测试。

```bash
python -m semiconductor_logistics rolling-distribution run --output artifacts/distribution-new
make verify-distribution
python -m scripts.check_research_progress
```

10项新增测试覆盖原基线兼容、未来隔离、划分约束、概率评分、依赖识别、整段路径不变性、篡改和计时检查；全套341项测试通过。全部划分、选择、512条策略轨迹及768次审计在另一BLAS分派下完整重执行通过；GitHub当前提交另做七项验收，本地成功不替代远端检查。原冻结研究代码、数据、提示词和证据包不变。

## English

**Publication pending approval:** local experiments/replay are complete; the 35-file public archive is incomplete and the PR remains draft. See [publication status](rolling_distribution_publication.md).

### Conclusion

Residual negative-binomial forecasts slightly improve one-step marginal NLL but do not lower overall rolling cost. Mean cost is 2.06% higher than original independent-Poisson MPC, and the paired interval crosses zero. The fixed quality-teacher screen fails. Retain original-EWMA/Poisson MPC as the comparison baseline; no rolling BC/PPO is trained.

A separate result concerns model structure: current MPC is invariant to cross-SKU scenario pairing. Across 768 audits preserving every SKU's complete demand paths, the maximum optimal-objective discrepancy is 1.14×10⁻¹³. Thirteen full schedules, including five first actions, differ because of multiple optima; these differences are not dependence benefits.

### Design and evidence

The [protocol, configuration and implementation](https://github.com/nomoretry/semiconductor-logistics-decarbonization/commit/e71d68d7a822508e2b574c61d97b9b2d356a6d9c) were committed before formal generation. The study uses 16 fitting,16 tuning and 64 previously unseen confirmation paths from the four existing synthetic processes. Fit/selection were saved before confirmation generation. EWMA alpha 0.35, seven scenarios, horizon six, carbon allocation and terminal value remain fixed. Tuning selects strength 12 from 12/48/192 by marginal one-step NLL, not confirmation cost.

Two methods×three sampler seeds×64 paths, plus base-stock and a clairvoyant bound per path, yield 512 trajectories and 6,144 periods. Sampler repeats are not new demand paths. The 768 extra dependence solves are excluded from deployment trajectories/timing. The 35-file evidence bundle ([manifest](../data_sources/rolling_distribution_artifact_audit.json), publication pending) includes residuals, all candidate scores, forecast ensembles, actions, dependence audits, timing, summaries and a SHA 256 manifest.

### Decision results

Costs and emissions use synthetic configuration units, not company savings. Fill rate measures immediate fulfillment of new demand.

| Method | Mean total cost | Fill rate | Mean emissions | Final stock |
|---|---:|---:|---:|---:|
| Original Poisson MPC | 270.2820 | 89.6693% | 106.7240 | 10.5052 |
| Residual NB MPC | 275.8435 | 90.4631% | 107.7344 | 11.2917 |
| Base-stock | 313.2336 | 83.3888% | 92.0781 | 9.8438 |
| Clairvoyant bound | 118.7883 | 98.3985% | 67.2656 | 0.0000 |

NB−Poisson cost is+5.5615, with a 95% stratified path-bootstrap interval[−0.9259,+12.7341]. The higher point estimate does not establish a statistically certain deterioration. Costs improve on 31 paths and worsen on 33. Sampler differences are+10.8273,−2.2969,+8.1539. Profile differences are stable+3.5188, volatile−7.6083, upshift+24.5083 and downshift+1.8271. The volatile subgroup is diagnostic, not permission to select a deployment rule on confirmation data.

Fill rate rises 0.7938 percentage points alongside emissions and final stock. Preserve these tradeoffs; improved service alone does not establish overall superiority under the unchanged objective.

### Forecasts and dependence

| Method | One-step marginal NLL | One-step marginal CRPS | Horizon-total energy | Horizon-total variogram |
|---|---:|---:|---:|---:|
| Poisson | 1.588357 | 0.711166 | 4.576435 | 2.477484 |
| Independent NB | 1.582202 | 0.711919 | 4.529341 | 2.498033 |
| Joint NB diagnostic | 1.582202 | 0.711919 | 4.540171 | 2.491267 |

Lower is better, but metric directions differ. NB improves NLL and total-demand energy while slightly worsening one-step CRPS; not every forecast metric improves. Rearrangement preserves each SKU's complete paths, so marginal NLL/CRPS agree. Joint scores can change while the planning objective cannot. This follows from objective separability and numerical verification, not a claim that dependence never matters in logistics. Joint service risk, random shared capacity or scenario-dependent recourse could change this boundary; they are not implemented here.

The 128-member empirical 80% intervals cover 89.24%/91.32% of one-step Poisson/NB outcomes and 68.06%/72.01% of horizon totals. Discreteness, mean bias and horizon errors affect coverage; higher coverage alone is not better calibration. Full metrics and members are in the local summary and `forecasts-*.jsonl.gz`.

### Learning decision and replay

The teacher screen fails cost reduction, interval and sampler consistency; fill/emission thresholds pass. There is no new stable teacher. No deployment deadline or tolerable quality loss is specified, so local timing does not establish a compute bottleneck. Neither rolling BC nor PPO starts; clairvoyance is not an achievable teacher.

The next substantive modeling question is whether joint risk or nonclairvoyant recourse reflects the intended business objective. It needs a separate protocol. Do not revise this confirmation set, thresholds or loss to manufacture success. These 64 inspected paths cannot be reused as new tests.

Use the commands above for a new run, complete replay and saved-result inventory. Ten new tests cover baseline compatibility, future isolation, split guards, probability scores, dependence detection, whole-path invariance, tampering and timing. All 341 tests pass. Full replay under another BLAS dispatch regenerates all splits, selection,512 trajectories and 768 audits successfully. Seven remote checks on the current commit remain separate; local success does not replace GitHub CI. Prior frozen code, data, prompts and evidence remain unchanged.
