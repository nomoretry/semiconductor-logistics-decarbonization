# 真实相似业务需求：Monash Car Parts

本文件解释真实汽车备件需求与两家半导体企业仿真假设的区别。

- 发布记录：[Car Parts Dataset with Missing Values, Version 2](https://zenodo.org/records/4656022)。
- DOI：`10.5281/zenodo.4656022`。
- 作者：Rakshitha Godahewa、Christoph Bergmeir、Geoff Webb、Rob Hyndman、Pablo Montero-Manso。
- 原始来源：R `expsmooth` 包；发布者说明其为汽车备件销售月度序列。
- 许可：CC BY 4.0，已从Zenodo记录API确认；复用需署名并说明任何处理。
- 范围：2,674条序列，1998-01至2002-03，共51个月。
- 本次原始下载：`raw/car_parts_dataset_with_missing_values.zip`，39,656字节。
- 原始下载URL：<https://zenodo.org/api/records/4656022/files/car_parts_dataset_with_missing_values.zip/content>。
- 下载日期：2026-10-30。SHA256见`source_manifest.json`和`carparts_metadata.json`。

## 实际解析与筛选

ZIP中为TSF文本；`?`表示缺失。本次解析得到2,509条没有缺失的完整51个月序列。仅在这些完整序列上计算的总体均值为每SKU每月0.50731875，零需求比例约74.9076%。这些是数据描述，不能用作半导体公司的已知参数。

若需要选定一小组序列，可先按原始ID顺序选择满足预先定义条件的完整序列，并在训练时间段内估计需求参数，保留后续月份做测试。不能看测试收益再挑选SKU。公开仓库仅保留外部压力测试的聚合结果；原始需求、选中序列ID及逐实例结果可通过下载原数据并运行实验在本地重新生成。

相关[作者研究论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC8629246/)曾采用2,503条序列，因为还施加了前45个月至少一次需求等条件。该数量与本次“仅排除缺失”所得2,509条不同，不应混用。

## 缺失与时间单位

另一个[不含缺失版本](https://zenodo.org/records/4656021)将缺失值填为0。本项目保留带缺失原版，避免把未知观测直接解释成真实零需求。若研究需要插补，必须单独记录插补方法，并做敏感性比较。

原始单位为月。周度仿真只能使用训练段估计的间歇性／需求大小特征，再通过明确标为合成的生成过程产生周需求；不能将一个月观测直接改称一周。任何归一化、缩放、重新采样与人为扰动都应写入实验数据说明。

## 不包含的数据

该数据不是ASML、Marvell或其他半导体公司的需求数据，也没有完整的对应SKU价格、质量、体积、库存、供货提前期、空海运运价和碳排放。它可验证需求不确定性下方法的稳健性，不能用于声称优化了真实半导体企业运营。
