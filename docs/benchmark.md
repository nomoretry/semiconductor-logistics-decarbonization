# 基准与结果

仓库分别评估文本解释、工具流程和物流规划。三者使用不同数据与统计单位，结果分别报告。

## 通知数据

独立文本基准包含 120 条开发文本与 400 条合成留出文本，覆盖 18 类语义：时间与单位换算、修订和否定、多窗口、无关路线、缺失信息及冲突等。开发集与留出集的事件 ID、推理载荷和渲染族 ID 均不重叠，每个划分包含 36 个渲染族。

模型只读取 `text` 和 `context`；标签和生成元数据用于离线评分。同一渲染族包含多条相关样本，400 个合成事件 ID 不等于 400 个独立真实事件。

| 身份 | SHA-256 |
| --- | --- |
| 数据集 | `1508cf37714eaa11542f151fe05d57d450f4c2e2f01bbea3c08437696d0a8a94` |
| 冻结规则源码 | `c692440d148cd37329a5524a6cf22684409eed3631095ad5ce19ede319b0bb73` |

冻结记录见 [`rules_freeze.json`](../benchmarks/notices_v1/rules_freeze.json)。规则仅依据开发集和独立语义测试开发，留出结果保留原值。

## 冻结规则结果

| 方法 | 留出集整条通知匹配 | 准确率 |
| --- | ---: | ---: |
| 冻结规则 | 204/400 | 51.0% |
| 始终澄清 | 176/400 | 44.0% |
| 忽略通知，保持原参数 | 66/400 | 16.5% |
| 参考标签输入 | 400/400 | 100.0% |

参考标签是标注上界；始终澄清和忽略通知是诊断对照。完整预测、分类指标和编译效果指标见 [`benchmark_results/notices_v1/`](../benchmark_results/notices_v1/)。

规则在开发集上匹配 120/120，在留出集上的 JSON/schema 有效性为 100%，但仅正确处理 45/224 条参考状态为 `ready` 的通知；对 176 条信息不足通知有 17 条误报 `ready`。结构合法与语义正确分别计量。

按事件计的 Wilson 95% 区间约为 `[46.1%, 55.9%]`。按 36 个渲染族重采样的宏平均准确率区间约为 `[34.6%, 66.7%]`，反映模板相关性带来的较大不确定性。当前规则的结构匹配率和编译效果匹配率均为 51.0%。

## API 评测

开发集 API smoke 已完成 20 条调用，整条通知匹配为 20/20。模型、调用记录、token 用量与验证方式见 [API smoke 结果](results/api_smoke.md)。这批开发样本用于验证真实 API 链路；400 条留出集的固定 LLM 对照尚未完成。

`api` 默认只生成费用估算，执行需要 `--execute` 和正数预算上限。运行记录包含输入、提示词、schema 与模型参数哈希，以及响应模型、调用状态和 token 用量；`score-api` 从保存结果重算指标。参数说明见 [API 连接说明](secure_api_connection.md)。

## 工具工作流

开发审计包含 200 组已知订单数值配置，复用 98 个开发通知事件、36 个渲染族。冻结规则与参考输入分别运行同一固定流程，共 400 次方法运行。

| 输入方法 | 终局流程完成 | 可行计划 | 正确澄清交接 | MILP 调用 |
| --- | ---: | ---: | ---: | ---: |
| 冻结规则 | 200/200 | 127 | 73 | 127 |
| 参考标签输入 | 200/200 | 127 | 73 | 127 |

两组平均工具步数均为 5.905。终局流程完成包含正确交接，因此可行计划数为 127。任务、400 条结果及全部工具轨迹见 [`workflow_development_v1/`](../benchmark_results/workflow_development_v1/)。

这些通知来自规则开发集，结果只说明当前固定流程能够完成现有工具顺序。当前环境未展示实质的信息获取或工具预算权衡，训练门槛 `rl_gate.passed=false`，尚未训练 BC/PPO，也未执行最终千任务评测。

## 真实文本来源

[`real_source_registry.json`](../notice_benchmark/real_source_registry.json) 登记 13 份官方承运人来源，分为 10 个操作事件组及 7 个较广的相关扰动组。所有条目仍为 `pending_human_review`，`usable_as_frozen_gold=false`。

该登记表尚未形成真实标注测试集。纳入评测前需核对公告全文、版本优先级、路线映射、有效日期和数值是否足以构造参考更新，并按相关事件分组划分数据。

## 物流实验

合成主实验为两个场景 × 3 类扰动 × 10 份订单簿 × 6 种策略。各实例的订单、初始库存和服务条件在策略间保持一致。

| 公开合成明细 | 求解记录 | 订单实例 | 可行计划 |
| --- | ---: | ---: | ---: |
| ASML | 180 | 30 | 162 |
| Marvell | 180 | 30 | 177 |
| 合计 | 360 | 60 | 339 |

归档汇总另含 ASML 的 10 组外部汽车备件月度压力测试，每组 4 种策略，共 40 次求解。因此 `reports/summary.json` 与运行清单覆盖 400 次实验，公开逐次明细覆盖上述 360 次合成实验。外部需求序列、选中序列 ID 和逐实例压力测试结果未列入公开明细。

场景参数和匹配结果见 [ASML](../asml/README.md)、[Marvell](../marvell/README.md)；成本、排放与约束定义见[方法](methodology.md)，综合结果见 [`study_report.md`](../reports/study_report.md)。

## 复现

在仓库根目录安装并运行离线基准：

```bash
python -m pip install -c constraints.txt -e .
semiconductor-logistics evaluate --output artifacts/offline_replay
semiconductor-logistics verify-run --output artifacts/offline_replay
semiconductor-logistics workflow-audit --output artifacts/workflow_replay
semiconductor-logistics workflow-audit --output artifacts/workflow_replay --verify
python -m unittest discover -s tests -v
```

重新生成通知时使用 `semiconductor-logistics generate --output artifacts/notices_v1`。冻结身份不允许被不同规则或数据覆盖；依据现有留出错误修改方法后，应另建留出集进行新的最终比较。

完整物流实验需要先下载原始数据：

```bash
semiconductor-logistics download-data
semiconductor-logistics optimize --project both
semiconductor-logistics sensitivity --project both
semiconductor-logistics report
```

`optimize` 会重写 `reports/` 中的实验结果，完整重跑也会生成外部压力测试明细。发布的合成明细与归档汇总范围见上表。
