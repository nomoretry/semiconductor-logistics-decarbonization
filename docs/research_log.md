# 研究记录

每项记录保留问题、修改、验证与结论。完整五步状态见[进度](progress.md)。后续每个实质修改随代码一起更新本文件，不覆盖旧实验。

| 记录 | 问题与修改 | 验证/结果 | 结论 |
|---|---|---|---|
| R01 | 固定模型与规则在独立合成文本上是否有差异 | [400条正式对照](results/api_test.md)，两次模型运行均400/400，规则204/400；逐条复算 | 合成任务有差异；第二轮不是新增400条独立案例 |
| R02 | 真实材料能否直接修改内部提前期 | [16条来源](data/real_notices.md)，两个助手审核；[真实API归档](../benchmark_results/real_notice_api/provenance.json)保留11个原始文件与下载包哈希，离线重评分一致 | 模型16/16，始终澄清16/16；无真实更新正例，人工复核未完成 |
| R03 | 固定工具流程是否存在决策价值 | 原200组工作流及[600组信息成本配置](decision_environment.md) | 原流程过易；费用环境有后果，但强适应性规则接近最优，未训练 |
| R04 | 文献与企业披露是否支持下一步问题 | [资料依据](research_basis.md)、[来源清单](../data_sources/research_sources.json)；Undermind检索，1篇全文定向阅读、2篇摘要，核对官方披露 | 支持研究等待/加急与有限预算信息选择；不支持套用企业参数或保证RL收益 |
| R05 | 多SKU、共享路线容量和预算是否改变策略 | [Python环境与120情境审计](coupled_environment.md)，720条运行、全世界期望核对、反事实与重放 | 容量和预算确有影响；两步前瞻与精确DP一致，学习条件仍未满足 |
| R06 | 全澄清集合如何推进真实抽取研究 | [两层评测协议](real_fact_protocol.md)，盘点5条数量正例与11条无目标数量材料 | 下一版先评分来源事实；内部更新需要另外提供显式映射。新字段API未运行 |
| R07 | 能否从真实材料抽取有证据的运输数量 | [独立包与冻结身份](../notice_facts/freeze.json)、[24条分组数据](../benchmarks/notice_facts_v1/dataset.json)、[逐条离线结果](../benchmark_results/notice_facts_development/offline.json)、[审核表](../reviews/notice_facts_v1/review.md) | 原16条用于开发；8份新材料规则6/8、空输出2/8。字段API待手动运行，全部人工审核pending；不是盲测 |
| R08 | 更大的SKU/扰动规模是否留下规划差距 | [18个开发任务、72条策略运行](decision_scale.md)，整数分配、跨路线容量池、预算查询、期望值与物理轨迹复算 | 单步VOI平均差距0.5378%，两步0.0811%；精确DP仍较快，尚不构成训练必要性证据 |
| R09 | 固定模型在新真实数量子任务上的实际表现 | [8次API结果](results/notice_facts_api.md)、[9个原始文件及来源清单](../benchmark_results/notice_facts_api/provenance.json)；下载包哈希核对、原响应和冻结规则离线复算一致 | 模型7/8、规则6/8；E06把停航三周抽成延误三周。参考标签待人工审核，未据此修改提示词或重跑 |
| R10 | 同求解调用上限下，强规划还留下多少差距 | [事前协议](query_budget_protocol.md)、[完整结果](query_budget_results.md)；54情境×4方法×5预算，全部策略分支、整条路径计算量与物理计划复算 | 主预算最强方法平均差距0.6253%，新36情境0.6836%；预设BC筛选未通过，未训练 |
| R11 | 平均成本是否掩盖少数严重损失 | [事后最差案例](../benchmark_results/query_budget_diagnostic/worst_case.json)，条件期望成本差×分支概率精确解释19.48125的任务损失 | 昂贵单次查询耗尽后续信息预算，便宜查询组合可更优；局部取舍成立，不把案例诊断包装成留出结论 |
| R12 | 如何接近参考项目的工程与研究完成度 | 阅读固定commit的架构、BC/PPO、策略输入、工具注册器、GAE、检查点、验证和发布结构；[逐项对照](framework_comparison.md)与[文件身份](../data_sources/framework_reference.json) | 借鉴训练到证据的完整流程；保留对方公开规则审计的教训，不照搬其数字和结论 |
| R13 | BC能否减少在线查询规划的求解次数 | [独立协议](query_policy_protocol.md)、[训练与结果](query_policy_results.md)、[证据包](../benchmark_results/query_bc_development)；72/18/36情境，1训练种子，880次更新，教师重算/重训/检查点重执行 | BC遗憾2.0833%、一次最终MILP；两步搜索0.3140%、约16.15次。减少在线求解但质量未达到强搜索，不宣称PPO收益 |
| R14 | BC损失主要来自何种决策 | [36情境逐节点分解](../benchmark_results/query_bc_diagnostic/errors.json)；每题占用概率加权的教师动作差精确解释策略损失 | 多余查询成本26.41785、过早停止14.328875、路线选择12.0948625；事后诊断，不改本轮模型 |
| R15 | 人工复核是否阻塞研究 | 维护者明确选择不填写人工意见；更新[操作说明](manual_steps.md)与当前状态，冻结数据及旧审核表不变 | 不代填人工意见；真实评测保留未复核探索范围，其他环境与策略研究继续 |
| R16 | 提供英文仓库首页 | 将README整理为英文，保留[中文版本](../README.zh-CN.md)与双向导航；核对命令、链接和实验数字 | 文档更新；不修改算法、原始证据或研究阶段，不新增API调用 |

