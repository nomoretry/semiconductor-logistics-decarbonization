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

固定模型在400条合成留出公告上完成两次完整运行，每次均为400/400整条精确匹配。冻结规则为204/400，成对差值为49.0个百分点。复测的解析输出全部一致，但没有增加独立案例数。

按生成事件重采样的差值95%区间为44.0至54.0个百分点；按36个渲染族重采样为32.67至65.58个百分点。两者均使用10,000次成对重采样。完整配置、分类结果、原始响应、用量和复算命令见[正式对照](results/api_test.md)。

模型名、提示词和配置固定，后端权重快照未锁定。结果适用于当前合成任务；20条开发集连接测试另存于[API smoke结果](results/api_smoke.md)。

## 工具工作流

开发审计包含 200 组已知订单数值配置，复用 98 个开发通知事件、36 个渲染族。冻结规则与参考输入分别运行同一固定流程，共 400 次方法运行。

| 输入方法 | 终局流程完成 | 可行计划 | 正确澄清交接 | MILP 调用 |
| --- | ---: | ---: | ---: | ---: |
| 冻结规则 | 200/200 | 127 | 73 | 127 |
| 参考标签输入 | 200/200 | 127 | 73 | 127 |

两组平均工具步数均为 5.905。终局流程完成包含正确交接，因此可行计划数为 127。任务、400 条结果及全部工具轨迹见 [`workflow_development_v1/`](../benchmark_results/workflow_development_v1/)。

这些通知来自规则开发集，结果只说明当前固定流程能够完成现有工具顺序。当前环境未展示实质的信息获取或工具预算权衡，训练门槛 `rl_gate.passed=false`，尚未训练 BC/PPO，也未执行最终千任务评测。

## 真实文本来源

新增[真实公告语料](data/real_notices.md)包含16份官方来源的逐字短摘录，分为12个操作事件组和9个相关事件组。摘录经两个助手核对；每条最多23个词，人工审核仍待完成。

在原有内部`NL_ocean`、16周、整数提前期增量任务下，这16条参考均为`needs_clarification`。路线映射、发运窗口或确定增量缺失时，真实公告不能直接转成规划参数。规则和始终澄清均得到16/16助手参考一致，因此没有建立更新抽取的优势；无正例的相关指标保持为空。

该语料是探索性短摘录审核，不是随机抽样、独立真实留出集或人工金标准。宽口径事件事实另行标注，尚未作为抽取指标评分。`Real notice audit (manual)`工作流可在合并后使用现有Secret完成固定模型的16条审核，程序预算为USD0.05；当前尚无该运行的真实模型成绩。

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
