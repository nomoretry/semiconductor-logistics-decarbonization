# 真实运输公告

语料包含16份官方运输材料的逐字短摘录，涉及12个操作事件组、9个相关事件组。两个助手分别打开来源页面，核对摘录、更新版本及参考判断；每条最多23个词。人工复核尚未完成。

## 评测范围

原任务要求把公告转成内部`NL_ocean`路线在16周发运窗口内的确定整数提前期增量。这些真实材料没有同时给出内部路线映射、模型发运窗口和确定增量，因此16条参考均为`needs_clarification`。

规则与始终澄清基线均得到16/16助手参考一致。它说明当前选择应请求澄清，没有建立真实更新抽取能力；没有更新正例的指标保持为空。该集合为探索性短摘录审核，不是随机样本、独立留出集或人工金标准。

摘录包含停航、改港、恢复、延误范围和平均改善等事实。宽口径标注仅使用模型可见摘录；全文中的航次表和其他版本事实单独保存在来源审核文件中，不作为摘录输入的隐藏答案。范围、平均数和减少量保留原语义，不转换成确定增加量。

## 文件

| 文件 | 内容 |
|---|---|
| [dataset.json](../../benchmarks/real_notices_v1/dataset.json) | 来源、原文、参考与分组 |
| [test.jsonl](../../benchmarks/real_notices_v1/test.jsonl) | 相同16条探索案例；文件名不表示独立留出 |
| [annotations.jsonl](../../benchmarks/real_notices_v1/annotations.jsonl) | 窄任务判断、缺失字段和宽口径事实 |
| [source_review.json](../../benchmarks/real_notices_v1/source_review.json) | 全文审核、版本说明及适用范围 |
| [second_assistant_review.json](../../benchmarks/real_notices_v1/second_assistant_review.json) | 第二助手的逐字与版本核对记录 |
| [manifest.json](../../benchmarks/real_notices_v1/manifest.json) | 文件校验值、数量和审核状态 |

原文、URL、来源日期和证据位置保存在数据文件。模型输入仅含逐字摘录和原任务的公开上下文，不包含标题、URL、分组、标签或解释。来源哈希用于检查文件一致性，不是外部真实性或独立标注的认证。

## 运行

```bash
semiconductor-logistics real-notices validate --dataset benchmarks/real_notices_v1/dataset.json
semiconductor-logistics real-notices offline --dataset benchmarks/real_notices_v1/dataset.json --output artifacts/real_notices
```

固定模型运行使用GitHub Actions的`Real notice audit (manual)`，选择`main`，复用仓库`OPENAI_API_KEY` Secret。16条输入的保守费用预留估算为USD0.01721410，程序预算为USD0.05；该预算不是账户级消费硬限制。

API输入导出与响应复算均有独立命令。工作流在结束后输出参考一致率、始终澄清基线、完成数和错误数；无完成输出时分数为空。目前尚未执行这一批真实摘录的模型调用。
