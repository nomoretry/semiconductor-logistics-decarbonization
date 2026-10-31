# 分布证据归档状态 / Distribution evidence publication

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

本地研究和复算已完成；公开证据包尚未完整发布，当前PR保持草稿，不应合并。自动上传审批拒绝压缩证据，理由是此前明确授权涵盖上一轮文件，不涵盖本轮新集合。

本轮共有35份文件、3,887,809字节，包括27份gzip和8份JSON/JSONL。[逐文件路径、长度、SHA256及Git blob身份](../data_sources/rolling_distribution_artifact_audit.json)是本轮批准和上传的固定清单。不得更换文件字节后沿用批准。[逐字段检查](../data_sources/rolling_distribution_content_check.json)验证全部27份压缩文件：4,160条顶层记录、5,452,544个有限数值；所有字符串仅是生成的合成任务ID、公开方法/过程标签或SHA256，没有自由文本、公司订单或API输出。完整512轨迹及768次审计也已重执行。

用户需要批准的范围：将该清单中的35份合成证据按清单SHA256公开上传到`nomoretry/semiconductor-logistics-decarbonization`。这不是再次批准上一轮73文件，不需要提供密钥、运行API或填写人工意见。

批准后，完成剩余文件上传，核对远端Git blob身份与完整树，运行本轮七项CI，更新本页归档状态，再将草稿PR转为可合并。批准前不绕过上传限制，不将缺证据的检查跳过后称为通过。代码、双语结果和清单可先审阅；它们不代表公开原始证据已经完整。

## English

Local research and replay are complete, but the public evidence bundle is incomplete. Keep the PR in draft and do not merge it. Automatic upload review rejected compressed evidence because the explicit prior authorization covered the previous set, not this new set.

This set contains 35 files totaling 3,887,809 bytes: 27 gzip files and eight JSON/JSONL files. The [per-file paths, sizes, SHA256 and Git blob identities](../data_sources/rolling_distribution_artifact_audit.json) define the exact approval/upload scope. Do not reuse approval for changed bytes. The [decompressed field audit](../data_sources/rolling_distribution_content_check.json) checks all 27 compressed files: 4,160 top-level records and 5,452,544 finite numeric values. Every string is a generated synthetic task ID, public method/profile label or SHA256. There is no free text, company order data or API response. All 512 trajectories and 768 dependence audits have also been reexecuted.

Required approval: publish these 35 synthetic evidence files, with their listed SHA256 digests, to `nomoretry/semiconductor-logistics-decarbonization`. This is a new set, not another approval for the previous 73 files. No key transfer, API run or human-review form is required.

After approval, finish uploading, verify remote blob identities and complete tree coverage, run all seven current-commit CI jobs, update publication status and mark the PR ready. Before approval, do not bypass the restriction or skip missing-evidence checks and claim success. Code, bilingual results and the manifest are reviewable now; they do not mean the raw public archive is complete.
