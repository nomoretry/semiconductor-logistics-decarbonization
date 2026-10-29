# 固定模型公告抽取

在公告开发集前 20 条文本上运行 GPT-6 Luna，逐条保存输入、原始响应、结构化输出和用量。20 次请求全部完成，抽取结果与参考标签一致。

## 配置

| 项目 | 设置 |
|---|---|
| 模型 | `gpt-6-luna` |
| 接口 | OpenAI Responses API |
| 推理参数 | `reasoning.effort=none` |
| 输出 | 严格 JSON Schema；最多 768 输出 token |
| 输入 | 公告正文与公开业务上下文 |
| 数据 | 冻结开发集前 20 条；每条调用一次 |
| 规则与参考标签 | 不发送给模型 |
| 模型版本 | 固定模型名和配置，未锁定带日期的后端快照 |

## 结果

| 指标 | 结果 |
|---|---:|
| 完成请求 | 20/20 |
| API/传输错误 | 0 |
| 整条公告抽取正确 | 20/20 |
| JSON 与 Schema 有效 | 20/20 |
| 编译后的提前期排程一致 | 20/20 |
| 输入 token | 9,892 |
| 输出 token | 566 |
| 按记录单价估算费用 | USD 0.00127220 |

费用按输入 USD 0.10/百万 token、输出 USD 0.50/百万 token 计算，未计缓存折扣，以平台账单为准。

这组结果用于验证开发集上的 API 调用和抽取流程。覆盖 18 类语义中的 14 类，含 12 条可处理公告和 8 条需澄清公告。400 条合成留出文本的 LLM 评测尚未运行，因此不能与留出集规则的 51.0% 直接比较。真实公告也尚未完成标注评测。

## 复算

```bash
semiconductor-logistics score-api --run benchmark_results/api_smoke
```

该命令校验数据、提示词、Schema、程序哈希和请求记录，从保存的响应重算指标，不调用 API。

| 文件 | 内容 |
|---|---|
| [manifest.json](../../benchmark_results/api_smoke/manifest.json) | 输入、模型、提示词和程序身份 |
| [records.jsonl](../../benchmark_results/api_smoke/records.jsonl) | 请求预留与逐条原始响应 |
| [evaluation.json](../../benchmark_results/api_smoke/evaluation.json) | 复算指标 |
| [provenance.json](../../benchmark_results/api_smoke/provenance.json) | GitHub 运行来源与文件校验值 |

来源：[成功的手动运行](https://github.com/nomoretry/semiconductor-logistics-decarbonization/actions/runs/40959872843)。后续修改 API 程序时，应保留原源码身份或使用产生该次结果的提交复算。
