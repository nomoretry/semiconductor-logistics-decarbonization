# 供应链计划副驾驶 PRD / Supply-chain planning copilot PRD

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; the English version follows the Chinese text.

## 中文

### 背景与问题

半导体物流的计划决策经常由外部事件触发：船公司发布红海绕行公告、台风封港、客户临时拉高需求，或者管理层提出“今年物流排放降 25%”。计划员需要很快回答三个问题：成本和排放会变多少？瓶颈在哪？要不要提前做准备（备货、预留空运舱位）？

现在通常的做法是：计划员把问题转给运筹或数据团队，对方改模型、跑一轮、整理表格，周期以天计；而且答案很难追溯到具体假设。

### 目标用户与场景

| 用户 | 典型问题 | 现在的痛点 |
|---|---|---|
| 区域物流计划员 | “公告说第 4–12 周海运延误 2 周、舱位减 30%，影响多大？” | 依赖他人建模，响应慢 |
| 供应链产品经理 / 经理 | “减排 25% 要多花多少？值不值？” | 拿不到边际成本，难以权衡 |
| 采购 / 运力经理 | “红海出事概率 25%，季前要不要多订空运舱位？” | 只能凭经验判断对冲力度 |

### 产品目标与衡量指标

| 指标 | 定义 | MVP 目标 |
|---|---|---|
| 决策时间 | 从提问到拿到有数字依据的回答 | 从“天”缩短到“分钟” |
| 数字准确率 | 评测集中回答包含引擎重算的金标准数字的比例 | ≥ 95%（开发集） |
| 数字忠实度 | 回答中每个数字都能追溯到工具结果 | 100%（护栏强制） |
| 工具选择召回率 | 调用了应调用的工具 | ≥ 90% |
| 业务价值 | 对冲方案相对名义计划节省的期望成本（VSS） | 在报告中量化，不预设 |

### MVP 功能范围

- 查看网络：线路、运力、单位排放、预设场景。
- 把公告或假设建模为扰动场景，没给的参数列为假设。
- 求解库存—运输计划（MILP），支持碳上限、碳价、服务水平。
- 方案对比（差值由工具计算），解释瓶颈、成本构成和影子价格。
- 减排成本曲线：边际减排成本与可达的最低排放。
- 两阶段随机对冲：输出 VSS、EVPI 和第一阶段建议（舱位预留、提前发货）。
- 生成决策备忘录（Markdown）。

**不做（非目标）**：不直接订舱下单；不接 ERP/TMS；不做需求预测；不替代人工审批。

### 方案设计

单个 LLM Agent 加 8 个工具，运筹引擎负责全部计算，数字护栏把关输出。没有 LLM 密钥时由规则 Agent 兜底，保证离线可用。详见 [Agent 设计](planning_agent.md) 和 [运筹模型](network_planning.md)。

人在回路：Agent 只给建议和备忘录，执行（订舱、调拨）仍由计划员确认。

### 风险与对策

| 风险 | 对策 |
|---|---|
| 大模型编造数字 | 所有数字来自工具；护栏逐个核对，不通过就要求重写或标注 |
| 误解用户意图 | 关键信息缺失时先澄清；评测集覆盖改写、英文、多意图问题 |
| 假设不透明 | create_scenario 返回 assumptions；备忘录固定附“假设与局限” |
| 求解太慢影响体验 | 战术层用连续流量 + 0/1 线路启用，单次求解约 0.2–3 秒；整数版本可选 |
| 数据质量 | 当前为合成情景，接真实数据前需要做数据校验与口径对齐 |
| 密钥安全 | API key 只通过环境变量读取，不写入文件和日志 |

### 路线图

1. **M1（已完成）**：运筹引擎、规则 Agent、工具层、护栏、评测集、离线 CI。
2. **M2**：接入 LLM（DeepSeek / Qwen / OpenAI 兼容接口），在 24 条评测上与规则 Agent 对比；扩充到 100 条并请业务同事独立出题。
3. **M3**：Web 界面（对话 + KPI 卡片 + 前沿图）；接入真实运价、运力与订单数据。
4. **M4**：多仓选址、滚动计划、CVaR 等风险偏好。

### 成功标准

M2 结束时：LLM Agent 在鲁棒性集上的成功率明显高于规则 Agent，数字忠实度保持 100%，单个问题的中位响应时间在 1 分钟以内。

## English

**Problem.** Semiconductor logistics decisions are triggered by events (carrier advisories, typhoons, demand spikes, emission targets). Planners need fast, traceable answers on cost, emissions, bottlenecks and whether to hedge; today this takes an analyst days.

**Users.** Regional logistics planners, supply-chain product managers, capacity and procurement managers.

**Goals and metrics.** Decision time from days to minutes; fact accuracy >= 95% on the development questions; 100% numeric faithfulness (enforced by the guardrail); tool recall >= 90%; hedging value (VSS) quantified per network.

**MVP scope.** Network inspection, scenario creation from notices, MILP planning with carbon caps/prices and service floors, plan comparison and explanation, abatement-cost frontier, two-stage hedging with VSS/EVPI and first-stage advice, decision memos. Non-goals: booking execution, ERP/TMS integration, demand forecasting, replacing approval.

**Design.** One LLM agent with eight tools; the OR engine does all arithmetic; a numeric guardrail checks every number; an offline rule agent is the fallback. Humans approve execution.

**Risks.** Hallucinated numbers (tool-only numbers + guardrail), misread intent (clarifying questions + evaluation set), hidden assumptions (explicit assumption lists), latency (continuous tactical flows), data quality (synthetic today), key safety (environment variables only).

**Roadmap.** M1 engine, rule agent, guardrail, evaluation and CI (done); M2 LLM comparison and 100 independent questions; M3 web UI and real data; M4 multi-warehouse design, rolling planning and risk measures.
