# 研究进度

| 步骤 | 已完成 | 下一项验收 |
|---|---|---|
| 1. 独立文本与固定模型 | 合成400条对照及复测归档；真实16条澄清、8条数量探索已运行，数量模型7/8、规则6/8与助手参考一致 | 不再要求填写人工意见；保留未进行人工复核的范围，内部路线更新仍未验证 |
| 2. 工具环境与强规则 | 多SKU、共享容量、有价查询及同求解预算对照；54情境、1,080运行、完整概率树与调用台账复算 | 保留原失败筛选；研究质量与计算量的取舍，不靠增加相似题数制造学习价值 |
| 3. BC/PPO | 5个训练种子各自重训BC，共15套PPO训练；完整PPO、无熵项、λ=1及最后检查点对照 | 开发稳定条件未通过：2个种子改善、2个变差、1个持平；保持原主要方法和负结果 |
| 4. 约1,000题、5种子、消融 | 1,000个不同合成情境、5训练种子、两项优化消融、最后检查点诊断、27,000评估和配对区间已完成；任务与模型在输出前提交冻结 | 未证实PPO稳定收益：BC/PPO遗憾3.1179%/3.1477%，差值区间跨零；掩码×成本势函数的五种子开发对照另已完成；组件尚无新留出确认，正式Release未完成 |
| 5. 未知需求与滚动决策 | 独立环境、12校准+32开发基线已复算；另完成24条新开发路径的碳分配/期末价值/情景数全组合，共2,304轨迹；另完成12校准+32新开发的预测对照、352轨迹 | 快速EWMA/季节短窗成本+7.19%/+8.48%，新教师筛选均失败；保留原EWMA，先确认预测分布与部署需求，暂不训练滚动RL |

## 本轮结果

[BC开发实验](query_policy_results.md)按独立的[计算替代协议](query_policy_protocol.md)运行，并未改写此前[预算筛选](query_budget_results.md)的失败结果。BC每条实际执行路径只需一次最终MILP；36个开发评估情境平均遗憾2.0833%，两步搜索约16.15次、0.3140%，迭代DP约36.51次、0.0064%。调用减少伴随质量损失，不等于已获得端到端加速或RL收益。

[误差分解](../benchmark_results/query_bc_diagnostic/errors.json)逐情境核对策略损失的来源，不必要查询占额外成本约一半。这36个情境已经被观察，不再作为未来未查看的正式测试集。

随后按[同起点PPO协议](query_ppo_protocol.md)运行40轮成本奖励训练，复用72/18训练验证情境，在另外36个情境评估；[结果](query_ppo_results.md)为BC/PPO平均遗憾2.6486%/1.9416%，6个改善、30个持平，两者每路径均一次最终MILP。两步搜索为0.7000%、约17.03次；迭代DP为0.0423%、约40.59次。保存5,760个采样episode、15,397个动作、576次更新和检查点重训证据；单种子结果不作正式显著性声明。

[五种子开发检查](query_study_development_results.md)已完成：BC/PPO平均遗憾2.5947%/2.5362%，差值−0.0585个百分点，95%配对区间[−0.4552, +0.3224]，描述性稳定条件失败。15套PPO实际完成86,400个episode与8,984次更新；结果不支持把此前单种子提升称为稳定收益。[最终千题评测](query_final_results.md)已按[既定协议](query_study_protocol.md)执行。BC/PPO平均遗憾3.1179%/3.1477%，PPO−BC为+0.0298个百分点，近似95%区间[−0.1817,+0.2540]。各训练种子3改善、1变差、1持平；当前证据不支持稳定的PPO增益。两个强搜索分别为0.6309%和0.0528%。

