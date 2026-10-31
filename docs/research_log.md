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
| R12 | 历史外部仓库阅读（定位已在R32修正） | 阅读固定commit的架构、BC/PPO、策略输入、工具注册器、GAE、检查点、验证和发布结构；[历史入口](framework_comparison.md)与[原阅读文件身份](history/repository_reading.json) | 借鉴训练到证据的完整流程；保留对方公开规则审计的教训，不照搬其数字和结论 |
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

| R23 | 掩码与冻结成本势函数分别有什么贡献 | [2×2五种子协议](query_components_protocol.md)、[结果](query_components_results.md)；20组PPO、115,200 episodes、10,996更新、1,332开发评估；掩码成本基线与旧PPO兼容 | 去掩码增加拒绝及惩罚成本；有掩码时势函数未显示稳定收益。已查看36情境，仅开发诊断，原千题未重评 |

| R24 | 未知需求、预测误差与在途库存下强基线如何表现 | [双语协议](rolling_inventory_protocol.md)、[结果](rolling_inventory_results.md)、[44路径证据](../benchmark_results/rolling_inventory_development)；12校准、32开发、196轨迹、2,352期，全部再生成与重执行 | 情景MPC成本282.2406低于base-stock330.6219但排放更高；均值MPC总体更差。无新RL或正式最终集，先诊断碳配额和终端效应 |

| R25 | 碳分配、期末库存价值和情景数是否改变滚动结论 | [事前协议](rolling_sensitivity_protocol.md)、[双语结果](rolling_sensitivity_results.md)、[全组合证据](../benchmark_results/rolling_sensitivity_development)；24条新路径、3采样种子、2,304轨迹、27,648期 | 碳分配影响小；ρ=0.9净成本−13.5955中记账−15.2656、行为+1.6701；7→21情景成本−0.36%但方向跨种子不稳，暂不训练滚动BC/PPO |

| R26 | 自查执行进度并恢复GitHub同步 | [进度核查命令](../scripts/check_research_progress.py)核对15/15本地文件及源码；远端缺归档错误已定位；补交traces-05并保留剩余三份审批状态 | 新增[预测研究计划](rolling_forecast_plan.md)，未新增实验结果；CI仅主分支Push和PR触发，保留五项检查 |

| R27 | 完成已授权的公开归档 | 最后三份文件按原SHA256上传，[15份数据与manifest](rolling_sensitivity_publication.md)完整；保留逐期重执行和五项CI | 解除缺文件导致的artifact_coverage；算法、参数、结果及已有负结论不变，下一预测研究尚未运行 |

| R28 | 历史预测更快响应是否改善同一滚动决策器 | [事前协议](rolling_forecast_protocol.md)、[双语结果](rolling_forecast_results.md)、[证据](../benchmark_results/rolling_forecast_development)；12新校准+32新开发，352轨迹、4,224期，3采样种子；331测试及全部策略跨BLAS重执行通过 | 快速EWMA/季节短窗成本+7.19%/+8.48%，两个教师筛选失败；3条路径NLL改善但成本变差，保留原EWMA、不启动滚动BC/PPO |

| R29 | 完成已授权的预测证据公开归档 | 73份文件逐一匹配批准清单SHA256，补齐[归档](rolling_forecast_publication.md)，保留六项CI完整重执行 | 实验数值、模型选择与负结果不变；无需再次授权，合并验收仍以当前提交为准 |

## 本轮检查与下一项

BC的15项学习验证保留。此前281项测试保留；本轮新增9项统计与冻结验证，共290项测试（另新增6项跨平台验证测试后为296项）。PPO新增13项测试覆盖clipped policy/value有限差分、终态GAE隔离、实际成本反馈、共享BC起点、真实更新、划分隔离和重算哈希后的篡改拒绝。CI继续重放旧证据，并新增PPO完整采样/重训、180条策略评估及打包检查。

