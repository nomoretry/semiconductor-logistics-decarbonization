# 静态模型与公告方法 / Static optimization and notice methods

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

本文限定原已知订单实验；后续查询学习与未知需求模型见[架构](architecture.md)和[研究说明](research_guide.md)。

## 中文

项目研究已知订单与已公告扰动下的物流规划：先将运输通知转成参数修改，再在相同服务约束下求解运输、库存与碳预算。ASML 和 Marvell 是业务启发的仿真场景；订单、SKU、成本和能力参数见各自配置，公开数据来源见 `data_sources/`。

## 通知接口

独立文本基准只处理 `NL_ocean` 的整数周提前期增量。抽取器输入为通知文本和业务上下文，输出示例为：

```json
{
  "status": "ready",
  "changes": [
    {
      "op": "add_lead",
      "route": "NL_ocean",
      "start_week": 5,
      "end_week": 9,
      "value": 2
    }
  ]
}
```

周窗口从 1 开始且包含两端，按发运周应用。`ready` 与空变更列表表示明确无需更新；`needs_clarification` 必须带空变更列表。缺少关键字段、冲突未消解、范围值未确定或天数无法整周换算时，需要澄清。到货窗口不能直接替代发运窗口。

`normalize_output` 拒绝额外字段、重复修改、无效数值及不支持的操作，仅规范化变更顺序。`compile_notice` 检查路线与规划范围，再生成分期参数。共享编译器还支持距离、运力、运价、来源释放量和碳预算修改，供两个场景的早期通知重放使用；这些操作不属于当前独立文本基准。

## 物流规划

设周期为 $t$、路线为 $j$、SKU 为 $k$。决策 $q_{tjk}$ 是非负整数发运量；$I_{tk}$、$B_{tk}$ 分别为期末现货和积压。提前期 $L_{tj}$ 取决于发运期，到货量由已承诺在途 $a_{tk}$ 和新发运共同决定：

$$
I_{tk}-B_{tk}=I_{t-1,k}-B_{t-1,k}+a_{tk}
+\sum_{s,j:s+L_{sj}=t}q_{sjk}-d_{tk}.
$$

初始净库存给定。当前实验要求每期 $B_{tk}=0$，且期末库存不低于共同初始库存。规划期外才到货的新发运被禁止。路线容量与来源共享容量均按 SKU 单位总数约束，路线资格矩阵限制可发运的 SKU。

设每件质量 $m_k$、货值 $v_k$、年资金占用率 $r$、每年周期数 $P$、每公斤运价 $f_{tj}$ 和仓储费用 $w_k$。目标为最小化运费、在途资金占用和现货持有费用：

$$
C=\sum_{t,j,k}q_{tjk}\left(m_kf_{tj}+\frac{v_krL_{tj}}{P}\right)
+\sum_{t,k}I_{tk}\left(\frac{v_kr}{P}+w_k\right).
$$

周度实验取 $P=52$，月度压力测试取 $P=12$。求解器支持积压罚金，但当前实验通过零积压硬约束保持各策略服务条件一致。

物流排放由运输和库存相关仓储分配排放组成：

$$
E=\sum_{t,j,k}q_{tjk}\frac{m_k}{1000}\,\ell_{tj}\,e_j
+\sum_{t,k}I_{tk}w^E_k.
$$

$\ell_{tj}$ 为公里距离，$e_j$ 为 kgCO₂e/吨公里因子。航空因子已含其距离修正，WTT 也只计一次。制造、产品隐含碳、货损、车辆制造和固定仓库能源不在本模型中。

## 策略与求解

| 策略 | 约束 |
| --- | --- |
| `cost_only` | 在共同服务条件下最小化成本 |
| `fast_only` | 仅允许空运 |
| `slow_only` | 仅允许非空运路线 |
| `carbon_minus10` | $E\leq0.90E_{cost}$ |
| `carbon_minus25` | $E\leq0.75E_{cost}$ |
| `carbon_minus50` | $E\leq0.50E_{cost}$ |

$E_{cost}$ 来自同一订单簿、同一扰动与同一服务约束下的 `cost_only` 解。由 SciPy `milp` 调用 HiGHS，实验设置相对 MIP gap 为 `1e-4`。`success` 表示存在经校验的可行计划，`optimal` 表示求解器在设定容差内正常终止；不可行与无 incumbent 的记录保留空成本和排放值。

均值按可行子集计算，并同时报告可行数。策略间费用或排放比较使用共同可行的匹配实例。周末零积压是模型约束，与日内交付服务指标分别解释。

## 文本与工作流评分

文本主指标是整条通知的结构精确匹配：状态及全部变更均正确才计 1。无效或缺失输出计为失败。另报告 JSON/schema 有效性、字段准确率、可执行输出覆盖率和信息不足时误报 `ready` 的比例。

