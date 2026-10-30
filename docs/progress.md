# 研究进度

| 步骤 | 已完成 | 下一项验收 |
|---|---|---|
| 1. 独立文本与固定模型 | 合成400条对照及复测归档；真实16条澄清、8条数量探索已运行，数量模型7/8、规则6/8与助手参考一致 | 不再要求填写人工意见；保留未进行人工复核的范围，内部路线更新仍未验证 |
| 2. 工具环境与强规则 | 多SKU、共享容量、有价查询及同求解预算对照；54情境、1,080运行、完整概率树与调用台账复算 | 保留原失败筛选；研究质量与计算量的取舍，不靠增加相似题数制造学习价值 |
| 3. BC/PPO | 5个训练种子各自重训BC，共15套PPO训练；完整PPO、无熵项、λ=1及最后检查点对照 | 开发稳定条件未通过：2个种子改善、2个变差、1个持平；保持原主要方法和负结果 |
| 4. 约1,000题、5种子、消融 | 五种子与优化组件消融已完成开发检查，种子×情境配对统计已接通；千题冻结方案已固定 | 先提交冻结任务与模型身份，再运行最终评测；进度奖励和Action Mask消融、正式Release尚未完成 |
| 5. 未知需求与滚动决策 | 未开始；当前订单已知、路线先验固定 | 前述策略研究之后加入逐期需求揭示、预测误差与在途状态演化 |

## 本轮结果

[BC开发实验](query_policy_results.md)按独立的[计算替代协议](query_policy_protocol.md)运行，并未改写此前[预算筛选](query_budget_results.md)的失败结果。BC每条实际执行路径只需一次最终MILP；36个开发评估情境平均遗憾2.0833%，两步搜索约16.15次、0.3140%，迭代DP约36.51次、0.0064%。调用减少伴随质量损失，不等于已获得端到端加速或RL收益。

[误差分解](../benchmark_results/query_bc_diagnostic/errors.json)逐情境核对策略损失的来源，不必要查询占额外成本约一半。这36个情境已经被观察，不再作为未来未查看的正式测试集。

随后按[同起点PPO协议](query_ppo_protocol.md)运行40轮成本奖励训练，复用72/18训练验证情境，在另外36个情境评估；[结果](query_ppo_results.md)为BC/PPO平均遗憾2.6486%/1.9416%，6个改善、30个持平，两者每路径均一次最终MILP。两步搜索为0.7000%、约17.03次；迭代DP为0.0423%、约40.59次。保存5,760个采样episode、15,397个动作、576次更新和检查点重训证据；单种子结果不作正式显著性声明。

[五种子开发检查](query_study_development_results.md)已完成：BC/PPO平均遗憾2.5947%/2.5362%，差值−0.0585个百分点，95%配对区间[−0.4552, +0.3224]，描述性稳定条件失败。15套PPO实际完成86,400个episode与8,984次更新；结果不支持把此前单种子提升称为稳定收益。正式测试仍按[既定协议](query_study_protocol.md)执行。

## 框架完成度

已按参考仓库的公开输入、动态候选BC、训练检查点、逐步证据和重执行方式建立[逐项对照](framework_comparison.md)。本轮补齐成本PPO/GAE，已接通多种子与两项优化消融；仍缺进度势函数、Action Mask等其他消融、完整依赖锁和发布验收。

## 证据索引

- [合成模型对照](results/api_test.md)：400个不同案例，两次运行不是800个不同案例。
- [真实澄清](data/real_notices.md)及[真实数量](results/notice_facts_api.md)：保留助手参考和原始响应，未进行人工复核。
- [信息成本](decision_environment.md)、[共享容量](coupled_environment.md)、[规模](decision_scale.md)及[预算](query_budget_results.md)：保留强规则与失败筛选。
- [BC结果](query_policy_results.md)、[代码](../query_policy)、[证据包](../benchmark_results/query_bc_development)：教师、训练、评估和复算。
- [PPO结果](query_ppo_results.md)、[代码](../query_ppo)、[证据包](../benchmark_results/query_ppo_development)：同一起点、真实成本训练、新情境比较和完整重执行。
- [多种子开发结果](query_study_development_results.md)、[协议](query_study_protocol.md)、[复现](query_study_evidence.md)：五种子、固定变体、配对统计与最终冻结入口。
- [研究记录](research_log.md)、[资料依据](research_basis.md)、[框架阅读来源](../data_sources/framework_reference.json)。

当前只需按[操作说明](manual_steps.md)合并通过检查的代码，不需重跑API或填写人工意见。

## 文档语言

仓库首页[README](../README.md)使用英文，保留[简体中文版本](../README.zh-CN.md)及双向切换链接。详细说明按[文档交付计划](documentation_plan.md)补齐：开头注明中英文版本，中文在前、英文在后。新增PPO协议和结果已经双语，历史详细说明在最终交付前完成；冻结协议保留原文件并提供双语配套说明。
