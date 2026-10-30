# Semiconductor Logistics Decarbonization

[![Python](https://img.shields.io/badge/Python-3.12-3776AB.svg)](https://www.python.org/)

面向半导体备件与成品物流的库存—运输联合优化框架。使用 SciPy/HiGHS 求解带交付、运输容量和碳预算约束的整数规划；提供固定 LLM 公告抽取评测、多步工具环境、逐期计划和结果复算。

两个案例共享求解器，分别保留业务约束：[ASML 备件物流](asml/README.md)与 [Marvell 成品物流](marvell/README.md)。

## 设计与实验

| 模块 | 实现 | 实验与输出 |
|---|---|---|
| 库存与运输 | 整数发货、在途库存、到仓库存、积压守恒 | 60 份合成订单实例、360 次策略求解 |
| 成本与碳预算 | 运费、资金占用、仓储成本和物流排放；三档碳约束 | 成本—排放对照、339 份可行计划、不可行实例 |
| 公告抽取 | 固定提示词、JSON Schema、冻结规则和固定模型配置 | 120 条开发文本、400 条合成留出文本 |
| LLM API | Responses API、调用预算、请求缓存和原始响应记录 | 400 条合成留出文本，主运行与复测均 400/400 |
| 多步工具环境 | 检查公告、抽取、校验、读取状态、求解、审计和提交 | 200 组开发任务，逐步轨迹与确定性重放 |
| 共享容量与查询 | 3–4个SKU、空海运分配、联合扰动先验、共用查询预算 | 120组开发情境、6种方法、720条运行及重放 |
| 真实数量抽取 | 总时长/增减量、原单位、区间与限定语、原文证据 | 16条开发、8份新来源；模型7/8、规则6/8，人工审核待完成 |
| 查询规模审计 | 4–12个SKU、2–6个扰动、跨路线容量池、整数规划 | 18个开发任务、72条运行；单步/两步平均成本差距0.5378%/0.0811% |
| 同计算预算对照 | 每次决策MILP限额、中断回退、分支缓存隔离、完整路径记账 | 54个开发情境、1,080条运行；主预算最强方法平均差距0.6253%，尾部15.9217% |
| 结果验证 | 输入与源码哈希、逐条预测复算、物流计划重放 | 离线验证命令与自动测试 |

原工具环境的固定工作流在开发任务中完成了 127 份可行计划和 73 次正确澄清交接。新增[信息成本环境](docs/decision_environment.md)检验查询、澄清和求解选择的实际代价；训练条件与后续工作见[进度记录](docs/progress.md)。

[多SKU环境](docs/coupled_environment.md)已经加入共享路线容量和查询预算。两步前瞻在当前120个开发情境达到精确规划结果，尚未训练BC/PPO。[研究记录](docs/research_log.md)逐项保存改动与验证，[文献与资料依据](docs/research_basis.md)说明每项资料如何影响设计。

[规模审计](docs/decision_scale.md)进一步增加独立扰动与容量池，保存成本差距和求解次数；两步前瞻仍接近精确DP。[真实数量评测](docs/real_fact_protocol.md)已具备单独的Python实现、离线对照和手动API入口。需要人工完成的合并、运行与标签核对见[操作说明](docs/manual_steps.md)。

新数量任务的[8次API运行与原始证据](docs/results/notice_facts_api.md)已归档：模型7/8与当前参考一致，唯一分歧是把停航持续时间抽成运输延误。当前先完成人工复核，无需重复调用。

[同求解预算对照](docs/query_budget_results.md)已完成。预算65的逐层查询DP将平均差距降至0.0118%；主预算13下的整体差距未通过事前BC筛选。本轮保留了一个15.9217%差距的分支诊断，展示昂贵查询与后续信息预算的实际取舍，未开始BC/PPO训练。

详见[架构](docs/architecture.md)、[数据与评测](docs/benchmark.md)和[模型与复现](docs/methodology.md)。

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

默认检查使用本地合成数据，不调用 API。`make smoke` 运行规则评测、工具环境和重放校验。

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
| `asml/`、`marvell/` | 两个案例的参数配置 |
| `benchmarks/` | 冻结公告集、规则身份及来源登记 |
| `benchmark_results/` | 逐条预测、API 响应、工具轨迹和校验清单 |
| `scripts/` | 数据获取、实验、报告与打包检查 |
| `tests/` | 求解、抽取、重放与命令行测试 |
| `docs/` | 架构、方法、评测和结果说明 |

## 数据与适用范围

订单、价格、质量、容量和仓储参数为仿真假设。排放因子、路线几何和类比需求保存来源与校验值，详见 [ASML 数据说明](data_sources/data_audit_asml.md)、[Marvell 数据说明](data_sources/data_audit_marvell.md)和[第三方数据声明](THIRD_PARTY_NOTICES.md)。

当前优化使用已知承诺订单和已公告扰动，覆盖运输与库存环节。结果用于比较仿真条件下的策略，不代表企业实测减排；未知需求、预测误差和滚动决策尚未加入。
