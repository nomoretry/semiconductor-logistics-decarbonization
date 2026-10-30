# 滚动环境敏感性结果 / Rolling sensitivity results

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

按[运行前写定的协议](rolling_sensitivity_protocol.md)，在24条新合成开发需求路径上完成三因素全组合：碳分配uniform/forecast/free、期末库存价值比例ρ=0/0.5/0.9、需求情景1/7/21条，并使用3个独立情景采样种子。另保留均值MPC、固定z=1补货规则和各ρ对应的预知需求下界。总计2,304条轨迹、27,648条逐期记录；采样重复不是新增需求路径，也不是训练种子。本轮不调用API，不训练新策略，不建立正式千题测试集。

**当前结论：先改进预测与强基线，不开始滚动BC/PPO。** 七情景规划相对规则的总体优势在新路径上仍存在，但分过程不一致；21情景相对7情景的收益没有跨采样种子保持。碳分配影响小，期末计价降低净成本主要来自对已有库存的返还，不能据此宣称决策改善。

### 三项主要对照

下表每次只改变一个因素，其余保持uniform、ρ=0、7情景。每格先在24条路径和3个采样种子上求平均。成本为仿真成本单位，排放为未校准的仿真单位，均不代表企业实测金额或吨CO2；即时履约率先服务旧欠单，再计算新需求的即时满足比例。

| Setting | Net cost | Operating cost | Immediate fill | Emissions | Final stock |
|---|---:|---:|---:|---:|---:|
| Reference: uniform, ρ=0, S=7 | 245.2882 | 245.2882 | 90.81% | 107.2083 | 10.4167 |
| forecast allocation | 245.0083 | 245.0083 | 90.84% | 107.1111 | 10.4028 |
| free allocation | 246.2160 | 246.2160 | 90.78% | 107.2917 | 10.4306 |
| ρ=0.5 | 238.0181 | 246.5944 | 90.86% | 108.0833 | 10.5833 |
| ρ=0.9 | 231.6927 | 247.2708 | 90.88% | 108.5278 | 10.6806 |
| S=1 | 392.3069 | 392.3069 | 77.06% | 117.3611 | 5.3889 |
| S=21 | 244.4056 | 244.4056 | 90.48% | 102.9167 | 9.9167 |

**碳预算分配。** forecast相对uniform平均成本−0.2799（−0.11%），2条路径改善、22条持平；free为+0.9278（+0.38%），2条改善、3条变差、19条持平。实际累计硬预算始终相同。交叉实验每个固定ρ/S单元内，三种分配的平均成本极差为0.2917–1.2076；对当前设置影响较小，但不能外推到更紧碳预算或不同需求结构。未测试碳总量敏感性。

**期末库存价值。** ρ是最低运输含碳成本的比例，仅给真实最后一期的正现货库存返还，不给中间窗口、欠单或在途计价。它是敏感性假设，不是采购残值或已验证的无限期价值函数。必须把改变账面口径与改变动作分开：

| ρ | Accounting effect on unchanged ρ=0 actions | Replanning behavior effect at the same ρ | Total net-cost change | Operating-cost change |
|---|---:|---:|---:|---:|
| 0.5 | −8.4809 | +1.2108 | −7.2701 | +1.3062 |
| 0.9 | −15.2656 | +1.6701 | −13.5955 | +1.9826 |

前两项精确相加等于净成本变化。两档价值下，重新规划的平均行为效应均为正，即比保持原动作再按相同ρ计价更贵；同时运营费用、排放和库存增加。不能把净成本下降当作策略学到了更好的补货。这里没有验证更长经营期或滚动窗口末端的近似价值。

**情景数量。** 从1条增加到7条，平均成本下降37.48%，24条路径中23条改善。1条是随机需求情景，不是均值MPC。7增至21条仅降0.8826（0.36%）；17条路径改善、7条变差，但即时履约率下降0.3314个百分点，排放下降4.2917。三个采样种子的配对均值如下，不能将其合并称为72条独立路径：

| Sampling seed | S=1 minus S=7 cost | S=21 minus S=7 cost |
|---|---:|---:|
| 901337 | +154.6646 | −10.3042 |
| 902347 | +125.2083 | +9.0354 |
| 903359 | +161.1833 | −1.3792 |

21条的收益方向未跨采样种子保持。三种情景数仍只使用当前公开均值下的Poisson采样，没有拟合潜在共同冲击或趋势变化；增加情景不能自动修正分布设定错误。

### 基线与过程差异

