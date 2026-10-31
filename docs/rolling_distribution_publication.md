# 分布证据归档记录 / Distribution evidence publication

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

用户已明确批准将固定清单中的35份分布研究证据，按所列SHA256公开上传到`nomoretry/semiconductor-logistics-decarbonization`。本轮补齐全部文件，保留原始字节、模型配置、实验数值和失败的教师筛选结论。

批准依据是提交`7ffc1910640c2deeef938f18973517e7f5022005`中的[固定清单](https://github.com/nomoretry/semiconductor-logistics-decarbonization/blob/7ffc1910640c2deeef938f18973517e7f5022005/data_sources/rolling_distribution_artifact_audit.json)。35份文件共3,887,809字节，含27份gzip及8份JSON/JSONL；逐一核对SHA256、长度及Git blob身份。12个先前已上传的文件对象按相同身份复用，其余23个补齐。完整目录：[分布确认归档](../benchmark_results/rolling_distribution_confirmation)。

[逐值检查](../data_sources/rolling_distribution_content_check.json)覆盖27份压缩文件、4,160条顶层记录、5,452,544个有限数值；字符串为合成任务ID、公开方法/过程标签或SHA256。归档不含公司订单或API响应。完整复算会重建拟合、选参、确认数据，重执行512轨迹和768次相关性不变性审计。

复算命令：`make verify-distribution`。合并必须以**当前提交的七项CI全部通过**为准，包含完整分布重执行；文件齐全不代替复算，旧提交通过不代替新提交通过。CI保留缺文件检查，错误说明更新为一般的归档完整性错误。

此前自动审核因新集合没有明确授权而拒绝上传，这一历史保留；本次针对35份文件的明确授权已解除该阻塞，不需要再次确认。维护者完成代码与结果审阅后按[操作说明](manual_steps.md)合并PR。

## English

The user explicitly authorized public upload of the 35 distribution evidence files, with their listed SHA256 digests, to `nomoretry/semiconductor-logistics-decarbonization`. This change completes the archive without changing bytes, model configuration, numerical results or the failed teacher-screen conclusion.

Authorization binds to the [fixed manifest](https://github.com/nomoretry/semiconductor-logistics-decarbonization/blob/7ffc1910640c2deeef938f18973517e7f5022005/data_sources/rolling_distribution_artifact_audit.json) at commit `7ffc1910640c2deeef938f18973517e7f5022005`. The set contains 35 files totaling 3,887,809 bytes: 27 gzip and eight JSON/JSONL files. Each length, SHA256 and Git blob identity is checked. Twelve existing objects are reused under identical identities; the remaining 23 are completed. The full directory is the [distribution confirmation archive](../benchmark_results/rolling_distribution_confirmation).

The [value audit](../data_sources/rolling_distribution_content_check.json) covers 27 compressed files, 4,160 top-level records and 5,452,544 finite numbers. Strings are synthetic task IDs, public method/profile labels or SHA256 hashes. No company orders or API responses are included. Complete replay regenerates fitting, selection and confirmation data, reexecutes 512 trajectories and repeats 768 dependence-invariance audits.

Run `make verify-distribution`. Merge requires **all seven CI jobs on the current commit**, including complete distribution reexecution. File coverage is not replay; previous-commit success is not current-commit success. The missing-file guard remains, with a general archive-integrity error message.

Earlier automatic review rejected upload because this new set lacked explicit authorization. That history is retained; approval of these exact 35 files now removes the blocker and needs no further confirmation. After reviewing code and results, the maintainer can merge using the [manual steps](manual_steps.md).
