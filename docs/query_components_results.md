# 组件对照结果 / Component comparison results

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

按[事前写定的开发协议](query_components_protocol.md)，完成掩码开/关×成本势函数开/关的四组、五种子实验。复用72个训练、18个验证和36个已经查看的开发情境；没有读取或重评原1,000题最终测试。新组件结果不改变[原最终结论](query_final_results.md)。

### 实际结果

| Method | Mean regret | Economic cost | Rejection probability | MILP calls |
|---|---:|---:|---:|---:|
| bc_masked | 2.5947% | 133.6799 | 0.0000% | 1.0000 |
| bc_unmasked | 29.6437% | 133.2656 | 88.2083% | 1.0000 |
| masked_cost | 2.5362% | 133.6267 | 0.0000% | 1.0000 |
| unmasked_cost | 4.6288% | 133.7607 | 14.3215% | 1.0000 |
| masked_potential | 2.7956% | 133.8073 | 0.0000% | 1.0000 |
| unmasked_potential | 3.6195% | 133.5877 | 11.8448% | 1.0000 |
| masked_cost_inference_off | 29.4825% | 133.2758 | 88.6250% | 1.0000 |
| lookahead_two_13 | 0.7000% | 132.4346 | 0.0000% | 17.0285 |
| iterative_dp_65 | 0.0423% | 131.9952 | 0.0000% | 40.5944 |


遗憾的成本包括每次拒绝25个仿真单位；economic cost不含该拒绝惩罚，但包含查询费、运费、延误、持有及模型中的碳成本。拒绝概率是按路线答案分支概率计算的“该任务发生非法动作终止”的期望概率，不是把每个开发情境当成一次二元试验。所有非法动作均被环境拒绝，随后执行可行的最终运输计划；零非法执行由环境约束保证，不能作为模型学会安全性的证据。

- 训练和推理都去掉掩码，平均遗憾从2.5362%升到4.6288%，五个种子均变差；拒绝概率14.3215%。经济成本只从133.6267变为133.7607，较大的总成本差主要来自事前规定的拒绝惩罚。
- 对有掩码训练的模型只在推理时移除掩码，拒绝概率为88.6250%，遗憾29.4825%。这反映训练/部署规则不一致，不等同于从一开始无掩码训练的效果。
- 有掩码时加入势函数，遗憾2.7956%，相对2.5362%增加0.2593个百分点，区间跨零；没有观察到稳定收益。
- 无掩码时加入势函数，遗憾从4.6288%下降至3.6195%，拒绝概率从14.3215%降至11.8448%。这是固定罚值、共享有掩码BC起点下的开发信号，不据此替换原正式方法或宣称广泛有效。

| Contrast | Mean difference (pp) | Approximate paired 95% interval (pp) |
|---|---:|---:|
| inference_only_remove_mask | +26.9463 | [+22.9491, +30.7256] |
| interaction | -1.2686 | [-2.1500, -0.2975] |
| potential_masked | +0.2593 | [-0.1818, +0.7357] |
| potential_unmasked | -1.0093 | [-1.8114, -0.1090] |
| remove_mask | +2.0925 | [+0.6587, +3.5208] |


全部区间为探索性。没有多重比较校正；36个开发情境已经查看，不能把其中未跨零的区间描述为新留出集上的确认性发现。势函数交互项为“无掩码塑形差值减有掩码塑形差值”。强搜索仍以更多求解调用取得更低成本。

### 训练与证据

新增20组PPO训练，共115,200个采样episode、299,095个动作、10,996次实际参数更新。四组所选检查点退回共享BC起点；最后参数、更新日志及全部轨迹仍保留。masked_cost的五个种子均通过与旧完整PPO的参数、日志和采样记录兼容性检查。

势函数拟合使用训练集的3,520个合法历史状态，按72个情境等权。训练加权RMSE为0.392261（成本/100单位）；这不是未见数据预测误差。拟合目标为立即提交成本，既不是精确查询DP值，也不是参考项目的成功概率Progress Estimator。额外训练监督和该估计器的限制均保留。

[原始包](../benchmark_results/query_components_development)包含配置、势函数、20组初始/所选/最后模型和完整中间检查点、每次优化更新、采样JSONL、1,332条开发评估和逐节点概率树。不同评估情境只有36个，五种子和部署诊断不增加任务数。

每行episode为`[iteration, task_id, repeat, steps]`；step为`[action, answer, base_reward, phi_before, phi_after, old_logp, old_value]`。action=0提交，action=i+1查询路线i。历史、拒绝、done、塑形差值、总奖励与GAE从环境和这些原始值恢复，浮点值不舍入。验证器重新计算这些量并对照重新训练记录，不能只重写哈希让篡改通过。中间检查点的完整系数允许保留原哈希同时按原数值容差进行跨BLAS重放。

```bash
python -m semiconductor_logistics query-components run --output artifacts/components
python -m semiconductor_logistics query-components verify --output artifacts/components
python -m semiconductor_logistics query-components verify
make verify-components
```


前两个命令在新的空目录重现，第三个核验仓库归档。`make ci`同时包含既有研究的完整检查与本轮20组重训；GitHub将二者放在独立job并行执行。所有命令均为离线数值计算，不调用模型API。

### 后续范围

保留动作掩码作为查询合法性约束，保留BC和强搜索作为基线；本轮不把势函数加入默认正式方法。下一阶段为未知需求、预测误差及在途状态的滚动环境，先制定新任务与强规则验收，不沿用当前已查看的测试任务来挑选新方法。完整依赖锁、发布验收和历史文档双语补齐仍未完成。

