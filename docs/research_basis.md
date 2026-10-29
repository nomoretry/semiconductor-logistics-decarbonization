# 文献与公开资料如何进入模型

本轮通过 Undermind 检索备件干预与预算查询文献，并核对公司原始披露。文献用于选择问题和基线，公开材料用于限定事实语义；当前仿真参数没有被企业数据校准。

## 文献依据

| 文献 | 阅读范围 | 对本项目的作用 | 未据此声称的内容 |
|---|---|---|---|
| Howard 等，*Inventory Control in a Spare Parts Distribution System with Emergency Stocks and Pipeline Information*，[DOI](https://doi.org/10.1287/msom.2014.0508) | 摘要和元数据，未取得全文 | 在途信息影响等待与加急决策；加入无查询和信息感知基线 | 未复现其两级库存算法或数值结果 |
| Topan、van der Heijden，*Operational level planning of a multi-item two-echelon spare parts inventory system with reactive and proactive interventions*，[DOI](https://doi.org/10.1016/j.ejor.2019.12.022)，[作者机构页面](https://research.utwente.nl/en/publications/operational-level-planning-of-a-multi-item-two-echelon-spare-part/) | 摘要、出版信息；机构全文下载受限 | 多品类联合干预，比较等待、加急与跨仓方案；当前只实现运输分配部分 | 未使用文中的企业原始数据，也未实现完整跨仓系统 |
| Azimi、Fern、Fern，*Budgeted Optimization with Constrained Experiments*，[DOI](https://doi.org/10.1613/jair.4896) | Undermind 全文定向阅读：§3、§5、§6，印刷页123–124、129–134、134–145 | 查询价格、总预算、观测后更新查询选择；对比一步与多步规划 | 原文目标是寻找最好的已观测函数值，并非物流损失；它没有证明本项目存在查询互补，也不能证明 PPO 有收益 |

Azimi 等的非序贯批量目标具有次模性质；不能把该结果写成“查询必然互补”。本仓库直接测量查询的物流收益，并用精确有限状态规划核验。文献检索得到的近期 BED 预印本只作为候选，不作为当前实现或性能证据。

## 公司披露

| 来源 | 可支持的事实 | 对模型的影响 |
|---|---|---|
| [ASML 2024 年报，208–209页](https://www.sec.gov/Archives/edgar/data/937966/000093796625000011/a2024annualreportbasedon.htm) | 公司讨论航空转海运的潜在成本与排放收益，以及时效、货损和周转器具投入 | 保留运输方式、服务和排放的取舍；不从公司总体比例反推单SKU运费、容量或延误概率 |
| [Maersk 客户更新，PDF第2–3页](https://www.maersk.com/~/media_sc9/maersk/news/news/files/2024/maersk-asia-pacific-customer-update-15-april-issue.pdf?h=576&hash=7AF808C675485A5D042FC0B0E4C586DF&w=1024) | 绕航同时影响航程、运输时间、周转容量，并提供航空和海空联运替代 | 支持共享容量与备选路线的研究问题；行业层面的容量估计不当作客户可用舱位 |
| [Maersk MECL 结构调整](https://www.maersk.com/news/articles/2026/07/09/structural-changes-to-mecl) | 公告区分东西行，并报告平均运输时间改善；全文另列首航航次 | 抽取保留方向、平均值和减少量；不能将平均减少量变成每票货物的确定延误增量 |

来源记录见[research_sources.json](../data_sources/research_sources.json)。仅保存短摘录已有文件、事实摘要、定位和链接，不复制整篇论文或企业报告。

## 当前需要哪些数据

| 数据 | 当前采用 | 获得实测数据后才能做什么 |
|---|---|---|
| 承诺订单、SKU重量、交期、路线适配 | 显式合成参数 | 校准真实业务负载与服务损失 |
| 每条路线每期可用容量、合同价格、运输排放 | 合成参数；公开披露只提供方向依据 | 评价真实约束下的成本和减排收益 |
| 公告服务名到内部路线/订舱的映射、生效日期 | 当前没有 | 将来源事实转成内部计划更新 |
| 查询费用、时延、信息源准确率与相关性 | 公开给策略的仿真假设 | 校准查询价值，避免凭空设定信息优势 |
| 真实文本字段标注 | 已有助手参考，人工复核待完成 | 建立更可信的独立字段评测 |

以上缺失项不阻止合成环境研究。公开论文和公告不能代替企业未披露的订单、配额和合同；所有假设都保留在任务JSON中，后续按参数替换，不伪装成公司数据。
