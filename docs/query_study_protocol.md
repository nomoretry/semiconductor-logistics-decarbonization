# 多种子与冻结评测协议 / Multi-seed and frozen-evaluation protocol

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

### 问题与变体

单种子 PPO 结果不能说明训练稳定性。本轮先在开发资料上检查完整训练链的随机性和两个优化组件，再对同一固定生成器上的 1,000 个新合成情境做预先冻结的最终评测。此前强规则筛选失败、短查询长度和已知先验的限制均保留。

训练种子固定为 17、29、43、71、97。每个种子重新初始化并训练 BC，使用原 72 个训练与 18 个验证情境、多正例教师和 80 epochs；该种子的 BC 检查点是它全部 PPO 变体的共同起点。PPO 继续采用既有 40 轮、每情境 2 episodes、验证集选模方案。不同种子不是只替换评测随机数。

| 方法 | 与完整 PPO 的差异 | 用途 |
|---|---|---|
| BC | 不继续 PPO | 主比较基线 |
| PPO | 既有配置，λ=0.95，entropy=0.01 | 唯一主要方法 |
| PPO，无熵项 | entropy=0，其余相同 | 检查熵正则贡献 |
| PPO，λ=1 | λ=1，其余相同，critic仍存在 | 检查GAE衰减；不是移除critic |
| PPO，最后检查点 | 同一完整PPO的第40轮，不新增训练 | 检查验证选模影响 |
| 两步搜索 / 迭代DP | 每决策求解预算13/65 | 确定性强基线，只计一次，不复制为5个“种子” |

本轮没有移除预算mask、修改查询费奖励或新增进度势函数。这些结果不能解释为上述组件的消融，也不能保证已达到参考项目的全部完成度。方法基于先前的[PPO协议](query_ppo_protocol.md)，不更改旧实现。

### 开发检查与最终冻结

开发检查复用上一轮已经看过的36个PPO开发情境，只用于稳定性和消融诊断，不再称独立留出测试。主要方法预先固定为完整PPO，不从三个PPO变体中挑选开发结果最好的一个。

开发稳定性描述条件为：完整PPO相对BC的平均遗憾至少在4/5个种子下降，且下述配对区间上界小于0。条件失败仍保留全部结果，并继续预定的合成最终评测；最终结论允许失败，不用更换种子或测试集获得通过。

训练和开发结果固定后，生成1,000个新情境：4/8/12 SKU × 2/4/6路线状态的9格，按固定顺序循环分配，第一格112个，其余111个；生成器种子为20000+题号×100000，避免生成器内部的SKU/路线偏移导致不同格复用同一随机数流。公开内容逐题去重，并与此前54个预算、126个BC、36个PPO开发情境去重。同一情境全部答案分支为一个统计单元。保留所有合法生成情境，不按难度或方法表现筛选。

在首次计算最终模型输出前，保存任务列表、SHA256、训练证据清单哈希、全部所选模型身份、配置和源码身份；将这个冻结版本提交到GitHub。最终评测必须读取这份冻结列表，不重新抽题、不再训练或选模。冻结提交是可追踪版本，不称独立第三方预注册。最终仍属于固定生成分布上的合成检验，不代表未知企业分布或长链工具任务。

### 指标与统计

主指标为每情境相对精确查询DP的归一化成本遗憾；主比较为PPO减BC，负值较好。每个种子在相同1,000题上评估；共5,000个主方法观测仍只有1,000个不同情境和5个训练种子。另报每种子的差值、最坏情境、查询次数及线上求解次数。

