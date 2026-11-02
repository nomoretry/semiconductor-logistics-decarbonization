# 来源与归属 / Provenance and attribution

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

### 早期查询策略协议

早期的查询策略 BC 协议（[`query_policy_protocol.md`](query_policy_protocol.md)）参考了另一个研究代码库 [agentic-tool-rl](https://github.com/Iams4kura/agentic-tool-rl)（阅读的是提交 `f5357240e66e969a50fe0be126a65c95f77d9e44`）的动态候选打分、公开输入和重执行设计。该协议及其后的冻结协议由实验证据的源码哈希绑定，原文保留；协议里指向的 [`framework_comparison.md`](framework_comparison.md) 作为旧链接保留。当时的逐项对照文档和阅读清单保存在 Git 历史中：[对照文档](https://github.com/nomoretry/semiconductor-logistics-decarbonization/blob/28ef2e92a553beaa6e74673dd7a06196dd568189/docs/framework_comparison.md)、[阅读清单](https://github.com/nomoretry/semiconductor-logistics-decarbonization/blob/fe8d27cf1609231de5d9715fbe5cdee9d60b6d70/docs/history/repository_reading.json)。

现行[研究设计](research_design.md)从物流问题、信息价值、预测误差与资源约束出发选择方法和验收条件，不以其他仓库的模块表作为实现蓝本。

### 代码来源检查

[有限代码检查](../data_sources/code_origin_check.json)比较了本项目提交 `28ef2e9` 的132个Python文件和上述参考提交中的97个Python文件：没有整文件Git字节身份匹配，也没有导入对方的Python包。此后又做了一次逐函数比较（规范化记号），只有 `scripts/download_source_data.py` 中的 `sha256_file` 与参考项目的 `_file_sha256` 结构相同（常见的分块哈希写法），[第三方声明](../THIRD_PARTY_NOTICES.md)附上了该项目的MIT许可声明。这些检查不判断语义相似或思想来源，不是完整的“无抄袭”证明。

### 方法、数据与模型输出

BC、PPO、GAE、BM25、混合整数规划、两阶段随机规划、ε-约束等是标准方法，出处写在各方法和协议文档中。第三方数据、船公司公告摘录和外部模型的输出列在[第三方声明](../THIRD_PARTY_NOTICES.md)，它们不适用本项目的MIT许可。项目自己的工作是具体的物流模型、信息边界、环境实现、决策对照和可复算分析；新颖性需要文献与实验支撑。

## English

### Early query-policy protocol

The early query-policy BC protocol ([`query_policy_protocol.md`](query_policy_protocol.md)) drew on the candidate scoring, public inputs and re-execution design of another research codebase, [agentic-tool-rl](https://github.com/Iams4kura/agentic-tool-rl) (commit `f5357240e66e969a50fe0be126a65c95f77d9e44` was read). That protocol and later frozen protocols are bound to experiment evidence by source hashes and keep their original text; the [`framework_comparison.md`](framework_comparison.md) link they contain is kept as a legacy entry. The item-by-item comparison and the reading inventory from that time are in the Git history: [comparison](https://github.com/nomoretry/semiconductor-logistics-decarbonization/blob/28ef2e92a553beaa6e74673dd7a06196dd568189/docs/framework_comparison.md), [reading inventory](https://github.com/nomoretry/semiconductor-logistics-decarbonization/blob/fe8d27cf1609231de5d9715fbe5cdee9d60b6d70/docs/history/repository_reading.json).

The current [research design](research_design.md) chooses methods and acceptance criteria from logistics questions, information value, forecast error and resource constraints; another repository's module list is not its blueprint.

### Code origin checks

A [limited code check](../data_sources/code_origin_check.json) compared 132 Python files at project commit `28ef2e9` with 97 Python files at the reference commit above: no whole-file Git identity matches and no imports of that package. A later function-level comparison on normalized tokens found one structurally identical helper, `sha256_file` in `scripts/download_source_data.py`, which matches `_file_sha256` in the reference project (the common chunked-hash idiom); the [third-party notices](../THIRD_PARTY_NOTICES.md) reproduce that project's MIT notice. These checks do not assess semantic similarity or intellectual influence and are not a comprehensive plagiarism clearance.

### Methods, data and model outputs

BC, PPO, GAE, BM25, mixed-integer programming, two-stage stochastic programming and the epsilon-constraint method are standard methods, cited in the method and protocol documents. Third-party data, carrier notice excerpts and outputs of external models are listed in the [third-party notices](../THIRD_PARTY_NOTICES.md) and are not covered by the project's MIT License. The project's own work is its logistics models, information boundaries, environments, decision comparisons and reproducible analyses; novelty requires literature and experimental support.
