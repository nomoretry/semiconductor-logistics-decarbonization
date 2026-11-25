# 决策图模型评测 / Decision graph model evaluation

本文先中文、后英文。Chinese precedes English.

## 中文

`pilot` · `S` · `full` · `operational` · `complete`

终态请求 / 计划请求 · 96 / 96

正确率、违约率、截断率和解析失败率以比例计。即时满足率差以百分点计。实际成本、排放和计划超额沿用合成环境单位。

### None

| 指标 | 样本数 | 均值 | 95% 下界 | 95% 上界 |
|---|---:|---:|---:|---:|
| accuracy | 32 | 1 | 1 | 1 |
| violation | 32 | 0 | 0 | 0 |
| truncated | 32 | 0 | 0 | 0 |
| parse_failure | 32 | 0 | 0 | 0 |
| plan_excess | 32 | 0 | 0 | 0 |
| relative_plan_excess_pct | 32 | 0 | 0 | 0 |
| cost_delta | 32 | 0.003125 | -0.665625 | 0.853125 |
| fill_rate_delta_pp | 32 | -0.0260417 | -0.234375 | 0.15625 |
| emissions_delta | 32 | -0.0625 | -0.15625 | 0 |

### None · 规则兜底

| 指标 | 样本数 | 均值 | 95% 下界 | 95% 上界 |
|---|---:|---:|---:|---:|
| plan_excess | 32 | 0 | 0 | 0 |
| relative_plan_excess_pct | 32 | 0 | 0 | 0 |
| cost_delta | 32 | 0.003125 | -0.665625 | 0.853125 |
| fill_rate_delta_pp | 32 | -0.0260417 | -0.234375 | 0.15625 |
| emissions_delta | 32 | -0.0625 | -0.15625 | 0 |

### Chain

| 指标 | 样本数 | 均值 | 95% 下界 | 95% 上界 |
|---|---:|---:|---:|---:|
| accuracy | 32 | 1 | 1 | 1 |
| violation | 32 | 0 | 0 | 0 |
| truncated | 32 | 0 | 0 | 0 |
| parse_failure | 32 | 0 | 0 | 0 |
| plan_excess | 32 | 0 | 0 | 0 |
| relative_plan_excess_pct | 32 | 0 | 0 | 0 |
| cost_delta | 32 | -0.423438 | -1.16875 | 0.0546875 |
| fill_rate_delta_pp | 32 | 0.100806 | 0 | 0.302419 |
| emissions_delta | 32 | 0.03125 | -0.125 | 0.25 |

### Chain · 规则兜底

| 指标 | 样本数 | 均值 | 95% 下界 | 95% 上界 |
|---|---:|---:|---:|---:|
| plan_excess | 32 | 0 | 0 | 0 |
| relative_plan_excess_pct | 32 | 0 | 0 | 0 |
| cost_delta | 32 | -0.423438 | -1.16875 | 0.0546875 |
| fill_rate_delta_pp | 32 | 0.100806 | 0 | 0.302419 |
| emissions_delta | 32 | 0.03125 | -0.125 | 0.25 |

### Graph

| 指标 | 样本数 | 均值 | 95% 下界 | 95% 上界 |
|---|---:|---:|---:|---:|
| accuracy | 32 | 1 | 1 | 1 |
| violation | 32 | 0 | 0 | 0 |
| truncated | 32 | 0 | 0 | 0 |
| parse_failure | 32 | 0 | 0 | 0 |
| plan_excess | 32 | 1.77636e-15 | 0 | 5.32907e-15 |
| relative_plan_excess_pct | 32 | 6.25132e-16 | 0 | 1.8754e-15 |
| cost_delta | 32 | 0.64375 | -0.0859375 | 1.6375 |
| fill_rate_delta_pp | 32 | -0.078125 | -0.234375 | 0 |
| emissions_delta | 32 | 0.0625 | -0.09375 | 0.28125 |

### Graph · 规则兜底

