# 真实公告检索 / Retrieval over real carrier notices

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

### 范围

在[公告到备忘录的决策流程](decision_workflow.md)里加入真实船公司公告的检索：

1. 计划员输入问题或扰动描述；
2. 系统从真实公告里找出最相关的段落，显示出处（船公司、标题、日期、链接）；
3. 从命中的段落和计划员自己的文字里解析参数，每个参数标出依据（“公告某条原文”或“计划员输入”）；公告里缺少、无法确定的信息（例如内部线路对应关系、确定的延误周数）明确列出，由计划员补上或确认；
4. 确认之后照常求解对比，备忘录附上参考公告。

**语料**（按用户决定，仓库只存链接和哈希）：

- 仓库里已有 24 条不重复的公告摘录：16 条与中断有关，分属 12 个事件；8 条是新航线的运输时间公告。它们已写进 `THIRD_PARTY_NOTICES.md`，作为离线语料，CI 和演示都用它。
- `data_sources/notice_corpus.json` 记录每个来源的链接、发布与访问日期、摘录哈希、所在数据集和已有标注摘要，不复制原文。
- `python -m planning_agent corpus fetch --yes` 把原文网页下载到本地 `data_sources/raw/notices/`（不进仓库），记录全文哈希；下载要用户明确同意，CI 和测试从不联网。

**检索方法**：纯 Python 的 BM25；英文按词切分，中文按相邻两字切分；用一份公开的中英物流术语对照表扩展中文查询，因为语料是英文的。不新增框架，也不调用模型。

**不包括**：向量检索、模型生成的答案、全文自动抽取确定参数（以往研究表明真实公告很少给出可直接执行的参数），以及独立出题人的评测。

### 评测

- 查询集 `benchmarks/notice_retrieval_v1/queries.json`：19 个事件分组（12 个中断事件、7 个航线分组）各写中文、英文问题一条，共 38 条；相关文档按数据集里已有的事件分组确定。独立情境数是 19，同一分组的中英文问题只是两种问法。
- **查询和术语表在看到任何检索结果之前一起提交**，由同一作者在读过语料之后编写，因此中文结果偏乐观；这是开发检查，不是独立评测（独立出题仍是 TASKS V2）。
- 指标：recall@1、recall@3、recall@5（前 k 条里找回了该分组多少比例的文档）、命中率@1/3/5（前 k 条里至少有一条相关）、MRR，按语言分别报告。
- 对照：同一查询不做术语扩展的 BM25，以及随机排序的精确期望值。
- 结果写入 `benchmark_results/notice_retrieval_v1/`，可用 `python -m planning_agent corpus evaluate` 重算。

### 验收条件

1. 语料清单由数据集重建后与仓库里的文件逐字一致，不包含公告原文。
2. 下载命令没有 `--yes` 就不联网；测试里用假的网络响应验证它的保存与哈希逻辑。
3. 评测按上述指标报告，结果可重算；查询集先于结果提交。
4. 在业务流程里，命中的公告显示出处和链接；每个参数标明依据；公告缺少的信息逐条列出；备忘录附参考公告。公告里的近似值和区间（例如“7 到 14 天”）只作参考显示，不自动变成确定参数。
5. 命令行和网页都能用；离线运行，不调用模型。

### 运行

```bash
python -m planning_agent corpus build          # 重建语料清单（不联网）
python -m planning_agent corpus search "红海绕行对亚欧航线的影响"
python -m planning_agent corpus evaluate        # 重算检索评测
python -m planning_agent flow --mode notice --notice "红海绕行好望角，第4到12周海运延误2周，对 ASML 备件有什么影响？"
python -m planning_agent corpus fetch --yes     # 下载原文到本地，需要你同意
```

## English

### Scope

Retrieval over real carrier notices is added to the [notice-to-memo workflow](decision_workflow.md):

1. the planner enters a question or disruption description;
2. the most relevant notice passages are shown with their source (carrier, title, date, link);
3. parameters are parsed from the matched passages and from the planner's own words, and each parameter states where it came from (a notice passage or the planner's input); information the notices do not give, such as the internal-route mapping or a definite delay in weeks, is listed for the planner to supply or confirm;
4. after confirmation the plans are solved and compared as before, and the memo lists the notices used.

**Corpus** (per the owner's decision, the repository stores links and hashes only):

- The repository already holds 24 distinct notice excerpts: 16 about disruptions across 12 events, and 8 transit-time announcements for new services. They are listed in `THIRD_PARTY_NOTICES.md` and serve as the offline corpus for CI and demos.
- `data_sources/notice_corpus.json` records each source's link, publication and access dates, excerpt hash, dataset location and existing annotation summary, without copying notice text.
- `python -m planning_agent corpus fetch --yes` downloads the original pages to the local `data_sources/raw/notices/` (not committed) and records full-text hashes. It needs explicit consent; CI and tests never go online.

**Method**: pure-Python BM25; English is split into words and Chinese into character bigrams; a public Chinese–English logistics glossary expands Chinese queries because the corpus is in English. No new framework and no model call.

**Out of scope**: vector search, model-generated answers, automatic extraction of definite parameters from full text (earlier studies found that real notices rarely state directly executable parameters), and evaluation by independent question writers.

### Evaluation

- Query set `benchmarks/notice_retrieval_v1/queries.json`: one Chinese and one English question for each of 19 event groups (12 disruption events and 7 service groups), 38 questions in total; relevance follows the event groups already in the datasets. There are 19 independent cases; the two questions of a group are two phrasings of one case.
- **The questions and the glossary are committed together before any retrieval result.** One author wrote them after reading the corpus, so the Chinese results are optimistic. This is a development check, not an independent evaluation (independent question writers remain TASKS V2).
- Metrics: recall@1, recall@3 and recall@5 (the share of the group's documents among the top k), hit rate@1/3/5 (at least one relevant document among the top k) and MRR, reported per language.
- Comparisons: the same BM25 without glossary expansion, and the exact expected value of a random ranking.
- Results go to `benchmark_results/notice_retrieval_v1/` and are recomputed by `python -m planning_agent corpus evaluate`.

### Acceptance

1. The corpus manifest rebuilt from the datasets matches the committed file byte for byte and contains no notice text.
2. The download command does not go online without `--yes`; tests check its saving and hashing logic with fake network responses.
3. The evaluation reports the metrics above, results can be recomputed, and the query set is committed before the results.
4. In the workflow, matched notices show their source and link, every parameter states its basis, missing information is listed, and the memo lists the notices used. Approximate values and ranges in notices (for example "7 to 14 days") are shown for reference and never become definite parameters automatically.
5. Both the command line and the web page work offline without a model call.

### How to run

```bash
python -m planning_agent corpus build
python -m planning_agent corpus search "Red Sea diversion impact on Asia-Europe services"
python -m planning_agent corpus evaluate
python -m planning_agent flow --mode notice --notice "Red Sea diversion via the Cape, weeks 4-12, ocean delayed by 2 weeks: impact on ASML spare parts?"
python -m planning_agent corpus fetch --yes
```
