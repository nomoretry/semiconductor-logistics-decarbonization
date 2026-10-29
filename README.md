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
| LLM API | Responses API、调用预算、请求缓存和原始响应记录 | 20 条开发文本实测，20/20 抽取一致 |
| 多步工具环境 | 检查公告、抽取、校验、读取状态、求解、审计和提交 | 200 组开发任务，逐步轨迹与确定性重放 |
| 结果验证 | 输入与源码哈希、逐条预测复算、物流计划重放 | 离线验证命令与自动测试 |

工具环境当前采用固定工作流。开发任务中，规则工作流完成了 127 份可行计划和 73 次正确澄清交接；尚未建立需要学习工具选择的决策取舍，BC/PPO 尚未训练。

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
| GPT-6 Luna | 开发集连接测试 | 20 | 100%（20/20） |

LLM 的 20 条结果只用于验证开发集上的调用和抽取流程；400 条留出文本的 LLM 对照尚未运行。13 份真实公告来源已登记，仍需人工标注。模型配置与逐条响应见 [API 实测记录](docs/results/api_smoke.md)。

```bash
semiconductor-logistics evaluate
semiconductor-logistics verify-run
semiconductor-logistics workflow-audit
semiconductor-logistics workflow-audit --verify
semiconductor-logistics score-api --run benchmark_results/api_smoke
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
| `notice_benchmark/` | 公告数据、规则、API、指标和工具环境 |
| `asml/`、`marvell/` | 两个案例的参数配置 |
| `benchmarks/` | 冻结公告集、规则身份及来源登记 |
| `benchmark_results/` | 逐条预测、API 响应、工具轨迹和校验清单 |
| `scripts/` | 数据获取、实验、报告与打包检查 |
| `tests/` | 求解、抽取、重放与命令行测试 |
| `docs/` | 架构、方法、评测和结果说明 |

## 数据与适用范围

订单、价格、质量、容量和仓储参数为仿真假设。排放因子、路线几何和类比需求保存来源与校验值，详见 [ASML 数据说明](data_sources/data_audit_asml.md)、[Marvell 数据说明](data_sources/data_audit_marvell.md)和[第三方数据声明](THIRD_PARTY_NOTICES.md)。

当前优化使用已知承诺订单和已公告扰动，覆盖运输与库存环节。结果用于比较仿真条件下的策略，不代表企业实测减排；未知需求、预测误差和滚动决策尚未加入。
