# API 配置

项目通过 OpenAI Responses API 抽取物流公告。模型、提示词、Schema 和调用预算写入运行清单；结果按实际响应复算。

## GitHub Actions

1. 打开仓库的 [Actions Secrets](https://github.com/nomoretry/semiconductor-logistics-decarbonization/settings/secrets/actions)。
2. 在 **Secrets → New repository secret** 中添加 `OPENAI_API_KEY`，值为项目 API 密钥。
3. 打开 [Actions](https://github.com/nomoretry/semiconductor-logistics-decarbonization/actions)，选择 **Notice API evaluation (manual)**。
4. 点击 **Run workflow**，选择 `main` 和评测配置。

| 配置 | 数据 | 最大请求数 | 程序预算 |
|---|---|---:|---:|
| `smoke20` | 开发集前 20 条 | 20 | USD 0.05 |
| `test400` | 冻结合成留出集 | 400 | USD 0.50 |

预算根据记录单价和请求上界预留，不是账户级消费硬限制。API 使用单独计费；仓库提交、离线测试和费用估算不发起模型请求。

工作流仅支持手动触发，并检出触发时的提交。代码更新后应新建 **Run workflow**；旧运行的 **Re-run jobs** 仍检出旧提交。密钥只注入调用步骤，结果文件保存在该次运行的 Artifact。

## 本地命令

在运行环境中配置 `OPENAI_API_KEY` 后，先估算：

```bash
semiconductor-logistics api --dataset benchmarks/notices_v1/dataset.json --split development --max-calls 20 --output artifacts/notice_api
```

执行同一配置时，显式提供执行参数和预算：

```bash
semiconductor-logistics api --dataset benchmarks/notices_v1/dataset.json --split development --max-calls 20 --output artifacts/notice_api --execute --max-usd 0.05
semiconductor-logistics score-api --run artifacts/notice_api
```

相同目录的已记录请求不会自动重复发送。程序不自动重试、不切换模型，首次错误后停止并保存已完成结果。新建目录或新建工作流运行会产生新的请求。

## 结果检查

`manifest.json` 保存模型、输入、提示词、Schema 和程序身份；`records.jsonl` 保存请求预留、响应、解析输出和用量；`evaluation.json` 保存复算指标。

先检查完成数、错误数和未调用数，再读取正确率。开发集连接测试和留出集评测分别呈现。[已保存的连接测试](results/api_smoke.md)可以离线复算，无需密钥。

官方说明：[API 认证](https://developers.openai.com/api/reference/overview)、[GitHub Secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)、[手动工作流](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)。
