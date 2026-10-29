# ASML-inspired：备件库存与空海运联合规划

研究荷兰供应点向新加坡区域仓补货时，运输速度、库存资金占用与物流碳预算的取舍。模型使用已承诺订单和已公告扰动，按周求解有限期混合整数规划。网络受 ASML 备件业务启发；SKU、订单、货值、运价和容量为仿真参数，核算范围为运输及仓储，不含制造隐含碳和货损。

## 问题设置

完整参数见 [config.json](config.json)，通用模型见 [methodology.md](../docs/methodology.md)。

| 项目 | 设置 |
| --- | --- |
| 时间 | 16 周；10 份合成订单簿，种子 100–109 |
| SKU | `electrical_module`、`pump_kit`、`sensor_unit`、`actuator_kit` |
| 基础周均订单 | 5、8、3、6 件；零订单概率 25%；第 9–10 周加入大单压力 |
| 运输 | `NL_air`：提前期 1 周；`NL_ocean`：提前期 5 周 |
| 运力 | 每条路线 100 件/周；两种模式共享 NL 供货池 120 件/周 |
| 服务 | 每周期末积压为 0；期末库存至少恢复至初始库存；初始在途为 0 |
| 成本 | 运费、在途资金占用、现货资金占用与仓储费用 |
| 排放 | 运输质量 × 距离 × 模式因子，加现货仓储排放 |

初始库存按基础提前期和周均订单设置，并至少覆盖首周订单；同一实例的所有策略使用相同初始状态和服务约束。周末无积压是模型硬约束，与日内交付时效属于不同指标。

航空和海运排放代理因子分别为 0.66646 和 0.01977 kgCO₂e/吨公里，均包含燃料 WTT；航空因子已包含距离修正。仓储排放采用 0.04 kgCO₂e/件周的情景系数。来源与核算边界见 [ASML 数据审计](../data_sources/data_audit_asml.md)和[排放因子记录](../data_sources/selected_emission_factors.json)。

## 实验

每份订单簿比较 `cost_only`、`fast_only`、`slow_only` 及 `carbon_minus10`、`carbon_minus25`、`carbon_minus50`，共 `3 × 10 × 6 = 180` 次求解。碳预算以同一实例 `cost_only` 的物流排放为基准，再最小化成本。

| 情景 | 参数变化 |
| --- | --- |
| `normal` | 基础网络 |
| `ocean_delay` | 第 5–9 周派发的海运提前期增加 2 周，距离改为 21,770 km |
| `capacity_restriction` | 第 7–9 周空运全 SKU 合计容量降至 8 件/周 |

## 结果

下表比较纯成本最优与 25% 碳预算。两策略在每个情景均为 10/10 可行，成本与排放分别为 10 份匹配订单簿的均值，单位为假设美元和 kgCO₂e。

| 情景 | 基准成本 | 25% 碳预算成本 | 成本增加 | 基准排放 | 25% 碳预算排放 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 正常 | 22,985.67 | 23,940.38 | 4.15% | 8,222.96 | 6,131.47 |
| 海运延误 | 23,853.73 | 24,215.25 | 1.52% | 10,293.09 | 7,700.78 |
| 空运限容 | 23,259.05 | 24,098.80 | 3.61% | 7,842.41 | 5,858.00 |

每个情景中，仅海运为 5/10 可行，50% 碳预算为 9/10 可行。成本均值仅统计可行实例；跨策略比较需使用共同可行的实例集合。碳降幅由预算约束规定，本实验考察其可行性、成本代价及运输组合变化。

[results/](results/) 发布 180 条求解记录、30 份合成实例和 162 份可行计划，包含状态、最优间隙、成本拆分及逐期库存轨迹。完整汇总见 [study_report.md](../reports/study_report.md)。

## 外部需求压力测试

归档结果另含 Monash 汽车备件的月度需求压力测试：以前 39 个月筛选候选序列及估计均值，固定选择 40 条序列组成 10 组实例，最后 12 个月作为已承诺订单。提前期和持有系数按月转换，运输网络仍沿用本项目的情景参数。

该部分比较成本最优、仅空运、仅海运和 25% 碳预算，共 40 次求解，分别有 10、10、7、9 份可行解。共同可行的 9 组中，成本最优与 25% 碳预算的平均成本为 6,710.81 和 6,840.39，平均物流排放为 510.85 和 355.92 kgCO₂e。

因此 ASML 归档汇总覆盖 220 次求解；公开逐次明细仅覆盖上述 180 次合成周度实验。外部需求序列、选中序列 ID 和逐实例结果不在发布明细中，可下载原数据后重跑生成。数据处理见 [carpartsREADME.md](../data_sources/carpartsREADME.md)。

## 通知接入

早期接口试点保留 6 条 ASML 合成通知及保存的抽取结果，用于参数编译和计划重放，记录见 [notice_pilot.json](../reports/notice_pilot.json)。独立文本测试、固定模型 API 记录和多步工具审计见 [benchmark.md](../docs/benchmark.md)。

## 复现

在仓库根目录运行：

```bash
python -m pip install -c constraints.txt -e .
semiconductor-logistics download-data
semiconductor-logistics optimize --project asml --smoke
semiconductor-logistics optimize --project asml
semiconductor-logistics sensitivity --project asml
semiconductor-logistics report
```

`--smoke` 使用一份合成订单簿并跳过外部月度需求。完整运行写入 `reports/`；使用 `--project both` 可生成两个项目的联合结果。
