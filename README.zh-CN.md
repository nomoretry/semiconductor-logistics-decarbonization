# 半导体物流减碳

[English](README.md) | 简体中文 · [文档索引](docs/README.md)

[![Python](https://img.shields.io/badge/Python-3.12-3776AB.svg)](https://www.python.org/) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

半导体备件和成品在少数几个站点之间，通过空运、海运和公路运输。每条线路每周运力有限，交付日期已经承诺，排放也有预算。船公司通知延误或削减舱位时，计划员要决定发什么、走哪条线路、什么时候发，并弄清这个变化在成本、服务和排放上的代价。

本仓库从两方面处理这个问题：

- **决策工具。** 规划引擎（混合整数规划与两阶段随机规划）和“公告到备忘录”流程，把船公司公告变成经人工确认的扰动场景，求解方案，对比成本、服务和排放，并生成决策备忘录。输出里的每个数字都来自求解器，每个参数都标明来源。
- **可复现的研究。** 研究问题是：在共享运力、库存动态和碳约束下，获取信息和预测建模什么时候能足够改善物流决策、值得付出相应成本。每项研究都保留协议、配置、逐例证据和复算命令。

适用对象：想看清扰动应对方案取舍的供应链计划员；想复算或扩展这些研究的运筹与机器学习研究者；开发工具调用型规划 Agent 的开发者。

两个案例 [ASML 启发的备件物流](asml/README.md)和 [Marvell 启发的成品物流](marvell/README.md)都是仿真。订单、价格、运力和扰动幅度是合成假设；距离和排放因子来自注明出处的公开资料。没有使用任何企业数据。

## 快速开始：从船公司公告到决策备忘录

推荐 Python 3.12。`requirements/` 里的锁文件用哈希固定全部依赖。

```bash
git clone https://github.com/nomoretry/semiconductor-logistics-decarbonization.git
cd semiconductor-logistics-decarbonization
python -m pip install --require-hashes -r requirements/planning.txt
python -m pip install --no-deps --no-build-isolation -e .
python -m planning_agent flow
```

最后一条命令用规则解析器离线运行，不需要 API key，也不调用模型。它会：

1. 读取内置公告（红海绕行好望角，第 4–12 周海运延误 2 周，舱位削减 30%），显示解析出的场景、每个参数对应的公告原文和默认假设；
2. 请你确认，回答 `y` 之前不做任何求解（`e` 修改扰动，`n` 取消）；
3. 用 HiGHS 求解正常方案和扰动方案，对比总成本、服务水平、排放和空运占比；
4. 生成 Markdown 决策备忘录并打印路径。

默认设置下（12 个合成 SKU、16 周），扰动方案成本 60,711 美元，正常方案 55,253 美元（+9.88%）；排放 27.12 吨 CO2e，正常方案 20.82 吨（+30.26%）；服务水平 100%。命令行和网页界面是中文，文档有中英文两版。

同一流程的其他运行方式：

```bash
python -m planning_agent flow --mode notice              # 同时检索真实船公司公告并引用
python -m planning_agent flow --mode replay --case D13   # 使用真实模型在录制评测中给出的参数
python -m streamlit run planning_agent/app.py            # 网页，步骤相同
```

`--mode live` 通过 LangGraph Agent 调用模型，需要 `LLM_API_KEY` 和 token 上限（`--max-tokens`），会产生费用。全部选项见[流程说明](docs/decision_workflow.md)。

## 现在能做什么

| 组成部分 | 功能 | 验证方式 |
|---|---|---|
| [网络规划引擎](docs/network_planning.md)（`network_planning/`） | 固定费用的多 SKU、多式联运 MILP，提前期和运力随扰动变化，空运舱位预留，服务水平下限，碳上限或碳价；两阶段随机规划，含 VSS/EVPI 及 MIP gap 区间；碳前沿、边际减排成本和 LP 影子价格；对每个方案独立复核账目 | 单元测试和[归档报告](benchmark_results/network_planning/report.md) |
| [公告到备忘录流程](docs/decision_workflow.md)（`planning_agent/workflow.py`、`app.py`） | 参数与假设 → 确认 → 方案对比 → 备忘录，可用命令行或网页；参数来源有 `rule`、`notice`、`replay`、`live` 四种 | 离线测试，含网页无头测试；`live` 只用脚本客户端测过 |
| [公告检索](docs/notice_retrieval.md)（`planning_agent/retrieval.py`） | 在 24 条船公司公告摘录上做 BM25 检索，中文问题经中英术语表扩展；在流程和备忘录中给出出处、链接、每个参数的依据和缺失信息；可选本地全文（网页不存入仓库） | 38 条问题的开发检查（见下方结果） |
| [规划 Agent](docs/planning_agent.md)（`planning_agent/`） | 调用 8 个经校验工具的 Agent，带数字忠实度护栏，另有 LangGraph 状态图版本；规则 Agent 作为离线后备和基线 | 24 题评测；录制模型运行的离线回放 |
| 研究环境 | 公告抽取基准、工具流程、有预算的查询规划（BC/PPO）、未知需求下的滚动库存 | 归档证据和 `verify` 命令（见[研究说明](docs/research_guide.md)） |

## 主要结果

| 问题 | 结果 | 证据 |
|---|---|---|
| 扰动影响（规划引擎，12 个 SKU，16 周） | ASML 启发案例红海绕行：成本 +12.38%，CO2e +28.4%。Marvell 启发案例台风：成本 +2.17% | [报告](benchmark_results/network_planning/report.md) |
| 服务水平 98% 下减排 25% 的代价 | ASML：成本 +1.76%，平均边际减排成本 187 美元/吨，影子价格 277 美元/吨。Marvell：+13.12%，平均边际减排成本 24,756 美元/吨 | [报告](benchmark_results/network_planning/report.md) |
| 针对扰动场景做计划的价值（VSS） | ASML：864 美元（1.51%）。Marvell：约为零，在 MIP gap 区间内 | [报告](benchmark_results/network_planning/report.md) |
| 规划 Agent，24 个计划员问题（开发 14、鲁棒性 10，同一作者编写） | 规则 Agent 14/14、4/10。gpt-6.1-sol（xhigh，运行一次，修复护栏后离线重评）9/14、9/10，数字忠实度 100%。用 LangGraph Agent 回放录制运行，每题评分都与录制一致（成功 18/24）；这不是新的模型运行 | [Agent](docs/planning_agent.md) |
| 公告检索，19 个事件分组的 38 个问题 | 37/38 的第一条结果属于正确事件（不用术语表时中文问题 4/19）。问题由同一作者在读过语料后编写，是开发检查，不是独立测试 | [检索](docs/notice_retrieval.md) |
| 400 条合成留出公告的抽取 | 固定模型 400/400（同一 400 条重复运行也是 400/400）；冻结规则 204/400 | [结果](docs/results/api_test.md) |
| 真实船公司公告 | 16 条摘录全部需要澄清；模型和“始终澄清”都与参考 16/16 一致，因此不能说明抽取能力。8 条数量抽取：模型 7/8，规则 6/8。参考标签由助手编写，未经人工复核 | [语料](docs/data/real_notices.md)、[数量](docs/results/notice_facts_api.md) |
| 查询策略，冻结千题，5 个训练种子 | 平均遗憾 BC 3.1179%、PPO 3.1477%；PPO−BC +0.0298 个百分点，95% 区间 [−0.1817, +0.2540]。两步搜索 0.6309%、迭代 DP 0.0528% 仍然更好。PPO 没有稳定收益 | [结果](docs/query_final_results.md) |
| 未知需求下的滚动库存 | 32 条开发路径上情景 MPC 成本 282.2406，base-stock 330.6219，排放更高。更快的预测使成本上升（+7.19%、+8.48%）；负二项需求模型成本 +2.06%，区间跨零。没有训练滚动 BC/PPO | [基线](docs/rolling_inventory_results.md)、[预测](docs/rolling_forecast_results.md)、[分布](docs/rolling_distribution_results.md) |

失败和负面结果都保留在结果文档里，包括同预算实验未通过的筛选和滚动教师未通过的筛选。

## 限制

- 所有运营数据都是合成的。结果是在给定假设下比较策略，不是企业运营或减排的实测。
- 各研究线分别评估；没有端到端验证把公告抽取、学习查询和滚动控制连起来。
- 真实公告评测规模小、属探索性质；参考标签未经人工复核，真实公告也很少给出可直接用于计划的参数；船公司航线没有对应到内部线路。
- Agent 和检索评测由同一作者编写。Agent 评测的模型运行只执行过一次；流程的 `live` 模式没有用真实模型跑过。会话记忆只在单个进程内有效。
- 工程方面：CI 只在 Ubuntu、Python 3.12 上运行；还没有打标签的 Release；Ruff 和 strict mypy 覆盖规划两个包，不覆盖归档的研究包；部分较早的协议和结果文档只有中文。

## 复现与验证

```bash
python -m pip install --require-hashes -r requirements/dev.txt   # 只做研究复算时装这个锁文件即可
python -m pip install --no-deps --no-build-isolation -e .
make test          # 离线测试（装了 planning 锁文件时也运行规划测试）
make planning-ci   # 规划测试、报告、规则评测、回放和两种流程模式
make quality       # 对 network_planning 和 planning_agent 运行 Ruff 与 strict mypy
make lock-check    # 锁文件仍与 pyproject.toml、constraints.txt 一致
make verify-final  # 复算一项归档研究；全部 verify 命令见研究说明
```

没有 Make 时，运行 `python -m unittest discover -s tests` 以及[命令参考](docs/commands.md)中的 Python 命令。默认检查都不调用模型 API。

## 文档

[文档索引](docs/README.md)按用途列出全部文档：使用指南、架构与设计、方法与协议、数据、结果、复现。建议从[架构](docs/architecture.md)、[研究设计](docs/research_design.md)和[研究说明](docs/research_guide.md)开始。

## 目录结构

| 路径 | 内容 |
|---|---|
| `network_planning/` | 规划引擎：MILP、随机规划、碳前沿、账目复核和报告 |
| `planning_agent/` | 决策流程和网页、公告检索、工具调用与 LangGraph Agent、规则 Agent、护栏、备忘录和评测 |
| `semiconductor_logistics/` | 研究实验的命令行（`python -m semiconductor_logistics`） |
| `shared/` | 原始案例研究的库存守恒、MILP 求解器和实验编排 |
| `notice_benchmark/`、`notice_facts/`、`real_notice_eval/` | 公告抽取基准、真实公告校验和 API 评测 |
| `decision_benchmark/`、`coupled_decision/`、`budgeted_decision/` | 查询与规划环境及强搜索基线 |
| `query_policy/`、`query_ppo/`、`query_study/`、`query_components/` | 查询策略 BC 与 PPO、多种子研究和组件审计 |
| `rolling_inventory/`、`rolling_sensitivity/`、`rolling_forecast/`、`rolling_distribution/`、`rolling_recourse/` | 未知需求下的滚动库存及后续研究 |
| `asml/`、`marvell/` | 案例配置与说明 |
| `benchmarks/`、`llm/` | 冻结数据集、提示词和问题集 |
| `benchmark_results/`、`reports/`、`reviews/` | 归档的逐例证据、校验清单、生成的报告，以及真实公告标签尚未填写的审核表 |
| `data_sources/` | 来源清单、选用的公开因子、数据审核和公告语料清单 |
| `scripts/` | 数据下载、报告生成、证据审计和打包检查 |
| `tests/` | 单元、回放和命令行测试 |
| `requirements/`、`constraints.txt` | 带哈希的依赖锁文件，以及解析它们所依据的已验证版本 |
| `docs/` | 使用指南、架构、方法、协议和结果 |

## 许可与来源

项目代码和文档采用 [MIT 许可](LICENSE)，引用信息见 [CITATION.cff](CITATION.cff)。第三方数据集、船公司公告摘录、外部模型的保存输出和一处参考代码保留各自的条款，列在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。[来源与归属](docs/source_history.md)说明了哪些外部设计和代码影响过本项目。