| 指标 | 样本数 | 均值 | 95% 下界 | 95% 上界 |
|---|---:|---:|---:|---:|
| plan_excess | 32 | 1.77636e-15 | 0 | 5.32907e-15 |
| relative_plan_excess_pct | 32 | 6.25132e-16 | 0 | 1.8754e-15 |
| cost_delta | 32 | 0.64375 | -0.0859375 | 1.6375 |
| fill_rate_delta_pp | 32 | -0.078125 | -0.234375 | 0 |
| emissions_delta | 32 | 0.0625 | -0.09375 | 0.28125 |

### Chain − None

| 指标 | 样本数 | 均值 | 95% 下界 | 95% 上界 |
|---|---:|---:|---:|---:|
| accuracy | 32 | 0 | 0 | 0 |
| violation | 32 | 0 | 0 | 0 |
| truncated | 32 | 0 | 0 | 0 |
| parse_failure | 32 | 0 | 0 | 0 |
| plan_excess | 32 | 0 | 0 | 0 |
| relative_plan_excess_pct | 32 | 0 | 0 | 0 |
| cost_delta | 32 | -0.426563 | -1.46875 | 0.404687 |
| fill_rate_delta_pp | 32 | 0.126848 | -0.104167 | 0.406586 |
| emissions_delta | 32 | 0.09375 | 0 | 0.28125 |

### Chain − None · 规则兜底

| 指标 | 样本数 | 均值 | 95% 下界 | 95% 上界 |
|---|---:|---:|---:|---:|
| plan_excess | 32 | 0 | 0 | 0 |
| relative_plan_excess_pct | 32 | 0 | 0 | 0 |
| cost_delta | 32 | -0.426563 | -1.46875 | 0.404687 |
| fill_rate_delta_pp | 32 | 0.126848 | -0.104167 | 0.406586 |
| emissions_delta | 32 | 0.09375 | 0 | 0.28125 |

### Graph − None

| 指标 | 样本数 | 均值 | 95% 下界 | 95% 上界 |
|---|---:|---:|---:|---:|
| accuracy | 32 | 0 | 0 | 0 |
| violation | 32 | 0 | 0 | 0 |
| truncated | 32 | 0 | 0 | 0 |
| parse_failure | 32 | 0 | 0 | 0 |
| plan_excess | 32 | 1.77636e-15 | 0 | 5.32907e-15 |
| relative_plan_excess_pct | 32 | 6.25132e-16 | 0 | 1.8754e-15 |
| cost_delta | 32 | 0.640625 | 0.0890625 | 1.43125 |
| fill_rate_delta_pp | 32 | -0.0520833 | -0.15625 | 0 |
| emissions_delta | 32 | 0.125 | 0 | 0.34375 |

### Graph − None · 规则兜底

| 指标 | 样本数 | 均值 | 95% 下界 | 95% 上界 |
|---|---:|---:|---:|---:|
| plan_excess | 32 | 1.77636e-15 | 0 | 5.32907e-15 |
| relative_plan_excess_pct | 32 | 6.25132e-16 | 0 | 1.8754e-15 |
| cost_delta | 32 | 0.640625 | 0.0890625 | 1.43125 |
| fill_rate_delta_pp | 32 | -0.0520833 | -0.15625 | 0 |
| emissions_delta | 32 | 0.125 | 0 | 0.34375 |

### Graph − Chain

| 指标 | 样本数 | 均值 | 95% 下界 | 95% 上界 |
|---|---:|---:|---:|---:|
| accuracy | 32 | 0 | 0 | 0 |
| violation | 32 | 0 | 0 | 0 |
| truncated | 32 | 0 | 0 | 0 |
| parse_failure | 32 | 0 | 0 | 0 |
| plan_excess | 32 | 1.77636e-15 | 0 | 5.32907e-15 |
| relative_plan_excess_pct | 32 | 6.25132e-16 | 0 | 1.8754e-15 |
| cost_delta | 32 | 1.06719 | 0.165625 | 2.125 |
| fill_rate_delta_pp | 32 | -0.178931 | -0.458669 | 0 |
| emissions_delta | 32 | 0.03125 | 0 | 0.09375 |

### Graph − Chain · 规则兜底