| Method, uniform / ρ=0 unless bound | Net cost | Immediate fill | Emissions |
|---|---:|---:|---:|
| Base-stock z=1 | 294.7979 | 84.98% | 93.2917 |
| Mean MPC | 357.1896 | 75.80% | 104.7917 |
| Scenario MPC, S=7 | 245.2882 | 90.81% | 107.2083 |
| Perfect-information bound | 101.8125 | 99.05% | 67.4167 |

七情景MPC相对base-stock成本低16.79%，即时履约率高5.8332个百分点，但排放高14.92%；按每路径三采样均值比较，15条更好、9条更差。均值MPC仍未胜过规则。每个ρ均单独重求预知需求下界，净成本均为101.8125且期末库存为零；同价最优动作的履约率可能略有差异。下界提前知道真实需求，差距不能全当作学习策略可以消除的损失。

| Process, 6 paths each | Base-stock | Mean MPC | S=7 | S=21 |
|---|---:|---:|---:|---:|
| downshift | 154.6417 | 158.0750 | 168.2778 | 159.2806 |
| stable | 221.5583 | 280.8917 | 200.6222 | 200.4500 |
| upshift | 564.1500 | 683.2250 | 393.1222 | 413.9361 |
| volatile | 238.8417 | 306.5667 | 219.1306 | 203.9556 |

下降过程仍有过量库存问题；上升过程中21条情景反而比7条更贵。过程标签用于报告，不暴露给策略。完整42个单元及分过程结果保存在[summary.json](../benchmark_results/rolling_sensitivity_development/summary.json)，未事后挑选全组合最低成本作为新的主方法。这里只作描述性开发比较，不声称统计显著或广泛泛化。

### 计算量与学习判断

| Scenarios | Mean / decision (ms) | P95 (ms) | Max integer variables | Max continuous variables |
|---|---:|---:|---:|---:|
| 1 | 2.7430 | 5.0895 | 36 | 36 |
| 7 | 5.9060 | 10.8733 | 36 | 252 |
| 21 | 12.8948 | 26.0285 | 36 | 756 |

每行864次决策，均为每期1次MILP；所有情景共享未来发货变量，不允许按未揭示需求提前分叉。21条的本地平均规划时间约为7条的2.18倍。计时包含规划及其物理核对，受机器、缓存、共享运行负载影响，不是部署时延承诺或独立性能基准；时间保存并校验哈希，但重放不要求再次计时逐值一致。

目前没有给定在线时限，也没有稳定胜过同信息强基线的学习教师。当前小规模MILP计时尚不说明存在迫切的在线计算瓶颈。因此保留7情景作为比较锚点，先在新开发路径比较仅使用历史数据的预测与不确定性模型，再固定可部署教师、时限及质量损失要求。满足这些条件后，BC可研究计算替代；只有BC留下可测的序列决策损失，才有依据继续PPO。不能以预知需求下界作可部署教师。

### 证据与复现

[代码](../rolling_sensitivity)、[配置](../rolling_sensitivity/config.json)及[证据包](../benchmark_results/rolling_sensitivity_development)保存全部任务、96种运行配置、逐期观测/动作/需求/费用、原始结果、配对分解、时间和源码身份。八份gzip分片无损保存全部轨迹；outcomes/timing也以`.jsonl.gz`保存。大文本上传未完成后，仅改变归档格式，[逐字节核对记录](../data_sources/rolling_sensitivity_packaging.json)保留原始摘要；解压内容和全部数值不变。独立旧账本检查物理守恒和运营成本；另核对期末信用额、净成本、分解恒等式及各ρ下界。完整重放重新生成任务并执行全部2,304条轨迹，不只读取汇总表。[公开归档内容检查](../data_sources/rolling_sensitivity_artifact_audit.json)记录合成身份、允许字段、全部轨迹覆盖和文件摘要。

322项测试通过，包括7项新增的未来隔离、前缀情景、硬预算、原求解器兼容、末期计价、微型枚举和重写哈希后的信用额篡改检查。wheel安装及CLI检查通过。Haswell BLAS分派下全部2,304条轨迹重执行通过。旧源码、协议和归档保持原字节；CI新增独立敏感性重放任务，保留既有四项任务。

```bash
python -m semiconductor_logistics rolling-sensitivity run --output artifacts/rolling_sensitivity
python -m semiconductor_logistics rolling-sensitivity verify --output artifacts/rolling_sensitivity
make verify-sensitivity
python -m scripts.audit_rolling_sensitivity_artifacts
```

前两个命令在新空目录重现，第三个核验仓库归档。没有新增人工审核表或API操作。

## English

