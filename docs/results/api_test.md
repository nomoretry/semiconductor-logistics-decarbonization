# 固定模型在合成留出集上的公告抽取

GPT-6 Luna 在同一组 400 条冻结合成留出公告上，两次完整运行均为 400/400 整条精确匹配；冻结规则为 204/400。主运行相对规则提高 49.0 个百分点，196 条由错误变为正确，没有反向变化。复测覆盖原来的 400 条，不能计为 800 条不同案例。

先完成的完整运行作为主运行，后续完整运行作为复测。此前 20 条开发集调用保留为[流程验证](api_smoke.md)。留出结果未用于修改规则、提示词、Schema、标签或 API 程序。

## 配置与比较口径

| 项目 | 设置 |
|---|---|
| 模型名 | `gpt-6-luna` |
| 接口与推理参数 | OpenAI Responses API；`reasoning.effort=none` |
| 输出约束 | 严格 JSON Schema；最多 768 输出 token |
| 输入 | 公告正文和公开业务上下文；参考答案与生成元数据不发送给模型 |
| 数据范围 | 冻结 `test` 全部 400 条；每次运行每条调用一次 |
| 参考状态 | 224 条可处理公告；176 条需要澄清 |
| 分组 | 400 个生成事件；36 个渲染族；18 类语义 |
| 主指标 | 整条公告精确匹配，仅忽略变更列表顺序 |
| 次指标 | 编译后的逐周提前期排程一致 |
| 基线 | 冻结规则在相同的 `text`、`context` 上重新执行 |

两次运行的请求配置、输入哈希、提示词、Schema 和 API 程序身份一致。模型名固定，但返回值仍为 `gpt-6-luna` 别名，未获得后端快照或系统指纹，不能声称锁定了模型权重版本。

## 完整运行结果

| 指标 | API 主运行 | API 复测 | 冻结规则 |
|---|---:|---:|---:|
| 完成请求 | 400/400 | 400/400 | 不适用 |
| API / 传输错误 | 0 / 0 | 0 / 0 | 不适用 |
| 未知结果 / 未尝试 | 0 / 0 | 0 / 0 | 不适用 |
| 整条公告精确匹配 | 400/400 | 400/400 | 204/400 |
| JSON 与 Schema 有效 | 400/400 | 400/400 | 400/400 |
| 排程效果一致 | 400/400 | 400/400 | 204/400 |
| 正确可处理覆盖率 | 100.0% | 100.0% | 20.1% |
| 可处理结果语义精度 | 100.0% | 100.0% | 61.6% |
| 澄清精度 | 100.0% | 100.0% | 48.6% |
| 澄清召回率 | 100.0% | 100.0% | 90.3% |

主运行和规则同时正确 204 条，只有主运行正确 196 条，只有规则正确 0 条，同时错误 0 条。复测的 400 条解析输出全部与主运行一致。两次运行共记录 800 次 API 调用，仍只有 400 条不同案例，新增独立留出案例为 0。

## 成对差值与分组不确定性

| 重采样分组 | 组数 | 精确匹配率差值 | 95% percentile bootstrap 区间 |
|---|---:|---:|---:|
| 生成事件 | 400 | +49.0 个百分点 | +44.0 至 +54.0 个百分点 |
| 渲染族 | 36 | +49.0 个百分点 | +32.67 至 +65.58 个百分点 |

两个区间都使用 10,000 次重采样和种子 `20261030`。每次对同一组案例同时抽取 API 与规则结果；抽取完整事件或完整渲染族，保留组内案例，按被抽中案例数计算差值。它们是分别按两种分组得到的敏感性区间，不是多维联合 bootstrap。复测独立计算差值，不与主运行合并增加样本数。

400 个事件由模板生成，共享 36 个渲染族；它们不是 400 条独立采集的真实公告。这里的 100% 是对保存输出和合成参考标签的结果，不能推导真实公告上的成功率。真实来源公告的双人标注与评测仍需另做。

## 各类案例