| 指标 | 样本数 | 均值 | 95% 下界 | 95% 上界 |
|---|---:|---:|---:|---:|
| plan_excess | 32 | 1.77636e-15 | 0 | 5.32907e-15 |
| relative_plan_excess_pct | 32 | 6.25132e-16 | 0 | 1.8754e-15 |
| cost_delta | 32 | 1.06719 | 0.165625 | 2.125 |
| fill_rate_delta_pp | 32 | -0.178931 | -0.458669 | 0 |
| emissions_delta | 32 | 0.03125 | 0 | 0.09375 |

### 计算代价

| 上下文 | 美元/调用 | 美元/B 决定 | 平均秒 | p95 秒 | 输入 token | 输出 token | 推理 token |
|---|---:|---:|---:|---:|---:|---:|---:|
| None | 0.0580832 | 0.0580832 | 87.3204 | 169.196 | 1568.25 | 5419.16 | 5400.16 |
| Chain | 0.0409413 | 0.0409413 | 62.8235 | 160.257 | 1705.25 | 3670.72 | 3651.72 |
| Graph | 0.0453155 | 0.0453155 | 68.983 | 185.349 | 2128.69 | 4002.28 | 3983.28 |

累计账本按相同请求哈希纳入历次已结算调用。

| 结算调用 | 结算美元 | 预留美元 | 结算美元/调用 | 结算美元/B 决定 |
|---:|---:|---:|---:|---:|
| 96 | 4.61888 | 0 | 0.0481133 | 0.0481133 |

32 张试点图的参考规划器与规则动作耗时中位数（秒）依次为 0.0160373 / 0.0007268.

### 同范围 DQ-2 基线

| 答题方 | B 正确率 | B 违约率 | P3 正确率 | 计划超额 | 相对超额（%） | 实际成本差 | 即时满足率差（百分点） | 排放差 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `gold` | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| `rule` | 0.125 | 0 | 0.630208 | 12.6449 | 10.8893 | 5.27031 | -2.57085 | -1.40625 |

### 同范围离线参照

| 参照 | B 正确率 | 相对超额均值（%） |
|---|---:|---:|
| 只读题目文字的程序 | 1 | — |
| 只用均值预测的规划 | 0.3125 | 14.1246 |
| 与 P3 标准答案一致的矩阵中随机取一个 | 0.500805 | 6.08603 |

### 返回模型

- S · `gpt-6.2-sol` (96)

## English

`pilot` · `S` · `full` · `operational` · `complete`

Terminal requests / planned requests · 96 / 96

Accuracy, violation, truncation and parse failure are proportions. Immediate fulfillment differences are in percentage points. Realized cost, emissions and planned excess use the synthetic environment's units.

### None

| Metric | n | Mean | 95% lower | 95% upper |
|---|---:|---:|---:|---:|
| accuracy | 32 | 1 | 1 | 1 |
| violation | 32 | 0 | 0 | 0 |
| truncated | 32 | 0 | 0 | 0 |
| parse_failure | 32 | 0 | 0 | 0 |
| plan_excess | 32 | 0 | 0 | 0 |
| relative_plan_excess_pct | 32 | 0 | 0 | 0 |
| cost_delta | 32 | 0.003125 | -0.665625 | 0.853125 |
| fill_rate_delta_pp | 32 | -0.0260417 | -0.234375 | 0.15625 |
| emissions_delta | 32 | -0.0625 | -0.15625 | 0 |

### None · rule fallback

| Metric | n | Mean | 95% lower | 95% upper |
|---|---:|---:|---:|---:|
| plan_excess | 32 | 0 | 0 | 0 |
| relative_plan_excess_pct | 32 | 0 | 0 | 0 |
| cost_delta | 32 | 0.003125 | -0.665625 | 0.853125 |
| fill_rate_delta_pp | 32 | -0.0260417 | -0.234375 | 0.15625 |
| emissions_delta | 32 | -0.0625 | -0.15625 | 0 |

### Chain

