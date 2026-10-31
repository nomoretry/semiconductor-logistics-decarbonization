# 有限情景追索结果 / Finite-support recourse results

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

36个有限模型已完成精确枚举、36次旧MILP交叉验证及1,920次逐叶物理重放。完整路径边际相同，固定计划目标相同；加入按已观察历史调整的后续动作后，期望成本可以随跨SKU配对改变。但目前没有发现需要更准确相关性模型或学习策略的决策收益。

### 对照结果

| 检查 | 结果 | 可支持的解释 |
|---|---|---|
| 追索 vs 固定字典序选解的滚动基线 | 18组更好、18组相同、0组更差 | 表面差距需要排查并列最优解 |
| 追索 vs 从全部固定计划最优首期动作中选最好后续表现 | 36组均相同 | 原目标的平局即可解释这次表面收益 |
| 跨相关性策略评估 | 108次，其中72次模型错配；成本遗憾全部0 | 本构造没有证明预测相关性改善实际动作 |
| 完整路径边际与固定计划目标 | 12个三模型对照组全部相同 | 保留原可分目标不变性 |
| 信号准确率1/2 | 18组追索与滚动基线相同 | 无预测信息时保留零收益 |
| 库存、在途、容量、逐路径碳、成本复算 | 1,920个策略×叶节点记录通过 | 每个模型分别精确加权，不把重复叶节点当作独立样本 |

表中“最好后续表现”是预先知道有限概率模型、对并列方案计算条件期望后的选择；没有观察实际未来。它比简单字典序选择更贵，不能声称免费获得，也不代表已经证明计算瓶颈。1,920=36模型下各8或16叶节点×5个方法；36模型是3容量×2碳预算×2信号准确率×3配对，不能写成1,920个新测试任务。

固定快线容量1、碳预算6、信号准确率3/4的一组示例：

| 配对 | 固定计划 | 滚动，字典序平局 | 滚动，最好平局 | 历史追索 |
|---|---:|---:|---:|---:|
| 正相关 | 13.87500 | 13.03125 | 11.40625 | 11.40625 |
| 独立 | 13.87500 | 13.50000 | 10.43750 | 10.43750 |
| 负相关 | 13.87500 | 13.03125 | 9.46875 | 9.46875 |

三种模型的最优期望值不同，但本例选出的追索策略相同。成本随需求分布变化不等于获得了更好的决策。快线容量至少2且碳预算100时，本构造追索成本在三种配对下又都为9；这些结果只是机制诊断，不能外推企业效应或更长周期的结论。

### 审计顺序与限制

[初始协议](rolling_recourse_protocol.md)在输出前固定36个模型、四种方法与平局记录。看到18组表面提升且首期动作并列后，**追加探索性审计**：枚举全部固定计划最优动作的后续期望，以及108次跨模型评估。这两项不是事前确认假设；没有更改36个模型参数或原四种方法数值，没有选新的参数来制造正结果。第五个方法为上述最好平局对照。

这不是12期、3SKU原环境的完整追索替代器，也不是从历史学习出的情景树。模型知道构造的概率分布，但不知道当前叶节点；相同观察历史强制同一动作。完全预知策略单独作为下界。没有调用LLM、训练BC/PPO或新增真实公司数据。

下一步是实现原时序下的较长情景树与历史条件预测，先检验相同信息、平局稳健的优化基线；只有实际决策差异或明确求解时限出现后，才开展新路径确认和教师筛选。本轮不增加新的千题或训练次数。

### 复现与证据

- [源码](../rolling_recourse/experiment.py)、[构造配置](../rolling_recourse/config.json)、[完整逐模型/节点/叶成本](../benchmark_results/rolling_recourse_mechanism/results.json)、[SHA256清单](../benchmark_results/rolling_recourse_mechanism/manifest.json)。这些是新机制检查的可读JSON，与已按授权补齐的35份分布证据是不同的工作。
- `python -m semiconductor_logistics rolling-recourse verify` 或 `make verify-recourse`：重新枚举、重放原环境、与原MILP交叉比较，最后逐字段比较。
- `python -m semiconductor_logistics rolling-recourse run --output artifacts/recourse-new`：在空目录重建。已存在的证据不会被覆盖。
- 新增测试覆盖精确概率、相同历史仍有未知未来、提前期、逐路径碳、平局审计，以及改动作并重算哈希后的拒绝。