Following the [prewritten protocol](rolling_sensitivity_protocol.md), this study evaluates a full factorial on 24 new synthetic development demand paths: uniform/forecast/free carbon allocation, final-stock credit fractions ρ=0/0.5/0.9, 1/7/21 demand scenarios and three independent scenario-sampling seeds. Mean MPC, the previously calibrated z=1 base-stock rule and a value-specific perfect-information bound are retained. There are 2,304 trajectories and 27,648 period records. Sampling repeats are neither additional demand paths nor training seeds. No API calls, new policy training or formal thousand-case test are introduced.

**Decision: improve forecasts and strong baselines before rolling BC/PPO.** Seven-scenario MPC retains an aggregate advantage over the rule on new paths, but not in every process. The benefit of 21 over seven scenarios changes sign across sampling seeds. Carbon allocation has a small effect; lower net cost under final-stock credit mostly reflects credit on existing inventory, not better decisions.

### Three primary contrasts

Each contrast changes one factor while holding uniform allocation, ρ=0 and seven scenarios as reference. Cells average the same 24 paths and three sampling seeds. Costs and emissions are uncalibrated simulation units, not measured company finances or tonnes of CO2. Immediate fill serves old backlog before measuring new demand met immediately.

| Setting | Net cost | Operating cost | Immediate fill | Emissions | Final stock |
|---|---:|---:|---:|---:|---:|
| Reference: uniform, ρ=0, S=7 | 245.2882 | 245.2882 | 90.81% | 107.2083 | 10.4167 |
| forecast allocation | 245.0083 | 245.0083 | 90.84% | 107.1111 | 10.4028 |
| free allocation | 246.2160 | 246.2160 | 90.78% | 107.2917 | 10.4306 |
| ρ=0.5 | 238.0181 | 246.5944 | 90.86% | 108.0833 | 10.5833 |
| ρ=0.9 | 231.6927 | 247.2708 | 90.88% | 108.5278 | 10.6806 |
| S=1 | 392.3069 | 392.3069 | 77.06% | 117.3611 | 5.3889 |
| S=21 | 244.4056 | 244.4056 | 90.48% | 102.9167 | 9.9167 |

**Carbon allocation.** Forecast-based allocation changes mean cost by −0.2799 (−0.11%): two paths improve and 22 tie. Free allocation changes it by +0.9278 (+0.38%): two improve, three worsen and 19 tie. The actual cumulative hard cap is identical. Across fixed ρ/S cells, the spread between the three allocation means is 0.2917–1.2076. Effects are small under these settings, without extrapolation to tighter caps or other demand structures. Total carbon-budget sensitivity is not tested.

**Final-stock value.** The fraction of cheapest freight-plus-carbon cost is credited only to positive on-hand stock at the actual episode end, not at intermediate cutoffs or to backlog/pipeline. This is a sensitivity assumption, not procurement salvage or a validated infinite-horizon value function. Separate accounting from action changes:

| ρ | Accounting effect on unchanged ρ=0 actions | Replanning behavior effect at the same ρ | Total net-cost change | Operating-cost change |
|---|---:|---:|---:|---:|
| 0.5 | −8.4809 | +1.2108 | −7.2701 | +1.3062 |
| 0.9 | −15.2656 | +1.6701 | −13.5955 | +1.9826 |

The first two terms exactly sum to the net-cost change. Replanning has a positive average cost effect under both values: it costs more than retaining the original actions and rescoring them at the same ρ. Operating cost, emissions and inventory also increase. Lower net cost is not evidence of improved replenishment decisions. This does not validate longer operation or an approximate value at intermediate planning cutoffs.

**Scenario count.** Increasing one scenario to seven lowers average cost by 37.48%, improving 23 of 24 paths. One random scenario is distinct from mean MPC. Increasing seven to 21 lowers cost by only 0.8826 (0.36%): 17 paths improve and seven worsen, while immediate fill falls 0.3314 percentage points and emissions fall 4.2917. Paired means by sampling seed are:

| Sampling seed | S=1 minus S=7 cost | S=21 minus S=7 cost |
|---|---:|---:|
| 901337 | +154.6646 | −10.3042 |
| 902347 | +125.2083 | +9.0354 |
| 903359 | +161.1833 | −1.3792 |

These are not 72 independent paths. The direction of the 21-scenario benefit does not persist across seeds. All counts sample Poisson demand around public means without fitting latent common shocks or trend shifts; more scenarios cannot automatically correct distribution misspecification.

### Baselines and process differences

