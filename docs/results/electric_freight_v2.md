# 电动重卡班次与充电设施的联合规划（model v2）/ Joint planning of electric truck trips and charging (model v2)

本文提供中英文版本，中文在前，英文在后。数字来自 [`benchmark_results/electric_freight_v2/`](../../benchmark_results/electric_freight_v2)（逐行结果 `runs.jsonl`，表格 `summary.md`），协议是 [`benchmarks/electric_freight_v2/protocol.json`](../../benchmarks/electric_freight_v2/protocol.json)。不调用模型，全部用本地 HiGHS 求解。订单来自 Marvell 启发网络的周计划；运输、车辆、电价和设备参数是带出处的假设或合成值，见 [`electric_freight/config_v2.json`](../../electric_freight/config_v2.json)。
This document provides Chinese first and English second. Numbers come from [`benchmark_results/electric_freight_v2/`](../../benchmark_results/electric_freight_v2) (per-run rows in `runs.jsonl`, tables in `summary.md`) under the protocol [`benchmarks/electric_freight_v2/protocol.json`](../../benchmarks/electric_freight_v2/protocol.json). No model is called; everything is solved locally with HiGHS. Orders come from the weekly plan of the Marvell-inspired network; transport, vehicle, tariff and equipment parameters are sourced assumptions or synthetic values, listed in [`electric_freight/config_v2.json`](../../electric_freight/config_v2.json).

## 中文

### 问题

马来西亚到新加坡的公路线路（`MY_road`）上，73 条芯片订单（16 周共 2,511.67 kg）搭承运人给其他客户跑的往返班次，空间不够时可以买溢价空间、加开班次或走空运。model v1 把加开班次当作固定费用。实际上，电动重卡每跑一趟都要占用一辆具体的车和它的充电时间，会改变充电时段、站点峰值，进而改变该装多大的充电设备。这里要回答：

1. 运输计划和充电设施分开做（先排车、再配设备）与一起做，差在哪里，什么条件下才有差别；
2. 设备和租车要在季节开始前定下，面对拥堵、空间紧张、需求上升和电网余量变化时，考虑不确定性值多少（VSS），完全信息值多少（EVPI）；
3. 电动比柴油贵多少，减排多少，结论对哪些价格敏感。

### 模型：model v2 新增的真实决策

代码在 [`electric_freight/fleet.py`](../../electric_freight/fleet.py)，独立核算在 [`electric_freight/fleet_accounting.py`](../../electric_freight/fleet_accounting.py)（每个方案的成本都由核算重新计算，与求解器目标值一致）。

- **周货物层**：每条订单在哪一周（周计划前后一周内）、走哪种方式（拼载空间、溢价空间、额外班次、空运兜底）；每一周属于哪种周型（通关条件 × 是否加开一个班次）。
- **小时车辆层**（每种周型一个 168 小时的代表周）：每趟背景往返由哪辆车、在 ±2 小时窗口内几点出发；额外班次由哪辆车、几点出发；在新加坡停留 4–12 小时；每辆车逐小时的电量（可用 590 kWh、下限 59 kWh、单程 457 kWh，拥堵时 467 kWh）；在哪个站、用哪档接口充多少电；接口按小时分时共用；站点容量和变电站余量。
- **第一阶段**（季节开始前定，所有情景共用）：开哪些站、每档接口几台、站点扩容、接哪座变电站、北站扩容、是否整季租一辆车。
- **成本**：班次（300 美元，夜班 +60、周日 +90、拥堵 +40）、等待（15 美元/小时）、电费、车场需量电费（19.84 美元/kW·月）、设备（10 年、8% 的资本回收，只算 16 周）、租车（1,000 美元/周）、货物持有/延误/溢价/空运；主结果碳价为 0。
- **代表周的边界**：所有车每周一 00:00 在车场、满电。这样同一周型的每一周是同一个问题，一个代表周对它们精确成立；这个边界本身是一个限制，用连续 16 周的模型核对它的代价（结果六）。

### 对比的方案

- **A 柴油**：同样的班次和货物规则，没有充电设备。
- **B 顺序**：第一步只排货物、班次和车辆，假设车停在哪里都有 150 kW、电价按 0.133 美元/kWh；第二步保持这个车辆计划，选设备和充电。
- **B\* 顺序（最好的平局选择）**：在和第一步同样便宜的车辆计划里，挑配上设备和充电后最便宜的一个。这是“先排车”流程能做到的最好情况。
- **C 联合**：货物、班次、车辆、设备和充电一起优化，从 B 和 B\* 中较好的一个出发，所以时间限制下 C 也不会比 B 差。

### 实验设计

- 三个实例：base（2 辆车，每周 6 趟背景往返）、dense（2 辆车，12 趟）、fleet（3 辆车，18 趟）。四个情景：normal；border_congestion（第 8–10 周通关 3 小时而不是 1 小时，拼载空间 ×0.6）；tight_space（拼载空间 200 kg）；grid_limited（200 kg 且北站余量 150 kW）。
- 每次求解 900 秒、相对间隙 0.1%，各执行一次。表中“可行”表示到时间限制时的解，括号里是间隙。
- 协议在第一次协议运行前提交；运行前用探索运行改过的求解设置写在协议的 `decided_before_running`；运行后才加的组（换求解器种子、从保存方案出发的局部搜索）在协议里注明加入时间和原因。
- 余下三组使用原协议及事先提交的[补充协议](../../benchmarks/electric_freight_v2/protocol_supplement_1.json)。两阶段分解和敏感性组沿用 900 秒上限，连续周期每项 1,800 秒，确定性等价为 3,600 秒。时间为共享机器实测。原清单对应提交 `6dadb43` 的文件。

### 结果一：A、B、B\*、C

成本是 16 周合计（美元）。

| 实例 | 情景 | A 柴油 | B | B\* | C | B − C | B\* − C | C − A |
|---|---|---|---|---|---|---|---|---|
| base | normal | 46,370.30 | 56,547.64 | 51,020.23 | 51,020.23（0.09%） | 5,527.40 | 0 | 4,649.93 |
| base | border_congestion | 49,827.08 | 59,943.52 | 54,509.18 | 54,509.18（0.08%） | 5,434.34 | 0 | 4,682.10 |
| base | tight_space | 47,225.87 | 58,010.02 | 53,119.34 | 52,308.63（可行，0.86%） | 5,701.39 | 810.71 | 5,082.75 |
| base | grid_limited | 47,225.87 | 58,010.02 | 53,119.34 | 52,308.63（可行，0.86%） | 5,701.39 | 810.71 | 5,082.75 |
| dense | normal | 92,740.61 | 98,724.05 | 98,599.27 | 98,599.27（0.10%） | 124.78 | 0 | 5,858.66 |
| dense | border_congestion | 97,078.09 | 122,677.75 | 122,677.75（可行，19.2%） | 122,677.75（可行，19.2%） | 0 | 0 | 25,599.66 |
| dense | tight_space | 93,716.18 | 103,004.22 | 101,865.09 | 100,084.86（0.10%） | 2,919.36 | 1,780.23 | 6,368.68 |
| dense | grid_limited | 93,716.18 | 103,004.22 | 101,854.10 | 100,084.86（0.10%） | 2,919.36 | 1,769.24 | 6,368.68 |
| fleet | normal | 144,870.91 | 146,626.23 | = B（可行，7.6%） | = B（可行，7.6%） | 0 | 0 | 1,755.32 |
| fleet | tight_space | 145,786.48 | 149,694.57 | = B（可行，9.5%） | = B（可行，9.5%） | 0 | 0 | 3,908.09 |
| fleet | grid_limited | 145,786.48 | 149,694.57 | = B（可行，9.5%） | = B（可行，9.5%） | 0 | 0 | 3,908.09 |
| fleet | border_congestion | 150,089.10 | 170,210.85 | = B（可行，17.0%） | = B（可行，17.0%） | 0 | 0 | 20,121.75 |