次指标将增量展开成路线—周提前期表后比较，可识别不同区间分解产生的相同规划效果。澄清匹配单独计数。事件 Wilson 区间和模板族 bootstrap 区间对应不同统计单位；合成模板的相关性与真实来源范围见[基准说明](benchmark.md)。

工具环境终局成功定义为以下两种结果之一：

1. 提交计划在参考配置下可行，且编译参数与参考一致。
2. 参考确实缺少信息，工作流完成澄清交接。

可见审计按抽取配置执行，终局审计按隐藏参考配置重建发运结果。报告分别保留可行计划、正确交接和不必要交接。环境奖励为终局成功 `+1`、失败 `-1`，每步扣 `0.01`，无效动作再扣 `0.2`；该奖励衡量流程完成与工具成本，未优化企业经营收益。


## English

This document concerns the original known-order experiments. Later query learning and unknown-demand control have distinct contracts, explained in the [architecture](architecture.md) and [research guide](research_guide.md).

### Notice interface

The project first converts transport notices into parameter changes, then optimizes transport, inventory and carbon under matched service constraints. ASML and Marvell are company-inspired simulations; orders, SKUs, costs and capacities are explicit configuration assumptions, with public sources in `data_sources/`.

The independent text benchmark accepts only integer-week lead-time increments on `NL_ocean`. The JSON example in the Chinese section adds two weeks to dispatches in weeks 5 through 9 inclusive. Week indices start at one. `ready` with an empty change list explicitly means no update; `needs_clarification` requires an empty list. Missing fields, unresolved conflicts, uncertain ranges and non-integral day-to-week conversions require clarification. Arrival windows cannot substitute for dispatch windows.

`normalize_output` rejects extra fields, duplicate changes, invalid values and unsupported operations, normalizing only change order. `compile_notice` checks route and horizon before producing period parameters. The shared compiler also supports distance, capacity, freight, source releases and carbon budgets for early scenario replay; these operations are outside the independent text benchmark.

### Static logistics model

Let t index periods, j routes and k SKUs. Nonnegative integer shipments are q, with end-period stock I and backlog B. The inventory-balance equation above accounts for old pipeline arrivals a and new shipments arriving according to dispatch-period lead time L. Initial net inventory is fixed. These experiments enforce B=0 every period and final inventory no lower than the common initial inventory. New shipments arriving beyond the horizon are prohibited. Route and shared source capacities use SKU unit counts; an eligibility matrix restricts route–SKU assignments.

The objective equation above sums freight, capital tied up in transit and on-hand holding/storage. Its parameters are item mass m, item value v, annual carrying rate r, periods per year P, per-kilogram freight f and warehouse holding charge w. Weekly experiments use P=52; monthly stress tests use P=12. The solver supports backlog penalties, but these static experiments impose no backlog to match service conditions.

Emissions E combine transport and allocated inventory-related warehouse emissions, as defined above. Distance is measured in km; transport factors are kgCO₂e per tonne-km. The aviation factor already includes distance adjustment, and well-to-tank emissions are counted once. Manufacturing, embodied product carbon, damage, vehicle production and fixed warehouse energy are excluded.

### Policies and solution status

| Policy | Restriction |
|---|---|
| `cost_only` | Minimize cost under common service conditions |
| `fast_only` | Air routes only |
| `slow_only` | Non-air routes only |
| `carbon_minus10` | E≤0.90×matched cost-only emissions |
| `carbon_minus25` | E≤0.75×matched cost-only emissions |
| `carbon_minus50` | E≤0.50×matched cost-only emissions |

The reference emissions come from identical orders, disruption and service constraints. SciPy `milp` calls HiGHS with relative MIP gap 1e-4. `success` means a validated feasible plan exists; `optimal` means normal termination within the configured tolerance. Infeasible cases and runs without incumbents retain missing costs/emissions, not zeros.

Means use feasible subsets and report their counts. Pairwise cost/emission comparisons use matched commonly feasible instances. End-of-week no-backlog constraints are not intraday service measurements.

### Text and workflow evaluation

The primary text metric is whole-notice structural exact match: status and every change must be correct. Invalid/missing outputs fail. Additional metrics cover JSON/schema validity, fields, actionable coverage and false `ready` decisions when information is incomplete.

A secondary measure expands changes into route-by-week lead-time tables, detecting equivalent effects from different interval decompositions. Clarification agreement is counted separately. Event Wilson intervals and template-family bootstrap intervals use different statistical units; synthetic dependence and real-source scope are documented in the [benchmark](benchmark.md).

Workflow terminal success is either a committed plan feasible under the reference configuration with matching compiled parameters, or a correct clarification handoff when the reference lacks information. The visible audit uses extracted parameters; terminal evaluation reconstructs shipments under hidden reference parameters. Reports separate feasible plans, correct handoffs and unnecessary handoffs. Reward is+1 for terminal success,−1 for failure,−0.01 per step and a further−0.2 for invalid actions. This rewards process completion and tool cost, not measured enterprise profitability.
