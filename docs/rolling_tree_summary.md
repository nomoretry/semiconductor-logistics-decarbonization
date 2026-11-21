本文先列中文，后列英文。 / Chinese first, English second.

# 需求关联是否改善滚动发运 / Does demand dependence improve rolling dispatch?

## 中文

### 最终回答

三个 SKU 争用有限运力时，保留同期需求配对会改变部分发运决定。160 条完整合成路径中，133 条至少有一期改变了发运件数。与只打乱配对的 M2 相比，M1 的平均总成本差为 0.205（相对 0.08%，配对 t 95% 区间 [-1.662, 2.071]），事前判定为 **没有实用价值（成本等效）**。即时满足率差为 0.192 个百分点，区间 [-0.00026, 0.38373]。排放差为 -0.281，区间 [-0.685, 0.123]。交付与排放两项指标的区间均跨零。本环境中没有测出保留配对带来的交付或排放改善。 [闭环收尾结果](rolling_tree_closing_test.md)

### 五个阶段的证据

| 阶段 | 设计与测得的结果 |
|---|---|
| [v1](rolling_tree_pilot.md) 开发试跑 | 2 条开发路径、1 个采样种子。22 个可发运状态中有 3 个在排除平局后仍受配对影响。两条路径的 M1−M2* 成本差为 −0.30、−12.55。 |
| [v2](rolling_tree_pilot_v2.md) 开发试跑 | 4 条路径、3 个采样种子，132 个非强制状态中有 14 个实质改变。M1−M2* 有 10 个完整配对，平均相对成本差 −1.5%，按采样种子方向不一致。第一期误差门槛也未通过。 |
| [首期稳定性](rolling_tree_stability.md) | 固定四条开发路径的 44 个观测。延续路径从 3 增至 12，首期动作改变 44/132。在 12 档只换种子，改变 53/132。两项均高于 10% 门槛。 |
| [实质性与三树选择](rolling_tree_consensus.md) | 上述 44 和 53 个动作差异均超过求解数值容差。三树选择后，跨种子组仍改变 17/44，跨档仍改变 20/44，稳定性门槛继续未通过。 |
| [闭环收尾结果](rolling_tree_closing_test.md) | 另行事前登记，使用 160 条新合成路径。五个在线策略和一个预知下界均完成 160 条路径，M1−M2 按同一路径比较实际成本、即时满足率及排放。 |

### 条件、局限与下一项验收

拟合的共同冲击方差约为 0.077。慢线和快线每期分别提供 8 和 4 个质量单位，全期碳预算为 132。首次分歧时，M1 / M2 的慢线满载比例为 60.90% / 57.14%，窗口碳约束取紧比例为 15.04% / 11.28%。B1 每期都会用新需求更新 EWMA 并重规划。这些结果说明比较发生在已有反馈和共享约束的系统。各因素对成本差的独立贡献仍未经测量。

证据限于一个合成环境，每路径一个规划采样种子，未独立验证。项目另一模块用 SciPy 1.17.0 的 HiGHS 复现了预处理返回错误最优与误报不可行，本研究沿用开启预处理的设置，个别首期动作和实质性分析中的目标超额可能受影响。环境对已执行动作独立记账。若动作受求解影响，轨迹仍会随之变化。另一模块的复现记录可用 `git show 92be4e6:docs/decision_graph_qa_protocol_amendment.md` 查阅。

R1 在本环境收尾。若重启，先在独立校准的环境中预登记相同的参考线，再检验成本区间能否支持至少 2% 的节约，同时满足率下降不超过 0.5 个百分点、排放增加不超过 2%。

## English

### Answer

When three SKUs share limited freight capacity, preserving contemporaneous pairing changes some dispatch decisions. Of 160 complete synthetic paths, 133 had at least one change in shipped units. Compared with shuffled-pairing M2, M1 had a mean total cost difference of 0.205 (0.08% relative, paired t 95% CI [-1.662, 2.071]). The preregistered decision was **equivalent within the practical cost margin**. Immediate fill differed by 0.192 percentage points, CI [-0.00026, 0.38373], and emissions by -0.281, CI [-0.685, 0.123]. Both the fill and emissions intervals included zero. This environment showed no measurable improvement in either outcome from preserving pairing. [Closing test](rolling_tree_closing_test.md)

### Evidence across five stages

| Stage | Design and measured result |
|---|---|
| [v1](rolling_tree_pilot.md) development pilot | Two paths and one planning seed. Pairing changed the action beyond ties in 3 of 22 dispatchable states. Realized M1−M2* cost differences were −0.30 and −12.55. |
| [v2](rolling_tree_pilot_v2.md) development pilot | Four paths and three planning seeds. Pairing materially changed 14 of 132 non-forced states. The ten complete M1−M2* pairs averaged −1.5% relative cost, with disagreement in sign across seeds. The first-period error gate also failed. |
| [First-action stability](rolling_tree_stability.md) | Across 44 fixed observations on four development paths, increasing continuations from 3 to 12 changed 44/132 actions. Changing the sampler at 12 continuations changed 53/132. Both exceeded the 10% gate. |
| [Materiality and three-tree selection](rolling_tree_consensus.md) | All 44 and 53 differences exceeded numerical tolerance. Three-tree selection still changed 17/44 actions across seed groups and 20/44 across continuation tiers. The stability gate again failed. |
| [Closing test](rolling_tree_closing_test.md) | A separately preregistered test covered 160 fresh synthetic paths and completed all five online policies and the offline bound, comparing realized M1−M2 cost, fill and emissions within each path. |

### Conditions, limitations and next acceptance condition

The fitted common-shock variance was about 0.077. Slow and fast capacity were 8 and 4 mass units per period, with an episode carbon budget of 132. At first divergence, M1 / M2 filled the slow route on 60.90% / 57.14% of pairs, and used their full window carbon allowance on at least one leaf on 15.04% / 11.28%. B1 updated its EWMA forecast and replanned each period. These quantities describe a system with feedback and shared constraints. Their separate contributions to the cost difference were unmeasured.

The evidence covers one synthetic environment and one planning seed per path, and awaits independent validation. Elsewhere in the project HiGHS in SciPy 1.17.0 reproduced incorrect optima and false infeasibility with presolve enabled. This study retained presolve, which could affect individual first actions and objective excesses in the materiality analysis. The environment independently calculates realized cost given the actions actually executed. A change in the solver-selected action can still change the trajectory. The separate reproductions are available via `git show 92be4e6:docs/decision_graph_qa_protocol_amendment.md`.

R1 closes for this environment. A future study should preregister the same reference thresholds in an independently calibrated environment, then test whether the cost interval supports at least 2% savings with a fill decline no greater than 0.5 percentage points and an emissions increase no greater than 2%.
