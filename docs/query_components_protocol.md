# 动作掩码与势函数对照 / Mask and potential comparisons

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

### 问题与设计

已完成的千题实验没有证实稳定的PPO收益。本轮检查动作约束和成本势函数的作用，不修改该最终测试或将已查看的任务重新称为盲测。使用原72个训练、18个选模验证、36个已查看开发情境；全部结论是开发性诊断。

采用2×2设计：动作掩码开/关，成本势函数开/关，共4个PPO变体×5种子（17、29、43、71、97）。每个种子直接读取上一轮保存的BC检查点，四组共享同一BC起点，不重新训练BC。优化设置沿用40轮、每训练情境2个episode、λ=0.95、entropy=0.01。按验证集原始成本加拒绝惩罚选模，不按塑形后回报选模。

| 变体 | 策略掩码 | 势函数奖励 |
|---|---|---|
| masked_cost | 开 | 无 |
| unmasked_cost | 关 | 无 |
| masked_potential | 开 | 有 |
| unmasked_potential | 关 | 有 |

另报BC掩码开/关、masked_cost检查点仅推理时关掩码，以及两步搜索与迭代DP。BC无掩码是部署诊断，不是重新训练的无掩码BC。masked_cost须与旧五种子完整PPO的训练日志、参数和开发成本数值一致；失败时先修实现，不解释组件效果。

### 环境与奖励

候选仍是提交和全部已有路线查询，公开特征相同。关闭策略掩码不会删除特征中的合法性线索；只取消对真实候选的概率过滤。变长批次的padding始终屏蔽。环境独立校验重复查询、预算和最大查询次数。非法动作不修改历史或消耗查询预算，立即结束查询并用当前信息执行安全的最终MILP，同时计25个仿真成本单位的拒绝惩罚；该数值在训练前固定，不是企业实测处罚。报告不含惩罚的经济成本和拒绝概率，避免单一合成惩罚掩盖结果。此终止约定限制结论，不代表所有非法动作处理方式。