| Metric | n | Mean | 95% lower | 95% upper |
|---|---:|---:|---:|---:|
| accuracy | 32 | 1 | 1 | 1 |
| violation | 32 | 0 | 0 | 0 |
| truncated | 32 | 0 | 0 | 0 |
| parse_failure | 32 | 0 | 0 | 0 |
| plan_excess | 32 | 0 | 0 | 0 |
| relative_plan_excess_pct | 32 | 0 | 0 | 0 |
| cost_delta | 32 | -0.423438 | -1.16875 | 0.0546875 |
| fill_rate_delta_pp | 32 | 0.100806 | 0 | 0.302419 |
| emissions_delta | 32 | 0.03125 | -0.125 | 0.25 |

### Chain · rule fallback

| Metric | n | Mean | 95% lower | 95% upper |
|---|---:|---:|---:|---:|
| plan_excess | 32 | 0 | 0 | 0 |
| relative_plan_excess_pct | 32 | 0 | 0 | 0 |
| cost_delta | 32 | -0.423438 | -1.16875 | 0.0546875 |
| fill_rate_delta_pp | 32 | 0.100806 | 0 | 0.302419 |
| emissions_delta | 32 | 0.03125 | -0.125 | 0.25 |

### Graph

| Metric | n | Mean | 95% lower | 95% upper |
|---|---:|---:|---:|---:|
| accuracy | 32 | 1 | 1 | 1 |
| violation | 32 | 0 | 0 | 0 |
| truncated | 32 | 0 | 0 | 0 |
| parse_failure | 32 | 0 | 0 | 0 |
| plan_excess | 32 | 1.77636e-15 | 0 | 5.32907e-15 |
| relative_plan_excess_pct | 32 | 6.25132e-16 | 0 | 1.8754e-15 |
| cost_delta | 32 | 0.64375 | -0.0859375 | 1.6375 |
| fill_rate_delta_pp | 32 | -0.078125 | -0.234375 | 0 |
| emissions_delta | 32 | 0.0625 | -0.09375 | 0.28125 |

### Graph · rule fallback

| Metric | n | Mean | 95% lower | 95% upper |
|---|---:|---:|---:|---:|
| plan_excess | 32 | 1.77636e-15 | 0 | 5.32907e-15 |
| relative_plan_excess_pct | 32 | 6.25132e-16 | 0 | 1.8754e-15 |
| cost_delta | 32 | 0.64375 | -0.0859375 | 1.6375 |
| fill_rate_delta_pp | 32 | -0.078125 | -0.234375 | 0 |
| emissions_delta | 32 | 0.0625 | -0.09375 | 0.28125 |

### Chain − None

| Metric | n | Mean | 95% lower | 95% upper |
|---|---:|---:|---:|---:|
| accuracy | 32 | 0 | 0 | 0 |
| violation | 32 | 0 | 0 | 0 |
| truncated | 32 | 0 | 0 | 0 |
| parse_failure | 32 | 0 | 0 | 0 |
| plan_excess | 32 | 0 | 0 | 0 |
| relative_plan_excess_pct | 32 | 0 | 0 | 0 |
| cost_delta | 32 | -0.426563 | -1.46875 | 0.404687 |
| fill_rate_delta_pp | 32 | 0.126848 | -0.104167 | 0.406586 |
| emissions_delta | 32 | 0.09375 | 0 | 0.28125 |

### Chain − None · rule fallback

| Metric | n | Mean | 95% lower | 95% upper |
|---|---:|---:|---:|---:|
| plan_excess | 32 | 0 | 0 | 0 |
| relative_plan_excess_pct | 32 | 0 | 0 | 0 |
| cost_delta | 32 | -0.426563 | -1.46875 | 0.404687 |
| fill_rate_delta_pp | 32 | 0.126848 | -0.104167 | 0.406586 |
| emissions_delta | 32 | 0.09375 | 0 | 0.28125 |

### Graph − None

