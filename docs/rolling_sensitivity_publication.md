# 敏感性实验归档状态 / Sensitivity archive publication

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

本轮实验已在本地完成：24条不同合成开发需求路径、2,304条轨迹、27,648期；322项测试、wheel/CLI检查及压缩归档的完整重执行通过。研究结果见[双语报告](rolling_sensitivity_results.md)。

当前草稿PR的公开证据包尚不完整，**不要合并**。自动审批拒绝向公开仓库`nomoretry/semiconductor-logistics-decarbonization`上传`traces-06.jsonl.gz`，理由是需要用户对该具体载荷和目的地作出明确批准。完整字段检查、物理审计以及用已经公开的代码和配置重新生成288条轨迹后的逐字节一致检查均已完成；自动审批仍未放行。traces-05已在继续同步时获准提交，剩余三份文件仍待逐项明确批准。

待批准上传的文件均位于`benchmark_results/rolling_sensitivity_development/`：

| File | Bytes | SHA256 |
|---|---:|---|
| `traces-06.jsonl.gz` | 221414 | `21225777b44a449ba004ed9965d76e9ffff6af97b07a9a6c66cb4c50695b1952` |
| `traces-07.jsonl.gz` | 220806 | `e7e8aca620a12e40cf2ebe3a2bc0ada3ead228f70d1881bc4b1e36c98ab43376` |
| `timing.jsonl.gz` | 263584 | `fe7698ad698fff44a7b8e4c4118e6b39e707006b36357d3a40db122181165d63` |

总计705,804字节。内容仅包含合成情境标识、固定方法名和数值，不包含API响应、密钥、私人订单或企业记录。完整检查见[归档审计](../data_sources/rolling_sensitivity_artifact_audit.json)。原始结果和计时的压缩前后摘要见[打包记录](../data_sources/rolling_sensitivity_packaging.json)。

公开分支仍保留要求全部文件的验证器；缺少这些文件时，敏感性CI会报告证据不完整，不会跳过或假装通过。取得批准后才能补齐三份文件，重新检查CI并转为可审阅PR。其他旧实验的源码和归档保持原字节。

## English

The local study is complete: 24 distinct synthetic development demand paths, 2,304 trajectories and 27,648 periods. All 322 tests, wheel/CLI checks and full reexecution of the compressed bundle pass. See the [bilingual results](rolling_sensitivity_results.md).

The public bundle in this draft PR is incomplete; **do not merge**. Automatic approval review rejected publication of `traces-06.jsonl.gz` to the public repository `nomoretry/semiconductor-logistics-decarbonization`, requiring explicit user approval of the exact payload and destination. Full field inspection, physical audits and byte-identical reconstruction of all 288 trajectories from already-public code/configuration were completed, but review still rejected publication. traces-05 has now been approved and submitted; three files still require explicit approval.

The three files listed above belong under `benchmark_results/rolling_sensitivity_development/` and total 705,804 bytes. They contain only synthetic identifiers, fixed method names and numerical records, with no API responses, credentials, private orders or corporate records. The [content audit](../data_sources/rolling_sensitivity_artifact_audit.json) documents inspection, and the [packaging record](../data_sources/rolling_sensitivity_packaging.json) records original and compressed digests.

The public branch retains complete-coverage verification. Until the three files are supplied, sensitivity CI must report missing evidence rather than skip checks or claim success. After approval, upload the exact files, check CI and mark the PR ready. All historical experiment source and archives retain their original bytes.

可明确回复：我批准将 `traces-06.jsonl.gz`、`traces-07.jsonl.gz` 和 `timing.jsonl.gz`（内容与上表SHA256一致）公开上传到 `nomoretry/semiconductor-logistics-decarbonization`。

Explicit approval may state: I approve public upload of `traces-06.jsonl.gz`, `traces-07.jsonl.gz` and `timing.jsonl.gz`, matching the SHA256 digests above, to `nomoretry/semiconductor-logistics-decarbonization`.
