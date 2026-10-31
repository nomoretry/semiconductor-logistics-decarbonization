# 网络规划引擎：碳约束与中断风险下的库存—运输联合优化 / Network planning engine

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; the English version follows the Chinese text.

## 中文

### 问题

半导体备件和芯片成品的物流要同时权衡四件事：运费、在途和在库的资金占用、服务水平（缺货代价很高），以及排放。外部扰动（红海绕行、台风封港、空运运力紧张、需求激增）会改变提前期、运力和运价。规划问题是：

1. 给定承诺订单，各 SKU 每周走哪条线路、发多少？
2. 碳排放上限收紧时，成本增加多少？每减 1 吨的边际代价是多少？
3. 扰动是否发生事先不知道时，应该提前做哪些准备（提前发货、预留空运舱位），这种准备值多少钱？

代码：[`network_planning/`](../network_planning)。复用仓库已有的线路距离、运价、提前期（`asml/config.json`、`marvell/config.json`）和排放因子（`data_sources/selected_emission_factors.json`）；SKU 组合、需求、运力、固定费用和扰动幅度是 [`config.json`](../network_planning/config.json) 中声明的情景假设。

### 网络

| 网络 | 线路 | 说明 |
|---|---|---|
| asml | NL_air、NL_ocean（荷兰→新加坡） | 光刻机备件，价值密度约 49–2,513 USD/kg |
| marvell | TW_air、TW_ocean、MY_air、MY_road（台湾/马来西亚→新加坡） | 芯片成品，价值密度约 6,000–18,800 USD/kg |

每个网络默认 12 个合成 SKU、16 周；SKU 数可扩到 2,000 用于规模测试。

### 数学模型

**集合**：SKU $s\in S$，线路 $l\in L$（空运线路 $L^{a}\subset L$），派发周 $t\in\{1,\dots,T\}$，场景 $k\in K$，概率 $\pi_k$。

**参数**：需求 $d_{stk}$；单件质量 $m_s$、价值 $v_s$；周资金费率 $h=0.2/52$；派发周 $t$ 的提前期 $\ell_{ltk}$、运力 $\kappa_{ltk}$（kg/周）、运价系数 $\phi_{ltk}$、每 kg 排放 $e_{ltk}$（距离 × 排放因子）；基础运价 $c_l$；线路周固定费 $f_l$；空运现货溢价 $\rho$；舱位预留费 $\alpha$（USD/kg·周）；可预留上限 $\bar R_l$；缺货罚金 $p_s$；仓储费用与排放 $w^{\$}, w^{c}$；期初库存 $I^0_s$；在途到货 $P_{st}$；期末目标 $\theta_s$；碳价 $\tau$；碳上限 $E^{\max}$；服务水平 $\beta$。

**决策变量**：发货量 $x_{sltk}\ge 0$（默认连续，可设为整数）；线路周启用 $y_{ltk}\in\{0,1\}$；空运预留舱位 $R_l\in[0,\bar R_l]$（第一阶段）；空运用预留/现货的 kg $a^{r}_{ltk}, a^{p}_{ltk}\ge 0$；库存 $I_{stk}$、缺货 $B_{stk}$、期末缺口 $U_{sk}\ge 0$。

**目标**（期望总成本，可加碳价）：

$$
\min\ \alpha T\sum_{l\in L^{a}}R_l+\sum_k\pi_k\Big[\sum_{l\notin L^{a}}c_l\phi_{ltk}m_s x_{sltk}+\sum_{l\in L^{a}}c_l\big(a^{r}_{ltk}+\rho\,\phi_{ltk}a^{p}_{ltk}\big)+\sum v_s h\,\ell_{ltk}x_{sltk}+\sum f_l y_{ltk}+\sum\big((v_sh+w^{\$})I_{stk}+p_sB_{stk}\big)+\sum p_s\lambda U_{sk}\Big]+\tau E
$$

**约束**：