## English

All 36 finite models have been exhaustively optimized, cross-checked against the archived MILP and replayed in 1,920 policy/leaf episodes. Identical full-path SKU marginals preserve open-loop objectives. History-conditioned future actions can make expected costs depend on cross-SKU pairing. This construction nevertheless provides no evidence of decision gains requiring better dependence forecasts or a learned policy.

### Comparisons

| Check | Result | Interpretation |
|---|---|---|
| Recourse vs lexicographically selected rolling open loop | 18 improvements,18 ties,0 worse | Apparent gains require an optimal-tie audit |
| Recourse vs best conditional continuation among every open-loop-optimal first action | All 36 tie | Open-loop ties explain all apparent gains here |
| Cross-coupling policy evaluation | 108 evaluations,72 misspecified models; zero cost regret throughout | No demonstrated decision benefit from forecasting coupling |
| Complete-path marginals and open-loop objective | Identical in all 12 three-model groups | Original separable-objective invariance retained |
| Signal accuracy1/2 | All 18 recourse/rolling comparisons tie | Retains the uninformative-signal negative control |
| Stock,pipeline,capacity,pathwise carbon and cost replay | All1,920 policy/leaf episodes pass | Exact weighting within each model; repeated leaves are not independent samples |

The best-tie comparator evaluates conditional expectations under the known finite probability model; it does not observe realized future demand. This requires more computation than lexicographic tie-breaking. We claim neither free tie resolution nor a demonstrated computation bottleneck. The1,920 episodes comprise8 or16 leaves per model times five methods. The36 models are3 capacities×2 budgets×2 accuracies×3 couplings, not1,920 independent test tasks.

At fast capacity1,carbon budget6,signal accuracy3/4:

| Coupling | Open loop | Rolling,lexicographic tie | Rolling,best tie | History recourse |
|---|---:|---:|---:|---:|
| Positive |13.87500|13.03125|11.40625|11.40625|
| Independent |13.87500|13.50000|10.43750|10.43750|
| Negative |13.87500|13.03125|9.46875|9.46875|

The three optimal expected values differ, but their selected recourse policies are identical. Distribution-dependent costs are not improved decisions. With fast capacity at least2 and budget100, recourse cost is9 under every coupling. These are mechanism diagnostics, not enterprise effects or longer-horizon conclusions.

### Audit sequence and limitations

The [initial protocol](rolling_recourse_protocol.md) specified36 models,four methods and tie records before outputs. After observing18 apparent improvements and tied first actions, we added **exploratory** best-open-loop-tie and108 cross-model audits. These were not preregistered confirmation hypotheses. Model parameters and the original four methods' values were unchanged; we did not select new parameters to force positive results. Best-tie rolling is the fifth method.

This is not a full recourse replacement for the12-period,3-SKU environment or a history-fitted scenario tree. Policies know the constructed probability model but not the realized leaf; identical histories require identical actions. Perfect information remains a separate nondeployable bound. No LLM calls,BC/PPO training or new company data were used.

Next, implement longer history-consistent trees and conditional forecasts under the original event ordering. Compare equal-information optimization with robust tie treatment before any new confirmation paths or teacher selection. A meaningful action difference or an explicit computation deadline is still required. This check adds no thousand-task benchmark or training runs.

### Reproduction and evidence

The linked source,configuration,complete model/node/leaf-cost JSON and SHA256 manifest support full reconstruction. These readable mechanism-check files are separate from the 35 distribution evidence files now archived with explicit approval. `make verify-recourse` or `python -m semiconductor_logistics rolling-recourse verify` enumerates again,replays the old environment,cross-checks the old MILP,and compares all fields. `python -m semiconductor_logistics rolling-recourse run --output artifacts/recourse-new` generates into an empty directory without overwriting evidence. Tests cover exact probabilities,unresolved futures at the same history,lead times,pathwise carbon,optimal ties,and rejection after an action is altered and its hash recomputed.
