# 来源与历史定位修正 / Sources and correction of earlier framing

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

用户要求匹配成熟研究项目的难度与完成度。此前维护过程中把这个要求写成了另一个仓库的“框架对照”，并在早期BC协议中引用其动态候选、公开输入和重执行设计。这个表述超出了用户希望的完成度比较，现予以纠正。

当前[研究设计](research_design.md)从物流问题、信息价值、预测误差与资源约束出发，不使用其他仓库的模块表作为实现蓝本或验收条件。README与研究指南不再展示逐项项目对应关系。旧对照内容保留在[原Git提交](https://github.com/nomoretry/semiconductor-logistics-decarbonization/blob/28ef2e92a553beaa6e74673dd7a06196dd568189/docs/framework_comparison.md)；[历史阅读清单](history/repository_reading.json)仅记录当时读过哪些文件。

不能据此声称早期从未受到参考实现影响。`docs/query_policy_protocol.md`及其他冻结协议由已有实验哈希绑定，保留原始字节；旧入口`framework_comparison.md`仅用于解释这段历史和指向当前设计。算法论文、真实数据来源和任何实际复用都应保留可核查归属。

本次[有限代码检查](../data_sources/code_origin_check.json)比较本项目提交`28ef2e9`的132个Python文件和当时阅读的固定提交中的97个Python文件：没有整文件Git字节身份匹配，没有导入对方Python包。`pyproject.toml`列出的运行依赖是NumPy、SciPy、Matplotlib与OpenPyXL。此检查不判断局部复制、语义相似或思想来源，不能作为全面“无抄袭”证明。我们不会用移除引用的方式把通用方法或历史借鉴改称原创算法。

项目自己的工作是具体的物流模型、信息边界、环境实现、决策对照和可复算分析。后续是否采用某种算法，取决于这些问题留下的实际缺口。新颖性需要通过文献与实验论证，不能由改名、换库或改变README获得。

## English

The user requested comparable research difficulty and completion. Earlier maintenance turned that into a repository-by-repository framework comparison, and the initial BC protocol referenced the reviewed project's candidate scoring, public inputs and replay design. This framing exceeded the intended comparison of completeness and is now corrected.

The current [research design](research_design.md) starts from logistics questions, information value, forecast error and resource constraints. Another repository's module list is neither its blueprint nor its acceptance checklist. The README and guide no longer present a one-to-one project mapping. The former comparison remains in the linked original Git commit; the [historical reading inventory](history/repository_reading.json) records what was inspected.

This does not assert that the early work had no conceptual influence. Existing evidence hashes bind `docs/query_policy_protocol.md` and other frozen protocols, so their original bytes remain. The legacy comparison URL explains this history and points to the current design. Algorithm papers, real data sources and any actual reuse must retain verifiable attribution.

The [limited code check](../data_sources/code_origin_check.json) compares 132 Python files at project commit `28ef2e9` with 97 files at the historically reviewed commit: no exact whole-file Git identity matches and no imports of that Python package were found. Declared runtime dependencies are NumPy, SciPy, Matplotlib and OpenPyXL. This does not assess partial copying, semantic similarity or intellectual influence and is not a comprehensive plagiarism clearance. Removing citations cannot turn standard methods or past influences into original algorithms.

The project's own work comprises its logistics models, information boundaries, environments, decision comparisons and reproducible analyses. Subsequent algorithms must address gaps in these problems. Novelty requires literature and experimental support; renaming, changing libraries or rewriting a README cannot establish it.