1. 库存平衡：$I_{stk}-B_{stk}=I_{s,t-1,k}-B_{s,t-1,k}+\sum_{l,t':\,t'+\ell_{lt'k}=t}x_{slt'k}+P_{st}-d_{stk}$
2. 海运/公路运力与启用：$\sum_s m_s x_{sltk}\le\kappa_{ltk}\,y_{ltk}$
3. 空运：$\sum_s m_s x_{sltk}=a^{r}_{ltk}+a^{p}_{ltk}$，$a^{r}_{ltk}\le R_l$，$a^{p}_{ltk}\le\kappa_{ltk}$，$\sum_s m_s x_{sltk}\le(\bar R_l+\kappa_{ltk})\,y_{ltk}$
4. 期末库存：$I_{sTk}-B_{sTk}+U_{sk}\ge\theta_s$（随机规划中为软约束，保证完全追索；碳前沿分析中去掉 $U$ 变为硬约束）
5. 服务水平：$\sum_k\pi_k\sum_{s,t}B_{stk}\le(1-\beta)\sum_k\pi_k\sum_{s,t}d_{stk}$
6. 碳上限：$E=\sum_k\pi_k\big[\sum m_s e_{ltk}x_{sltk}+w^{c}\sum I_{stk}\big]\le E^{\max}$
7. 非预期性：扰动在第 $r$ 周揭示，派发周 $t<r$ 的 $x, y, a^{r}, a^{p}$ 在所有场景中相同（实现上共用同一个变量）。

固定费用 $f_l y_{ltk}$ 让模型成为固定费用网络流问题（MILP）：多条线路分摊固定费用，会产生“集中发货 vs 多付库存”的权衡。

### 两阶段随机规划

第一阶段（不知道哪个场景会发生）：前 $r-1$ 周的发货和整季的空运舱位预留 $R_l$。第二阶段：揭示后各场景分别调整。指标：

- **RP**：随机规划的最优期望成本。
- **WS**：完全信息，每个场景单独最优，再按概率加权。
- **EEV**：把第一阶段固定为“名义计划”（按正常场景做的计划），揭示后再最优应变的期望成本。
- **VSS = EEV − RP ≥ 0**：考虑不确定性做计划的价值。
- **EVPI = RP − WS ≥ 0**：提前知道场景最多值多少钱。

MIP 只能求到一定 gap，所以同时用 HiGHS 的对偶界给出区间：VSS ∈ [EEV_下界 − RP, EEV − RP_下界]，EVPI ∈ [RP_下界 − WS, RP − WS_下界]。

### 碳分析

- **ε-约束前沿**：把排放上限设为不设上限方案的 90%、80%、75% … 40%，逐个求最低成本。
- **边际减排成本（MAC）**：平均 MAC =（成本 − 基准成本）/（基准排放 − 排放）；分段 MAC 用相邻两点计算。
- **影子价格**：MIP 没有对偶。做法是把线路启用变量固定在 MIP 最优值、放松发货整数性，求得到的 LP 中碳约束的对偶值（fix-and-price）。
- **碳价扫描**：把碳价 τ 放进目标函数。有 0/1 变量时，部分帕累托点不能由任何单一碳价得到（非支撑点），所以碳上限和碳价不完全等价。

### 工程与可信度

- **独立核算**：[`accounting.py`](../network_planning/accounting.py) 只根据决策变量和场景数据重新计算库存、成本、排放并检查每条约束，不读取求解器的目标值；求解器目标与重算结果的相对差异要求 ≤ 1e-6，否则记为问题。
- **手算校验**：测试里有一个 1 个 SKU、1 条线路的实例，最优成本可以手算（120 美元）。
- **求解参数**：HiGHS 默认在这些实例上大部分时间花在改进可行解上；`mip_heuristic_effort=0.3` 让一个带碳约束的 ASML 实例从 60 秒超时变为 12–25 秒得到最优。
- **整数性代价**：发货量取整数时求解时间是连续流量的数倍到数十倍，目标值只差约 0.01–0.08%，所以战术层默认用连续流量，整数版本可选（见结果中的对照表）。
- **拆分 big-M**：教科书式的逐 SKU 启用约束 $x\le U y$ 在这里没有稳定提速（HiGHS 预处理已覆盖大部分作用），保留为可选项并在规模测试中报告。

### 结果

每个网络 12 个合成 SKU、16 周、种子 7，HiGHS 相对 gap ≤ 0.1%。完整表格和图见[实验报告](../benchmark_results/network_planning/report.md)。

**1. 扰动影响**（每个场景按完全信息重新规划，相对正常场景）

| 网络 | 场景 | 成本变化 | 说明 |
|---|---|---:|---|
| ASML | 红海绕行 | +12.38% | 排放 +28.4%：绕行距离更长，空运占比从 19.8% 升到 25.7% |
| ASML | 空运运力紧张 | 0.00% | 预留的空运舱位已覆盖这几周的需求 |
| ASML | 需求 +30% | +15.58% | |
| Marvell | 台风封港 | +2.17% | 排放略降：空运运力受限，更多货物提前走海运 |
| Marvell | 边境拥堵 | +0.71% | |
| Marvell | 需求 +30% | +17.63% | |

**2. 减排成本**（服务水平 ≥ 98%，期末库存硬约束）

| 排放上限 | ASML 成本增幅 | ASML 平均 MAC | ASML 影子价格 | Marvell 成本增幅 | Marvell 平均 MAC |
|---:|---:|---:|---:|---:|---:|
| 90% | +0.36% | 95 | 155 | +4.40% | 20,731 |
| 75% | +1.76% | 187 | 277 | +13.12% | 24,756 |
| 60% | +3.42% | 227 | 296 | +22.92% | 27,021 |
| 40% | +12.97% | 574 | 3,237 | +36.31% | 28,539 |

（MAC 与影子价格单位为 USD/t CO2e。）

- ASML 备件的减排成本曲线呈“曲棍球棒”形：前 40% 的减排每吨约 100–300 美元，之后急升到每吨上千美元；该服务水平下最低可达排放比成本最优方案低 72.5%。
- 碳价扫描：50 USD/t 不改变方案，100 USD/t 只减排 6.6%，400 USD/t 减排 46.6%；400 与 800 USD/t 得到同一方案，说明有 0/1 变量时部分帕累托点无法由单一碳价得到。
- Marvell 芯片的隐含碳价约 2–3 万 USD/t，碳价扫描到 6,400 USD/t 方案也不变。芯片价值密度为 6,000–18,800 USD/kg，在途资金成本压倒运费和碳成本，切换运输方式不是芯片的减排杠杆。

**3. 两阶段随机规划**（第 3 周揭示扰动）

| 网络 | RP | EEV | WS | VSS（gap 感知区间） | EVPI（区间） |
|---|---:|---:|---:|---|---|
| ASML | 57,154 | 58,018 | 56,964 | 864（1.51%），[821, 869] | 190（0.33%），[186, 234] |
| Marvell | 466,996 | 466,996 | 466,947 | 0，[−228, 237] | 49（0.01%），[−188, 252] |

- ASML：随机方案在揭示前多发约 836 kg 海运（1,767 kg 对 931 kg），并把空运舱位预留从 164 提高到 199 kg/周。红海中断发生时，它比名义方案便宜 6.0%（62,310 对 66,311 美元）；不发生时贵 0.33%。
- Marvell：VSS 区间包含 0，名义方案已经足够稳健（扰动只持续 2–3 周，而且揭示得早）。对冲是否值得，取决于具体网络。

**4. 整数性与规模**

- 发货量取整数时，目标值只高 0.04–0.09%，求解时间却是连续流量的 3–26 倍。
- 连续流量版本：400 个 SKU（26,065 个变量）建模 2.0 秒、求解 3.9 秒。整数版本：100 个 SKU 需 41 秒。加上 SKU 级下单费（3,232 个 0/1 变量）后，100 个 SKU 在 60 秒内只能求到 0.2% gap，这时需要分解或启发式。
- 逐 SKU 的拆分 big-M 约束没有稳定提速，保留为可选项。

### 复现

```bash
python -m pip install -c constraints.txt -e ".[planning]"
python -m network_planning solve --network asml --scenario red_sea --explain
python -m network_planning frontier --network marvell
python -m network_planning stochastic --network asml --reveal-week 3
python -m network_planning report --output benchmark_results/network_planning
python -m unittest tests.test_network_planning -v
```

### 局限与下一步

- 需求是已知承诺订单，不确定性只来自离散扰动场景；下一步可接入[滚动预测环境](rolling_forecast_results.md)的需求分布。
- 目标是风险中性的期望成本；可加 CVaR 约束研究风险偏好。
- 只有一个目的仓（新加坡）；可扩展为多仓选址与库存部署（facility location）。
- 运力、费率和扰动幅度是情景假设，结论用于比较策略，不代表企业实测。
- 依赖 PuLP 3.3（已使用 4.x 风格的 `add_variable` 建模接口）；PuLP 4.x 的求解状态接口不同，迁移是后续工作。

## English

**Problem.** Plan weekly shipments per SKU and lane for semiconductor spare parts (ASML-inspired, Netherlands to Singapore) and finished chips (Marvell-inspired, Taiwan/Malaysia to Singapore), trading off freight, capital tied up in transit and stock, service and CO2e under disruptions such as the Red Sea diversion, typhoons and air-capacity crunches. Distances, freight rates, lead times and emission factors reuse the repository's sourced inputs; SKUs, demand, capacities, fixed costs and disruption magnitudes are declared assumptions in `network_planning/config.json`.

**Model.** A fixed-charge multi-commodity, multi-period MILP: flow balance with scenario- and week-dependent lead times, lane capacities with binary lane-week activation, air block-space reservation (first stage) with reserved and spot air, soft or hard terminal stock targets, an optional service floor and an expected-emissions cap or carbon price. Shipments are continuous tactical flows by default and integer on request.

**Two-stage stochastic programming.** Decisions departing before the reveal week and the air reservation are shared across scenarios (non-anticipativity). The engine reports RP, WS, EEV (nominal first stage plus optimal recourse), VSS = EEV − RP and EVPI = RP − WS, with intervals from HiGHS dual bounds so remaining MIP gaps cannot masquerade as value.

**Carbon analysis.** Epsilon-constraint frontier, average and step marginal abatement cost, shadow prices from the LP obtained by fixing lane activations at the MIP optimum, and a carbon-price sweep; with binaries some Pareto points are not supported by any single price.

**Engineering.** Independent accounting recomputes every cost, emission and constraint from the decisions alone and must match the solver objective to 1e-6; a hand-checkable instance anchors the tests; HiGHS heuristic effort, integrality cost and disaggregated big-M constraints were measured rather than assumed.

**Results** (12 synthetic SKUs per network, 16 weeks, seed 7, relative MIP gap <= 0.1%; [full report](../benchmark_results/network_planning/report.md)):

- *Disruptions*: the Red Sea diversion raises ASML spare-parts cost by 12.38% and emissions by 28.4%; the air-capacity crunch costs nothing because reserved block space covers it; a typhoon raises Marvell chip cost by 2.17%.
- *Abatement*: ASML cuts of 10/25/40/60% cost +0.36/+1.76/+3.42/+12.97% (average MAC 95–574 USD/t; shadow price 277 USD/t at the 25% cut), a hockey-stick curve with at most a 72.5% cut at 98% service. A 100 USD/t carbon price cuts only 6.6%; 400 and 800 USD/t select the same plan, showing non-supported Pareto points. Marvell's implied carbon price is about 20,000–30,000 USD/t and a 6,400 USD/t price changes nothing, because transit capital dominates for chips worth 6,000–18,800 USD/kg.
- *Stochastic value*: ASML VSS is 864 USD (1.51% of RP, gap-aware interval [821, 869]) and EVPI 190 USD (0.33%); the two-stage plan pre-ships about 836 kg more by ocean before the reveal and reserves 199 instead of 164 kg/week of air space, making it 6.0% cheaper if the Red Sea scenario occurs and 0.33% dearer otherwise. Marvell's VSS interval contains zero: its nominal plan is already robust.
- *Integrality and scale*: integer shipments raise the objective by only 0.04–0.09% but take 3–26 times longer; continuous flows solve 400 SKUs (26,065 variables) in about 4 seconds, while SKU-level order fees with 3,232 binaries reach the 60-second limit at a 0.2% gap. Disaggregated big-M links gave no consistent speed-up.

**Limitations.** Known committed demand with discrete scenarios, risk-neutral objective, a single destination warehouse and synthetic parameters. The engine targets PuLP 3.3 with its 4.x-style `add_variable` API; PuLP 4.x changed the solve-status interface, so migrating is follow-up work. Results compare policies under stated assumptions and are not company measurements.
