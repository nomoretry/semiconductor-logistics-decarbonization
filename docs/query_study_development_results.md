# 多种子开发结果 / Multi-seed development results

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

按[固定协议](query_study_protocol.md)，从头训练5套BC，并从每个种子自己的BC起点训练完整PPO、无熵项PPO及λ=1 PPO，共15套PPO训练。它们使用相同72个训练和18个验证情境；开发诊断复用此前已查看的36个情境，不是新的留出集。

15套PPO合计86,400个episode、236,185个动作、8,984次更新。每个变体保留所选和最后检查点；4套训练的验证选模回退到BC起点，实际更新记录仍保留。最终评估另计不同任务数，不能把episode和动作当作独立题目。

| Method | Mean regret | Worst regret | Mean queries | Expected MILP calls |
|---|---:|---:|---:|---:|
| BC | 2.5947% | 11.1829% | 1.6732 | 1.0000 |
| PPO | 2.5362% | 13.7715% | 1.6935 | 1.0000 |
| PPO, entropy=0 | 2.4998% | 11.1829% | 1.6606 | 1.0000 |
| PPO, λ=1 | 2.6071% | 11.1829% | 1.6788 | 1.0000 |
| PPO, last checkpoint | 2.4710% | 13.7715% | 1.6782 | 1.0000 |
| Two-step, 13 | 0.7000% | 10.5648% | 1.5096 | 17.0285 |
| Iterative DP, 65 | 0.0423% | 1.4002% | 1.4641 | 40.5944 |

主要比较为完整PPO减BC：平均遗憾差 **−0.0585个百分点**，配对种子×分层情境bootstrap的95%区间为 **[−0.4552, +0.3224]个百分点**。五个种子中2个改善、2个变差、1个持平，未通过协议中的描述性稳定条件。此前种子17的改善没有稳定地扩展到全部训练种子。

| Seed | BC mean regret | PPO mean regret | PPO − BC (pp) |
|---|---:|---:|---:|
| 17 | 2.6486% | 1.9416% | -0.7070 |
| 29 | 2.6406% | 2.7026% | +0.0621 |
| 43 | 2.6406% | 2.6406% | +0.0000 |
| 71 | 2.5096% | 2.3906% | -0.1190 |
| 97 | 2.5343% | 3.0059% | +0.4716 |

无熵项相对完整PPO的平均差为−0.0364个百分点，95%区间[−0.4313, +0.3773]；λ=1为+0.0709个百分点，区间[−0.3038, +0.4600]；使用最后检查点为−0.0652个百分点，区间[−0.4928, +0.3761]。这些探索性比较均包含零，不能给出明确的组件优劣结论。强搜索仍有较低遗憾，但需要更多线上求解。

开发评估总计972条：5种学习检查点×5种子×36情境=900条，两个确定性搜索各36条。相同动作树仅在文件存储层去重为127棵，各策略实际独立执行。原始结果、训练、检查点和采样记录见[证据包](../benchmark_results/query_study_development)。

本阶段仍按预先协议推进1,000个新合成情境的冻结与最终评测。主要方法固定为完整PPO，开发结果更好的消融不会被替换为新的主要方法。最终检验允许得出没有明确收益的结论，不删除失败种子。复现与证据格式见[说明](query_study_evidence.md)。

## English

Under the [fixed protocol](query_study_protocol.md), train five BC models from their own initializations, then train full PPO, PPO without entropy and PPO with λ=1 from each seed's BC actor: 15 PPO training runs. All use the same 72 training and 18 validation contexts. Development diagnostics reuse the already inspected 36 contexts and are not a new holdout.

The PPO runs total 86,400 episodes, 236,185 actions and 8,984 updates. Selected and last checkpoints are retained for every run. Four selections fall back to the BC start; their actual training updates remain archived. Episodes and actions are not distinct tasks.

| Method | Mean regret | Worst regret | Mean queries | Expected MILP calls |
|---|---:|---:|---:|---:|
| BC | 2.5947% | 11.1829% | 1.6732 | 1.0000 |
| PPO | 2.5362% | 13.7715% | 1.6935 | 1.0000 |
| PPO, entropy=0 | 2.4998% | 11.1829% | 1.6606 | 1.0000 |
| PPO, λ=1 | 2.6071% | 11.1829% | 1.6788 | 1.0000 |
| PPO, last checkpoint | 2.4710% | 13.7715% | 1.6782 | 1.0000 |
| Two-step, 13 | 0.7000% | 10.5648% | 1.5096 | 17.0285 |
| Iterative DP, 65 | 0.0423% | 1.4002% | 1.4641 | 40.5944 |

The primary full-PPO-minus-BC mean-regret difference is **−0.0585 percentage points**, with a paired seed-by-stratified-context bootstrap 95% interval of **[−0.4552, +0.3224] percentage points**. Two seeds improve, two worsen and one ties. The predefined descriptive stability condition fails. Seed 17's improvement does not consistently extend across training seeds.

| Seed | BC mean regret | PPO mean regret | PPO − BC (pp) |
|---|---:|---:|---:|
| 17 | 2.6486% | 1.9416% | -0.7070 |
| 29 | 2.6406% | 2.7026% | +0.0621 |
| 43 | 2.6406% | 2.6406% | +0.0000 |
| 71 | 2.5096% | 2.3906% | -0.1190 |
| 97 | 2.5343% | 3.0059% | +0.4716 |

Removing entropy differs from full PPO by −0.0364 percentage points, with interval [−0.4313, +0.3773]. Setting λ=1 differs by +0.0709, interval [−0.3038, +0.4600]. Using the last checkpoint differs by −0.0652, interval [−0.4928, +0.3761]. These exploratory intervals all include zero and do not establish component superiority. Strong search retains lower regret at greater online solver cost.

Development evaluation contains 972 outcomes: five learned checkpoint types × five seeds × 36 contexts = 900, plus 36 cases for each deterministic search. Storage deduplicates identical action trees into 127 trees after independent execution. See the [evidence bundle](../benchmark_results/query_study_development) for raw outcomes, training, checkpoints and sampled records.

Proceed with the previously specified freeze and final evaluation of 1,000 new synthetic contexts. Full PPO remains the primary method; a better development ablation does not replace it. A negative final conclusion is permitted, and failing seeds are retained. See [reproduction and evidence formats](query_study_evidence.md).
