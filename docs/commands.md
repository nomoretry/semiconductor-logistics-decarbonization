# 命令参考 / Command reference

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

安装方法见 [README](../README.zh-CN.md#快速开始从船公司公告到决策备忘录)。下面的命令都在仓库根目录运行，默认离线，不调用模型 API；会产生费用的调用都需要显式参数。

### 规划引擎与决策流程

```bash
python -m network_planning describe --network asml           # 网络、线路与场景
python -m network_planning solve --network asml --scenario red_sea --explain
python -m network_planning frontier --network marvell        # 碳前沿与边际减排成本
python -m network_planning stochastic --network asml --reveal-week 3   # 两阶段计划、VSS、EVPI
python -m network_planning report --output benchmark_results/network_planning

python -m planning_agent flow                                 # 公告 → 参数确认 → 方案对比 → 备忘录（规则模式）
python -m planning_agent flow --mode notice                   # 同上，并检索真实船公司公告
python -m planning_agent flow --mode replay --case D13        # 录制的模型参数，本次不调用模型
python -m streamlit run planning_agent/app.py                 # 网页
python -m planning_agent ask "红海中断对 ASML 备件成本有什么影响？"
python -m planning_agent demo --output artifacts/planning_agent/demo
python -m planning_agent --agent rule eval --output artifacts/planning_agent/eval   # 24 题评测（规则 Agent）
python -m planning_agent replay --output artifacts/planning/replay                  # 用 LangGraph 回放录制运行
python -m planning_agent corpus search "鹿特丹码头罢工"          # 公告检索
python -m planning_agent corpus evaluate --check              # 复算检索评测
python -m planning_agent corpus fetch --yes                   # 下载公告原文到本地（访问船公司网站）
python -m planning_agent eval-v2 run --agent rule             # 20 题评测的规则基线（不调用模型）
python -m planning_agent eval-v2 analyze                      # 由保存的运行计算统计（不调用模型）
python -m planning_agent eval-v2 verify                       # 重新评分并核对哈希（不调用模型）
```

`--agent llm`、`--agent graph` 和 `flow --mode live` 会产生费用，需要 `LLM_API_KEY`、`LLM_MODEL_ID` 和限额变量，缺一项就不调用；`python -m planning_agent llm-check` 检查配置（不联网）。见[实时模型调用的配置与限额](live_model_safety.md)。

### 研究实验

全部子命令也可写成 `python -m semiconductor_logistics <命令>`；在仓库外运行时用 `--workspace` 指定检出目录。每个命令的参数见 `<命令> --help`。

| 命令 | 用途 |
|---|---|
| `download-data` | 下载并按哈希核对两个公开来源数据集 |
| `optimize` | 运行公司启发案例的 MILP 网格 |
| `sensitivity` | 运行独立的假设敏感性研究 |
| `report` | 从保存的结果生成 Markdown 报告、表格和图 |
| `generate` | 生成合成的开发与测试公告 |
| `evaluate` | 评测冻结的离线公告规则 |
| `verify-run` | 只读校验冻结的离线运行 |
| `workflow-audit` | 运行或校验开发集工具流程审计 |
| `api` | 估算 API 费用；实际调用需要 `--execute` 和预算 |
| `score-api` | 离线校验并评分已有的 API 记录 |
| `compare-api` | 把已校验的留出集 API 运行与冻结规则对比 |
| `real-notices` | 审核并评测官方公告摘录 |
| `notice-facts` | 评测来源中的数量，不推断内部线路 |
| `decision-audit` | 审计信息成本与物流决策 |
| `coupled-audit` | 审计共享运力与信息预算 |
| `scale-audit` | 在更大的开发规模上测量 MILP 与查询规划 |
| `query-budget` | 在相同的每次决策 MILP 调用上限下审计规划方法 |
| `query-bc` | 训练并回放查询策略 BC 开发实验 |
| `query-ppo` | 从冻结的 BC 检查点训练并回放基于成本的 PPO |
| `query-study` | 配对多种子消融、冻结最终任务并回放最终证据 |
| `query-components` | 在开发数据上审计动作掩码和只用训练数据的成本势函数 |
| `rolling-inventory` | 运行并回放未知需求下的滚动库存基线 |
| `rolling-sensitivity` | 量化碳分配、期末库存价值和情景数量 |
| `rolling-forecast` | 比较只用历史的预测并回放配对的滚动决策 |
| `rolling-distribution` | 比较残差离散度并审计跨 SKU 相关性的不变性 |
| `rolling-recourse` | 用精确滚动基线检验有限情景的非预知追索 |

`download-data` 之后才能运行完整的优化网格，因为其中包含外部汽车备件月度需求压力测试。主实验写入 `reports/`；单独运行一个案例会替换该目录里的主实验汇总。

公告抽取的 API 命令默认只估算费用，例如：

```bash
semiconductor-logistics api --dataset benchmarks/notices_v1/dataset.json --split test --max-calls 400 --output artifacts/notice_api
```

实际调用通过 GitHub Actions 手动工作流和仓库 Secret 运行，见 [API 配置](secure_api_connection.md)。

### 校验与维护

| 命令 | 作用 |
|---|---|
| `make test` | 全部离线测试 |
| `make smoke` | 规则评测与离线校验、小规模工具流程/决策/共享运力审计及回放、API 费用估算（不调用），以及 BC、PPO 和各滚动研究的冒烟检查 |
| `make planning-ci` | 规划测试、快速报告、规则评测、回放和两种流程模式 |
| `make quality` | 对规划两个包运行 Ruff 和 strict mypy |
| `make lock` / `make lock-check` | 重新生成锁文件 / 检查锁文件是否过期 |
| `make package-check` | 检查 Python 分发包 |
| `make verify-core`、`verify-final`、`verify-components`、`verify-rolling`、`verify-sensitivity`、`verify-forecast`、`verify-distribution`、`verify-recourse` | 复算各项归档研究，范围见[研究说明](research_guide.md) |
| `python -m scripts.check_research_progress` | 核对已保存结果与清单是否完整，不重新运行实验 |

## English

See the [README](../README.md#quick-start-from-a-carrier-notice-to-a-decision-memo) for installation. Run the commands from the repository root. They work offline and make no model API calls by default; paid calls need explicit options.

### Planning engine and decision workflow

```bash
python -m network_planning describe --network asml           # network, lanes and scenarios
python -m network_planning solve --network asml --scenario red_sea --explain
python -m network_planning frontier --network marvell        # carbon frontier and marginal abatement cost
python -m network_planning stochastic --network asml --reveal-week 3   # two-stage plan, VSS and EVPI
python -m network_planning report --output benchmark_results/network_planning

python -m planning_agent flow                                 # notice → confirmation → plan comparison → memo (rule mode)
python -m planning_agent flow --mode notice                   # the same, with real carrier notices retrieved
python -m planning_agent flow --mode replay --case D13        # recorded model parameters, no model call
python -m streamlit run planning_agent/app.py                 # web page
python -m planning_agent ask "How would a Red Sea diversion change ASML spare-parts cost?"
python -m planning_agent demo --output artifacts/planning_agent/demo
python -m planning_agent --agent rule eval --output artifacts/planning_agent/eval   # 24-question evaluation (rule agent)
python -m planning_agent replay --output artifacts/planning/replay                  # replay recorded runs through LangGraph
python -m planning_agent corpus search "Rotterdam strike"     # notice retrieval
python -m planning_agent corpus evaluate --check              # recompute the retrieval evaluation
python -m planning_agent corpus fetch --yes                   # download original notice pages locally (contacts carrier sites)
python -m planning_agent eval-v2 run --agent rule             # rule baseline of the 20-task evaluation (no model)
python -m planning_agent eval-v2 analyze                      # statistics from saved runs (no model)
python -m planning_agent eval-v2 verify                       # re-score and check hashes (no model)
```

`--agent llm`, `--agent graph` and `flow --mode live` are paid calls and need `LLM_API_KEY`, `LLM_MODEL_ID` and the limit variables; without any of them nothing is called. `python -m planning_agent llm-check` checks the configuration without touching the network. See [live model calls: configuration and limits](live_model_safety.md).

### Research studies

Every subcommand is also available as `python -m semiconductor_logistics <command>`; outside the repository, pass `--workspace` to select the checkout. Run `<command> --help` for its options.

| Command | Purpose |
|---|---|
| `download-data` | Download and hash-check the two public source datasets |
| `optimize` | Run the company-inspired MILP grids |
| `sensitivity` | Run the separate assumption sensitivity study |
| `report` | Generate Markdown reports, tables and figures from saved results |
| `generate` | Generate synthetic development and test notices |
| `evaluate` | Evaluate frozen offline notice rules |
| `verify-run` | Read-only verification of the frozen offline run |
| `workflow-audit` | Run or verify the development tool-workflow audit |
| `api` | Estimate API cost; live calls require `--execute` and a budget |
| `score-api` | Verify and score an existing API ledger offline |
| `compare-api` | Compare a verified held-out API run with frozen rules |
| `real-notices` | Review and evaluate official notice excerpts |
| `notice-facts` | Evaluate source quantities without inferring internal routes |
| `decision-audit` | Audit information costs and logistics decisions |
| `coupled-audit` | Audit shared freight capacities and information budgets |
| `scale-audit` | Measure MILP and query planning at larger development sizes |
| `query-budget` | Audit planners under the same per-decision MILP call caps |
| `query-bc` | Train and replay the development query-policy BC experiment |
| `query-ppo` | Train and replay cost-based PPO from the frozen BC checkpoint |
| `query-study` | Run paired multi-seed ablations, freeze final tasks and replay final evidence |
| `query-components` | Audit policy masks and train-only cost-potential rewards on development data |
| `rolling-inventory` | Run and replay unknown-demand rolling inventory baselines |
| `rolling-sensitivity` | Quantify carbon pacing, final stock credit and scenario count |
| `rolling-forecast` | Compare history-only forecasts and replay paired rolling decisions |
| `rolling-distribution` | Compare residual dispersion and audit cross-SKU dependence invariance |
| `rolling-recourse` | Check finite-support nonanticipative recourse against exact rolling baselines |

Run `download-data` before the full optimization grid, which includes an external automotive spare-parts monthly-demand stress test. Main experiments write to `reports/`; running a single case replaces the main summaries there.

The notice-extraction API command only estimates cost by default, for example:

```bash
semiconductor-logistics api --dataset benchmarks/notices_v1/dataset.json --split test --max-calls 400 --output artifacts/notice_api
```

Live calls run through a manual GitHub Actions workflow with a repository Secret; see [API setup](secure_api_connection.md).

### Verification and maintenance

| Command | Effect |
|---|---|
| `make test` | All offline tests |
| `make smoke` | Rule evaluation and offline verification, small tool-workflow, decision and shared-capacity audits with replay, an API cost estimate (no call), and smoke checks of BC, PPO and the rolling studies |
| `make planning-ci` | Planning tests, quick report, rule evaluation, replay and both workflow modes |
| `make quality` | Ruff and strict mypy on the two planning packages |
| `make lock` / `make lock-check` | Regenerate the lock files / check that they are current |
| `make package-check` | Check the Python distribution |
| `make verify-core`, `verify-final`, `verify-components`, `verify-rolling`, `verify-sensitivity`, `verify-forecast`, `verify-distribution`, `verify-recourse` | Replay each archived study; see the [research guide](research_guide.md) for scope |
| `python -m scripts.check_research_progress` | Check saved results and manifests without rerunning experiments |
