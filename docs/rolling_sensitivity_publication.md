# 敏感性实验归档与验收 / Sensitivity archive and verification

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

敏感性研究的公开证据包覆盖24条不同合成开发需求路径、2,304条轨迹、27,648期，位于`benchmark_results/rolling_sensitivity_development/`。15份数据文件及manifest齐全，包括8份轨迹分片、结果表、计时和配置。完整列表与摘要见[manifest](../benchmark_results/rolling_sensitivity_development/manifest.json)，研究结论见[双语报告](rolling_sensitivity_results.md)。

最后补入归档的3份文件如下，均按原SHA256保存；算法、参数、实验结果和验收条件没有改变：

| File | Bytes | SHA256 |
|---|---:|---|
| `traces-06.jsonl.gz` | 221414 | `21225777b44a449ba004ed9965d76e9ffff6af97b07a9a6c66cb4c50695b1952` |
| `traces-07.jsonl.gz` | 220806 | `e7e8aca620a12e40cf2ebe3a2bc0ada3ead228f70d1881bc4b1e36c98ab43376` |
| `timing.jsonl.gz` | 263584 | `fe7698ad698fff44a7b8e4c4118e6b39e707006b36357d3a40db122181165d63` |

上述文件共705,804字节，内容为合成情境标识、固定方法名和数值，不包含API响应、密钥、私人订单或企业记录。[内容审计](../data_sources/rolling_sensitivity_artifact_audit.json)和[无损打包记录](../data_sources/rolling_sensitivity_packaging.json)保留检查依据。归档时，322项测试、wheel/CLI检查以及全部2,304条轨迹重执行均通过；完整性检查、物理账本核验、源代码身份检查及全部策略重执行仍在验证命令里。

```bash
python -m scripts.check_research_progress
make verify-sensitivity
```

第一个命令只核对保存的实验计数、文件和源码身份；第二个命令重生成需求、重执行全部策略并核对逐期证据。二者均不调用模型API。

## English

The public sensitivity bundle covers 24 distinct synthetic development demand paths, 2,304 trajectories and 27,648 periods in `benchmark_results/rolling_sensitivity_development/`. All 15 data files and the manifest are present, including eight trace shards, outcomes, timings and configuration. See the [manifest](../benchmark_results/rolling_sensitivity_development/manifest.json) for file identities and the [bilingual report](rolling_sensitivity_results.md) for findings.

The three files listed above were the last added to the archive, with their original SHA256 digests. No algorithm, setting, numerical result or acceptance requirement was changed. The files total 705,804 bytes and contain synthetic identifiers, fixed method names and numbers, with no API responses, credentials, private orders or corporate records. The [content audit](../data_sources/rolling_sensitivity_artifact_audit.json) and [lossless packaging record](../data_sources/rolling_sensitivity_packaging.json) retain the inspection evidence. At archive time, 322 tests, wheel/CLI checks and reexecution of all 2,304 trajectories passed; complete-coverage checks, physical audits, source identities and full policy replay remain in the verification commands.

```bash
python -m scripts.check_research_progress
make verify-sensitivity
```

The first command inventories saved experiment counts and checks files/source identities; the second regenerates demand, reexecutes all policies and compares period evidence. Neither uses model APIs.
