# 冻结千题结果 / Frozen 1,000-context results

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

### 范围与冻结

按[固定协议](query_study_protocol.md)，在五种子开发检查之后完成1,000个新合成情境的最终评测。所有任务、模型身份、配置和训练证据在首次最终输出前保存于[冻结提交](https://github.com/nomoretry/semiconductor-logistics-decarbonization/commit/09eea0ec98b54b13ca504ad3533480b819a8a1ca)。最终运行没有重新训练、选模或替换任务。小型验收与最终集的生成种子隔离修正见[记录](../data_sources/query_study_preflight_correction.json)。

这里的“最终”指当前已知订单、已知独立路线先验、最多3次查询的查询策略实验。它不是整个项目已完成，也不是长链LLM工具能力、未知需求或企业部署评测。

### 结果

| Method | Mean regret | Worst regret | Mean queries | Expected MILP calls |
|---|---:|---:|---:|---:|
| BC | 3.1179% | 47.0475% | 1.6446 | 1.0000 |
| PPO | 3.1477% | 50.1372% | 1.6458 | 1.0000 |
| PPO, entropy=0 | 3.1237% | 50.1372% | 1.5993 | 1.0000 |
| PPO, λ=1 | 3.1037% | 49.0358% | 1.6388 | 1.0000 |
| PPO, last checkpoint | 3.0653% | 60.1452% | 1.6148 | 1.0000 |
| Two-step, 13 | 0.6309% | 22.8809% | 1.5113 | 17.0779 |
| Iterative DP, 65 | 0.0528% | 11.6053% | 1.4811 | 40.1486 |


完整PPO相对同种子BC的平均遗憾差为 **+0.0298个百分点**，配对种子×分层情境bootstrap的近似95%区间为 **[-0.1817, +0.2540]个百分点**。负值表示PPO较好。主比较的近似区间包含零，不能据此确认PPO有稳定的平均收益。

| Seed | BC mean regret | PPO mean regret | PPO − BC (pp) |
|---|---:|---:|---:|
| 17 | 3.0267% | 2.8154% | -0.2113 |
| 29 | 3.1419% | 3.1187% | -0.0232 |
| 43 | 3.0219% | 3.0219% | +0.0000 |
| 71 | 3.1477% | 3.0976% | -0.0502 |
| 97 | 3.2514% | 3.6851% | +0.4337 |


按种子平均值，3个改善、1个变差、1个持平。各情境遗憾先相对该情境精确查询DP归一化，再在情境与种子上平均。最坏遗憾是该方法所有所报seed×context中的最大值，不是置信上界。成本使用仿真单位。

### 组件比较

| Contrast | Mean difference (pp) | Approximate paired 95% interval (pp) |
|---|---:|---:|
| ppo_lambda1_minus_ppo | -0.0440 | [-0.2553, +0.1563] |
| ppo_last_minus_ppo | -0.0824 | [-0.3116, +0.1330] |
| ppo_minus_bc | +0.0298 | [-0.1817, +0.2540] |
| ppo_no_entropy_minus_ppo | -0.0240 | [-0.2238, +0.1302] |


完整PPO与BC是唯一预定主比较。无熵项、λ=1与最后检查点均为探索性诊断，没有多重比较显著性声明；λ=1仍保留critic，最后检查点不代表新增训练。未进行Action Mask、查询费奖励或进度势函数消融，不能从此表推断这些组件的贡献。

### 计数、计算与证据

- 1,000个不同情境，5个真实训练种子；各种子从头训练BC，PPO变体共享该种子的BC起点。
- 5类学习检查点×5种子×1,000情境=25,000条评估；两个确定性强搜索各1,000条，合计27,000条。主方法的5,000条观察并非5,000个独立任务。
- 动作树仅在存储层去重为3936棵；各方法独立执行。学习策略每路径一次最终MILP，强搜索表中为整任务的期望调用，不能当成墙钟加速比。
- [冻结任务](../benchmarks/query_final_v1)、[训练证据](../benchmark_results/query_study_development)、[最终原始结果](../benchmark_results/query_final_v1)与[复现说明](query_study_evidence.md)公开保留。统计按共同种子/情境索引重采样，不把重复题目平铺成独立样本。

```bash
python -m semiconductor_logistics query-study verify-development
python -m semiconductor_logistics query-study verify-final
```

完整重放会重新训练5套BC、15套PPO，并由保存模型重执行全部27,000条最终评估，复算物理方案、成本和区间。文件与源码哈希只是一层检查，不能替代重执行。小样本训练种子下的bootstrap区间是近似描述；固定合成生成器上的最终留出不能支持广泛泛化。

本轮完成五种子、两项优化组件消融和冻结千题评测；进度奖励/Action Mask等其他消融、完整依赖锁、发布验收与未知需求滚动决策仍需分别推进。此前开发稳定条件失败的结论保留，不能用当前更大的样本量抹去种子间差异。

## English

### Scope and freeze

Following the [fixed protocol](query_study_protocol.md), the five-seed development study is followed by final evaluation on 1,000 new synthetic contexts. Tasks, model identities, settings and training evidence were saved in the [freeze commit](https://github.com/nomoretry/semiconductor-logistics-decarbonization/commit/09eea0ec98b54b13ca504ad3533480b819a8a1ca) before final outputs. No retraining, checkpoint selection or task replacement occurs in the final run. The smoke/final generator-isolation correction is documented in the [record](../data_sources/query_study_preflight_correction.json).

“Final” refers to this query-policy experiment with known orders, known independent route priors and at most three queries. It does not mean the whole project is complete, nor does it evaluate long-horizon LLM tools, unknown demand or enterprise deployment.

### Results

| Method | Mean regret | Worst regret | Mean queries | Expected MILP calls |
|---|---:|---:|---:|---:|
| BC | 3.1179% | 47.0475% | 1.6446 | 1.0000 |
| PPO | 3.1477% | 50.1372% | 1.6458 | 1.0000 |
| PPO, entropy=0 | 3.1237% | 50.1372% | 1.5993 | 1.0000 |
| PPO, λ=1 | 3.1037% | 49.0358% | 1.6388 | 1.0000 |
| PPO, last checkpoint | 3.0653% | 60.1452% | 1.6148 | 1.0000 |
| Two-step, 13 | 0.6309% | 22.8809% | 1.5113 | 17.0779 |
| Iterative DP, 65 | 0.0528% | 11.6053% | 1.4811 | 40.1486 |


Full PPO minus its same-seed BC baseline differs in mean regret by **+0.0298 percentage points**, with an approximate paired seed-by-stratified-context bootstrap 95% interval of **[-0.1817, +0.2540] percentage points**. Negative favors PPO. The approximate primary interval includes zero and does not establish a stable mean PPO benefit.

| Seed | BC mean regret | PPO mean regret | PPO − BC (pp) |
|---|---:|---:|---:|
| 17 | 3.0267% | 2.8154% | -0.2113 |
| 29 | 3.1419% | 3.1187% | -0.0232 |
| 43 | 3.0219% | 3.0219% | +0.0000 |
| 71 | 3.1477% | 3.0976% | -0.0502 |
| 97 | 3.2514% | 3.6851% | +0.4337 |


By seed mean, 3 improve, 1 worsen and 1 tie. Regret is normalized against exact query DP within each context, then averaged across contexts and seeds. Worst regret is the maximum across the method's reported seed-by-context outcomes, not a confidence bound. Costs use simulation units.

### Component contrasts

| Contrast | Mean difference (pp) | Approximate paired 95% interval (pp) |
|---|---:|---:|
| ppo_lambda1_minus_ppo | -0.0440 | [-0.2553, +0.1563] |
| ppo_last_minus_ppo | -0.0824 | [-0.3116, +0.1330] |
| ppo_minus_bc | +0.0298 | [-0.1817, +0.2540] |
| ppo_no_entropy_minus_ppo | -0.0240 | [-0.2238, +0.1302] |


Full PPO versus BC is the sole predefined primary comparison. No entropy, λ=1 and last-checkpoint contrasts are exploratory and carry no multiple-comparison significance claim. λ=1 retains the critic, and the last checkpoint requires no additional training. Action masks, query-fee rewards and potential shaping are not ablated; their contributions cannot be inferred from this table.

### Counts, computation and evidence

- There are 1,000 distinct contexts and five actual training seeds. Each seed retrains BC from scratch and shares that actor across its PPO variants.
- Five learned checkpoint types × five seeds × 1,000 contexts produce 25,000 evaluations. Two deterministic searches add 1,000 each, totaling 27,000. The primary method's 5,000 observations are not 5,000 independent tasks.
- Action-tree storage deduplicates to 3936 trees after independent execution. Learned policies use one final MILP per executed path. Search counts are expected calls over an entire task, not wall-clock speedups.
- The [frozen tasks](../benchmarks/query_final_v1), [training evidence](../benchmark_results/query_study_development), [raw final results](../benchmark_results/query_final_v1) and [reproduction instructions](query_study_evidence.md) remain available. Resampling preserves paired seed/context indices rather than flattening repeated cases into independent observations.

```bash
python -m semiconductor_logistics query-study verify-development
python -m semiconductor_logistics query-study verify-final
```

Full replay retrains five BC and 15 PPO runs, executes all 27,000 final evaluations from saved models and recomputes physical plans, costs and intervals. File/source hashes supplement reexecution. With few training seeds, bootstrap intervals are approximate descriptions. A final holdout from a fixed synthetic generator does not support broad generalization.

This stage completes five seeds, two optimization-component ablations and the frozen 1,000-context evaluation. Potential-shaping/action-mask ablations, complete dependency locking, release acceptance and unknown-demand rolling decisions remain separate work. The failed development stability condition is retained; a larger case count does not erase differences across training seeds.
