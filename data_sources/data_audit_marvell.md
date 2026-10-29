# Marvell子项目：公开数据审查与使用边界

检索日期：2026-10-30。范围为Marvell、三个相似半导体企业、电子元器件分销商，以及常见公开制造／供应链数据集。

**结论：在本次检查到的官方披露及公开基准中，未发现同时包含适用的逐SKU需求、库存动态、真实货运路径和运费的完整Marvell运营数据。**这不是“世界上不存在相关数据”的判断。本研究可以先用明确标记的合成数据检验模型与算法，再在获得授权数据后替换参数。

## 1. Marvell公开事实与模型边界

| 官方材料 | 本次核实的信息 | 本项目能据此做什么 |
| --- | --- | --- |
| [Responsible Supply Chain](https://www.marvell.com/company/sustainability/responsible-supply-chain.html) | Marvell为fabless企业；直接制造供应商，例如晶圆厂及外包封装测试供应商，占其上游GHG排放超过98% | 将研究范围明确限定为物流环节，不能把本模型的运输减排解释为全公司减排 |
| [FY2026 Form10-K，2026-03-11提交](https://investor.marvell.com/sec-filings/all-sec-filings/content/0001835632-26-000011/mrvl-20260131.htm) | 多数第三方晶圆制造位于台湾，另有其他地区来源；OSAT设施主要分布在中国、马来西亚、新加坡、台湾和加拿大 | 支持“外包制造／封测与跨地区供货”的业务背景；不确定任一具体厂址、客户或运输线路 |
| 同一10-K的供应链与库存段落 | 公司可在预期客户交付前最长26周下达firm orders，并可能作出最长52周供给承诺；提到缓冲库存、需求预测和多SKU风险 | 说明长期供给安排与短期物流决策应区分；这些数字**不是海运或空运提前期**，也不是每一SKU的固定采购提前期 |

第一版把制造产出／可发货释放量作为外生输入，优化发运模式、补货、库存与积压。制造排放与制造生产计划不在优化范围内；本次也不考虑货损。若采用台湾、马来西亚、新加坡等地理节点，需注明为受公开业务结构启发的假设节点，而非已确认的Marvell物流网络。

## 2. 相似公司和分销商的有界检索

以下记录核查了与本任务相关的公开材料，并未对各公司所有网页或内部系统进行穷尽搜索。

| 检索对象与原始来源 | 本次看到的数据 | 对实验的用途及限制 |
| --- | --- | --- |
| [NXP 2025全年业绩，2026-02-02发布](https://investors.nxp.com/news-releases/news-release-details/nxp-semiconductors-reports-fourth-quarter-and-full-year-2025) | 财务库存、DIO与渠道库存周数；2025年末DIO为154天、渠道库存为10周 | 可作行业库存背景；不能直接据此恢复逐SKU需求、仓库流水或路径运价 |
| [Texas Instruments2025年报](https://investor.ti.com/static-files/fc9d9346-cf77-40db-902a-e9961e9c5736) | 年末库存48.0亿美元，DIO为222天 | 汇总财务指标，不等于订单级需求和物流提前期分布 |
| [Infineon2025年报](https://www.infineon.com/row/public/documents/corporate/investors/annual-reports/2025/2025-annual-report-v01-00-en.pdf) | 原料、在制品和成品库存金额，以及公司／分部库存汇总 | 能说明库存层次；所查表格未提供本实验需要的逐SKU库存轨迹、发运模式和运费 |
| [DigiKey官方API说明](https://developer.digikey.com/faq/products-plans-and-apis)、[ProductDetails](https://developer.digikey.com/products/product-information-v4/productsearch/productdetails) | 目录价格与当前可用量；关键词搜索数据可能缓存，ProductDetails面向实时产品信息 | 可在获得API权限后取得产品属性／报价快照，但目录可用量不是历史客户需求，也不能恢复企业物流成本 |
| [Mouser API Hub](https://www.mouser.com/en/api-hub/)、[Order History API](https://www.mouser.de/en/api-orderhistory/) | 搜索索引中的官方说明区分产品价格／可用量与账户自身订单历史；Order History需要账户API凭据 | 不是可直接下载的全体客户订单集。本次直接读取页面返回403，因此本项依据官方页面的检索结果，不声称已读取完整接口文档 |

没有把NXP Semiconductors与`nxp.nz`办公用品分销商混用。财务库存天数、销售价格、采购成本、货运价格和物理运输时间分别属于不同变量，不应直接互相替代。

## 3. 公开基准数据集筛选

| 数据集与原始来源 | 数据内容／已确认开放情况 | 是否能直接校准本实验 |
| --- | --- | --- |
| [UCI SECOM](https://archive.ics.uci.edu/dataset/179/secom) | 1,567条半导体制造过程记录，含传感器／测量特征及良率标签；CC BY4.0 | 不能。适用于制造异常和良率研究，没有适用的SKU需求与货运账本 |
| [A Benchmark Time Series Dataset for Semiconductor Fabrication Manufacturing，2024](https://arxiv.org/abs/2408.09307) | 基于Intel半导体工厂基准模型和DEVS-Suite的仿真时间序列 | 可在后续扩展为供货释放波动来源；它不是实际企业商业订单或运费数据。本次未确认原始数据再分发许可证，不将其标为无条件开放许可 |
| [FernUniHagen p2SchedGen模型目录](https://p2schedgen.fernuni-hagen.de/downloads/simulation)、[SMT2020论文](https://doi.org/10.1109/TSM.2020.3001933) | 公开列出MIMAC、Supply chain models及SMT2020等仿真模型 | 可用作制造／供给过程基准；公开下载不自动等于可任意再分发，也不等于真实公司SKU物流数据 |
| [Putting a price tag on hot lots and expediting in semiconductor manufacturing，2022](https://data.mendeley.com/datasets/zvm9b7mgvv/1) | 半导体制造加急／hot-lot情景的仿真结果；CC BY4.0 | 研究主题相关，但不是海空运、区域仓及客户订单的原始运营数据 |
| [Simulated Analog Wafer Test Data，2019](https://zenodo.org/records/2542504) | 模拟晶圆电测试数据，侧重空间图案识别 | 不适用于库存与运输校准；不能仅因带有“半导体”标签就用于本任务 |
| [UCI Online Retail](https://archive.ics.uci.edu/dataset/352/online+retail) | 541,909条英国礼品零售交易，包括商品代码、数量、日期、售价和国家；CC BY4.0 | 可作为非半导体需求形态压力测试。缺少本项目所需的库存流水、实际运费和碳排参数，不能标成Marvell真实需求 |
| [DataCo V5，2019](https://data.mendeley.com/datasets/8gx2fvg2k6/5) | 衣物、体育用品与电子用品等供应链交易，另有clickstream；CC BY4.0 | 经字段与语义审核后可用于订单／延误模式压力测试，不是Marvell网络校准。字段如“shipping mode”也需先核实是否表示物理运输方式 |
| [M5官方竞赛数据](https://www.kaggle.com/c/m5-forecasting-accuracy/data)、[官方研究仓库](https://github.com/Mcompetitions/M5-methods) | Walmart逐商品日销量、日历与售价；Kaggle页面标示依竞赛规则使用 | 可作需求预测基准，但不是半导体数据，也没有完整库存与运费。销量是受实际销售过程影响的观测，不应无条件当作潜在需求；使用时核对竞赛条款 |

上述公开数据集本轮仅做适配审查，没有用于伪装或替换Marvell真实SKU记录。数值实验中的订单、库存起点、运价、能力与扰动强度均应在配置文件中列为合成假设；公共距离与排放因子则单独注明来源、单位和适用边界。

## 4. 当前实验的建议标注

> 本实验是基于Marvell公开fabless供应链背景的物流减碳仿真，不使用Marvell私有运营数据。公开资料用于支持业务结构与研究范围；合成数据用于检验库存—运输联合优化和扰动响应。结果不代表Marvell实际成本或减排成效。

后续获得实际数据时，优先替换逐SKU需求、已发运在途订单、各节点库存、可发货释放量、线路报价及运输时间分布；保留统一的单位、碳边界、服务约束和测试集，以便判断参数更新是否改变结论。