| Metric | n | Mean | 95% lower | 95% upper |
|---|---:|---:|---:|---:|
| accuracy | 32 | 0 | 0 | 0 |
| violation | 32 | 0 | 0 | 0 |
| truncated | 32 | 0 | 0 | 0 |
| parse_failure | 32 | 0 | 0 | 0 |
| plan_excess | 32 | 1.77636e-15 | 0 | 5.32907e-15 |
| relative_plan_excess_pct | 32 | 6.25132e-16 | 0 | 1.8754e-15 |
| cost_delta | 32 | 0.640625 | 0.0890625 | 1.43125 |
| fill_rate_delta_pp | 32 | -0.0520833 | -0.15625 | 0 |
| emissions_delta | 32 | 0.125 | 0 | 0.34375 |

### Graph − None · rule fallback

| Metric | n | Mean | 95% lower | 95% upper |
|---|---:|---:|---:|---:|
| plan_excess | 32 | 1.77636e-15 | 0 | 5.32907e-15 |
| relative_plan_excess_pct | 32 | 6.25132e-16 | 0 | 1.8754e-15 |
| cost_delta | 32 | 0.640625 | 0.0890625 | 1.43125 |
| fill_rate_delta_pp | 32 | -0.0520833 | -0.15625 | 0 |
| emissions_delta | 32 | 0.125 | 0 | 0.34375 |

### Graph − Chain

| Metric | n | Mean | 95% lower | 95% upper |
|---|---:|---:|---:|---:|
| accuracy | 32 | 0 | 0 | 0 |
| violation | 32 | 0 | 0 | 0 |
| truncated | 32 | 0 | 0 | 0 |
| parse_failure | 32 | 0 | 0 | 0 |
| plan_excess | 32 | 1.77636e-15 | 0 | 5.32907e-15 |
| relative_plan_excess_pct | 32 | 6.25132e-16 | 0 | 1.8754e-15 |
| cost_delta | 32 | 1.06719 | 0.165625 | 2.125 |
| fill_rate_delta_pp | 32 | -0.178931 | -0.458669 | 0 |
| emissions_delta | 32 | 0.03125 | 0 | 0.09375 |

### Graph − Chain · rule fallback

| Metric | n | Mean | 95% lower | 95% upper |
|---|---:|---:|---:|---:|
| plan_excess | 32 | 1.77636e-15 | 0 | 5.32907e-15 |
| relative_plan_excess_pct | 32 | 6.25132e-16 | 0 | 1.8754e-15 |
| cost_delta | 32 | 1.06719 | 0.165625 | 2.125 |
| fill_rate_delta_pp | 32 | -0.178931 | -0.458669 | 0 |
| emissions_delta | 32 | 0.03125 | 0 | 0.09375 |

### Computational cost

| Context | USD/call | USD/B decision | Mean s | p95 s | Input tokens | Output tokens | Reasoning tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| None | 0.0580832 | 0.0580832 | 87.3204 | 169.196 | 1568.25 | 5419.16 | 5400.16 |
| Chain | 0.0409413 | 0.0409413 | 62.8235 | 160.257 | 1705.25 | 3670.72 | 3651.72 |
| Graph | 0.0453155 | 0.0453155 | 68.983 | 185.349 | 2128.69 | 4002.28 | 3983.28 |

The cumulative ledger includes settled attempts with matching request hashes.

| Settled calls | Settled USD | Reserved USD | Settled USD/call | Settled USD/B decision |
|---:|---:|---:|---:|---:|
| 96 | 4.61888 | 0 | 0.0481133 | 0.0481133 |

Median local time (seconds) on 32 pilot graphs, reference planner then rule action, was 0.0160373 / 0.0007268.

### DQ-2 baselines over the same graph scope

| Responder | B accuracy | B violation | P3 accuracy | Planned excess | Relative excess (%) | Cost delta | Immediate fulfillment delta (pp) | Emissions delta |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `gold` | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| `rule` | 0.125 | 0 | 0.630208 | 12.6449 | 10.8893 | 5.27031 | -2.57085 | -1.40625 |

### Offline references over the same graph scope

| Reference | B accuracy | Mean relative excess (%) |
|---|---:|---:|
| Text-only program | 1 | — |
| Plan on the mean forecast | 0.3125 | 14.1246 |
| Random dispatch that agrees with the P3 reference answers | 0.500805 | 6.08603 |

### Returned models

- S · `gpt-6.2-sol` (96)
