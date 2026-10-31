# Semiconductor Logistics Decarbonization

[研究说明 / Research guide](docs/research_guide.md) · [系统结构 / Architecture](docs/architecture.md)
[English](README.md) | 简体中文

[![Python](https://img.shields.io/badge/Python-3.12-3776AB.svg)](https://www.python.org/)

面向半导体备件与成品物流的库存—运输联合优化框架。使用 SciPy/HiGHS 求解带交付、运输容量和碳预算约束的整数规划；提供固定 LLM 公告抽取评测、多步工具环境、查询策略行为克隆（BC）和结果复算。

两个案例共享求解器，分别保留业务约束：[ASML 备件物流](asml/README.md)与 [Marvell 成品物流](marvell/README.md)。

[分布确认研究](docs/rolling_distribution_results.md)固定均值预测和MPC，新增16拟合、16选参、64确认路径，共512轨迹。残差NB/Poisson成本275.8435/270.2820，差值区间跨零，教师筛选失败。768次审计验证：当前可分目标与共享计划结构无法利用跨SKU完整路径的配对信息。尚未训练滚动BC/PPO；公告抽取、查询学习和滚动控制仍分别验证。

本轮分布研究的35份证据尚待公开批准，PR保持草稿；[清单与归档状态](docs/rolling_distribution_publication.md)。

## 设计与实验

| 模块 | 实现 | 实验与输出 |
|---|---|---|
| 库存与运输 | 整数发货、在途库存、到仓库存、积压守恒 | 60 份合成订单实例、360 次策略求解 |
| 成本与碳预算 | 运费、资金占用、仓储成本和物流排放；三档碳约束 | 成本—排放对照、339 份可行计划、不可行实例 |
| 公告抽取 | 固定提示词、JSON Schema、冻结规则和固定模型配置 | 120 条开发文本、400 条合成留出文本 |
| LLM API | Responses API、调用预算、请求缓存和原始响应记录 | 400 条合成留出文本，主运行与复测均 400/400 |
| 多步工具环境 | 检查公告、抽取、校验、读取状态、求解、审计和提交 | 200 组开发任务，逐步轨迹与确定性重放 |
| 共享容量与查询 | 3–4个SKU、空海运分配、联合扰动先验、共用查询预算 | 120组开发情境、6种方法、720条运行及重放 |
| 真实数量抽取 | 总时长/增减量、原单位、区间与限定语、原文证据 | 16条开发、8份新来源；模型7/8、规则6/8，未进行人工复核 |
| 查询规模审计 | 4–12个SKU、2–6个扰动、跨路线容量池、整数规划 | 18个开发任务、72条运行；单步/两步平均成本差距0.5378%/0.0811% |
| 同计算预算对照 | 每次决策MILP限额、中断回退、分支缓存隔离、完整路径记账 | 54个开发情境、1,080条运行；主预算最强方法平均差距0.6253%，尾部15.9217% |
| 查询策略BC | 公开候选特征、多正例模仿、验证集选模、检查点重执行 | 72/18/36个训练/验证/开发评估情境；BC平均遗憾2.0833%，每任务一次最终MILP |
| 查询策略PPO | 同一BC起点、成本奖励、GAE、策略/价值裁剪与验证选模 | 1训练种子、36个新开发情境；BC/PPO平均遗憾2.6486%/1.9416% |
| 五种子冻结评测 | 独立训练BC起点；PPO、熵项和GAE衰减消融；种子/情境配对区间 | 1,000冻结情境、27,000评估；BC/PPO遗憾3.1179%/3.1477%，未证实稳定PPO增益 |
| 掩码与成本势函数 | 同一BC起点、2×2设计、仅训练集拟合并冻结势函数 | 五种子、20组PPO、1,332开发评估；去掩码增加拒绝，有掩码时塑形未见稳定收益 |
| 结果验证 | 输入与源码哈希、逐条预测复算、物流计划与训练重放 | 离线验证命令与自动测试 |

原工具环境的固定工作流在开发任务中完成了 127 份可行计划和 73 次正确澄清交接。新增[信息成本环境](docs/decision_environment.md)检验查询、澄清和求解选择的实际代价；训练条件与后续工作见[进度记录](docs/progress.md)。

[查询策略BC](docs/query_policy_results.md)已完成训练与开发评估：只用一次最终运输求解，平均成本遗憾2.0833%；预算13的两步搜索约需16.15次求解，遗憾0.3140%。模型降低了在线求解量，但尚未达到强搜索的决策质量。随后完成了[同起点PPO开发实验](docs/query_ppo_results.md)：36个新情境上，平均遗憾从BC的2.6486%降到1.9416%，每条路径仍只需一次最终MILP。6个情境改善、30个持平；单种子结果仍未达到强搜索质量。随后完成[五种子、冻结千题评测](docs/query_final_results.md)：BC/PPO平均遗憾3.1179%/3.1477%，PPO−BC差值+0.0298个百分点，近似95%配对区间[−0.1817,+0.2540]，未证实稳定PPO增益。两种强搜索的成本仍更低，负结果完整保留。

[组件对照](docs/query_components_results.md)已完成：在36个已查看开发情境上，去掩码使含拒绝惩罚的遗憾从2.5362%升至4.6288%，拒绝概率14.3215%；有掩码时成本势函数为2.7956%，未见稳定收益。本轮不重评或改写千题结果。

[同求解预算实验](docs/query_budget_results.md)的失败筛选保留原结论；BC另按[计算替代协议](docs/query_policy_protocol.md)开展。[框架对照](docs/framework_comparison.md)逐项说明与Agentic Tool RL的结构对应和剩余工作；[研究记录](docs/research_log.md)保存每轮实现与证据。

[真实数量评测](docs/results/notice_facts_api.md)已归档：模型7/8、规则6/8与助手参考一致。维护者选择不填写人工意见，结果保留为未进行人工复核的探索证据，不阻塞环境研究，也不重复调用API。需要手动操作的内容见[操作说明](docs/manual_steps.md)。

详见[架构](docs/architecture.md)、[数据与评测](docs/benchmark.md)和[模型与复现](docs/methodology.md)。新增详细研究说明采用中文在前、英文在后的双语格式；历史说明在最终交付时补齐，见[文档计划](docs/documentation_plan.md)。

## 快速开始

推荐 Python 3.12。`constraints.txt` 固定已验证的数值计算依赖，供实验重放与 CI 使用。

```bash
git clone https://github.com/nomoretry/semiconductor-logistics-decarbonization.git
cd semiconductor-logistics-decarbonization
python -m pip install -c constraints.txt -e ".[dev]"
make test
make smoke
```

Windows 没有 Make 时可直接使用 Python：

```bash
python -m unittest discover -s tests
python -m semiconductor_logistics --help
python -m semiconductor_logistics evaluate --output artifacts/rules
python -m semiconductor_logistics verify-run --output artifacts/rules
```

默认检查使用本地合成数据，不调用 API。`make smoke` 运行规则评测、工具环境、小型BC/PPO训练和重放校验。

## 运行优化实验

```bash
semiconductor-logistics download-data
semiconductor-logistics optimize --project asml --smoke
semiconductor-logistics optimize --project marvell --smoke
semiconductor-logistics optimize --project both
semiconductor-logistics sensitivity --project both
semiconductor-logistics report
```

`download-data` 根据来源清单下载并校验第三方原始文件。完整优化实验包含外部汽车备件月度需求压力测试，因此需先下载数据。主实验会写入 `reports/`；单独运行一个案例会替换该目录的主实验汇总。公开仓库中的合成明细与外部压力测试汇总范围见[数据与评测](docs/benchmark.md)。

Python 脚本生成 [Markdown 实验报告](reports/study_report.md)、CSV/JSON 结果和 Matplotlib 图表。

## 公告抽取评测

| 方法 | 数据划分 | 文本数 | 整条公告抽取正确率 |
|---|---|---:|---:|
| 冻结规则 | 开发集 | 120 | 100% |
| 冻结规则 | 合成留出集 | 400 | 51.0%（204/400） |
| 总是请求澄清 | 合成留出集 | 400 | 44.0% |
| 忽略公告 | 合成留出集 | 400 | 16.5% |
| GPT-6 Luna | 合成留出集，主运行 | 400 | 100%（400/400） |
| GPT-6 Luna | 同一留出集复测 | 400 | 100%（400/400） |

主运行相对冻结规则提高 49.0 个百分点，复测的解析输出全部一致；两轮仍为同一批 400 条案例。逐条结果、分组区间及原始响应见[正式对照](docs/results/api_test.md)，20 条开发样本另存为[连接测试](docs/results/api_smoke.md)。

[真实公告语料](docs/data/real_notices.md)包含16份官方运输材料短摘录，经两次助手审核。固定模型已完成16次调用，与助手参考一致率100%，始终澄清基线也是100%。原始记录已归档，人工复核未完成；这组全澄清结果不能证明真实更新抽取能力。[下一版协议](docs/real_fact_protocol.md)将来源事实抽取与内部路线更新分别评测。

```bash
semiconductor-logistics evaluate
semiconductor-logistics verify-run
semiconductor-logistics workflow-audit
semiconductor-logistics workflow-audit --verify
semiconductor-logistics compare-api --run benchmark_results/api_test --repeat-run benchmark_results/api_repeat
semiconductor-logistics real-notices offline --dataset benchmarks/real_notices_v1/dataset.json --output artifacts/real_notices
semiconductor-logistics decision-audit --tasks 200 --output artifacts/decision_audit
semiconductor-logistics coupled-audit --contexts 120 --output artifacts/coupled_development
python -m scripts.verify_real_notice_archive
semiconductor-logistics notice-facts offline --output artifacts/notice_facts
semiconductor-logistics scale-audit --verify --output benchmark_results/decision_scale
semiconductor-logistics query-budget --verify --output benchmark_results/query_budget_development
semiconductor-logistics query-bc --verify --output benchmark_results/query_bc_development
semiconductor-logistics query-ppo --verify --output benchmark_results/query_ppo_development
semiconductor-logistics query-study verify-development
semiconductor-logistics query-study verify-final
semiconductor-logistics query-components verify
```

API 命令默认只估算费用：

```bash
semiconductor-logistics api --dataset benchmarks/notices_v1/dataset.json --split test --max-calls 400 --output artifacts/notice_api
```

实际调用通过 GitHub Actions 手动运行，密钥保存在仓库 Secret。`smoke20` 使用开发集，`test400` 使用冻结留出集，设置步骤见 [API 配置](docs/secure_api_connection.md)。

## 常用命令

| 命令 | 用途 |
|---|---|
| `generate` | 生成公告开发集、留出集及校验信息 |
| `optimize` | 运行 ASML、Marvell 的库存与运输策略 |
| `evaluate` | 评测冻结规则与诊断基线 |
| `api` | 估算或执行固定模型 API 抽取 |
| `score-api` | 校验请求记录并复算 API 指标 |
| `compare-api` | 复算固定模型与冻结规则的成对差值及复测 |
| `real-notices` | 校验真实语料、运行离线基线、导出输入和复算响应 |
| `decision-audit` | 检验信息成本、规划选择和强适应性基线 |
| `coupled-audit` | 检验多SKU共享容量、查询预算、精确规划与前瞻基线 |
| `notice-facts` | 验证真实数量数据、评分规则、估算/执行新字段API并复算 |
| `scale-audit` | 重放较大SKU/扰动开发网格，核对期望成本、轨迹与整数计划 |
| `query-budget` | 在同MILP调用上限下比较查询规划，复算完整策略树和计算台账 |
| `query-bc` | 生成查询教师、训练BC、比较强搜索并重执行检查点 |
| `query-ppo` | 从冻结BC训练PPO，重放采样轨迹、更新记录和检查点 |
| `query-study` | 配对多种子重训、组件消融、新任务冻结和最终复算 |
| `workflow-audit` | 运行或重放多步工具任务 |
| `verify-run` | 校验离线数据、预测、指标和源码身份 |
| `sensitivity` | 运行参数及排放边界敏感性实验 |
| `report` | 生成 Markdown 报告、表格和图表 |

安装后的命令也可通过 `python -m semiconductor_logistics` 调用。离开仓库目录运行实验时，使用 `--workspace /path/to/repository` 指定数据与配置所在的工作目录。

## 仓库结构

| 路径 | 内容 |
|---|---|
| `semiconductor_logistics/` | Python 命令行入口 |
| `shared/` | 库存守恒、MILP 求解与实验调度 |
| `notice_benchmark/` | 冻结合成公告、规则、API、指标和原工具环境 |
| `real_notice_eval/` | 真实公告来源校验与探索性评测 |
| `notice_facts/` | 单独的真实数量合同、冻结规则、预算API与原始响应复算 |
| `decision_benchmark/` | 查询成本、物理物流结果与决策基线 |
| `coupled_decision/` | 多SKU整数分配、共享容量、预算查询及完整重放 |
| `budgeted_decision/` | 有限计算预算的查询规划、中断处理及逐分支复算 |
| `query_policy/` | 公开特征、NumPy BC、教师生成和检查点绑定验证 |
| `query_ppo/` | 轨迹隔离GAE、成本PPO、验证选模与完整训练复算 |
| `query_study/` | 多种子训练、无损证据、任务/模型冻结及配对统计 |
| `rolling_inventory/`、`rolling_sensitivity/` | 未知需求库存仿真、强基线规划及敏感性复算 |
| `query_components/` | 掩码与成本势函数对照、拒绝语义、完整开发训练重放 |
| `asml/`、`marvell/` | 两个案例的参数配置 |
| `benchmarks/` | 冻结公告集、规则身份及来源登记 |
| `benchmark_results/` | 逐条预测、API 响应、工具轨迹和校验清单 |
| `scripts/` | 数据获取、实验、报告与打包检查 |
| `tests/` | 求解、抽取、重放与命令行测试 |
| `docs/` | 架构、方法、评测和结果说明 |

## 数据与适用范围

订单、价格、质量、容量和仓储参数为仿真假设。排放因子、路线几何和类比需求保存来源与校验值，详见 [ASML 数据说明](data_sources/data_audit_asml.md)、[Marvell 数据说明](data_sources/data_audit_marvell.md)和[第三方数据声明](THIRD_PARTY_NOTICES.md)。

当前优化使用已知承诺订单和已公告扰动，覆盖运输与库存环节。结果用于比较仿真条件下的策略，不代表企业实测减排；独立滚动环境现已加入未知需求、预测误差和在途库存演化，与原固定订单研究分开报告。

## 未知需求滚动环境

[滚动库存实验](docs/rolling_inventory_results.md)已完成：12个校准、32个开发需求路径，4个可部署基线及预知需求下界。情景MPC平均成本282.2406，base-stock为330.6219；服务改善伴随排放增加。均值MPC未在总体胜过补货规则，未训练新RL。复算：`python -m semiconductor_logistics rolling-inventory verify`。

[滚动敏感性实验](docs/rolling_sensitivity_results.md)新增24条开发路径、3个采样种子和2,304条轨迹，量化碳分配、期末库存价值和情景数量。1→7情景成本降37.48%，7→21仅降0.36%且种子方向不一致；期末价值主要改变账面净成本。先验证预测分布及同信息教师，暂不训练滚动BC/PPO。复算：`python -m semiconductor_logistics rolling-sensitivity verify`。

敏感性证据包已补齐，覆盖全部2,304条轨迹，详见[文件身份与验收](docs/rolling_sensitivity_publication.md)。合并以前须确认PR当前提交的CI通过。

## 预测与滚动决策

[预测对照](docs/rolling_forecast_results.md)已完成：12条校准与32条新开发路径，共352轨迹、4,224期。固定同一优化器后，快速EWMA和季节短窗成本比原EWMA分别高7.19%/8.48%，三个采样种子方向一致；两者均未通过描述性教师筛选。另有3条路径预测NLL改善而成本上升。保留原EWMA情景MPC，暂不训练滚动BC/PPO。

运行 `make verify-forecast` 可重新选参、求解和核对全部证据；本轮不调用LLM API。

本轮73份预测证据已获明确授权并按原SHA256归档，见[文件身份与验收](docs/rolling_forecast_publication.md)。合并前检查当前提交的全部六项CI。
