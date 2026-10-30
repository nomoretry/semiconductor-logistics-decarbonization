# 同一起点的查询策略 PPO / Query PPO from a shared BC checkpoint

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; the English version follows the Chinese text.

## 中文

### 问题与依据

上一轮 BC 的误差分解发现，多余查询、过早停止和查询对象选择均造成成本损失。本轮检验：保持公开特征、合法动作和运输求解器不变，仅从同一 BC 检查点继续进行基于实际成本的策略优化，能否改善查询与停止决策？此前预算实验的筛选失败结论保留；本轮仍研究质量与在线计算量的取舍。

算法依据为 [PPO 原论文](https://arxiv.org/abs/1707.06347v2)的 clipped surrogate 和 [GAE 原论文](https://arxiv.org/abs/1506.02438v6)的优势估计。这里独立实现 NumPy 小型策略，不训练 LLM，不复制参考仓库代码。PPO 只代表所用优化方法，不预设会优于 BC。

### 运行前固定的设计

- 起点为 `benchmark_results/query_bc_development/checkpoint.json`，输入仍是 37 维公开候选特征，actor 为 32 单元 tanh 评分器。critic 单独读取其中 20 维公共状态特征，32 单元 tanh 隐层；不读取动作教师值、任务 ID、种子或未查询答案。
- 继续使用原来 72 个训练与 18 个验证情境。新开发评估使用 4/8/12 SKU × 2/4/6 路线状态 × 种子 4001–4004，共 36 个情境；按公开内容与旧 54 个预算情境、原 BC 全部情境去重。同一情境的所有历史始终属于同一划分。它仍是固定生成器上的开发评估，不是正式冻结测试。
- 训练种子 17；40 轮，每轮每训练情境采样 2 个完整 episode。查询后才按公开先验采样该路线答案；各路线独立。最多 3 次查询后提交，不跨 episode 计算 GAE。
- 查询奖励为负查询费，提交奖励为当前信息下最优运输方案的条件期望成本的负值，统一除以 100。条件期望成本是已知先验下的环境反馈，不是精确查询 DP 的动作价值；它整合未查询路线的随机性。没有教师 Q 奖励、进度势函数、BC 辅助损失或奖励调参。
- gamma=1，lambda=0.95；策略比率与 value clip 均为 0.2；value 系数 0.5，entropy 系数 0.01；Adam 学习率 0.0003，联合梯度范数上限 0.5；每轮最多 4 个更新 epoch，batch 128，整批近似 KL 超过 0.02 时停止当前轮更新。每轮优势统一标准化。精确超参数保存在配置文件。
- 每 5 轮在原验证情境完整枚举答案分支，按贪心策略的平均期望总成本选择检查点；迭代 0 的原 BC 也参加选择。不依靠新 36 个情境选择模型。保留最后检查点与选中检查点，分别记录真实参数变化，避免把没有改善的模型写成成功。
- 原 BC、PPO 所选模型、PPO 最后模型、13 次预算两步搜索和 65 次预算迭代 DP 在相同新情境评估。学习策略只在提交时执行一次 MILP；训练环境的终端解缓存和评估器枚举开销单独计数，不作为免费计算或在线加速倍数。

### 证据与验收

保存配置、来源身份、训练和开发任务、每个采样 episode 的历史/动作/奖励/old log-prob/value/GAE、更新日志、验证选模记录、初始/选中/最后检查点、每个方法的完整评估树和汇总。验证器从原 BC 重训，核对采样轨迹和每次更新的记录，再由保存的检查点重执行评估并复算成本。固定源码、数据和检查点的哈希绑定与数值比较共同使用，不能只改指标后重新计算哈希。

实现验收要求 GAE 终态隔离、clipped policy/value 的有限差分梯度、masked 动作合法性、同一 BC 起点、真实参数更新、独立新情境和篡改拒绝。性能无预定通过阈值；结果改善、持平或退步均发布。本轮仅一个训练种子，无显著性结论，也不代表完整五种子消融。协议在首次完整训练前写入，与代码一同发布，不声称外部预注册。

## English

### Question and basis

The previous BC diagnostic attributed excess cost to unnecessary queries, premature commitment and query choice. This experiment asks whether cost-based policy optimization from the same BC checkpoint improves these decisions while keeping public features, legal actions and the shipping solver fixed. The earlier failed budget gate remains unchanged; the question concerns the tradeoff between decision quality and online computation.

The algorithm follows the clipped policy objective in [PPO](https://arxiv.org/abs/1707.06347v2) and the advantage estimator in [GAE](https://arxiv.org/abs/1506.02438v6). This is an independent small NumPy implementation, not LLM training or copied reference code. Using PPO does not imply that it will outperform BC.

### Fixed design

- Initialize the actor from `benchmark_results/query_bc_development/checkpoint.json`. Keep the 37 public candidate features and 32-unit tanh scorer. A separate 32-unit critic uses the 20 public state features only. Neither network sees teacher values, task IDs, seeds or unqueried answers.
- Reuse the 72 training and 18 validation contexts. Evaluate on 36 new contexts: 4/8/12 SKUs × 2/4/6 route states × seeds 4001–4004. Check public-content uniqueness against the earlier 54 budget contexts and every BC context. All histories of a context remain in one split. These are development contexts from the same generator, not a final frozen test.
- Use training seed 17, 40 iterations and two complete episodes per training context per iteration. Sample a route answer from its public prior only after querying it; routes are independent. Commit after at most three queries. GAE never crosses episode boundaries.
- Query rewards are negative fees; commitment rewards are the negative conditional expected cost of the optimal shipping plan, divided by 100 throughout. This environment feedback integrates unqueried route uncertainty under the known priors. It is not an exact query-DP action value. There is no teacher-Q reward, potential shaping, auxiliary BC loss or reward tuning.
- Use gamma=1, lambda=0.95, policy/value clipping=0.2, value coefficient=0.5, entropy coefficient=0.01, Adam learning rate=0.0003 and joint gradient norm limit=0.5. Run up to four update epochs per iteration with minibatches of 128. Stop that iteration's updates when whole-batch approximate KL exceeds 0.02. Normalize advantages per rollout batch. The configuration records all settings.
- Every five iterations, enumerate answer branches on the original validation contexts and select by mean expected total cost of the greedy policy. Include iteration 0, the original BC actor. Never select using the new 36 contexts. Save both selected and last checkpoints and report their parameter changes separately.
- Evaluate BC, selected PPO, last PPO, two-step search with a budget of 13 and iterative DP with a budget of 65 on identical new contexts. Learned policies execute one terminal MILP per deployed path. Training terminal caches and evaluator enumeration work are counted separately; solver-call reductions are not wall-clock speedups.

### Evidence and acceptance

Save configuration and source identities, tasks, sampled histories/actions/rewards/old log-probabilities/values/GAE, update logs, validation selection, initial/selected/last checkpoints, full evaluation trees and summaries. Verification retrains from the original BC actor, compares sampled evidence and update records, then executes saved checkpoints and recomputes costs. Hash binding and numerical reexecution are both required.

Implementation checks cover episode-safe GAE, finite-difference gradients for clipped policy/value objectives, legal masked actions, shared initialization, actual updates, disjoint evaluation contexts and tamper rejection. Publish improvements, ties and regressions alike. This is one training seed, with no significance claim or completed five-seed ablation. The protocol is written before the first full training run and published with the implementation, not externally preregistered.
