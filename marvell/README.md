# Marvell-inspired：fabless 物流与库存联合规划

研究可发货产品从两个来源池向新加坡区域仓补货时，运输方式、库存资金占用与物流碳预算的取舍。模型使用已承诺订单和已公告扰动，按周求解有限期混合整数规划。网络受 Marvell 的 fabless 供应链启发；SKU 箱、订单、货值、费率和容量为仿真参数。制造释放量作为外生输入，核算范围为运输及仓储，不含制造隐含碳和货损。

## 网络与参数

两个来源池的 SKU 资格固定，各池跨运输模式共享释放容量。箱为本实验的归一化订货单位。完整参数见 [config.json](config.json)，通用模型见 [methodology.md](../docs/methodology.md)。

| 来源池 | 路线与基础提前期 | 合格 SKU |
| --- | --- | --- |
| TW | `TW_air`：1 周；`TW_ocean`：3 周 | `switch_carton`、`network_controller_carton` |
| MY | `MY_air`：1 周；`MY_road`：1 周 | `storage_controller_carton`、`custom_silicon_carton` |

| 项目 | 设置 |
| --- | --- |
| 时间 | 16 周；10 份合成订单簿，种子 100–109 |
| 基础周均订单 | 30、20、25、15 箱；零订单概率 5%；第 9–10 周加入大单压力 |
| 箱重 | 1.5、2.0、1.2、2.5 kg |
| 箱货值 | 15,000、22,000、18,000、30,000 假设美元 |
| 运费 | 空运 5.5、海运 0.6、公路 0.7 美元/kg |
| 运力 | 每条路线 140 箱/周；TW、MY 各池共享释放量 160 箱/周 |
| 持有成本 | 年资本持有率 20%；仓储费 0.4 美元/箱周 |
| 服务 | 每周期末积压为 0；期末库存至少恢复至初始库存；初始在途为 0 |

初始库存为基础周均订单的 4 倍，并至少覆盖首周订单；同一实例的所有策略使用相同初始状态和服务约束。成本包含运费、在途资金占用及现货持有成本。

航空、海运和公路排放代理因子分别为 0.66646、0.01977 和 0.12715 kgCO₂e/吨公里，均包含燃料 WTT；航空因子已包含距离修正。仓储排放采用 0.04 kgCO₂e/箱周的情景系数。机场大圆距离、说明性海运/公路距离及来源适用性见 [Marvell 数据审计](../data_sources/data_audit_marvell.md)和[排放因子记录](../data_sources/selected_emission_factors.json)。

## 实验

每份订单簿比较 `cost_only`、`fast_only`、`slow_only` 及 `carbon_minus10`、`carbon_minus25`、`carbon_minus50`，共 `3 × 10 × 6 = 180` 次求解。碳预算以同一实例 `cost_only` 的物流排放为基准，再最小化成本。

| 情景 | 参数变化 |
| --- | --- |
| `normal` | 基础网络 |
| `ocean_delay` | 第 5–9 周派发的 TW 海运和 MY 公路提前期各增加 1 周 |
| `capacity_restriction` | 第 7–9 周 TW 空运容量降至 12 箱/周，MY 公路降至 10 箱/周 |

## 结果

180 次求解中有 177 份可行最优计划，3 份不可行记录均来自 `slow_only`。求解器相对 MIP gap 容差为 `1e-4`。下表两策略在每个情景均为 10/10 可行，成本与排放分别为 10 份匹配订单簿的均值，单位为假设美元和 kgCO₂e。

| 情景 | 基准成本 | 25% 碳预算成本 | 成本增加 | 基准排放 | 25% 碳预算排放 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 正常 | 207,267.72 | 230,273.61 | 11.10% | 3,231.99 | 2,423.46 |
| 海运/公路延误 | 209,207.07 | 232,736.14 | 11.25% | 3,291.54 | 2,468.11 |
| 路线限容 | 226,634.53 | 243,852.11 | 7.60% | 2,811.44 | 2,107.86 |

常态下，25% 碳预算使空运质量份额从 56.13% 降至 41.37%，平均现货库存从 63.675 箱降至 58.25 箱，同时增加在途资金占用。碳降幅由预算约束规定，本实验考察在相同周度服务要求下的可行性、成本和库存位置变化。

[results/](results/) 发布 180 条求解记录、30 份合成实例和 177 份可行计划，包含状态、最优间隙、成本拆分及逐期库存轨迹。完整汇总见 [study_report.md](../reports/study_report.md)。共享归档汇总覆盖两个项目共 400 次求解，其中包含 ASML 的 40 次外部汽车备件需求压力测试；Marvell 明细均为合成周度实验。

## 通知接入

早期接口试点保留 6 条 Marvell 合成通知，涉及提前期、路线容量、来源释放量、碳预算、运费和信息不足场景。保存的抽取结果经允许列表编译为参数更新；延误与容量通知各在 10 份订单簿上重放，记录见 [notice_pilot.json](../reports/notice_pilot.json)。独立文本测试、固定模型 API 记录和多步工具审计见 [benchmark.md](../docs/benchmark.md)。

## 复现

在仓库根目录运行：

```bash
python -m pip install -c constraints.txt -e .
semiconductor-logistics download-data
semiconductor-logistics optimize --project marvell --smoke
semiconductor-logistics optimize --project marvell
semiconductor-logistics sensitivity --project marvell
semiconductor-logistics report
```

`--smoke` 使用一份合成订单簿。完整运行写入 `reports/`；使用 `--project both` 可生成两个项目的联合结果。
