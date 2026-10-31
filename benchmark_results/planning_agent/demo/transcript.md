# Planning agent demo (rule agent)

## 问：介绍一下 ASML 备件网络有哪些运输线路，各自运力多少？

**工具调用**：`describe_network({"network": "asml"})`

asml 网络：12 个 SKU，16 周承诺需求 1,132 件。线路：
- NL_air（air）：提前期 1 周，运费 5.0 美元/kg，周运力 803.8 kg，每 kg 货物排放 7.007 kgCO2e
- NL_ocean（ocean）：提前期 5 周，运费 0.35 美元/kg，周运力 1,507.1 kg，每 kg 货物排放 0.303 kgCO2e
说明：SKU、需求、容量、费率和扰动幅度为合成情景假设；距离与排放因子来自公开来源。

*护栏：通过；0.07 秒*

## 问：船公司通知：受红海安全局势影响，第4到12周亚欧航线绕行好望角，海运延误2周，舱位削减30%。这对我们新加坡备件仓的成本和排放有什么影响？

**工具调用**：`create_scenario({"network": "asml", "name": "custom_red_sea_w4_12", "disruptions": [{"mode": "ocean", "start_week": 4, "end_week": 12, "extra_lead_weeks": 2, "capacity_change_pct": -30, "distance_factor": 1.4183}]})`, `solve_plan({"network": "asml"})`, `solve_plan({"network": "asml", "scenario": "custom_red_sea_w4_12"})`, `compare_plans({"plan_ids": ["P1", "P2"]})`

建模假设：NL_ocean weeks 4-12: cost_change_pct not given, assumed 0
方案 P2（custom_red_sea_w4_12）：总物流成本 60,711 美元，比正常方案 P1 增加 5,458 美元（+9.88%）；排放 27.12 吨（+30.26%）；空运占比 26.2%；服务水平 100.0%。
说明：SKU、需求、容量、费率和扰动幅度为合成情景假设；距离与排放因子来自公开来源。

*护栏：通过；3.33 秒*

## 问：如果在这种情况下还要求减排 25%，成本代价是多少？瓶颈在哪？

**工具调用**：`solve_plan({"network": "asml"})`, `solve_plan({"network": "asml", "scenario": "custom_red_sea_w4_12", "carbon_cap_pct": 75})`, `compare_plans({"plan_ids": ["P1", "P3"]})`, `explain_plan({"plan_id": "P3"})`

方案 P3（custom_red_sea_w4_12 / cap 75%）：总物流成本 62,271 美元，比正常方案 P1 增加 7,018 美元（+12.70%）；排放 20.34 吨（-2.31%）；空运占比 18.2%；服务水平 100.0%。
碳约束的影子价格约 396 美元/吨，即在该上限下每多减 1 吨的边际成本。
主要成本项：transit_capital 29,907 美元（48.0%），freight 16,079 美元（25.8%），holding 10,131 美元（16.3%）。
接近满载的线路：NL_ocean 第 2 周（100.0%），NL_ocean 第 3 周（100.0%），NL_ocean 第 4 周（100.0%）。
说明：SKU、需求、容量、费率和扰动幅度为合成情景假设；距离与排放因子来自公开来源。

*护栏：通过；2.93 秒*

## 问：红海中断大概有 25% 的概率发生，要不要提前对冲？

**工具调用**：`solve_plan({"network": "asml"})`, `solve_plan({"network": "asml", "scenario": "red_sea"})`, `compare_plans({"plan_ids": ["P1", "P4"]})`, `hedge_disruption_risk({"network": "asml", "scenarios": ["normal", "red_sea"], "probabilities": [75, 25]})`

方案 P4（red_sea）：总物流成本 62,095 美元，比正常方案 P1 增加 6,842 美元（+12.38%）；排放 26.73 吨（+28.39%）；空运占比 25.7%；服务水平 100.0%。
两阶段随机方案（第 3 周才知道是否中断）：期望成本 57,154 美元；按正常预测计划、事后再应变为 58,018 美元；VSS = 864 美元（1.51%），EVPI = 190 美元（0.33%）。
- normal（75.0%）：随机方案 55,435，名义方案 55,253，差额 -181 美元
- red_sea（25.0%）：随机方案 62,310，名义方案 66,311，差额 4,001 美元
第一阶段建议：reserve 199.1 kg/week of NL_air block space (nominal plan: 164.1)；ship 1766.8 kg on NL_ocean before week 3 (nominal plan: 931)
说明：SKU、需求、容量、费率和扰动幅度为合成情景假设；距离与排放因子来自公开来源。

*护栏：通过；12.75 秒*

## 问：把结论写成备忘录给物流经理。

**工具调用**：`write_memo({"plan_ids": ["P1", "P2", "P3", "P4", "P5", "P6"], "question": "把结论写成备忘录给物流经理。"})`

备忘录已写入 benchmark_results/planning_agent/demo/memo-93dca21b91.md。
说明：SKU、需求、容量、费率和扰动幅度为合成情景假设；距离与排放因子来自公开来源。

*护栏：通过；0.01 秒*