| R17 | 成本奖励能否改进同一BC起点的查询策略 | [双语协议](query_ppo_protocol.md)、[结果](query_ppo_results.md)、[证据包](../benchmark_results/query_ppo_development)；40轮、5,760 episodes、15,397动作、576更新，36新情境 | BC/PPO平均遗憾2.6486%/1.9416%；6改善、30持平；仍落后于强搜索，仅单种子开发结论 |
| R18 | 最终详细说明需要中英文版本 | [文档交付计划](documentation_plan.md)与AGENTS规范；新增PPO协议/结果已中文在前、英文在后 | 最终补齐历史说明；冻结协议用双语配套说明，保留原哈希记录 |

| R19 | 单种子PPO改善能否跨训练种子保持 | [五种子协议](query_study_protocol.md)、[开发结果](query_study_development_results.md)和[证据](../benchmark_results/query_study_development)；5套BC、15套PPO、8,984更新、972评估 | 稳定条件失败，差值−0.0585pp、95%区间[−0.4552,+0.3224]；消融未见明确优势，保留全部种子 |
| R20 | 最终任务如何避免开发集重复使用 | [固定划分与模型冻结入口](query_study_evidence.md)；1,000个新情境，模型/训练/源码身份绑定 | 正式输出前提交冻结版本，再评估；[预检修正](../data_sources/query_study_preflight_correction.json)将小型验收与最终随机流隔离，不改训练/变体 |

| R21 | 冻结千题是否支持稳定的PPO增益 | [最终结果](query_final_results.md)、[冻结提交](https://github.com/nomoretry/semiconductor-logistics-decarbonization/commit/09eea0ec98b54b13ca504ad3533480b819a8a1ca)与[27,000条评估](../benchmark_results/query_final_v1)；1,000不同情境、5训练种子 | 未证实：BC/PPO遗憾3.1179%/3.1477%，差值+0.0298pp，近似95%区间[−0.1817,+0.2540]；不替换主方法、种子或测试集 |

| R22 | 相同依赖版本在不同BLAS分派下能否重放 | [配套参数与验证器](query_study_evidence.md#跨平台训练重放)保留每个训练检查点完整系数；旧严格重放通过后生成，逐系数比较并保留原归档哈希 | 中间SHA可因舍入变化；不跳过参数、动作、奖励或选模检查，不改冻结任务和结果 |

## 本轮检查与下一项

BC的15项学习验证保留。此前281项测试保留；本轮新增9项统计与冻结验证，共290项测试（另新增6项跨平台验证测试后为296项）。PPO新增13项测试覆盖clipped policy/value有限差分、终态GAE隔离、实际成本反馈、共享BC起点、真实更新、划分隔离和重算哈希后的篡改拒绝。CI继续重放旧证据，并新增PPO完整采样/重训、180条策略评估及打包检查。

教师生成首次在训练情境12-6-1004触及连续碳超额变量的浮点容差，已按[数值修复记录](query_policy_protocol.md#运行前检查的数值修复)新增后端和回归测试。保持同一数据划分、旧源码与旧结果，不删除失败情境。

教师与轨迹最终使用明文JSONL，转存前后内容SHA256一致；重新执行全部离线检查。旧实验的压缩归档不变。

本轮没有新增模型API请求。五种子稳定性与两项组件消融已执行，主要方法与最终冻结方案已固定；正式千题评测已执行并保留负结果。进度奖励、Action Mask等其他消融、依赖锁与Release尚未完成；未知需求滚动决策未执行。R10失败门槛保持原结论，R13是另一个计算替代问题。
