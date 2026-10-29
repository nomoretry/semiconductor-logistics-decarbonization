# ASML 子项目：公开数据核验与使用边界

核验日期：2026-10-30。以下材料用于业务动机、路线和因子溯源；实验中的订单、SKU质量、运价、持有成本和仓储系数仍需明确标为合成或假设。

## 有边界的数据搜索

本轮定向检查ASML及相似半导体设备／工业备件企业的公开业务页面、年度报告和数据集入口，未发现可直接下载、可联合使用的SKU需求、库存、补货提前期与运价面板。这不证明该类数据从未公开，也不代表取得了企业内部运营数据。

| 对象与原始来源 | 找到的材料 | 第一版能支持什么 | 未取得什么 |
| --- | --- | --- | --- |
| [ASML 2025年报](https://www.sec.gov/Archives/edgar/data/937966/000162828026011377/asml-2025xannualxreportx.htm)，物流段164–165页 | 空运转海运计划、运输／外包仓储范围及汇总排放 | 库存与运输方式联合决策的现实动机 | SKU订单、库存轨迹、合同运价、实际每票提前期 |
| [ASML客户支持](https://www.asml.com/en/products/customer-support) | 靠近客户配置备件库存、服务指标和受保护CustomerNet入口 | 在区域仓配置库存、以服务约束控制补货的设计背景 | 公开可下载SKU运营数据 |
| [Applied Materials Supply Chain Solutions](https://www.appliedmaterials.com/eu/en/supply-chain-solutions.html) | Forecast Parts Management、OnDemand备件和全球备件网络 | 近客户库存、计划补货与紧急补货作为相似业务机制 | 客户级需求、库存、运价数据 |
| [Lam Research Spares](https://www.lamresearch.com/customer-support/spares/) | 全球配送中心及库存规划；具体方案引导MyLam或代表 | 配送中心与备件可用性背景 | 开放SKU级历史面板 |
| [SKF SIMO说明](https://de.promo.skf.com/acton/attachment/21301/f-076e6154-c81e-4f0f-8da6-8595d2ecb35a/0/-/-/-/file.pdf) | 需求、关键性、价格、提前期与库存优化流程 | 决策变量和成本／服务指标的相似业务依据 | 原始企业需求和库存表 |
| [KLA 2026年度报告](https://ir.kla.com/sec-filings/annual-reports/content/0000319201-26-000027/klac-20260630.htm) | 客户服务备件库存等财务汇总、供货中断背景 | 备件库存与供应风险确为相关业务议题 | SKU数量、逐期库存和每票运输数据 |

ASML年报中的物流汇总量、空运转海运的潜在收益不能当作本模型的路线因子或校准目标。本项目是ASML业务启发的仿真实验，不是对ASML真实运营的优化结果。

## 场景边界

第一版将荷兰供应点至新加坡区域仓的海运／空运补货与区域库存联合考虑。该网络是可复现的代表性设计，不是已核实的ASML具体备件流。按用户要求不建模货损风险。

ASML支持页面提及24小时备件服务能力；周度模型中的缺货期比例、周内需求满足率不能直接解释成这一24小时KPI。运输成本和库存成本应与服务约束一起比较。

## 公开路线数据

[鹿特丹港官方2024年说明](https://www.portofrotterdam.com/en/news-and-press-releases/impact-of-red-sea-unrest-on-rotterdam-throughput-expected-to-be-slight)给出新加坡—鹿特丹经苏伊士8,288海里（15,349公里），绕好望角11,755海里（21,770公里），并说明当时集装箱航程增加8–12天。
[苏伊士运河管理局距离表](https://www.suezcanal.gov.eg/English/About/Pages/WhySuezCanal.aspx)独立给出相同海里距离。模型采用发布的取整公里数；这些是历史走廊几何与扰动背景，不是2026年实时航线或船期。

[OurAirports原始开放数据](https://ourairports.com/data/)提供机场坐标，许可为Public Domain。`airport_coordinates.json`记录本次抓取的AMS、SIN、TPE与KUL坐标、上游CSV哈希及Haversine计算结果。地球半径取6,371公里：

| 航段 | 派生大圆距离，公里 |
| --- | ---: |
| AMS—SIN | 10,513.91347 |
| TPE—SIN | 3,222.38288 |
| KUL—SIN | 297.47223 |

大圆距离不等于实际飞行轨迹。下述DESNZ航空因子已含8%距离修正，不能再将距离乘1.08。

## 排放因子

采用[UK DESNZ 2026官方因子](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2026)作为可审计的代理参数。原始修订平表保存在`raw/ghg_factors_2026_flat_revised.xlsx`，6条选定原始记录的ID、行号、单位与组合逻辑见`selected_emission_factors.json`。

国际非英国航空不含RF的运营因子0.53130，加燃料WTT 0.13516，合计0.66646；平均集装箱船0.01612，加WTT 0.00365，合计0.01977，单位均为kg CO2e／tonne.km。含RF的航空合计1.03455另做气候影响敏感性。官方说明推荐考虑航空非CO2间接影响，同时提示其不确定性。

计算为“单位数×假设每件毛重kg÷1,000×距离km×因子”。这些是英国报告均值向境外运输的代理转用，不是企业实测值。货物体积、装载率和特殊运输设备可能导致实际值不同。

仓储排放需另行核算。主实验若使用0.04 kgCO2e／件·周，它是未验证的情景假设，不是从这些交通因子、ASML或EMA数据推导的结果。EMA最新统计覆盖至2025年，但本轮Excel下载被拦截，未核验其最新数值，因此不引用未经核实的最新电网因子。

## 可用的真实相似需求

已找到并下载Monash发布的真实汽车备件月度需求数据；它能支持间歇需求分布校准或单独的月度鲁棒性检验，但没有配套库存和运价。详见`carpartsREADME.md`。不得把汽车需求改名为ASML需求，也不得直接把月度观测当作周度事实。
