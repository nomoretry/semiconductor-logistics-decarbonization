# 查询策略 PPO 开发结果 / Query PPO development results

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; the English version follows the Chinese text.

## 中文

### 实验与结果

本轮按[固定协议](query_ppo_protocol.md)执行真实 PPO 更新，直接继承上一轮 BC 检查点。训练和验证仍为 72/18 个情境，新开发评估为 36 个情境；训练种子只有 17。公开特征、预算 mask 和运输求解器保持一致。原来的 36 个 BC 开发情境没有参与本轮评估。

40 轮训练采样 5,760 个 episode、15,397 个动作，完成 576 次参数更新。验证集选择第 40 轮，恰好也是最后一轮；所选 actor 相对 BC 的参数 L2 变化为 0.360529。episode 和动作数不是不同任务数。PPO 使用实际成本奖励和 GAE，没有进度势函数或教师 Q 奖励。

| 方法 | 平均遗憾 | 最大遗憾 | 平均期望总成本 | 每任务期望 MILP 次数 | 平均查询次数 |
|---|---:|---:|---:|---:|---:|
| 同一起点 BC | 2.6486% | 11.1829% | 133.707777 | 1.0000 | 1.6857 |
| PPO 所选模型 | 1.9416% | 11.1829% | 133.251316 | 1.0000 | 1.5576 |
| PPO 最后模型 | 1.9416% | 11.1829% | 133.251316 | 1.0000 | 1.5576 |
| 两步搜索，预算 13 | 0.7000% | 10.5648% | 132.434629 | 17.0285 | 1.5096 |
| 迭代 DP，预算 65 | 0.0423% | 1.4002% | 131.995204 | 40.5944 | 1.4641 |

遗憾是相对同情境精确查询 DP 的成本差，先逐情境归一化，再取平均。PPO 相对 BC 的平均遗憾减少 **0.7070 个百分点**；36 个配对情境中 6 个成本改善、30 个持平、0 个变差。最坏情境没有改善。运输成本使用合成模型单位，不是已校准的企业费用。

学习策略每条实际执行路径仅在最终提交时求解一次运输 MILP；表中搜索预算限制每次决策，因此一整个任务的期望调用可以超过 13。PPO 的质量仍低于强搜索，不能据此宣称替代了精确规划。

### 选模与计算成本

验证集平均成本从起点的 136.567994 降到所选模型的 136.325431。训练并非单调改善：第 15 轮为 136.805907，第 25–35 轮为 136.699730。全部验证记录和每次更新的 policy loss、value loss、KL、熵、clip fraction、梯度范数均保留；本轮没有触发 KL 提前停止。没有根据新评估结果重新调参。

训练环境缓存产生 882 次不同终端状态求解，验证选模产生 80 次；新评估的精确参考计算另需 1,948 次。这些是离线成本，不计入部署路径的一次最终求解，也不能忽略。墙钟时间在运行文件中仅作机器相关诊断，不报告加速倍数。

### 复算与限制

证据包位于 [query_ppo_development](../benchmark_results/query_ppo_development)。它保存原始采样轨迹、三个检查点、逐轮日志、完整评估树和逐情境指标。验证器从固定 BC 检查点重新采样、重训、核对 GAE 和全部更新记录，再读取保存模型重执行 180 次策略评估。即使同步修改文件哈希，篡改的训练奖励或检查点仍会被拒绝。

```bash
python -m semiconductor_logistics query-ppo --output artifacts/query_ppo
python -m semiconductor_logistics query-ppo --verify --output artifacts/query_ppo
python -m semiconductor_logistics query-ppo --verify --output benchmark_results/query_ppo_development
```

输出目录必须为空；完整离线检查通过 `make ci` 运行，不调用模型 API。

这是单训练种子、固定生成器、复用验证集的开发结果，没有统计显著性结论。已知订单、已知路线先验和条件期望反馈仍是重要假设。它不是 LLM 微调，也没有加入未知需求。此前平均遗憾筛选失败的记录不变。

