# 敏感性实验归档与验收 / Sensitivity archive and verification

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

[PR #15](https://github.com/nomoretry/semiconductor-logistics-decarbonization/pull/15)已补齐本轮公开证据包：24条不同合成开发需求路径、2,304条轨迹、27,648期。15份数据文件及manifest齐全，包括8份轨迹分片、结果表、计时和配置。完整列表与摘要见[manifest](../benchmark_results/rolling_sensitivity_development/manifest.json)，研究结论见[双语报告](rolling_sensitivity_results.md)。

先前的`artifact_coverage`错误来自未上传的文件。维护者明确批准后，以下3份文件按原SHA256补交；没有修改算法、参数、实验结果或放宽验收条件。文件均位于`benchmark_results/rolling_sensitivity_development/`：

| File | Bytes | SHA256 |
|---|---:|---|
| `traces-06.jsonl.gz` | 221414 | `21225777b44a449ba004ed9965d76e9ffff6af97b07a9a6c66cb4c50695b1952` |
| `traces-07.jsonl.gz` | 220806 | `e7e8aca620a12e40cf2ebe3a2bc0ada3ead228f70d1881bc4b1e36c98ab43376` |
| `timing.jsonl.gz` | 263584 | `fe7698ad698fff44a7b8e4c4118e6b39e707006b36357d3a40db122181165d63` |

上述文件共705,804字节，内容为合成情境标识、固定方法名和数值，不包含API响应、密钥、私人订单或企业记录。[内容审计](../data_sources/rolling_sensitivity_artifact_audit.json)和[无损打包记录](../data_sources/rolling_sensitivity_packaging.json)保留检查依据。

本地322项测试、wheel/CLI检查以及全部2,304条轨迹重执行已经通过。合并以PR当前提交的五项CI检查全部成功为准，不能沿用旧提交的通过状态。完整性检查、物理账本核验、源代码身份检查及全部策略重执行继续保留。

```bash
python -m scripts.check_research_progress
make verify-sensitivity
```

第一个命令只核对保存的实验计数、文件和源码身份；第二个命令重生成需求、重执行全部策略并核对逐期证据。二者均不调用模型API。通过当前提交的CI后，按[操作说明](manual_steps.md)合并即可，不再需要文件上传授权或人工审核表。

## English

[PR #15](https://github.com/nomoretry/semiconductor-logistics-decarbonization/pull/15) now includes the complete public bundle: 24 distinct synthetic development demand paths, 2,304 trajectories and 27,648 periods. All 15 data files and the manifest are present, including eight trace shards, outcomes, timings and configuration. See the [manifest](../benchmark_results/rolling_sensitivity_development/manifest.json) for file identities and the [bilingual report](rolling_sensitivity_results.md) for findings.

The earlier `artifact_coverage` failure was caused by missing uploads. After explicit maintainer approval, the three files listed above were added with their original SHA256 digests. No algorithm, setting, numerical result or acceptance requirement was changed. The files total 705,804 bytes and contain synthetic identifiers, fixed method names and numbers, with no API responses, credentials, private orders or corporate records. The [content audit](../data_sources/rolling_sensitivity_artifact_audit.json) and [lossless packaging record](../data_sources/rolling_sensitivity_packaging.json) retain the inspection evidence.

All 322 local tests, wheel/CLI checks and reexecution of all 2,304 trajectories have passed. Merge acceptance requires all five CI jobs on the current PR commit; success on an older commit is not a substitute. Complete-coverage checks, physical audits, source identities and full policy replay remain enabled.

```bash
python -m scripts.check_research_progress
make verify-sensitivity
```

The first command inventories saved experiment counts and checks files/source identities; the second regenerates demand, reexecutes all policies and compares period evidence. Neither uses model APIs. After current-head CI succeeds, follow the [merge instructions](manual_steps.md). No additional upload approval or human-review form is required.