掩码设计参考[Huang与Ontañón](https://arxiv.org/abs/2006.14171v3)的策略梯度动作掩码研究。该文支持检查训练/推理掩码的作用，不保证本场景有收益。

势函数用训练情境合法历史的20维公开状态特征拟合岭回归，目标为立即提交的期望成本/100，而非最优查询动作价值或成功概率。使用已有教师记录中的提交成本，按情境等权；标准化、ridge=0.001及上界=2×训练目标最大值均仅由训练资料确定。验证/开发任务不进入拟合。模型冻结并由所有种子共享，推理不调用求解器。它需要额外的训练成本监督，不能被描述成无监督进度估计器。

令非终态Φ(s)=−clip(预测成本/100,0,上界)，终态Φ=0；加入F=γΦ(s′)−Φ(s)，γ=1。每条完整轨迹的额外回报必须等于−Φ(s₀)，包括非法动作终止；因此完整回报的差值与动作无关。设计依据为[Ng、Harada与Russell](https://people.eecs.berkeley.edu/~russell/papers/icml99-shaping.pdf)的势函数奖励变换。此性质不保证有限样本PPO改善。

### 指标、证据与验收

每情境按精确查询DP归一化成本遗憾；报告经济成本、拒绝概率、查询和决策次数、求解次数。主要开发对照为unmasked_cost−masked_cost、masked_potential−masked_cost；另报无掩码条件下塑形作用及交互项。使用原配对种子×SKU/路线分层情境bootstrap（2,000次），全部区间为探索性，不做多重比较显著性声明。七类学习/部署设置×5种子×36情境加两个搜索基线，共1,332次开发评估，只有36个不同评估情境。

保存所有训练配置、初始/所选/最后参数、完整中间检查点、更新日志、采样动作/答案/基础奖励/势函数/塑形奖励、逐节点概率树与统计。重放重新拟合训练势函数、训练20个PPO并执行全部开发策略，验证环境拒绝、奖励恒等式、原始成本选模及跨数值实现的参数一致性。协议先于完整训练结果写入；不是独立第三方预注册。本轮不读千题测试，不调用模型API，不填写人工意见。

## English

### Question and design

The completed 1,000-context study did not establish a stable PPO benefit. This experiment tests action filtering and a cost potential without changing that final study or relabeling inspected cases as unseen. Reuse the original 72 training, 18 selection-validation and 36 inspected development contexts. All conclusions are developmental diagnostics.

Use a 2×2 design: policy mask on/off and cost potential on/off, giving four PPO variants × five seeds (17, 29, 43, 71, 97). Each seed loads its previously saved BC checkpoint; all four variants share that start. BC is not retrained. Retain 40 iterations, two episodes per training context, λ=0.95 and entropy=0.01. Select checkpoints by original validation cost plus rejection penalty, never shaped return.

| Variant | Policy mask | Potential reward |
|---|---|---|
| masked_cost | On | None |
| unmasked_cost | Off | None |
| masked_potential | On | Enabled |
| unmasked_potential | Off | Enabled |

Also report BC with/without its inference mask, masked_cost with its mask removed only at inference, and two-step/iterative-DP search. Unmasked BC is a deployment probe, not newly trained unmasked BC. masked_cost must numerically reproduce the earlier five-seed full PPO parameters, training logs and development costs. Resolve compatibility failures before interpreting component effects.

### Environment and reward

Candidates remain commitment and all existing route queries with unchanged public features. Removing the policy mask retains legality clues in those features; only probability filtering of real candidates changes. Batch padding remains masked. The environment independently validates duplicate queries, budgets and query limits. An invalid action leaves history and query budget unchanged, ends querying, executes a safe final MILP from current information, and adds 25 simulated cost units. This penalty is fixed before training, not a measured enterprise charge. Report economic cost excluding that penalty and rejection probability separately. This termination convention limits interpretation and does not represent every invalid-action treatment.

The design follows the policy-gradient masking question studied by [Huang and Ontañón](https://arxiv.org/abs/2006.14171v3). Their work motivates training/inference comparisons, not a guaranteed benefit here.

Fit ridge regression on the 20 public state features of legal histories from training contexts. Targets are immediate expected commitment cost/100, not optimal query action values or success probabilities. Use existing teacher commitment costs with equal context weights. Standardization, ridge=0.001 and the upper bound of twice the maximum training target use training data only. Validation/development cases never enter fitting. Freeze one predictor for all seeds; inference is solver-free. This consumes additional training cost supervision and is not an unsupervised progress estimator.

Set nonterminal Φ(s)=−clip(predicted cost/100,0,upper bound), terminal Φ=0, and add F=γΦ(s′)−Φ(s), with γ=1. The extra return of every complete trajectory must equal −Φ(s₀), including rejected termination, so the total-return shift is action-independent. The construction follows the potential-based transformation of [Ng, Harada and Russell](https://people.eecs.berkeley.edu/~russell/papers/icml99-shaping.pdf). That property does not guarantee improvement from finite-sample PPO.

### Metrics, evidence and acceptance

Normalize cost regret against exact query DP within each context. Report economic cost, rejection probability, query/decision counts and solver calls. The main development contrasts are unmasked_cost−masked_cost and masked_potential−masked_cost, with unmasked shaping and the interaction also reported. Use the existing paired seed-by-context bootstrap within SKU/route strata (2,000 replicates). All intervals are exploratory, without multiple-comparison significance claims. Seven learned/deployment settings × five seeds × 36 contexts plus two searches yield 1,332 evaluations but only 36 distinct evaluation contexts.

Archive settings, initial/selected/last parameters, all intermediate checkpoints, update logs, sampled actions/answers/base rewards/potentials/shaping rewards, node-level probability trees and statistics. Replay refits the training potential, retrains 20 PPO runs and executes all development policies, checking rejection behavior, reward identities, original-cost selection and numerical parameter agreement across implementations. This protocol precedes full results but is not external preregistration. The study does not read the 1,000-case test, call model APIs or fill human reviews.