| 类别 | 案例数 | API 主运行正确 | 冻结规则正确 |
|---|---:|---:|---:|
| added_days | 23 | 23 | 0 |
| added_fortnights | 23 | 23 | 0 |
| added_weeks | 23 | 23 | 11 |
| arrival_window | 22 | 22 | 22 |
| conflicting_reports | 22 | 22 | 11 |
| correction | 22 | 22 | 0 |
| missing_increment | 22 | 22 | 22 |
| missing_route | 22 | 22 | 22 |
| missing_window | 22 | 22 | 22 |
| multiple_windows | 22 | 22 | 0 |
| negated_alert | 22 | 22 | 0 |
| no_change | 22 | 22 | 0 |
| nonintegral_days | 22 | 22 | 22 |
| revised_total | 23 | 23 | 23 |
| superseded_window | 22 | 22 | 11 |
| uncertain_range | 22 | 22 | 16 |
| unknown_route | 22 | 22 | 22 |
| unrelated_route | 22 | 22 | 0 |

## 用量与原始记录

| 记录 | 主运行 | 复测 |
|---|---:|---:|
| 输入 token | 199,935 | 199,935 |
| 输出 token | 12,966 | 12,966 |
| 按记录单价估算费用 | USD 0.02647650 | USD 0.02647650 |

费用按运行文件记录的输入 USD 0.10/百万 token、输出 USD 0.50/百万 token 计算，未计缓存折扣，以平台账单为准。原文件中的定价日期、请求时间戳、响应 ID、响应时间及其他提供方元数据均原样保留。

每次运行完整保留 10 个原始文本文件：`estimate.json`、`evaluation.json`、`evaluation.md`、`inputs.jsonl`、`ledger-anchor.json`、`manifest.json`、`prompt.txt`、`records.jsonl`、`schema.json`、`summary.json`。`provenance.json` 记录下载包 SHA-256、逐文件 SHA-256、工作流、artifact、源码提交和 API 程序哈希。

| 来源 | 主运行 | 复测 |
|---|---|---|
| 工作流 | [40962758214](https://github.com/nomoretry/semiconductor-logistics-decarbonization/actions/runs/40962758214) | [40966053738](https://github.com/nomoretry/semiconductor-logistics-decarbonization/actions/runs/40966053738) |
| Artifact ID | `12936629568` | `12938901519` |
| 源码提交 | [4cacb43e](https://github.com/nomoretry/semiconductor-logistics-decarbonization/commit/4cacb43e071e8a8911247a2cdd7c10ddbc92d4d3) | [faf8740e](https://github.com/nomoretry/semiconductor-logistics-decarbonization/commit/faf8740e2495c52491128cc94fae1ba33a637155) |
| 原始输入 | [inputs.jsonl](../../benchmark_results/api_test/inputs.jsonl) | [inputs.jsonl](../../benchmark_results/api_repeat/inputs.jsonl) |
| 完整响应账本 | [records.jsonl](../../benchmark_results/api_test/records.jsonl) | [records.jsonl](../../benchmark_results/api_repeat/records.jsonl) |
| 来源与文件哈希 | [provenance.json](../../benchmark_results/api_test/provenance.json) | [provenance.json](../../benchmark_results/api_repeat/provenance.json) |

## 离线复算

```bash
python -m scripts.compare_notice_api \
  --run benchmark_results/api_test \
  --repeat-run benchmark_results/api_repeat
python -m unittest tests.test_notice_api_comparison tests.test_notice_api_runner
```

比较程序先在临时副本上调用严格 `score_run`，验证数据、请求身份、输入、提示词、Schema、API 程序、原始响应解析和哈希链，再校验冻结规则身份并逐条成对比较。缺失、重复、篡改或未完成的运行会失败；同一账本不能重复充当复测。复算不读取凭据、不调用 API、不改写 10 个原始文件，仅生成 [comparison.json](../../benchmark_results/api_test/comparison.json) 和 [comparison.md](../../benchmark_results/api_test/comparison.md)。