跨平台重放补充见[证据说明](query_study_evidence.md#跨平台训练重放)：中间检查点SHA绑定完整参数，原数值容差下核对重新训练结果，保留原严格哈希验证器。冻结证据未改写。

[组件对照](query_components_results.md)新增20组PPO、1,332次开发评估。去掩码使含惩罚遗憾从2.5362%升至4.6288%，拒绝概率14.3215%；有掩码时势函数为2.7956%，未见稳定收益。复用36个开发情境，不改千题正式结果。随后完成[滚动库存基线](rolling_inventory_results.md)：情景MPC/base-stock成本282.2406/330.6219，但排放更高；均值MPC总体更差。新增[三因素敏感性](rolling_sensitivity_results.md)：碳分配平均影响小；期末价值净成本下降主要来自记账；1→7情景成本降37.48%，7→21仅降0.36%且种子方向不一。先验证历史信息预测及教师，不开始滚动BC/PPO。

## 框架完成度

已按参考仓库的公开输入、动态候选BC、训练检查点、逐步证据和重执行方式建立[逐项对照](framework_comparison.md)。本轮补齐成本PPO/GAE，已接通多种子与两项优化消融；新增掩码×成本势函数开发对照及20组PPO重放；成功概率估计器未实现，完整依赖锁和发布验收仍待补齐。

## 证据索引

- [合成模型对照](results/api_test.md)：400个不同案例，两次运行不是800个不同案例。
- [真实澄清](data/real_notices.md)及[真实数量](results/notice_facts_api.md)：保留助手参考和原始响应，未进行人工复核。
- [信息成本](decision_environment.md)、[共享容量](coupled_environment.md)、[规模](decision_scale.md)及[预算](query_budget_results.md)：保留强规则与失败筛选。
- [BC结果](query_policy_results.md)、[代码](../query_policy)、[证据包](../benchmark_results/query_bc_development)：教师、训练、评估和复算。
- [PPO结果](query_ppo_results.md)、[代码](../query_ppo)、[证据包](../benchmark_results/query_ppo_development)：同一起点、真实成本训练、新情境比较和完整重执行。
- [多种子开发结果](query_study_development_results.md)、[协议](query_study_protocol.md)、[复现](query_study_evidence.md)：五种子、固定变体、配对统计与最终冻结入口。
- [千题最终结果](query_final_results.md)、[冻结任务](../benchmarks/query_final_v1)、[原始证据](../benchmark_results/query_final_v1)：同分布合成最终检验，保留负结果。
- [研究记录](research_log.md)、[资料依据](research_basis.md)、[框架阅读来源](../data_sources/framework_reference.json)。

新增[掩码与成本势函数协议](query_components_protocol.md)、[结果与复现](query_components_results.md)和[原始证据](../benchmark_results/query_components_development)。

当前只需按[操作说明](manual_steps.md)合并通过检查的代码，不需重跑API或填写人工意见。

## 文档语言

仓库首页[README](../README.md)使用英文，保留[简体中文版本](../README.zh-CN.md)及双向切换链接。详细说明按[文档交付计划](documentation_plan.md)补齐：开头注明中英文版本，中文在前、英文在后。新增PPO协议和结果已经双语，历史详细说明在最终交付前完成；冻结协议保留原文件并提供双语配套说明。

新增[滚动协议](rolling_inventory_protocol.md)、[基线结果](rolling_inventory_results.md)及[逐期证据](../benchmark_results/rolling_inventory_development)。旧固定订单研究继续保持原范围，不将未知需求结果追记到旧实验。

新增[敏感性协议](rolling_sensitivity_protocol.md)、[双语结果](rolling_sensitivity_results.md)及[全组合证据](../benchmark_results/rolling_sensitivity_development)。24条不同路径、3个采样重复、2,304轨迹，不能称为72条独立路径。

**公开归档已补齐：**维护者明确授权后，最后3份文件按原SHA256上传；15份数据文件与manifest齐全。合并验收使用当前提交的五项CI，详见[归档与验收](rolling_sensitivity_publication.md)。

## 进度核查与下一步

运行 `python -m scripts.check_research_progress` 核对已保存实验计数、敏感性15份及预测研究72份数据/运行文件的摘要和源码身份。它不会重新训练或调用API，也不代表远端CI；完整策略重执行分别使用 `make verify-sensitivity` 和 `make verify-forecast`。

PR #15已合并。补齐归档后的[当前提交检查](https://github.com/nomoretry/semiconductor-logistics-decarbonization/actions/runs/41125643556)五项全部通过；此前`artifact_coverage`失败记录保留，未删除检查。

[预测研究](rolling_forecast_results.md)已执行，协议和配置先于实验提交。新12校准+32开发路径，352轨迹、4,224期，331项测试、全部轨迹跨BLAS复算通过；GitHub本轮新增forecast-study，保留此前五项CI。两种新预测器的成本分别增加7.19%/8.48%，三个采样种子和四种过程方向均一致；短窗3条路径出现预测NLL改善而成本变差。两个描述性教师条件均失败，当前没有训练新的滚动策略。

下一项先检查需求分布模型或更强收缩预测，使用另行登记的新路径确认；同时明确在线时限和可接受质量损失。不能把预知需求下界差距称为可被学习回收的收益，也不能把当前32条已查看路径重新称作未知测试。

本轮公开归档已补齐：维护者明确批准全部73份证据按清单SHA256公开上传，原字节与结果不变，见[归档验收](rolling_forecast_publication.md)。当前提交须通过全部六项CI后再合并，旧缺文件失败记录保留。
