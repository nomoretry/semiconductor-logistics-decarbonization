# 预测与滚动决策结果 / Forecast and rolling-decision results

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

**公开归档尚未完成：** 本地73份文件及完整复算均齐全，73份新证据的公开上传被自动审批拒绝。文件与SHA256见[待上传清单](rolling_forecast_publication.md)；PR保持草稿，不能把本地通过写成远端CI通过。

### 结论与范围

新预测器没有优于原EWMA。快速EWMA成本增加7.19%，季节调整短窗增加8.48%；三个采样种子和四类需求过程的平均成本方向一致。两者均未通过预先固定的描述性教师稳定条件。本轮完成预测与决策对照，继续保留原EWMA情景MPC作为比较基线，不训练滚动BC/PPO。

[协议和配置](rolling_forecast_protocol.md)在[提交a0089c5](https://github.com/nomoretry/semiconductor-logistics-decarbonization/commit/a0089c5dda6541fa3ca62f8a3d77098113a4976b)中先于执行固定。12条新校准路径、32条新开发路径来自4类合成过程，每条12期；3预测器×3采样种子，加base-stock与预知需求下界，共352条轨迹、4,224期。32条路径各自的采样重复不能算96个独立案例；这不是正式最终集或企业数据。

### 预测与选参

[校准结果](../benchmark_results/rolling_forecast_development/selection.json)按一步、逐SKU Poisson NLL选择快速EWMA α=0.55、短窗长度6。原EWMA保持α=0.35。候选分别为0.55/0.70/0.85和2/4/6，开发结果没有反过来调参。校准选择分别落在候选边界，这是后续研究线索，不能据此修改本轮候选或删除失败方法。

| 方法 | 一步MAE | RMSE | Poisson NLL |
|---|---:|---:|---:|
| 原EWMA | 1.0872 | 1.4237 | 1.6406 |
| 快速EWMA | 1.1466 | 1.5092 | 1.7606 |
| 季节短窗 | 1.1289 | 1.4936 | 1.7765 |

以上是32路径×12期×3 SKU的1,152个预测观测值；相关的期和SKU并非独立样本。1至6期提前量、各过程、预测偏差和逐值证据见[完整汇总](../benchmark_results/rolling_forecast_development/summary.json)及`forecasts-00.jsonl`至`forecasts-31.jsonl`。三种方法仍使用相同的独立Poisson分布，NLL只评分SKU边际，不验证共同冲击的联合分布。季节规律与初始base_mean为公开先验，企业中未必已知。

### 实际决策

固定7情景、6期规划、uniform碳分配及零期末库存信用；成本保留实际运费、碳、持有和积压，不能把它理解为美元。排放也是合成模型单位，未校准为企业kgCO₂e。

| 方法 | 成本 | 即时履约率 | 排放 | 期末库存 |
|---|---:|---:|---:|---:|
| 原EWMA | 267.7031 | 89.77% | 110.7292 | 10.8125 |
| 快速EWMA | 286.9531 | 89.41% | 115.7917 | 11.5833 |
| 季节短窗 | 290.3990 | 87.40% | 111.1250 | 10.4271 |
| Base-stock | 354.9938 | 81.13% | 93.3750 | 10.6250 |
| 预知需求下界 | 98.3109 | 99.36% | 68.8438 | 0.0000 |

| 新方法−原EWMA | 成本差 | 描述性95%区间 | 改善/变差/持平路径 |
|---|---:|---|---|
| 快速EWMA | +19.2500 | [7.9659, 33.0017] | 7/25/0 |
| 季节短窗 | +22.6958 | [12.0091, 35.6977] | 6/26/0 |

按路径先平均3个采样种子，再分过程分层bootstrap 2,000次。区间仅描述当前均衡混合的开发路径，不是确认性检验。快速EWMA在采样种子901337/902347/903359下成本差为+18.7719/+22.5687/+16.4094；短窗为+26.6281/+19.2953/+22.1641。逐过程与逐路径差值均保留在汇总中。

原EWMA相比base-stock成本下降约24.59%，即时履约更高，但排放也更高。预知需求下界只用于审计，不是可部署教师；与其差距不能被当作RL潜在收益。

### 预测评分与成本并不总同向

短窗在`volatile-4001`、`volatile-4603`、`downshift-4409`上的一步NLL分别改善0.045666、0.025989、0.019462，成本却分别增加15.1167、3.9500、10.9667。另有6条路径成本降低而NLL没有改善。快速EWMA有7条路径成本降低，但没有路径的一步NLL改善。该现象说明当前预测评分不能直接代替库存决策评估；它不证明某种新的学习算法有效。

### 计算与是否训练

| 规划器 | 平均规划ms | P95规划ms |
|---|---:|---:|
| 原EWMA | 6.173 | 11.301 |
| 快速EWMA | 6.072 | 11.860 |
| 季节短窗 | 5.947 | 11.817 |
| Base-stock | 0.249 | 0.460 |

这是当前CPU上的本地测量，包含预测与规划，不是部署延迟承诺。没有业务在线时限和允许质量损失，本轮也没有得到优于原EWMA的新教师，因此继续延后滚动BC/PPO。下一项可研究更强收缩的历史预测或历史残差估计的分布模型，但应先固定协议，在新的校准和确认路径上检验；不得重复使用这32条路径声称未知测试。

### 复现与证据

```bash
python -m semiconductor_logistics rolling-forecast run --output artifacts/rolling_forecast_new
make verify-forecast
python -m scripts.check_research_progress
```

[73文件证据包](../benchmark_results/rolling_forecast_development)含72份数据/运行文件及manifest，保存全部候选校准分数、预测、动作、物理台账、逐步计时和SHA256。[验证器](../rolling_forecast/experiment.py)再生成数据并重新选参和求解352轨迹，独立核对库存/在途守恒、容量、累计碳、实际成本及下界，再比较预测和结果。计时汇总由归档计时重新计算；不要求另一次计时相等。哈希被重算后的动作篡改仍被重执行拒绝。9项新测试覆盖未来输入隔离、原方法兼容、精确NLL、季节调整、选参隔离和篡改拒绝；331项测试及另一BLAS分派下的完整复算均通过。GitHub当前提交的CI状态另行验收，不用本地结果替代。

旧源码、冻结协议、数据和API响应保持原字节。本轮没有新LLM API请求、人工标签或滚动学习训练。

## English

**Public archive incomplete:** all 73 files and full replay are available locally; automatic approval review blocked all 73 new evidence files. See the [pending files and SHA256](rolling_forecast_publication.md). The PR remains a draft; local validation is not remote CI success.

### Conclusion and scope

Neither new predictor improves on original EWMA. Fast EWMA increases cost by 7.19%; the seasonal window increases it by 8.48%. Mean cost changes have the same adverse direction across all three sampling seeds and all four demand profiles. Both fail the fixed descriptive teacher-stability condition. Keep original-EWMA scenario MPC as the comparison baseline and defer rolling BC/PPO.

The [protocol/config](rolling_forecast_protocol.md) were committed as [a0089c5](https://github.com/nomoretry/semiconductor-logistics-decarbonization/commit/a0089c5dda6541fa3ca62f8a3d77098113a4976b) before execution. The study uses 12 new calibration and 32 new development paths across four synthetic profiles, each lasting 12 periods. Three predictors by three sampling seeds plus base-stock and the clairvoyant bound yield 352 trajectories and 4,224 periods. Sampling repeats do not turn 32 paths into 96 independent cases. This is neither a final test nor company data.

### Forecasts and selection

[Calibration](../benchmark_results/rolling_forecast_development/selection.json) selects fast-EWMA alpha=0.55 and window=6 using one-step per-SKU Poisson NLL. Original EWMA retains alpha=0.35. Candidates were 0.55/0.70/0.85 and 2/4/6; development costs were not used for tuning. Both selections lie at candidate boundaries, which may motivate future research but does not justify revising this experiment or removing failed methods.

| Method | One-step MAE | RMSE | Poisson NLL |
|---|---:|---:|---:|
| Original EWMA | 1.0872 | 1.4237 | 1.6406 |
| Fast EWMA | 1.1466 | 1.5092 | 1.7606 |
| Seasonal window | 1.1289 | 1.4936 | 1.7765 |

These are 1,152 observations from 32 paths ×12 periods ×3 SKUs; periods and SKUs are not independent samples. Lead-1–6 scores, profile breakdowns, bias and individual values are in the [summary](../benchmark_results/rolling_forecast_development/summary.json) and `forecasts-00.jsonl` through `forecasts-31.jsonl`. All methods retain independent Poisson predictions; NLL scores SKU marginals, not joint common shocks. Known seasonality and initial base_mean are public priors that may be unavailable in an enterprise setting.

### Realized decisions

Hold seven scenarios, six-period planning, uniform carbon allocation and zero terminal-stock credit fixed. Cost includes realized freight, carbon, holding and backlog; it is not denominated in dollars. Emissions are synthetic model units, not company-calibrated kgCO₂e.

| Method | Cost | Immediate fill | Emissions | Final stock |
|---|---:|---:|---:|---:|
| Original EWMA | 267.7031 | 89.77% | 110.7292 | 10.8125 |
| Fast EWMA | 286.9531 | 89.41% | 115.7917 | 11.5833 |
| Seasonal window | 290.3990 | 87.40% | 111.1250 | 10.4271 |
| Base-stock | 354.9938 | 81.13% | 93.3750 | 10.6250 |
| Clairvoyant bound | 98.3109 | 99.36% | 68.8438 | 0.0000 |

| Alternative − original EWMA | Cost difference | Descriptive 95% interval | Better / worse / tied paths |
|---|---:|---|---|
| Fast EWMA | +19.2500 | [7.9659, 33.0017] | 7/25/0 |
| Seasonal window | +22.6958 | [12.0091, 35.6977] | 6/26/0 |

Average three sampling seeds within each path, then use 2,000 profile-stratified path bootstrap replicates. The intervals describe this balanced development mixture rather than a confirmatory test. Fast-EWMA cost differences at sampling seeds 901337/902347/903359 are +18.7719/+22.5687/+16.4094; window differences are +26.6281/+19.2953/+22.1641. Every profile and path difference remains in the summary.

Original EWMA reduces cost by about 24.59% versus base-stock and raises immediate fill, with higher emissions. The clairvoyant bound is an audit reference, not a deployable teacher or an estimate of recoverable RL gain.

### Forecast scores and decision cost can disagree

The window improves one-step NLL by 0.045666,0.025989 and0.019462 on `volatile-4001`, `volatile-4603` and `downshift-4409`, yet increases cost by 15.1167,3.9500 and10.9667. Another six paths improve cost without improving NLL. Fast EWMA improves cost on seven paths but one-step NLL on none. Forecast scores cannot substitute for inventory-decision evaluation here; this does not validate a new learning algorithm.

### Computation and training decision

| Planner | Mean planning ms | P95 planning ms |
|---|---:|---:|
| Original EWMA | 6.173 | 11.301 |
| Fast EWMA | 6.072 | 11.860 |
| Seasonal window | 5.947 | 11.817 |
| Base-stock | 0.249 | 0.460 |

These are local CPU measurements including forecasting and planning, not deployment latency guarantees. No business deadline or acceptable quality loss is specified, and no new teacher beats original EWMA; rolling BC/PPO remains deferred. Stronger shrinkage or a history-residual distribution model may be investigated next, with a protocol fixed before new calibration and confirmation paths. These 32 inspected paths cannot be relabeled unseen tests.

### Reproduction and evidence

```bash
python -m semiconductor_logistics rolling-forecast run --output artifacts/rolling_forecast_new
make verify-forecast
python -m scripts.check_research_progress
```

The [73-file bundle](../benchmark_results/rolling_forecast_development) contains 72 data/runtime files plus a manifest: every candidate calibration score, forecast, action, physical ledger, step timing and SHA256. The [verifier](../rolling_forecast/experiment.py) regenerates data, repeats parameter selection, resolves 352 trajectories, independently audits stock/pipeline conservation, capacity, cumulative carbon, realized costs and lower bounds, then compares forecasts and results. Archived timing summaries are recomputed; fresh timing equality is not required. Rehashed action tampering is still rejected by reexecution. Nine new tests cover future-input isolation, baseline compatibility, exact NLL, seasonality, split isolation and tamper rejection. All 331 tests and full replay under another BLAS dispatch passed. Current-commit GitHub CI is checked separately.

Earlier source files, frozen protocols, data and API responses retain their original bytes. There are no new LLM API requests, human labels or rolling-policy training runs.