教师生成首次在训练情境12-6-1004触及连续碳超额变量的浮点容差，已按[数值修复记录](query_policy_protocol.md#运行前检查的数值修复)新增后端和回归测试。保持同一数据划分、旧源码与旧结果，不删除失败情境。

教师与轨迹最终使用明文JSONL，转存前后内容SHA256一致；重新执行全部离线检查。旧实验的压缩归档不变。

本轮新增10项组件测试，共306项通过；新增组件job重新拟合训练势函数、重训20组PPO、核对紧凑轨迹和1,332条结果。CI保留既有千题重放。

本轮没有新增模型API请求。五种子稳定性与两项组件消融已执行，主要方法与最终冻结方案已固定；正式千题评测已执行并保留负结果。掩码与成本势函数开发消融已完成；成功概率估计器、依赖锁与Release尚未完成，未知需求滚动基线已执行（R24），查询与滚动环境联训未执行。R10失败门槛保持原结论，R13是另一个计算替代问题。

滚动环境新增9项测试，共315项通过；本轮全部196轨迹重执行、轮子安装检查通过。CI将冻结千题拆为独立job，保留所有原检查，新增滚动复算job。

敏感性新增7项测试，共322项通过；wheel/CLI检查及Haswell分派下全部2,304轨迹重执行通过。旧实验文件保持原字节，新增独立敏感性重放CI。后续先验证历史信息预测与不确定性模型，并明确在线时限及同信息教师；不把记账返还或预知需求差距写成学习收益。

大文本上传未完成后，将本轮结果与计时表无损压缩；[迁移记录](../data_sources/rolling_sensitivity_packaging.json)验证解压内容逐字节一致，不改数值。压缩归档仍执行完整策略重放。

初次公开上传被自动审批阻止；当时先整理草稿，4份证据待批准。R26补交1份，R27在明确授权后补齐余下3份。[具体文件与摘要](rolling_sensitivity_publication.md)已列明，未绕过完整CI或把本地通过写成公开CI通过。

R28的9项新测试覆盖未来需求隔离、原预测兼容、校准划分、精确NLL、季节调整及重算哈希后的篡改拒绝。新增预测复算CI，保留原五项检查；API、旧模型和旧协议没有改变。

R28归档发布补充：新预测轨迹的公开上传被自动审批拒绝，要求针对新文件明确授权；已完成全部字段及物理台账审核。保留73份原证据文件与SHA256，见[清单](rolling_forecast_publication.md)，不重编码、拆分或跳过完整验收。

R29在获得针对全部73份文件的明确授权后补齐预测归档。此前R28的上传阻塞已解除；不把旧CI或本地成功替代当前提交的远端验收。

## 架构同步与分布预检 / Architecture update and distribution preflight

问题：固定均值预测后，历史误差的离散度估计是否改善滚动成本？读代码发现情景MPC无情景追索且损失按SKU相加，跨SKU整段路径重排不改变目标。因此将研究分成边际离散度比较与相关性不变性审计，先固定[协议](rolling_distribution_protocol.md)、`rolling_distribution/config.json`和实现；不把重排引起的多最优解差异解释为收益。烟雾测试只使用独立小数据；正式16/16/64划分尚未运行。来源、指标、质量教师条件及尚未指定的计算时限均在协议中记录。旧冻结记录不改。

Question: does past-error dispersion improve rolling cost with fixed means? Code inspection shows no scenario recourse and additive SKU losses, so whole-path cross-SKU permutations preserve the objective. Separate the marginal-dispersion comparison from the dependence-invariance audit. Fix the [protocol](rolling_distribution_protocol.md), config and implementation first; tie-breaking differences are not benefits. Smoke uses isolated small data; formal16/16/64 splits have not run. The protocol records sources, metrics, teacher screening and unspecified compute targets. Prior frozen records remain unchanged.

## 分布确认与学习判断 / Distribution confirmation and learning decision

正式运行前提交为`e71d68d7a822508e2b574c61d97b9b2d356a6d9c`。完成16拟合、16选参和64新确认路径，512轨迹/6,144期，35份证据。NB均值成本275.8435、Poisson270.2820（+2.06%），主配对区间跨零。NLL略好不等于库存成本更低；教师筛选失败。768次跨SKU整段路径重排审计验证可分目标不变性，5次首期动作变化来自多最优解，不报告相关性收益。

341测试、wheel安装检查及另一BLAS分派下的完整重执行通过，拟合/选参/预测/策略/物理台账和相关性审计均复算。新增第七项CI进行独立分布研究重执行。旧源码绑定协议和证据原字节保持不变。当前无部署时限和容许损失，不训练滚动BC/PPO；下一问题应先明确联合风险或追索是否属于业务目标。详见[结果](rolling_distribution_results.md)和[清单](../benchmark_results/rolling_distribution_confirmation/manifest.json)。

Formal execution follows commit `e71d68d7a822508e2b574c61d97b9b2d356a6d9c`. The study completes16 fitting,16 tuning and64 new confirmation paths,512 trajectories/6,144 periods and35 evidence files. NB/Poisson costs are275.8435/270.2820 (+2.06%); the primary paired interval crosses zero. Slightly better NLL does not imply lower inventory cost; teacher screening fails. The768 whole-path pairing audits verify separability; five changed first actions arise from multiple optima, not dependence value.

All341 tests, installed-wheel checks and complete replay under another BLAS dispatch pass. Replay covers fitting, selection, forecasts, policies, physical ledgers and dependence audits. A seventh CI job reexecutes this study. Prior source-bound protocols and evidence retain their bytes. No deployment deadline or tolerable loss exists, so rolling BC/PPO stays untrained. Define the business relevance of joint risk or recourse before the next protocol. See the linked results and manifest.

## 本轮公开归档阻塞 / Current publication block

本地全部检查完成。自动上传审批在压缩文件上拒绝，补做27文件的解压逐值允许列表检查后部分上传成功，但后续文件仍因新集合缺少明确公开授权而拒绝。不继续尝试绕过；完成代码、双语说明、逐文件SHA256清单和草稿PR。35文件待批准后补齐，七项CI验收前不合并。见[归档状态](rolling_distribution_publication.md)。

Local validation is complete. Automatic review rejected compressed files. A strict decompressed-value check allowed some uploads, but subsequent files were still rejected for lacking explicit publication approval for this new set. Do not try another bypass. Finish code, bilingual explanations, the per-file SHA256 list and a draft PR. Complete all 35 files after approval and require seven passing checks before merge. See the publication-status page.


## R31：进度复核与有限情景追索 / Progress review and finite recourse

复核PR #17提交`7ffc191`：六项原有CI成功，分布job因35份证据未获新批准而在归档完整性步骤停止；不重试被拒绝的上传，也不降低验收。旧协议、分布数据和原模型保留原字节。

先写[追索协议](rolling_recourse_protocol.md)，再运行36组有限概率模型，沿用原需求揭示顺序、路线提前期和物理重放。目标是检验相关性是否进入可用决策，而非开始训练。初始18组改善触发追加平局与跨模型审计；36组最好平局基线均追平追索，108次跨模型评估全部零遗憾。[完整结果](rolling_recourse_results.md)记录追加检查为探索性，不作事前假设声明。36次MILP核对、1,920次逐叶重放通过；不把这些重复计算计作独立测试任务。

工程检查补上`check_package.py`对`rolling_distribution`的漏项，并加入新模块与CLI检查。348项离线测试、安装后的wheel/CLI检查、不同BLAS分派下的追索完整重执行通过。`verify-recourse`加入原offline job，因此仍为七个job。归档、架构、双语说明、五阶段进度与复算命令一起更新；没有调用API或训练滚动BC/PPO。

Reviewed PR #17 at `7ffc191`: all six existing CI jobs pass; distribution verification stops at archive completeness because the new 35-file publication still requires approval. No rejected upload is retried and no acceptance check is weakened. Frozen protocols, distribution evidence and original models retain their bytes.

The [recourse protocol](rolling_recourse_protocol.md) preceded the 36 finite probability models, preserving demand revelation, route lead times and physical replay. The question is decision value of dependence, not training. The initial 18 improvements prompted additional exploratory tie and cross-model checks: best-open-loop-tie replanning matches recourse in every model, and all 108 cross-model evaluations have zero regret. The [results](rolling_recourse_results.md) identify these audits as post-output diagnostics. All 36 MILP comparisons and 1,920 policy/leaf replays pass; repeated calculations are not independent test tasks.

Fixed the omission of `rolling_distribution` from installed-wheel verification and added the new module/CLI. All 348 offline tests, installed-wheel checks and complete recourse replay under another BLAS dispatch pass. `verify-recourse` runs inside the existing offline job, retaining seven jobs. Evidence, architecture, bilingual explanations, the five-stage ledger and reproduction commands are updated together. No model API calls or rolling BC/PPO training were performed.


## R32：完成授权归档并纠正研究定位 / Authorized archive and research framing

用户明确批准固定清单中的35份分布证据按SHA256公开上传。全部文件与提交`7ffc191`的清单逐一匹配，保留12个已创建的文件对象，补齐其余23个并归入PR；不重生成数据、不重跑API、不改变任何模型结果。清单总计3,887,809字节，旧缺文件CI失败记录保留，当前提交须通过完整七项检查。

此前将“匹配难度与完成度”写成逐项框架映射，偏离了用户意图。本轮新增[本项目研究设计](research_design.md)和[来源历史说明](source_history.md)，首页改用独立的问题与验收标准；旧逐项对照退出当前设计，原阅读清单移入历史目录。冻结BC协议及既有归属保持原字节，既不把通用方法当作原创，也不声称历史上从未受过参考影响。

有限检查：本项目132份Python文件与历史固定提交的97份Python文件无整文件身份匹配，也无该包导入；详见[检查范围和限制](../data_sources/code_origin_check.json)。这不是局部复制或思想独立性的全面鉴定。研究路线仍围绕物流信息价值、资源耦合和预测误差，后续模块按实际研究缺口决定。本轮不新增训练或性能结果。

The user explicitly approved public upload of the 35 distribution evidence files by the fixed SHA256 manifest at `7ffc191`. Each file matches: retain 12 existing Git objects, complete the other 23 and attach the entire archive to the PR. No data regeneration, API requests or result changes. Total size is 3,887,809 bytes. Historical missing-file CI failures remain; the current commit must pass all seven complete checks.

Earlier documentation turned comparable difficulty/completeness into a module-by-module framework mapping, contrary to the user's intent. This update introduces [project-specific research design](research_design.md) and [source history](source_history.md); current entry points use our questions and acceptance criteria. The comparison is retired and the reading inventory moves to history. Frozen BC protocols and actual attribution retain their bytes. Standard methods are not claimed as inventions, and historical conceptual influence is not denied.

A limited check finds no exact whole-file identities between 132 project Python files and 97 files at the historically reviewed commit, and no imports of that package. The [scope and limitations](../data_sources/code_origin_check.json) explicitly exclude comprehensive partial-copy or intellectual-independence judgments. Work remains centered on logistics information value, resource coupling and forecast error. Further modules follow research gaps. This change adds no training or performance claims.
