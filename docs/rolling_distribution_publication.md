# 分布证据归档记录 / Distribution evidence archive

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

分布研究的完整证据包在[分布确认归档](../benchmark_results/rolling_distribution_confirmation)，共35份文件、3,887,809字节，其中27份gzip、8份JSON/JSONL。文件清单与SHA256固定在提交`7ffc1910640c2deeef938f18973517e7f5022005`的[清单文件](https://github.com/nomoretry/semiconductor-logistics-decarbonization/blob/7ffc1910640c2deeef938f18973517e7f5022005/data_sources/rolling_distribution_artifact_audit.json)中；归档时逐一核对了长度、SHA256和Git blob身份。归档保留原始字节、模型配置、实验数值和未通过的教师筛选结论。

[逐值检查](../data_sources/rolling_distribution_content_check.json)覆盖27份压缩文件、4,160条顶层记录、5,452,544个有限数值；字符串只有合成任务ID、公开方法/过程标签或SHA256。归档不含公司订单或API响应。

复算命令：`make verify-distribution`。它重建拟合、选参与确认数据，重执行512条轨迹和768次相关性不变性审计；缺少任何文件都会报归档完整性错误。文件齐全不等于复算通过。

## English

The complete distribution-study bundle is the [distribution confirmation archive](../benchmark_results/rolling_distribution_confirmation): 35 files totaling 3,887,809 bytes, 27 gzip and eight JSON/JSONL files. The file list and SHA256 digests are fixed in the [manifest](https://github.com/nomoretry/semiconductor-logistics-decarbonization/blob/7ffc1910640c2deeef938f18973517e7f5022005/data_sources/rolling_distribution_artifact_audit.json) at commit `7ffc1910640c2deeef938f18973517e7f5022005`; each length, SHA256 and Git blob identity was checked when the files were archived. The archive keeps the original bytes, model configuration, numerical results and the failed teacher-screen conclusion.

The [value audit](../data_sources/rolling_distribution_content_check.json) covers 27 compressed files, 4,160 top-level records and 5,452,544 finite numbers. Strings are synthetic task IDs, public method/profile labels or SHA256 hashes. No company orders or API responses are included.

Run `make verify-distribution`. It regenerates fitting, selection and confirmation data, reexecutes 512 trajectories and repeats 768 dependence-invariance audits; a missing file is reported as an archive-integrity error. File coverage alone is not a replay.
