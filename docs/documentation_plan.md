# 研究文档交付 / Research documentation delivery

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; the English version follows the Chinese text.

## 中文

最终交付时，详细研究说明提供完整的中文与英文内容。每份双语文档开头注明语言结构，中文正文在前，英文正文在后。两种语言共享同一组结果、限制、复现命令和证据链接；翻译不改变研究结论。

仓库首页维持英文 `README.md` 与单独的 `README.zh-CN.md`，保留双向链接。详细说明采用同一文件内的双语正文。新研究文档从本轮 PPO 协议与结果开始执行；历史文档在方法和结果定稿后补齐，最终发布前逐项验收。

| 文档范围 | 当前安排 | 最终验收 |
|---|---|---|
| PPO、多种子与冻结评测协议/结果 | 新增双语正文及复现说明 | 配置、指标和命令一致 |
| 优化模型、来源与假设 | 历史中文文档保留；定稿后补英文 | 符号、参数单位和公司启发范围一致 |
| 文本与真实材料评估 | 历史证据与中文说明保留 | 区分合成、助手参考、未人工复核和内部路线更新限制 |
| 查询环境、预算、BC 与最终消融 | 定稿后补双语研究说明 | 保留失败门槛和负结果 |
| 复现、证据复算与人工操作 | 随流程更新，最终双语验收 | 命令能运行，证据链接可访问 |
| 进度、研究日志、框架差距 | 开发中持续更新 | 区分已执行和未执行工作 |

冻结协议被旧证据包的源码哈希引用时，不直接改写其字节。为它新增中文在前、英文在后的双语说明，链接回原协议，并在索引注明对应关系；旧实验继续验证原始协议。

文档完成和项目完成分开验收：英文 README 不代表研究文档已经全部翻译，完整文档也不代表五种子实验或滚动决策已经完成。

## English

At final delivery, detailed research explanations will be available in both Chinese and English. Each bilingual document starts with a language notice, followed by Chinese and then English. Both versions must use the same results, limitations, reproduction commands and evidence links. Translation does not change the conclusions.

The repository keeps an English `README.md` and a separate `README.zh-CN.md` with reciprocal links. Detailed explanations use both languages in one file, starting with the current PPO protocol and results. Historical documentation will be translated after its methods and results are finalized and checked before final release.

| Scope | Current arrangement | Final check |
|---|---|---|
| PPO, multi-seed and frozen-evaluation protocols/results | Bilingual text and reproduction notes | Matching settings, metrics and commands |
| Optimization, sources and assumptions | Preserve historical Chinese documents; translate after finalization | Consistent notation, units and company-inspired scope |
| Text and real-source evaluations | Preserve historical evidence and explanations | Distinguish synthetic data, assistant references, absent human review and internal-route limitations |
| Query environments, budgets, BC and final ablations | Add bilingual explanations after finalization | Retain failed gates and negative results |
| Reproduction, evidence replay and manual steps | Update with the workflow; check both languages at delivery | Runnable commands and accessible evidence links |
| Progress, research log and framework gaps | Maintain throughout development | Distinguish executed work from remaining work |

When an archived evidence bundle hashes an original protocol as source identity, do not change those original bytes. Add a bilingual companion with Chinese first and English second, link it to the frozen original and document the correspondence in the index. The old experiment continues to verify against its original protocol.

Documentation completion and research completion are separate checks. An English README does not mean all research explanations have been translated; complete documentation does not mean five-seed experiments or rolling decisions have been executed.