### 结果二：B 为什么贵——第一步随便选的车辆分配

第一步不关心哪辆车跑哪一趟，有许多同样便宜的排法，求解器碰到哪个用哪个。用 HiGHS 的随机种子 1–5 重跑 B（只改搜索顺序，模型不变），第一步的成本每次相同：

| 设定 | B，种子 0–5 | B − B\* |
|---|---|---|
| base normal | 56,547.64 / 56,699.36 / 57,051.14 / 57,735.71 / 56,747.69 / 57,723.35 | 5,527–6,715 |
| base tight_space | 58,010.02 / 63,512.65 / 59,521.87 / 64,915.83 / 59,405.44 / 64,908.07 | 4,891–11,796 |
| dense normal | 6 次都是 98,724.05 | 124.78 |

- base 每天 06:00 一趟，往返加周转只要 20 小时，一辆车就能跑完 6 趟。6 个种子每次都有车连续两天出车，回车场只停约 6 小时，车场必须装 150 kW 接口（峰值 70.9–85.1 kW，需量电费 5,000 美元以上）。B\* 和 C 让两车隔天轮流，每车在车场停约 30 小时，50 kW 接口就够（峰值 24.8 kW）。固定 T1 跑第一趟后，剩下 5 趟的分车方式有 32 种，完全隔天轮流只有 1 种，所以 B 贵是常态，不是偶然。
- dense 每车每 24 小时一趟，几乎只能轮流跑，6 个种子得到同一个计划。**运输计划里的空闲越多，先排车的流程可以随便选的地方越多，顺序规划的损失越大。**

### 结果三：联合规划比 B\* 好在哪里

结果一的 900 秒主求解在正常和拥堵情景中返回了相同成本的 B\* 与 C；结果七另列延长搜索得到的可行解。主求解中，背景往返的窗口只有 ±2 小时，挪动出发时刻要付夜班加价，而 B\* 已经在同样运输成本的计划里挑出了充电最省的一个。C 比 B\* 便宜的两处，都是多付运输成本、换更低的车场峰值：

- **base 紧情景（−810.71 美元）**：C 让 T2 在周一 00:00 跑第 15 周的额外班次（夜班多付 60 美元），车场峰值 42.3 → 30.4 kW，需量电费 3,091.46 → 2,220.75 美元；设备相同。
- **dense 紧情景（−1,780.23 美元）**：C **不开**第 15 周的额外班次，改为提前或延后、溢价空间和空运（持有 825、挤出 295、空运 366 美元，开班次时是 0 / 190 / 183），少付 510 美元班次费；车场峰值 126.9 → 84.3 kW，需量电费 9,274.39 → 6,157.80 美元。额外班次的真实边际成本包括它推高的约 3,100 美元需量电费，先排车的流程看不到这一项。
- grid_limited 与 tight_space 结果相同：HUB 只接一台 150 kW 接口，北站余量降到 150 kW 不起作用。

### 结果四：拥堵周电动车队要多一辆车

拥堵时单程 9 小时、耗电 467 kWh。车回到车场最多剩 123 kWh，下一趟出发要 526 kWh；车场接口最高 150 kW（效率 0.9），至少要 3 小时，比 2 小时的装卸周转多 1 小时，每个往返从 24 小时变成 25 小时。dense 两车、每车每 24 小时一趟（窗口 ±2 小时），6 趟累计多出 5 小时，超过窗口的 4 小时余量，排不下；柴油车不用充电，排得下。电动方案只能整季租第 3 辆车（16,000 美元），dense 拥堵情景 C − A = 25,599.66 美元。fleet 三车每 24 小时一趟，同理要租第 4 辆。线性松弛看不到这个整数时间约束，dense 拥堵的间隙停在 19%。

fleet 拥堵情景的 B 也租了第 4 辆车（16,000 美元），车场和 HUB 各一台 150 kW 接口，车场峰值 149.3 kW，C − A = 20,121.75 美元；B\* 和 C 从 B 出发，900 秒内没有改进（间隙 17%）。这一行最初报告为“B 不可行、B\* 和 C 无解”，原因是第二步固定货运量的方式有缺陷，不是充不上电，见“修正与负结果”。

### 结果五：边界扫描（base 实例）

