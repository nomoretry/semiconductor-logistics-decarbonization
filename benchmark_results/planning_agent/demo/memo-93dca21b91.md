# 物流方案决策备忘录

**问题**：把结论写成备忘录给物流经理。

## 结论

- 单一场景方案中成本最低：P1（normal），55,253 美元。
- 单一场景方案中排放最低：P3（custom_red_sea_w4_12 / cap 75%），20.34 吨 CO2e。
- 对冲：两阶段随机方案 P5 的期望成本 57,154 美元，按名义预测计划再应变（P6）为 58,018 美元，差额（VSS）864 美元。

## 单一场景方案对比

以 P1（normal）为基准。

| 方案 | 说明 | 总成本 USD | 变化 | 排放 t | 变化 | 空运占比 | 服务水平 |
|---|---|---:|---:|---:|---:|---:|---:|
| P1 | normal | 55,253 | +0.00% | 20.82 | +0.00% | 19.8% | 100.00% |
| P2 | custom_red_sea_w4_12 | 60,711 | +9.88% | 27.12 | +30.27% | 26.2% | 100.00% |
| P3 | custom_red_sea_w4_12 / cap 75% | 62,271 | +12.70% | 20.34 | -2.30% | 18.2% | 100.00% |
| P4 | red_sea | 62,095 | +12.38% | 26.73 | +28.38% | 25.7% | 100.00% |

## 对冲方案（按场景概率加权的期望值）

| 方案 | 说明 | 期望成本 USD | 期望排放 t | normal 成本 USD | red_sea 成本 USD |
|---|---|---:|---:|---:|---:|
| P5 | stochastic hedge | 57,154 | 22.28 | 55,435 | 62,310 |
| P6 | nominal plan, adapted after reveal | 58,018 | 23.49 | 55,253 | 66,311 |

场景概率：normal 75%，red_sea 25%。

## 驱动因素

- **P1**（normal 场景）：成本构成 transit_capital 43.3%，freight 30.4%，holding 15.0%；接近满载 NL_ocean 第 3 周，NL_ocean 第 10 周，NL_ocean 第 11 周；空运舱位预留 NL_air 164.1 kg/周。
- **P2**（custom_red_sea_w4_12 场景）：成本构成 transit_capital 39.6%，freight 34.7%，holding 14.7%；接近满载 NL_ocean 第 3 周，NL_ocean 第 4 周，NL_ocean 第 5 周；空运舱位预留 NL_air 212 kg/周。
- **P3**（custom_red_sea_w4_12 场景）：成本构成 transit_capital 48.0%，freight 25.8%，holding 16.3%；接近满载 NL_ocean 第 2 周，NL_ocean 第 3 周，NL_ocean 第 4 周；空运舱位预留 NL_air 150.5 kg/周。
- **P4**（red_sea 场景）：成本构成 transit_capital 39.3%，freight 35.1%，holding 14.6%；接近满载 NL_ocean 第 3 周，NL_ocean 第 4 周，NL_ocean 第 5 周；空运舱位预留 NL_air 238.6 kg/周。
- **P5**（normal 场景）：成本构成 transit_capital 43.0%，freight 30.3%，holding 15.0%；接近满载 NL_ocean 第 10 周，NL_ocean 第 11 周，NL_ocean 第 2 周；空运舱位预留 NL_air 199.1 kg/周。
- **P6**（normal 场景）：成本构成 transit_capital 43.3%，freight 30.4%，holding 15.0%；接近满载 NL_ocean 第 3 周，NL_ocean 第 10 周，NL_ocean 第 11 周；空运舱位预留 NL_air 164.1 kg/周。

## 假设与局限

- SKU、承诺需求、运力、费率和扰动幅度为合成情景假设；距离与排放因子来自公开来源（见 data_sources/）。
- 优化为期望成本最小（风险中性），需求为已知承诺订单；结果用于比较策略，不代表企业实测。
- 求解器 HiGHS，相对 MIP gap ≤ 0.2%。

*由 planning_agent 根据优化结果自动生成；表中数字均直接取自求解结果。*