区间采用配对的种子×情境重采样：独立有放回抽取5个种子；在9个SKU/路线格内有放回抽取相同数量的情境；每次抽样对全部方法共用索引。做2,000次，取2.5%和97.5%分位数。不能把5,000条扁平化当独立样本。分别重采样交叉维度的依据见[Owen的pigeonhole bootstrap](https://arxiv.org/abs/0712.1111)；本研究另固定SKU/路线分层。它是小样本种子下的近似描述区间，不保证精确覆盖率。其他组件比较为探索性区间，无多重比较显著性声明。主结论仅检验预定完整PPO对BC，不事后选最好变体。

### 证据与验证

保存5套BC训练记录、15套PPO初始/所选/最后模型、每次实际更新记录、采样动作/答案/奖励/old log-prob/value、开发指标、冻结任务与最终逐题指标。采样JSONL使用有说明的紧凑数组；历史、done与GAE可从记录恢复，原始数值不舍入。最终动作树按内容去重仅减少文件重复；它不共享线上规划缓存，不改变所报求解次数。每条结果绑定模型哈希与动作树哈希。推理概率由保存模型重算，不把动作树相同解释为概率相同。

验证重新生成任务、重算教师、重新训练所有BC/PPO、比对日志和紧凑轨迹，再从保存模型重执行全部最终题目，检查整数方案可行性、最优终端成本、逐题结果与配对统计。旧实验保持原字节和验证入口。该协议在多种子训练前写入，代码、负结果和双语说明一起发布。

### 冻结前验收修正

小型端到端验收曾使用正式生成器的前3个情境（起始种子10000）。它们只由小型验收模型运行，没有用于方法选择；仍不应再称未查看。正式发布前，将整个最终集改为起始种子20000，小型验收单独使用900000000，增加两者内容及有效随机流不重叠检查。旧本地预检冻结作废，保留记录；多种子训练重新验证，模型、日志和开发结果逐字节保持一致，未改变训练或消融超参数。正式1,000题评测只运行修正后、预先提交的冻结版本。

## English

### Question and variants

A single PPO seed does not establish training stability. This study first checks randomness across the full training chain and two optimization components on development data, then evaluates 1,000 newly frozen synthetic contexts from the same generator. Earlier failed baseline gates, short query horizons and known-prior limitations remain unchanged.

Training seeds are 17, 29, 43, 71 and 97. Retrain BC from its own initialization for every seed using the original 72 training and 18 validation contexts, multi-positive teachers and 80 epochs. Each seed's BC checkpoint initializes all of its PPO variants. Keep the existing 40-iteration PPO schedule, two episodes per training context and validation-based selection. Seeds are not merely evaluation randomness.

| Method | Difference from full PPO | Purpose |
|---|---|---|
| BC | No PPO continuation | Primary baseline |
| PPO | Existing settings, λ=0.95, entropy=0.01 | Sole primary method |
| PPO without entropy | entropy=0, everything else fixed | Entropy regularization ablation |
| PPO with λ=1 | λ=1, critic retained | GAE decay ablation, not critic removal |
| Last PPO checkpoint | Iteration 40 of the same full PPO run | Selection diagnostic; no extra training |
| Two-step search / iterative DP | Per-decision solve budgets 13/65 | Deterministic strong baselines, counted once rather than duplicated over five seeds |

Budget masks, query-fee rewards and potential shaping are not ablated here. Results cannot establish their contributions or claim all reference-project components are complete. The implementation uses the earlier [PPO protocol](query_ppo_protocol.md) without changing frozen code.

### Development and final freeze

Development diagnostics reuse the already inspected 36 PPO contexts. They are not a new holdout. Full PPO is fixed as the primary method before seeing multi-seed results; do not choose the best of three PPO variants afterward.

The descriptive development stability condition requires lower mean regret than BC in at least four of five seeds and an upper paired interval below zero. Retain failures and continue the planned synthetic final evaluation regardless. Never change seeds or test cases to manufacture a pass.

After training and development results are fixed, generate 1,000 new contexts across the nine combinations of 4/8/12 SKUs and 2/4/6 route states, assigned cyclically in fixed order. The first stratum has 112 cases and the other eight have 111. Generator seeds are 20000 + case index × 100000, preventing the generator’s internal SKU/route offsets from reusing a random stream across strata. Check public-content uniqueness within the set and against the 54 budget, 126 BC and 36 PPO development contexts. All answer branches of one context form one statistical unit. Do not filter by difficulty or policy performance.

Before computing any final policy outputs, save the task list, SHA256, training-manifest hash, all selected-model identities, configuration and source identities, and commit the freeze to GitHub. Final evaluation reads this list, with no resampling, retraining or checkpoint selection. The commit is a traceable version, not independent third-party preregistration. This remains a synthetic same-distribution evaluation, not evidence for unseen enterprise distributions or long-horizon tools.

### Metrics and statistics

The primary metric is per-context normalized cost regret against exact query DP. The primary contrast is PPO minus BC; negative is better. Five seeds evaluated on 1,000 shared contexts produce 5,000 primary-method observations, but only 1,000 distinct contexts and five training seeds. Also report per-seed differences, worst cases, query counts and online solve counts.

Use paired seed-by-context resampling: independently sample five seeds with replacement and sample contexts with replacement within each of the nine SKU/route strata, retaining stratum sizes. All methods share the sampled indices. Use 2,000 replicates and the 2.5th/97.5th percentiles. Do not treat the 5,000 rows as independent. Separate resampling of crossed dimensions follows the rationale of [Owen’s pigeonhole bootstrap](https://arxiv.org/abs/0712.1111); this study additionally fixes SKU/route strata. With only five seeds, these are approximate descriptive intervals, not guaranteed-coverage intervals. Component contrasts are exploratory, with no multiple-comparison significance claim. The primary conclusion concerns the predefined full PPO versus BC.

### Evidence and verification

Archive five BC training records, 15 PPO initial/selected/last checkpoint sets, every update log, sampled actions/answers/rewards/old log-probabilities/values, development results, frozen tasks and final per-case outcomes. Training JSONL uses documented compact arrays without rounding; histories, done flags and GAE can be reconstructed. Content-based deduplication of final action trees reduces storage only. It does not share online planning caches or change reported solver calls. Each outcome binds a model hash and an action-tree hash. Probabilities are recomputed from saved models; identical action trees do not imply identical probabilities.

Verification regenerates tasks, recomputes teachers, retrains all BC/PPO runs, compares logs and compact trajectories, then executes saved models on all final contexts and checks integer feasibility, optimal terminal costs, per-case results and paired statistics. Earlier experiments retain their original bytes and verification commands. This protocol is written before multi-seed training and published with code, negative results and bilingual explanations.

### Pre-freeze acceptance correction

The end-to-end smoke check initially used the first three contexts of the planned final generator, starting at seed 10000. Only smoke models evaluated them, and they were not used for method selection; they should nevertheless not be called unseen. Before publication, move the whole final set to seed start 20000 and isolate smoke generation at 900000000. Add content and effective-RNG-stream disjointness checks. Retain and supersede the local preflight freeze. Reverify multi-seed training and compare model, log and development-result bytes; training and ablation settings are unchanged. The formal 1,000-case evaluation uses only the corrected, previously committed freeze.