| Method, uniform / ρ=0 unless bound | Net cost | Immediate fill | Emissions |
|---|---:|---:|---:|
| Base-stock z=1 | 294.7979 | 84.98% | 93.2917 |
| Mean MPC | 357.1896 | 75.80% | 104.7917 |
| Scenario MPC, S=7 | 245.2882 | 90.81% | 107.2083 |
| Perfect-information bound | 101.8125 | 99.05% | 67.4167 |

Seven-scenario MPC costs 16.79% less than base-stock and improves immediate fill by 5.8332 points, but emits 14.92% more. Averaging the three sampling repeats within each path, 15 paths improve and nine worsen. Mean MPC still fails to beat the rule. The bound is separately reoptimized for each ρ: all give net cost 101.8125 and zero final stock; tied optimal actions can have slightly different fill rates. The bound knows future realized demand, so its gap is not entirely recoverable by a learned policy.

| Process, 6 paths each | Base-stock | Mean MPC | S=7 | S=21 |
|---|---:|---:|---:|---:|
| downshift | 154.6417 | 158.0750 | 168.2778 | 159.2806 |
| stable | 221.5583 | 280.8917 | 200.6222 | 200.4500 |
| upshift | 564.1500 | 683.2250 | 393.1222 | 413.9361 |
| volatile | 238.8417 | 306.5667 | 219.1306 | 203.9556 |

Downward shifts retain an overstocking problem; 21 scenarios cost more than seven under upward shifts. Process labels are used for reporting, not exposed to policies. All 42 cells and process breakdowns are retained in [summary.json](../benchmark_results/rolling_sensitivity_development/summary.json). The post-hoc minimum does not replace the primary method. These are descriptive development comparisons, without significance or broad-generalization claims.

### Computation and learning decision

| Scenarios | Mean / decision (ms) | P95 (ms) | Max integer variables | Max continuous variables |
|---|---:|---:|---:|---:|
| 1 | 2.7430 | 5.0895 | 36 | 36 |
| 7 | 5.9060 | 10.8733 | 36 | 252 |
| 21 | 12.8948 | 26.0285 | 36 | 756 |

Each row contains 864 decisions, one MILP per period. Future dispatch is shared across scenarios, with no branches conditioned on unrevealed demand. The local mean for 21 scenarios is about 2.18 times that for seven. Timing includes planning and its physical checks and is affected by hardware, caches and shared workload; it is not a deployment guarantee or isolated performance benchmark. Timing files are hashed, but replay does not require identical newly measured durations.

No online latency target or validated teacher advantage over same-information strong baselines has been established. The current small MILPs do not demonstrate an urgent online computation bottleneck. Keep seven scenarios as the comparison anchor; first compare history-only forecasting and uncertainty models on new development paths, then fix a deployable teacher, time limit and acceptable quality loss. BC could subsequently test computation substitution. PPO requires a measurable sequential decision loss remaining after BC. The clairvoyant bound is not a deployable teacher.

### Evidence and reproduction

[Code](../rolling_sensitivity), [settings](../rolling_sensitivity/config.json) and the [bundle](../benchmark_results/rolling_sensitivity_development) retain all tasks, 96 run configurations, period observations/actions/demand/costs, outcomes, paired decompositions, timings and source identity. Eight lossless gzip shards retain all traces; outcomes/timings also use `.jsonl.gz`. After a large-text upload did not complete, only packaging changed. The [byte-comparison record](../data_sources/rolling_sensitivity_packaging.json) retains original digests; decompressed contents and all numerical values are unchanged. The original independent ledger checks physical conservation and operating cost; additional checks cover final credit, net cost, decomposition and value-specific bounds. Full replay regenerates tasks and reexecutes all 2,304 trajectories rather than just reading summary metrics. The [public-artifact inspection](../data_sources/rolling_sensitivity_artifact_audit.json) records synthetic provenance, allowed fields, full coverage and file digests.

All 322 tests pass, including seven new tests for future isolation, nested scenarios, hard budgets, original-solver compatibility, final-period credit, tiny exhaustive optimization and rehashed credit tampering. Wheel installation and CLI checks pass. All 2,304 trajectories pass full reexecution under Haswell BLAS dispatch. Previous source, protocols and archives remain byte-identical. CI adds an independent sensitivity replay job while preserving the four existing jobs.

```bash
python -m semiconductor_logistics rolling-sensitivity run --output artifacts/rolling_sensitivity
python -m semiconductor_logistics rolling-sensitivity verify --output artifacts/rolling_sensitivity
make verify-sensitivity
python -m scripts.audit_rolling_sensitivity_artifacts
```

The first two commands reproduce into a new empty directory; the third verifies the archive. No new human-review form or API operation is required.
