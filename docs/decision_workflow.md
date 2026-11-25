# 公告到备忘录的决策流程 / Notice-to-memo decision workflow

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

### 范围

在现有规划引擎（[`network_planning/`](../network_planning)）和规划 Agent（[`planning_agent/`](../planning_agent)）之上，做一个计划员可以亲自操作的最小业务闭环：

1. 输入运输公告或扰动描述；
2. 展示解析出的参数和默认假设，每个参数标出对应的原文；
3. 计划员确认，可以先修改参数；
4. 求解正常方案和扰动方案，可选加减排上限、中断概率对冲；
5. 展示成本、服务水平、排放和空运占比的对比；
6. 生成决策备忘录。

**参数来源有三种模式，每个结果都标明用的是哪一种**：

| 模式 | 参数从哪里来 | 是否调用大模型 |
|---|---|---|
| 离线规则 `rule` | `rules.py` 的规则解析器 | 否，结果确定，能识别的写法有限 |
| 录制回放 `replay` | 24 题正式评测中，真实模型（gpt-6.1-sol，Responses 接口，xhigh）对案例 D13、H05 实际给出的场景参数 | 否，本次不调用模型；界面标明“录制回放” |
| 实时模型 `live` | 大模型经 LangGraph Agent 提出参数，任何工具执行前暂停 | 是，付费；需要 `LLM_API_KEY` 和 token 上限，预算须先经用户批准 |

不论哪种模式，优化计算都在确认之后实时求解（MILP，HiGHS），不使用预先算好的结果；数字都来自引擎。

**不包括**：真实公告检索（RAG）、跨进程的会话记忆、多用户和部署。这些是后续里程碑。

### 验收条件

1. 默认公告（红海绕行，第 4–12 周海运延误 2 周，舱位削减 30%）在规则模式下解析出：海运、第 4–12 周、延误 2 周、运力 −30%、距离系数 1.4183（苏伊士改走好望角）；列出默认假设（未给出运费变化，按 0）；每个参数显示对应的原文片段。
2. 确认之前不做任何求解。
3. 确认之后给出正常和扰动两套方案（设了减排上限则三套）的总成本、变化、服务水平、排放和空运占比，与直接调用引擎的结果一致。
4. 修改参数（例如延误改为 3 周）后再确认，结果随之改变，不会沿用旧的计算缓存。
5. 备忘录包含方案对比表，网页上可以下载。
6. 回放模式显示录制来源；实时模式在没有 key 或没有设 token 上限时拒绝运行。
7. 命令行和网页各用一条命令启动。

### 启动方式

```bash
python -m pip install -c constraints.txt -e ".[planning,agent,ui]"
python -m planning_agent flow                                   # 命令行，规则模式，默认公告
python -m planning_agent flow --mode replay --case D13          # 命令行，录制回放
python -m planning_agent flow --notice "第5到8周海运延误1周，舱位减少20%，对 ASML 影响多大？"
python -m streamlit run planning_agent/app.py                   # 网页
```

## English

### Scope

A minimal business loop that a planner can operate, built on the existing planning engine and planning agent:

1. enter a carrier notice or disruption description;
2. see the parsed parameters and default assumptions, each linked to the text it came from;
3. confirm, optionally after editing;
4. solve the normal and disrupted plans, optionally with an emission cap and a probability-weighted hedge;
5. compare cost, service level, emissions and air share;
6. write a decision memo.

**Three parameter sources; every result states which one was used**:

| Mode | Parameters come from | Model call |
|---|---|---|
| Offline rule `rule` | the rule parser in `rules.py` | No; deterministic, limited wording |
| Recorded replay `replay` | scenario arguments a real model (gpt-6.1-sol, Responses API, xhigh) produced for cases D13 and H05 in the 24-question evaluation | No; labelled as a replay |
| Live model `live` | a model proposes arguments through the LangGraph agent, paused before any tool runs | Yes, paid; needs `LLM_API_KEY` and a token cap, with the budget approved by the user first |

In every mode the optimization is solved live after confirmation (MILP, HiGHS); no precomputed results are shown, and every number comes from the engine.

**Out of scope**: retrieval over real notices (RAG), memory across processes, multiple users and deployment. These are later milestones.

### Acceptance

1. In rule mode, the default notice (Red Sea diversion, weeks 4–12, ocean delay 2 weeks, space cut 30%) parses to ocean, weeks 4–12, +2 weeks, −30% capacity and distance factor 1.4183 (Suez to Cape). The default assumption (no freight change given, so 0) is listed, and each parameter shows its source text.
2. Nothing is solved before confirmation.
3. After confirmation, the normal and disrupted plans (and a capped plan when a cap is set) show total cost, change, service level, emissions and air share, identical to direct engine calls.
4. Editing a parameter (for example, a 3-week delay) and confirming again changes the result; no stale cache is reused.
5. The memo contains the plan comparison and can be downloaded from the web page.
6. Replay mode shows where the recording came from. Live mode refuses to run without a key or without a token cap.
7. The command line and the web page each start with one command.

### How to run

```bash
python -m pip install -c constraints.txt -e ".[planning,agent,ui]"
python -m planning_agent flow
python -m planning_agent flow --mode replay --case D13
python -m planning_agent flow --notice "Weeks 5-8 ocean delayed 1 week, capacity cut 20%: impact on ASML?"
python -m streamlit run planning_agent/app.py
```