## English

The [development protocol](query_components_protocol.md), written before full results, defines a four-cell mask on/off × cost-potential on/off experiment with five seeds. It reuses 72 training, 18 validation and 36 already inspected development contexts. The original 1,000-case final test is neither read nor reevaluated. These component results do not change the [original final conclusion](query_final_results.md).

### Observed results

| Method | Mean regret | Economic cost | Rejection probability | MILP calls |
|---|---:|---:|---:|---:|
| bc_masked | 2.5947% | 133.6799 | 0.0000% | 1.0000 |
| bc_unmasked | 29.6437% | 133.2656 | 88.2083% | 1.0000 |
| masked_cost | 2.5362% | 133.6267 | 0.0000% | 1.0000 |
| unmasked_cost | 4.6288% | 133.7607 | 14.3215% | 1.0000 |
| masked_potential | 2.7956% | 133.8073 | 0.0000% | 1.0000 |
| unmasked_potential | 3.6195% | 133.5877 | 11.8448% | 1.0000 |
| masked_cost_inference_off | 29.4825% | 133.2758 | 88.6250% | 1.0000 |
| lookahead_two_13 | 0.7000% | 132.4346 | 0.0000% | 17.0285 |
| iterative_dp_65 | 0.0423% | 131.9952 | 0.0000% | 40.5944 |


Regret includes 25 simulated cost units per rejection. Economic cost excludes that penalty but includes query fees, freight, lateness, holding and the modeled carbon costs. Rejection probability is the expected probability of an invalid-action termination over route-answer branches, not a binary trial for each context. The environment rejects every invalid action and then executes a feasible final transport plan. Zero illegal execution follows from environment constraints and is not evidence of learned safety.

- Removing the mask in both training and inference raises mean regret from 2.5362% to 4.6288%, with all five seeds worse and 14.3215% rejection probability. Economic cost only changes from 133.6267 to 133.7607; most of the larger total-cost difference comes from the predefined rejection penalty.
- Removing the mask only at inference from a mask-trained policy produces 88.6250% rejection probability and 29.4825% regret. This is a training/deployment mismatch, distinct from training without a mask from the start.
- With masks retained, potential shaping yields 2.7956% regret, an increase of 0.2593 percentage points over 2.5362%, with an interval spanning zero. No stable benefit is observed.
- Without masks, shaping reduces regret from 4.6288% to 3.6195% and rejection probability from 14.3215% to 11.8448%. This is a development signal under a fixed penalty and a shared mask-trained BC start, not grounds to replace the original formal method or claim broad effectiveness.

| Contrast | Mean difference (pp) | Approximate paired 95% interval (pp) |
|---|---:|---:|
| inference_only_remove_mask | +26.9463 | [+22.9491, +30.7256] |
| interaction | -1.2686 | [-2.1500, -0.2975] |
| potential_masked | +0.2593 | [-0.1818, +0.7357] |
| potential_unmasked | -1.0093 | [-1.8114, -0.1090] |
| remove_mask | +2.0925 | [+0.6587, +3.5208] |


All intervals are exploratory and unadjusted for multiple comparisons. The 36 contexts were already inspected, so intervals excluding zero are not confirmatory findings on a new holdout. The interaction subtracts the masked shaping contrast from the unmasked shaping contrast. Strong search still achieves lower costs with more solver calls.

### Training and evidence

The 20 new PPO runs contain 115,200 sampled episodes, 299,095 actions and 10,996 actual updates. Four selected checkpoints fall back to their shared BC initialization; final parameters, update logs and all trajectories remain archived. The five masked_cost runs pass numerical compatibility checks against earlier full PPO parameters, logs and sampled records.

The potential fits 3,520 legal histories from training contexts with equal weight per each of the 72 contexts. Weighted training RMSE is 0.392261 in cost/100 units; this is not unseen-data prediction error. Its target is immediate commitment cost, neither exact query-DP value nor the reference project's success-probability Progress Estimator. Additional supervision and estimator limitations are explicitly retained.

The [raw bundle](../benchmark_results/query_components_development) includes settings, the potential, 20 initial/selected/last model sets and full intermediate checkpoints, every optimizer update, sampled JSONL, 1,332 development outcomes and node-level probability trees. There are only 36 distinct evaluation contexts; seeds and deployment probes do not add tasks.

Each episode line is `[iteration, task_id, repeat, steps]`; each step is `[action, answer, base_reward, phi_before, phi_after, old_logp, old_value]`. Action 0 commits; action i+1 queries route i. History, rejection, termination, shaping difference, total reward and GAE are reconstructed from the environment and these unrounded values. Verification recomputes them against retraining; rehashing changed evidence cannot bypass it. Full intermediate coefficients bind original checkpoint hashes while permitting the original numerical tolerances across BLAS implementations.

```bash
python -m semiconductor_logistics query-components run --output artifacts/components
python -m semiconductor_logistics query-components verify --output artifacts/components
python -m semiconductor_logistics query-components verify
make verify-components
```


The first two commands reproduce into a new empty directory; the third verifies the repository archive. `make ci` combines all existing evidence checks with this 20-run retraining. GitHub executes them as independent parallel jobs. Every command is offline numerical computation, without model API calls.

### Remaining scope

Retain action masks for query legality, and retain BC and strong search as baselines. Do not add this potential to the default formal method. The next stage is a rolling environment with unknown demand, forecast error and evolving in-transit inventory, starting with a new task definition and strong-rule acceptance criteria. Do not select new methods using the already inspected final tasks. Complete dependency locking, release acceptance and historical bilingual documentation remain unfinished.