每组扫描只改变一个参数。下列切换位置取自已保存的可行排班。美元均为 16 周合计。[51 条扫描记录及各行求解间隙](../../benchmark_results/electric_freight_v2/summary.md#boundary-sweeps-base-instance)

| 改变的条件 | B\* 与 C 的班次或设备决策 |
|---|---|
| 每周拼载空间 | 从 220 降至 215 kg 时，B\* 开始在第 15 周加班。C 在 215、210、205 kg 均不开，在 200 kg 开一趟（52,308.63 美元）。175 kg 时 B\* 加两趟、C 加一趟，150 kg 时两者均在第 14、15 周加班。|
| 持有成本倍数（200 kg） | 0 和 0.1 时两者均不加班。0.30、0.35、0.50 时 B\* 在第 15 周加班，C 仍不加班。0.30 时，两者成本分别为 53,119.34 和 51,913.11 美元。倍数回到 1 时两者均加班。|
| 新加坡北站余量（200 kg） | 250、213、212、150 kW 时，C 的成本均为 52,308.63 美元。107 kW 时仍用 HUB，取消加班，成本为 52,490.73 美元。106 kW 时改用接南站的 YARD，成本为 54,324.94 美元。这两个 C 解的间隙分别为 1.15% 和 3.90%。|

因此，在试过的空间水平中，顺序排班比联合排班更早加开班次。在北站余量扫描中，改变货运安排和改变充电地点出现在不同的试验点。未逐点证明最优的区段只能给出观察到的切换范围。

### 结果六：代表周与连续 16 周

保持逐周货物安排与加开班次数，连续模型只在季首和季末要求车辆回场、满电。车辆可跨过周一继续往返或充电，同一周型也可逐周采用不同排班。固定设备时只比较运营费用；放开时另计设备和租车。两列均扣除两种模型共有的货物费用。各行均从原方案拼接后的可行排班启动，达到 1,800 秒求解预算。区间下端为代表周成本减去连续模型的可行成本，上端为代表周成本减去其下界。单位为美元，按 16 周合计。[六项核算及求解界](../../benchmark_results/electric_freight_v2/runs.jsonl)

| 已保存的 C 方案 | 设备与租车 | 代表周 | 连续周期 | 状态与间隙 | 限制代价点估计 | 限制代价区间 |
|---|---|---:|---:|---|---:|---:|
| base / normal | 固定 | 42,537.02 | 42,444.12 | 可行，4.40% | 92.90 | 92.90 至 1,962.29 |
| base / normal | 放开 | 51,020.23 | 50,927.33 | 可行，8.47% | 92.90 | 92.90 至 4,406.67 |
| base / tight_space | 固定 | 43,452.87 | 43,031.26 | 可行，4.81% | 421.60 | 421.60 至 2,492.49 |
| base / tight_space | 放开 | 51,936.08 | 51,434.91 | 可行，8.57% | 501.17 | 501.17 至 4,910.12 |
| dense / normal | 固定 | 88,511.12 | 88,511.12 | 可行，5.33% | 0.00 | 0.00 至 4,716.29 |
| dense / normal | 放开 | 98,599.27 | 98,599.27 | 可行，6.22% | 0.00 | 0.00 至 6,134.75 |

base 正常季的需量费少了 120.74 美元，电费多了 27.84 美元，合计节省 92.90 美元。紧空间下，固定、放开两次求解分别省下 391.90、493.50 美元需量费，班次费都少了 60 美元。放开的求解仍选择原设备和租车安排，两个可行成本的差异来自搜到的运营排班。dense 两行的原始差值分别为 −0.000049、−0.000053 美元，来自已存代表周账单的舍入；两种排班在美分精度下相同。以上界限只适用于这三个已保存的方案，连续模型仍有优化空间。

### 结果七：fleet 规模——从保存方案出发的局部搜索

每组的 B\* 与 C 在原整模中得到相同的可行成本。搜索先固定已保存的班次重建起点，再逐步放开一辆车或一个 48 小时窗口，最多两轮。B\* 保留第一步的运输成本上限。表中最后一列给出最优 B\* 与最优 C 的成本差范围。下端利用 C 可以采用任一 B\* 方案，上端用 B\* 搜到的可行成本减去 C 的原整模下界。单位为美元，按 16 周合计。[搜索轨迹、原下界和用时](../../benchmark_results/electric_freight_v2/summary.md#fix-and-optimize-search-from-the-saved-plans)

| 实例与情景 | 搜索前成本 | 搜索后 B\* | 搜索后 C | 两个可行解之差 B\* − C | 最优成本差范围 |
|---|---:|---:|---:|---:|---:|
| dense / border_congestion | 122,677.75 | 118,315.88 | 117,405.41 | 910.47 | 0 至 19,147.13 |
| fleet / normal | 146,626.23 | 145,209.95 | 145,209.95 | 0.00 | 0 至 9,754.14 |
| fleet / tight_space | 149,694.57 | 146,079.87 | 146,079.87 | 0.00 | 0 至 10,536.01 |
| fleet / border_congestion | 170,210.85 | 165,348.67 | 165,377.19 | −28.52 | 0 至 24,110.75 |

fleet 拥堵情景中，两条启发式搜索走了不同的排班序列。B\* 搜到的可行解比 C 搜到的解低 28.52 美元，该解同样可供 C 使用。各区间都包含零。

### 结果八：两阶段随机规划（VSS 与 EVPI）

季前决定设备和整季租车，季初揭示全部情景。下表给出两套设备在六个情景中的 16 周核算成本（美元）。两者均在 MY_DEPOT 装一台 50 kW 接口、接 MY_SUB，在新加坡装一台 150 kW 接口、接 SG_SUB_N，均不扩容、不租车。新加坡设备分别安装在 HUB 和 YARD。六项概率均为假设。[逐情景求解、核算和设备记录](../../benchmark_results/electric_freight_v2/stochastic.json)

| 情景 | 概率 | HUB 方案 | YARD 方案 |
|---|---:|---:|---:|
| normal | 0.45 | 51,020.23 | 52,380.80 |
| border_congestion | 0.15 | 54,509.18 | 56,029.60 |
| tight_space | 0.15 | 52,308.63 | 53,866.39 |
| demand_surge | 0.10 | 51,005.14 | 52,380.80 |
| grid_cut | 0.10 | 52,308.63 | 53,866.39 |
| sg_window | 0.05 | 56,269.57 | 52,380.80 |
| 概率加权成本 | 1.00 | 52,126.63 | 53,299.52 |

两套设备在全部情景中均有可行排班。HUB 方案的季内设备成本为 8,483.22 美元，YARD 为 9,858.87 美元。YARD 仅在 HUB 白天限充且电价上涨的 sg_window 情景中更便宜，节省 3,888.77 美元，按 5% 概率加权为 194.44 美元。在其余五种情景中，YARD 每季多花 1,360.56 至 1,557.76 美元。综合六种情景，分解选中的 HUB 方案比 YARD 方案便宜 1,172.88 美元，与只按正常季规划的设备和租车决策一致。

| 量（16 周，美元） | 可行解点估计 | 最优值区间 |
|---|---:|---:|
| WS，预知情景后选择设备 | 51,932.19 | 51,784.02 至 51,932.19 |
| RP，季前统一选择设备 | 52,126.63 | 51,886.52 至 52,126.63 |
| EEV，固定正常季设备后分情景排班 | 52,126.63 | 51,820.57 至 52,126.63 |
| VSS = EEV − RP | 0.00 | 0.00 至 240.12 |
| EVPI = RP − WS | 194.44 | 0.00 至 342.62 |

六个情景共享一套设备的确定性等价模型返回同一方案，独立核算总额同为 52,126.63 美元。3,600 秒求解预算结束时下界为 51,886.52 美元，间隙为 0.46%。该下界适用于所有季前设备选择，收紧了 RP 和 VSS 的区间。VSS 的点估计为零，现有界仍允许更好的季前方案。[确定性等价及六份独立账单](../../benchmark_results/electric_freight_v2/stochastic_de.json)

### 结果九：敏感性

每行只改变 base 正常季的一项输入。成本差为 16 周美元，按独立核算的可行方案计算。最后两列比较 C 与正常季基准的设备和租车选择，并给出 C 的求解间隙。12 行的 B\* 与 C 成本均相同。[四种方案的成本、排放、车场峰值、状态与基准差值](../../benchmark_results/electric_freight_v2/summary.md#sensitivity-of-the-base-instance-in-the-normal-season)

| 改变的输入 | C − A | B − C | B\* − C | C 设备与租车 | C 间隙 |
|---|---:|---:|---:|---|---:|
| 碳价 100 美元/t CO₂e | 4,139.41 | 5,402.99 | 0.00 | 相同 | 0.06% |
| 碳价 300 美元/t CO₂e | 3,148.57 | 5,123.98 | 0.00 | 相同 | 0.10% |
| 碳价 400 美元/t CO₂e | 2,383.11 | 5,240.96 | 0.00 | 相同 | 0.10% |
| 碳价 600 美元/t CO₂e | 502.95 | 5,240.96 | 0.00 | 相同 | 2.73% |
| 马来西亚电价 0.10 美元/kWh | 6,543.61 | 5,403.40 | 0.00 | 相同 | 0.07% |
| 马来西亚电价 0.15 美元/kWh | 9,375.61 | 5,197.03 | 0.00 | 相同 | 0.07% |
| 新加坡电价 0.15 美元/kWh | 2,592.17 | 5,336.13 | 0.00 | 相同 | 0.08% |
| 新加坡电价 0.30 美元/kWh | 8,720.17 | 5,955.24 | 0.00 | 相同 | 0.04% |
| 设备价 × 0.5 | 393.23 | 4,740.03 | 0.00 | 相同 | 0.07% |
| 设备价 × 1.5 | 8,876.45 | 6,344.96 | 0.00 | 相同 | 0.06% |
| 行驶耗电 1.00 kWh/km | 2,416.17 | 5,472.32 | 0.00 | 相同 | 0.07% |
| 行驶耗电 1.25 kWh/km | 6,682.84 | 6,413.08 | 0.00 | 相同 | 0.06% |

设备、租车、周型和各运输方式的总货量在 12 个 C 方案中均与基准一致。两地电价和设备价的扫描改变了成本，保留了两地的季内充电总量。碳价从 300 升至 400 美元/吨时，新加坡充电量从 40,853.33 升至 54,008.89 kWh，马来西亚从 56,640.00 降至 43,484.44 kWh，排放从 58.337 降至 53.890 t CO₂e。行驶耗电从 1.00 增至 1.25 kWh/km 时，新加坡充电量从 29,760.00 增至 51,093.33 kWh。保存的车辆排班存在同价选择，因此设备或总电量相同也不等于逐车逐时安排相同。

基准方案固定时，油价持平点为 0.941 美元/升，碳价持平点为 939 美元/吨。油价保持 0.744 美元/升、碳价取 600 美元/吨时，基准排班直接计价得到 C − A 为 1,677.39 美元；重新求解后，可行差值缩至 502.95 美元。这一行到时限，最优差值区间为 −1,814.69 至 502.95 美元，两种动力的成本次序仍未确定。其余 11 行的 C 下界都高于相应的柴油可行成本。

### 电动对柴油

按已保存的方案 A、C 直接计算，不重新求解，所以不改变任何决策（`summary.md` 的 “Closed form” 表）：

- 每个往返柴油 183 美元（每程 123 升，0.744 美元/升）；电费加需量电费 base 143、dense 161、fleet 154 美元。电动每趟省 22–40 美元，但充电设备一季约 8,500–10,100 美元，要摊到足够多的往返上。零售油价下 C − A：base 4,650、dense 5,859、fleet 1,755 美元（fleet 的 C 未证明最优）。
- 油价持平点 0.941 / 0.868 / 0.769 美元/升（零售 0.744，车队卡 0.478）。加上每车 200,000 美元的购车溢价（16 周摊 9,171.05 美元/车）后，差距 22,992 / 24,201 / 29,268 美元。
- 减排只有 7.8–10.1%：车场在马来西亚充电，电网 0.74 kg CO2e/kWh。把车场电量换成 0.363 kg/kWh（德国 2024 年平均，只作反事实排放因子，不是德国案例），base 的 C 为 37.0 t，A 为 63.3 t。决策不变时的碳价持平点 939 / 481 / 104 美元/吨（不含购车溢价）。

### 修正与负结果

预先指定的四个预处理抽查目标中，有两项满足“原求解标记最优或间隙不高于 0.10%”。两项都沿用原时限，通过原代码版本 `b2ceb2b` 重建前序方案，并核对归档设备、周型、往返、成本和独立账单。历史归档未保存完整初始向量，无法逐字节比对该向量。以下是美元金额。[抽查记录](../../benchmark_results/electric_freight_v2/presolve_check.json)

| 目标 | 原可行成本 | 原下界 | 关预处理后的可行成本 | 关预处理后的下界 | 关预处理后的状态与间隙 |
|---|---:|---:|---:|---:|---|
| base / normal / C | 51,020.23 | 50,973.50 | 51,020.23 | 50,973.50 | 达到目标间隙，0.09% |
| base / tight_space / B\* | 53,119.34 | 53,095.91 | 55,826.93 | 51,856.04 | 到时限可行，7.11% |

两项复算均通过独立核算。第一项的目标和下界在美分精度下一致；第二项关闭预处理后在相同预算内得到较贵的可行解和较低的下界。此次比较未发现更低的可行成本或与原可行解矛盾的下界。RP 的 tight_space 记录间隙为 0.88%，六项连续周期记录的间隙为 4.40% 至 8.57%，这两类目标均未进入关预处理复算。

- **顺序方案第二步把充得上电的计划判为不可行（已修正）**：第二步原来把第一步的连续货运量全部固定。fleet 拥堵情景中，这个计划被判为不可行，但逐车核对时每辆车按 150 kW 充电都够，新加坡同时最多 1 辆车，固定往返、放开货物后联合模型也可行。先试的修正（每个货运量留 ±1e-6 件，`f5d1904`）没有用；逐块放开后查明，全部货运量一起固定时，三行互相耦合的货物约束差 2.4e-7 到 1.8e-6，关掉预处理也一样。现在第二步固定货运量不可行时，改为只固定周型（也就固定了每个额外班次）、往返、车辆和租车，货运量重解，并在结果行记 `cargo_fixing`（`aaf22d2`）。fleet 拥堵情景的 B 由此为 170,210.85 美元；其他情景的 B 在固定货运量下本来可行，不受影响。
- **没有加入模型的有效不等式**：每趟往返在每一侧至少补“去程 + 回程 + 下限 − 电池上限”kWh。线性松弛下界几乎不变（base 不变，dense +54，fleet +300 美元），没有采用。下界弱主要是分数的在场时间让车场充电能摊开，峰值和接口数被低估。

### 局限

- 单一走廊、单一承运人时刻表；车辆、电价、设备价格和背景往返是假设或合成值；不是企业运营数据。
- 电网只建模接入容量（站点容量、变电站余量、扩容），没有交流潮流；没有拓扑数据，不对电压或线路载荷下结论。
- 情景在季节开始时一次揭示，季中不逐周学习；代表周要求每周一满电在车场（结果六量化其代价）。
- 六种情景的概率是研究假设。两阶段分析仅覆盖 base；未在时限内证明最优的设定，报告可行成本并用上下界表达不确定范围。
- 对于时限内未证明最优的两阶段和连续周期求解，成本区间的下端取自开启预处理时的对偶界，VSS、EVPI 和连续 16 周限制代价的区间都依赖这些未经关闭预处理复核的下界。
- fleet 规模的整数规划在时间限制内没有收敛，那里的 C 与 B\* 之差只给出界（结果七）。
- 每个设定执行一次；同一作者设计情景，未独立验证。

### 复现

从提交 `05dce39` 的独立检出运行可重放余下三组。该提交带有原始 128 行。按[补充清单](../../benchmark_results/electric_freight_v2/supplement_1/manifest.json)可核对两份协议和各结果文件的 SHA-256。

```bash
python scripts/run_fleet.py deterministic --workers 3
python scripts/run_fleet.py tie_break --workers 3
python scripts/run_fleet.py search --workers 2
python scripts/run_fleet.py boundaries --workers 3
python scripts/run_fleet.py stochastic --workers 3 &
stochastic_pid=$!
python scripts/run_fleet.py horizon --workers 1 &
horizon_pid=$!
wait "$stochastic_pid" && wait "$horizon_pid" || exit 1
python scripts/summarize_fleet.py
python scripts/run_fleet.py manifest
python scripts/run_fleet.py sensitivity --workers 3
python scripts/summarize_fleet.py
python scripts/run_fleet.py manifest
python scripts/check_fleet_presolve.py
python scripts/summarize_fleet.py
python scripts/run_fleet.py manifest
python -m unittest tests.test_fleet tests.test_electric_freight -v
```

每组可中断后续跑（已保存的作业跳过）；`--only <作业>/<方案> --note <原因>` 只重跑指定作业，新行排在旧行之后，旧行保留。base 实例一次求解约 0.6 GB 内存。

### 下一项验收条件

下一项验收应优先判定碳价 600 美元/吨时 base 正常季的动力选择。它是 12 个敏感性设置中唯一一个最优 C − A 区间跨过零的设定。沿用同一成本口径，获得一份核算无误且低于柴油下界的电动排班，或获得高于柴油可行成本的有效电动下界，即可确定排序。该项属于后续验证。

## English

### Question

On the Malaysia–Singapore road lane (`MY_road`), 73 chip orders (2,511.67 kg over 16 weeks) ride on round trips that a carrier runs for other customers; when space runs short they can buy premium space, take an extra trip or fly. Model v1 priced an extra trip as a fixed fee. An electric truck, however, needs a specific vehicle and its charging time for every trip, which moves charging hours and site peaks and so the charging equipment worth installing. The questions:

1. What separates planning transport first and charging second from planning both together, and under which conditions does it matter?
2. Equipment and a season lease are decided before the season. Facing congestion, tight space, a demand surge and grid headroom changes, what is planning for uncertainty worth (VSS), and what would perfect information be worth (EVPI)?
3. How much more does electric cost than diesel, how much CO2e does it save, and which prices move that answer?

### Model: the decisions model v2 adds

Code in [`electric_freight/fleet.py`](../../electric_freight/fleet.py); an independent accounting in [`electric_freight/fleet_accounting.py`](../../electric_freight/fleet_accounting.py) recomputes every plan's cost, which matches the solver's objective.

- **Weekly cargo**: the week each order leaves (within one week of the weekly plan) and its channel (consolidated space, premium space, extra trip, air fallback); each week's type (crossing condition × whether an extra trip runs).
- **Hourly trucks** (one 168-hour representative week per week type): which truck runs each background trip and when within its ±2 h window; which truck runs an extra trip and when; a 4–12 h stay in Singapore; each truck's hourly state of charge (590 kWh usable, 59 kWh reserve, 457 kWh a leg, 467 kWh when congested); charging by site and connector tier; connectors shared within an hour; site capacity and substation headroom.
- **First stage** (before the season, shared by all scenarios): sites to open, connectors per tier, site upgrades, which substation each site is wired to, the northern substation's expansion, and a season lease of one more truck.
- **Costs**: trips (300 USD; +60 at night, +90 on Sunday, +40 when congested), waiting (15 USD/h), energy, the depot's demand charge (19.84 USD/kW-month), equipment (capital recovery at 8% over 10 years, charged for 16 weeks), the lease (1,000 USD/week), cargo holding, backlog, premium space and air; carbon price 0 in the main runs.
- **Representative-week boundary**: every truck is at the depot and full at every Monday 00:00. All weeks of one type are then the same problem and one representative week is exact for them; the boundary itself is a restriction, whose cost an unbroken 16-week model measures (result 6).

### Plans compared

- **A diesel**: the same trips and cargo rules, no charging equipment.
- **B sequential**: step 1 schedules cargo, trips and trucks as if a 150 kW charger stood wherever a truck stops, energy at 0.133 USD/kWh; step 2 keeps that schedule and chooses equipment and charging.
- **B\* sequential, best tie-break**: among schedules exactly as cheap as step 1, the one cheapest once equipment and charging are added — the best a transport-first process can do.
- **C joint**: cargo, trips, trucks, equipment and charging together, started from the better of B and B\*, so a time limit never leaves C worse than B.

### Design

- Three instances: base (2 trucks, 6 background round trips a week), dense (2 trucks, 12), fleet (3 trucks, 18). Four scenarios: normal; border_congestion (weeks 8–10 take 3 h at the border instead of 1, consolidation space ×0.6); tight_space (200 kg of consolidation space); grid_limited (200 kg and 150 kW of northern substation headroom).
- 900 s and a 0.1% relative gap per solve, each solved once. "Feasible" marks the plan at the time limit, with its gap.
- The protocol was committed before the first protocol run; solver settings changed after exploratory runs are listed in its `decided_before_running`; groups added after a run (other solver seeds, the search from saved plans) state when and why.
- The remaining three groups use the original protocol and a preregistered [supplement](../../benchmarks/electric_freight_v2/protocol_supplement_1.json). Decomposition and sensitivity solves retain the 900 s limit. Each continuous-horizon solve has 1,800 s and the deterministic equivalent has 3,600 s. Timings are from a shared machine. The original manifest identifies the files at commit `6dadb43`.

### Result 1: plans A, B, B\* and C

16-week totals in USD.

| instance | scenario | A diesel | B | B\* | C | B − C | B\* − C | C − A |
|---|---|---|---|---|---|---|---|---|
| base | normal | 46,370.30 | 56,547.64 | 51,020.23 | 51,020.23 (0.09%) | 5,527.40 | 0 | 4,649.93 |
| base | border_congestion | 49,827.08 | 59,943.52 | 54,509.18 | 54,509.18 (0.08%) | 5,434.34 | 0 | 4,682.10 |
| base | tight_space | 47,225.87 | 58,010.02 | 53,119.34 | 52,308.63 (feasible, 0.86%) | 5,701.39 | 810.71 | 5,082.75 |
| base | grid_limited | 47,225.87 | 58,010.02 | 53,119.34 | 52,308.63 (feasible, 0.86%) | 5,701.39 | 810.71 | 5,082.75 |
| dense | normal | 92,740.61 | 98,724.05 | 98,599.27 | 98,599.27 (0.10%) | 124.78 | 0 | 5,858.66 |
| dense | border_congestion | 97,078.09 | 122,677.75 | 122,677.75 (feasible, 19.2%) | 122,677.75 (feasible, 19.2%) | 0 | 0 | 25,599.66 |
| dense | tight_space | 93,716.18 | 103,004.22 | 101,865.09 | 100,084.86 (0.10%) | 2,919.36 | 1,780.23 | 6,368.68 |
| dense | grid_limited | 93,716.18 | 103,004.22 | 101,854.10 | 100,084.86 (0.10%) | 2,919.36 | 1,769.24 | 6,368.68 |
| fleet | normal | 144,870.91 | 146,626.23 | = B (feasible, 7.6%) | = B (feasible, 7.6%) | 0 | 0 | 1,755.32 |
| fleet | tight_space | 145,786.48 | 149,694.57 | = B (feasible, 9.5%) | = B (feasible, 9.5%) | 0 | 0 | 3,908.09 |
| fleet | grid_limited | 145,786.48 | 149,694.57 | = B (feasible, 9.5%) | = B (feasible, 9.5%) | 0 | 0 | 3,908.09 |
| fleet | border_congestion | 150,089.10 | 170,210.85 | = B (feasible, 17.0%) | = B (feasible, 17.0%) | 0 | 0 | 20,121.75 |

### Result 2: why B costs more — the truck assignment step 1 picks at random

Step 1 does not care which truck runs which trip; many schedules cost the same and the solver keeps whichever it meets first. Plan B solved again under HiGHS random seeds 1–5 (search order only; the model is unchanged), with the same step-1 cost every time:

| setting | B, seeds 0–5 | B − B\* |
|---|---|---|
| base normal | 56,547.64 / 56,699.36 / 57,051.14 / 57,735.71 / 56,747.69 / 57,723.35 | 5,527–6,715 |
| base tight_space | 58,010.02 / 63,512.65 / 59,521.87 / 64,915.83 / 59,405.44 / 64,908.07 | 4,891–11,796 |
| dense normal | 98,724.05 under all six | 124.78 |

- Base runs one trip at 06:00 each day; a round trip with turnaround takes 20 hours, so one truck can run all six. Under all six seeds some truck runs on two consecutive days and stands about 6 hours at the depot in between, which forces a 150 kW depot charger (peak 70.9–85.1 kW, demand charge above 5,000 USD). B\* and C alternate the trucks, each stands about 30 hours at the depot, and a 50 kW charger suffices (peak 24.8 kW). With T1 on the first trip, the other five trips can be split between the trucks in 32 ways and only one alternates fully: an expensive B is the rule, not bad luck.
- In dense each truck runs one trip every 24 hours and the trucks can hardly do anything but alternate; all six seeds give the same schedule. **The more slack the transport plan leaves, the more a transport-first process decides arbitrarily, and the more it loses.**

### Result 3: where joint planning beats B\*

In result 1, the 900 s main solves returned equally costly B\* and C plans in normal and congested conditions. Result 7 reports the subsequent search. In the main solves, background trips have ±2 h windows, moving a departure costs a night premium, and B\* already picks the cheapest-to-charge schedule among the equally cheap ones. Both cases where C beats B\* pay more for transport to lower the depot peak:

- **base, tight space (−810.71 USD)**: C runs week 15's extra trip on T2 at Monday 00:00 (+60 USD night premium); the depot peak falls from 42.3 to 30.4 kW and the demand charge from 3,091.46 to 2,220.75 USD, with the same equipment.
- **dense, tight space (−1,780.23 USD)**: C does **not** run week 15's extra trip. It ships earlier or later, buys premium space and flies instead (holding 825, displaced cargo 295, air 366 USD, against 0 / 190 / 183 with the trip) and saves the 510 USD trip; the depot peak falls from 126.9 to 84.3 kW and the demand charge from 9,274.39 to 6,157.80 USD. The extra trip's true marginal cost includes about 3,100 USD of demand charge it adds, which a transport-first process cannot see.
- grid_limited equals tight_space: the hub uses one 150 kW connector, so 150 kW of northern headroom does not bind.

### Result 4: congested weeks need one more electric truck

A congested leg takes 9 hours and 467 kWh. A truck returns to the depot with at most 123 kWh and needs 526 kWh to leave again; at 150 kW (efficiency 0.9) that takes at least 3 hours, one more than the 2-hour turnaround, so each round trip takes 25 hours instead of 24. In dense each truck runs a trip every 24 hours (windows ±2 h): six trips add 5 hours against 4 hours of window slack, which does not fit; diesel trucks do not charge and fit. The electric plan has to lease a third truck for the season (16,000 USD), and dense/border_congestion costs C − A = 25,599.66 USD. Fleet runs three trucks at one trip per 24 hours and needs a fourth for the same reason. The linear relaxation does not see this integer timing argument, so the dense gap stays at 19%.

Plan B for fleet/border_congestion also leases a fourth truck (16,000 USD) with one 150 kW connector at the depot and one at the hub (depot peak 149.3 kW); C − A = 20,121.75 USD. B\* and C, started from B, did not improve within 900 s (gap 17%). This row was first reported as "B infeasible, no plan for B\* and C"; the cause was the way step 2 fixed cargo quantities, not charging (see Corrections and negative results).

### Result 5: boundary sweeps (base instance)

Each sweep varies one input. The switches below refer to the saved feasible schedules. Costs are USD for 16 weeks. [All 51 sweep records and solve gaps](../../benchmark_results/electric_freight_v2/summary.md#boundary-sweeps-base-instance)

| Input | Trip and equipment decisions under B\* and C |
|---|---|
| Weekly consolidation space | B\* adds a trip in week 15 when space falls from 220 to 215 kg. C adds none at 215, 210 or 205 kg, then one at 200 kg (52,308.63 USD). At 175 kg B\* adds two and C adds one. At 150 kg both add trips in weeks 14 and 15. |
| Holding-cost multiplier at 200 kg | Both avoid extra trips at 0 and 0.1. At 0.30, 0.35 and 0.50, B\* adds a trip in week 15 and C adds none. At 0.30 their costs are 53,119.34 and 51,913.11 USD. Both add a trip at the baseline multiplier of 1. |
| Northern substation headroom at 200 kg | C costs 52,308.63 USD at 250, 213, 212 and 150 kW. At 107 kW it keeps HUB, drops the extra trip and costs 52,490.73 USD. At 106 kW it switches to YARD on the southern substation and costs 54,324.94 USD. The last two C gaps are 1.15% and 3.90%. |

Across the tested space levels, sequential planning adds a trip earlier than joint planning. Reducing grid headroom changes the cargo schedule and charging location at different tested values. Where optimality remains open, the sweep brackets the observed change.

### Result 6: representative weeks against 16 unbroken weeks

The continuous model keeps weekly cargo and extra-trip counts and requires trucks to be home and fully charged at the beginning and end of the season. Trips and charging can continue across Monday, and individual weeks of the same type can use different schedules. The fixed comparison covers operations. The free comparison also includes equipment and lease costs. Both omit the common cargo cost. Concatenating the saved weeks gave a feasible start in every case. All six solves reached the 1,800 s budget. The lower endpoint subtracts the continuous feasible cost from the representative cost. The upper endpoint subtracts the continuous lower bound. Costs are USD over 16 weeks. [All six accounts and solve bounds](../../benchmark_results/electric_freight_v2/runs.jsonl)

| Saved C plan | Equipment and lease | Representative | Continuous | Status and gap | Restriction cost estimate | Restriction cost interval |
|---|---|---:|---:|---|---:|---:|
| base / normal | fixed | 42,537.02 | 42,444.12 | feasible, 4.40% | 92.90 | 92.90 to 1,962.29 |
| base / normal | free | 51,020.23 | 50,927.33 | feasible, 8.47% | 92.90 | 92.90 to 4,406.67 |
| base / tight_space | fixed | 43,452.87 | 43,031.26 | feasible, 4.81% | 421.60 | 421.60 to 2,492.49 |
| base / tight_space | free | 51,936.08 | 51,434.91 | feasible, 8.57% | 501.17 | 501.17 to 4,910.12 |
| dense / normal | fixed | 88,511.12 | 88,511.12 | feasible, 5.33% | 0.00 | 0.00 to 4,716.29 |
| dense / normal | free | 98,599.27 | 98,599.27 | feasible, 6.22% | 0.00 | 0.00 to 6,134.75 |

In the base normal season the demand charge falls by 120.74 USD and the energy bill rises by 27.84 USD, saving 92.90 USD. With tight space the fixed and free solves reduce demand charges by 391.90 and 493.50 USD respectively, and both reduce trip charges by 60 USD. The free solve keeps the original equipment and lease. The two feasible costs differ through the operating schedules found. In dense the raw differences are −0.000049 and −0.000053 USD because the saved representative accounts were rounded. The schedules cost the same to the nearest cent. These bounds apply to the three saved plans, with further improvements still possible in the continuous model.

### Result 7: fleet scale — a search from the saved plans

In each setting the original full solves returned the same feasible cost for B\* and C. The search reconstructs its start with the saved trips fixed, then frees one truck or a 48-hour window per step for up to two rounds. B\* keeps the step-1 transport-cost cap. The last column bounds the optimal B\* cost minus the optimal C cost. C can use any feasible B\* schedule, giving a lower endpoint of zero here. The upper endpoint uses the feasible B\* cost minus the original full-model C lower bound. Costs are USD for 16 weeks. [Search steps, original bounds and elapsed times](../../benchmark_results/electric_freight_v2/summary.md#fix-and-optimize-search-from-the-saved-plans)

| Instance and scenario | Before search | B\* after search | C after search | Feasible B\* − C | Optimal cost difference |
|---|---:|---:|---:|---:|---:|
| dense / border_congestion | 122,677.75 | 118,315.88 | 117,405.41 | 910.47 | 0 to 19,147.13 |
| fleet / normal | 146,626.23 | 145,209.95 | 145,209.95 | 0.00 | 0 to 9,754.14 |
| fleet / tight_space | 149,694.57 | 146,079.87 | 146,079.87 | 0.00 | 0 to 10,536.01 |
| fleet / border_congestion | 170,210.85 | 165,348.67 | 165,377.19 | −28.52 | 0 to 24,110.75 |

In fleet congestion the two heuristic searches visit different schedules. The B\* search finds a feasible schedule 28.52 USD cheaper than the C search's result, and C can also use that schedule. All four bounds include zero.

### Result 8: two-stage stochastic plan (VSS and EVPI)

Equipment and the season lease are decided before the scenario is revealed at the start of the season. The table gives independently accounted 16-week costs in USD for both designs. Each uses one 50 kW connector at MY_DEPOT on MY_SUB and one 150 kW connector in Singapore on SG_SUB_N, with no upgrades, expansions or lease. The Singapore installation is at HUB or YARD. All six probabilities are assumptions. [Scenario solves, accounts and equipment](../../benchmark_results/electric_freight_v2/stochastic.json)

| Scenario | Probability | HUB design | YARD design |
|---|---:|---:|---:|
| normal | 0.45 | 51,020.23 | 52,380.80 |
| border_congestion | 0.15 | 54,509.18 | 56,029.60 |
| tight_space | 0.15 | 52,308.63 | 53,866.39 |
| demand_surge | 0.10 | 51,005.14 | 52,380.80 |
| grid_cut | 0.10 | 52,308.63 | 53,866.39 |
| sg_window | 0.05 | 56,269.57 | 52,380.80 |
| Probability-weighted cost | 1.00 | 52,126.63 | 53,299.52 |

Both designs have feasible schedules in every scenario. The seasonal equipment cost is 8,483.22 USD for HUB and 9,858.87 USD for YARD. YARD saves 3,888.77 USD in sg_window, where daytime charging at HUB is restricted and its tariff rises. At the assumed 5% probability this saves 194.44 USD in expectation. YARD costs 1,360.56 to 1,557.76 USD more in each of the other five scenarios. Across all six, HUB costs 1,172.88 USD less in expectation. The decomposition chooses the same equipment and lease as planning for the normal season alone.

| Quantity (USD over 16 weeks) | Feasible point estimate | Bounds on the optimum |
|---|---:|---:|
| WS, equipment chosen with advance knowledge of each scenario | 51,932.19 | 51,784.02 to 51,932.19 |
| RP, one shared preseason design | 52,126.63 | 51,886.52 to 52,126.63 |
| EEV, the normal-season design with scenario-specific operations | 52,126.63 | 51,820.57 to 52,126.63 |
| VSS = EEV − RP | 0.00 | 0.00 to 240.12 |
| EVPI = RP − WS | 194.44 | 0.00 to 342.62 |

The deterministic equivalent with one design shared across the six scenarios returns the same plan at the same independently accounted cost of 52,126.63 USD. At its 3,600 s solve budget the lower bound is 51,886.52 USD and the gap is 0.46%. This bound covers all preseason designs and tightens the RP and VSS intervals. The VSS point estimate is zero, while the bounds leave room for a better preseason design. [Deterministic equivalent and six scenario accounts](../../benchmark_results/electric_freight_v2/stochastic_de.json)

### Result 9: sensitivity

Each row varies one input in the base normal season. Differences use independently accounted feasible plans and are USD for 16 weeks. The last two columns compare C's equipment and lease with the normal-season baseline and give C's solve gap. B\* and C have the same feasible cost in all 12 rows. [All four plan costs, emissions, depot peaks, statuses and changes from baseline](../../benchmark_results/electric_freight_v2/summary.md#sensitivity-of-the-base-instance-in-the-normal-season)

| Changed input | C − A | B − C | B\* − C | C equipment and lease | C gap |
|---|---:|---:|---:|---|---:|
| Carbon price 100 USD/t CO₂e | 4,139.41 | 5,402.99 | 0.00 | same | 0.06% |
| Carbon price 300 USD/t CO₂e | 3,148.57 | 5,123.98 | 0.00 | same | 0.10% |
| Carbon price 400 USD/t CO₂e | 2,383.11 | 5,240.96 | 0.00 | same | 0.10% |
| Carbon price 600 USD/t CO₂e | 502.95 | 5,240.96 | 0.00 | same | 2.73% |
| Malaysia electricity 0.10 USD/kWh | 6,543.61 | 5,403.40 | 0.00 | same | 0.07% |
| Malaysia electricity 0.15 USD/kWh | 9,375.61 | 5,197.03 | 0.00 | same | 0.07% |
| Singapore electricity 0.15 USD/kWh | 2,592.17 | 5,336.13 | 0.00 | same | 0.08% |
| Singapore electricity 0.30 USD/kWh | 8,720.17 | 5,955.24 | 0.00 | same | 0.04% |
| Equipment prices × 0.5 | 393.23 | 4,740.03 | 0.00 | same | 0.07% |
| Equipment prices × 1.5 | 8,876.45 | 6,344.96 | 0.00 | same | 0.06% |
| Driving energy 1.00 kWh/km | 2,416.17 | 5,472.32 | 0.00 | same | 0.07% |
| Driving energy 1.25 kWh/km | 6,682.84 | 6,413.08 | 0.00 | same | 0.06% |

All 12 C plans retain the baseline equipment, lease, week types and total freight by channel. The electricity and equipment price sweeps change cost while retaining the seasonal energy bought on each side. From 300 to 400 USD/t, Singapore charging increases from 40,853.33 to 54,008.89 kWh, Malaysian charging falls from 56,640.00 to 43,484.44 kWh, and emissions fall from 58.337 to 53.890 t CO₂e. Raising driving energy from 1.00 to 1.25 kWh/km increases Singapore charging from 29,760.00 to 51,093.33 kWh. Equally costly truck assignments exist, so the hourly schedules can differ even when the equipment and seasonal energy totals agree.

With the baseline plans fixed, the break-even diesel price is 0.941 USD/L and the break-even carbon price is 939 USD/t. At 0.744 USD/L for diesel and 600 USD/t for carbon, charging the baseline schedules at those prices gives C − A of 1,677.39 USD. Reoptimising reduces the feasible difference to 502.95 USD. This run reached the time limit. Its optimal cost difference lies between −1,814.69 and 502.95 USD, leaving the cost ordering open. In each of the other 11 cases C's lower bound exceeds the corresponding feasible diesel cost.

### Electric against diesel

Computed from the saved plans A and C without solving again, so no decision changes (the "Closed form" table of `summary.md`):

- Diesel costs 183 USD a round trip (123 litres a leg at 0.744 USD/L); electricity plus demand charge cost 143 (base), 161 (dense) and 154 (fleet) USD. Electric saves 22–40 USD a trip, but the charging equipment costs about 8,500–10,100 USD a season and needs enough trips to pay back. At the retail diesel price C − A is 4,650 (base), 5,859 (dense) and 1,755 (fleet) USD; the fleet C is not proven optimal.
- Diesel break-even prices are 0.941 / 0.868 / 0.769 USD/L (retail 0.744, fleet card 0.478). With a 200,000 USD purchase premium per truck (9,171.05 USD per truck over 16 weeks) the gaps are 22,992 / 24,201 / 29,268 USD.
- CO2e falls by only 7.8–10.1%: the depot charges on Malaysia's grid at 0.74 kg CO2e/kWh. With the depot's energy at 0.363 kg/kWh (Germany's 2024 average, used only as a counterfactual factor, not as a German case), base C emits 37.0 t against A's 63.3 t. Carbon prices that close the gap with decisions fixed are 939 / 481 / 104 USD/t (without the purchase premium).

### Corrections and negative results

Two of the four designated presolve targets met the original eligibility rule of an optimal solver status or a relative gap at most 0.10%. Both replays kept the original time limit and reconstructed the preceding plan with its recorded source revision `b2ceb2b`. Equipment, week types, trips, cost and independent accounts were checked against the archive. The archive lacks the full starting vectors for a byte-for-byte comparison. Amounts are USD. [Presolve comparison records](../../benchmark_results/electric_freight_v2/presolve_check.json)

| Target | Original feasible cost | Original lower bound | Feasible cost with presolve off | Lower bound with presolve off | Status and gap with presolve off |
|---|---:|---:|---:|---:|---|
| base / normal / C | 51,020.23 | 50,973.50 | 51,020.23 | 50,973.50 | target gap met, 0.09% |
| base / tight_space / B\* | 53,119.34 | 53,095.91 | 55,826.93 | 51,856.04 | time limit, feasible, 7.11% |

Both replays passed independent accounting. The first reproduced the cost and bound to the cent. With presolve disabled, the second found a higher feasible cost and a lower bound further from the incumbent within the same budget. Neither replay yielded a cheaper feasible plan or a lower bound contradicting the original feasible plan. The RP tight_space record had a 0.88% gap. Gaps for the six continuous-horizon solves ranged from 4.40% to 8.57%. These two targets therefore had no eligible presolve-off replay.

- **Step 2 of plan B declared a chargeable plan infeasible (corrected)**: step 2 used to fix all of step 1's continuous cargo quantities. In fleet/border_congestion that plan was declared infeasible, although a truck-by-truck check shows every truck has enough energy at 150 kW, at most one truck is in Singapore at a time, and the joint model is feasible with the trips fixed and cargo free. A first correction (a ±1e-6 unit band on each quantity, `f5d1904`) did not help; releasing one part at a time showed that with all quantities fixed together, three coupled cargo rows miss by 2.4e-7 to 1.8e-6, with or without presolve. Step 2 now, when fixed quantities are infeasible, fixes only week types (and so every extra trip), trips, trucks and the lease and solves the quantities again, recording `cargo_fixing` in the row (`aaf22d2`). Plan B for fleet/border_congestion is then 170,210.85 USD; plan B elsewhere was feasible with the quantities fixed and is unaffected.
- **Valid inequalities not adopted**: each round trip must recharge at least outbound + return + reserve − battery kWh on each side. The linear relaxation bound barely moved (base unchanged, dense +54, fleet +300 USD), so they were not added. The bound is weak mainly because fractional presence lets the relaxation spread depot charging, understating the peak and the number of connectors.

### Limitations

- One corridor and one carrier timetable; vehicle, tariff, equipment and background-trip parameters are assumptions or synthetic; not company operating data.
- The grid is modelled as connection capacity (site capacity, substation headroom, expansion), not AC power flow; without topology data nothing is claimed about voltages or line loading.
- A scenario is revealed once at the start of the season, with no week-by-week learning; representative weeks require every truck full at the depot every Monday (result 6 measures what that costs).
- The six scenario probabilities are assumptions. The two-stage analysis covers only the base instance. Where the time limit leaves optimality open, feasible costs and bounds describe the remaining uncertainty.
- For the two-stage and continuous-horizon solves that reached the time limit without proving optimality, the cost intervals use dual bounds obtained with presolve enabled as their lower endpoints, and the intervals for VSS, EVPI and the 16-week restriction cost all depend on these bounds, which were not checked with presolve disabled.
- At fleet scale the integer program does not converge within the time limit, so the difference between C and B\* there is only bounded (result 7).
- Each setting solved once; scenarios designed by the same author; not independently verified.

### Reproduction

To replay the remaining groups, start in a separate checkout of `05dce39`, which includes the original 128 rows. The [supplementary manifest](../../benchmark_results/electric_freight_v2/supplement_1/manifest.json) gives the SHA-256 values for both protocols and each result file.

```bash
python scripts/run_fleet.py deterministic --workers 3
python scripts/run_fleet.py tie_break --workers 3
python scripts/run_fleet.py search --workers 2
python scripts/run_fleet.py boundaries --workers 3
python scripts/run_fleet.py stochastic --workers 3 &
stochastic_pid=$!
python scripts/run_fleet.py horizon --workers 1 &
horizon_pid=$!
wait "$stochastic_pid" && wait "$horizon_pid" || exit 1
python scripts/summarize_fleet.py
python scripts/run_fleet.py manifest
python scripts/run_fleet.py sensitivity --workers 3
python scripts/summarize_fleet.py
python scripts/run_fleet.py manifest
python scripts/check_fleet_presolve.py
python scripts/summarize_fleet.py
python scripts/run_fleet.py manifest
python -m unittest tests.test_fleet tests.test_electric_freight -v
```

Every group resumes (saved jobs are skipped); `--only <job>/<plans> --note <reason>` runs chosen jobs again, appending new rows after the old ones, which stay. A base-instance solve needs about 0.6 GB of memory.

### Next acceptance condition

The next acceptance condition is to determine the lower-cost powertrain for the base normal season at 600 USD/t. This is the only one of the 12 sensitivity settings whose optimal C − A interval crosses zero. Under the same cost definitions, an independently checked electric schedule below the diesel lower bound or a valid electric lower bound above the feasible diesel cost would settle the ordering. This is a future check.