下一项先在训练/验证范围比较种子稳定性、停止决策和奖励设计，固定变体后再冻结约 1,000 个最终任务、运行 5 种子与关键消融。已经查看的开发情境不进入新的未查看测试集。

## English

### Experiment and results

This experiment executes actual PPO updates under the [fixed protocol](query_ppo_protocol.md), starting directly from the previous BC checkpoint. It reuses 72 training and 18 validation contexts and evaluates on 36 new development contexts. The only training seed is 17. Public features, budget masks and the shipping solver remain fixed. The earlier 36 BC development contexts are not reused for this evaluation.

Forty iterations collected 5,760 episodes and 15,397 actions, with 576 parameter updates. Validation selected iteration 40, also the last iteration. The selected actor's L2 parameter change from BC is 0.360529. Episodes and actions are not distinct tasks. PPO uses actual cost rewards and GAE, without potential shaping or teacher-Q rewards.

| Method | Mean regret | Maximum regret | Mean expected total cost | Expected MILP calls per task | Mean queries |
|---|---:|---:|---:|---:|---:|
| Shared-start BC | 2.6486% | 11.1829% | 133.707777 | 1.0000 | 1.6857 |
| Selected PPO | 1.9416% | 11.1829% | 133.251316 | 1.0000 | 1.5576 |
| Last PPO | 1.9416% | 11.1829% | 133.251316 | 1.0000 | 1.5576 |
| Two-step search, budget 13 | 0.7000% | 10.5648% | 132.434629 | 17.0285 | 1.5096 |
| Iterative DP, budget 65 | 0.0423% | 1.4002% | 131.995204 | 40.5944 | 1.4641 |

Regret is the cost difference from exact query DP for each context, normalized before averaging. PPO reduces mean regret by **0.7070 percentage points** relative to BC. Among 36 paired contexts, costs improve in six, tie in 30 and worsen in none. The worst case does not improve. Costs are synthetic model units, not calibrated enterprise expenses.

A learned policy solves one shipping MILP at final commitment on each executed path. Search budgets apply per decision, so expected calls over a whole task can exceed 13. PPO still has worse cost performance than strong search; this result does not establish a replacement for exact planning.

### Selection and computation

Mean validation cost decreases from 136.567994 at initialization to 136.325431 for the selected model. Training is not monotonic: iteration 15 reaches 136.805907, and iterations 25–35 reach 136.699730. All validation records and per-update policy loss, value loss, KL, entropy, clipping fraction and gradient norm are retained. No update iteration triggers the KL stop. Settings were not retuned after viewing the new evaluation.

Training terminal caches require 882 distinct terminal solves; validation selection requires 80. Exact references for the new evaluation require another 1,948 solves. These offline costs are separate from the one terminal solve on a deployed path and must not be ignored. Recorded wall-clock times are machine-dependent diagnostics, not speedup claims.

### Verification and limits

The [evidence bundle](../benchmark_results/query_ppo_development) contains sampled trajectories, three checkpoints, iteration logs, complete evaluation trees and per-context outcomes. Verification starts from the frozen BC checkpoint, resamples and retrains, compares GAE and every update record, then reads the saved models and reexecutes 180 policy evaluations. Altered rewards or checkpoints are rejected even when file hashes are updated to match them.

```bash
python -m semiconductor_logistics query-ppo --output artifacts/query_ppo
python -m semiconductor_logistics query-ppo --verify --output artifacts/query_ppo
python -m semiconductor_logistics query-ppo --verify --output benchmark_results/query_ppo_development
```

The output directory must be empty. `make ci` runs the complete offline checks without model API calls.

This is a single-seed development result from a fixed generator with reused validation contexts. It supports no statistical-significance claim. Known orders, known route priors and conditional expected feedback remain important assumptions. This is not LLM fine-tuning and does not include unknown demand. The earlier failed mean-regret gate remains unchanged.

Next, compare seed stability, stopping decisions and reward designs within training/validation data. Fix the variants before freezing approximately 1,000 final tasks for five-seed evaluation and key ablations. Previously inspected development contexts must not enter a new unseen test set.
