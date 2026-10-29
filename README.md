# Semiconductor logistics decarbonization — two distinct subprojects

第一版可复现实验，2026-10-30。包含独立的[ASML子项目](asml/README.md)与[Marvell子项目](marvell/README.md)，共享库存守恒、运输模式及碳预算MILP实现。

**这是企业业务背景启发的仿真，不能当作企业实际经营结果或减排承诺。**第一版使用已知的承诺订单簿与已公告扰动，未运行需求预测或未知未来扰动的滚动控制。ASML不考虑货损；Marvell仅研究物流环节，制造、良率及产品隐含碳不在可优化边界内。

## 可复现命令

Python3.10+，无需训练神经网络、API密钥或商业优化器。

```bash
python -m pip install -r requirements.txt
python scripts/download_source_data.py
python -m unittest discover -s tests -v
python scripts/run_experiments.py --project asml
python scripts/run_experiments.py --project marvell
# 同时生成两个项目的完整主实验：
python scripts/run_experiments.py --project both
python scripts/evaluate_notice_pilot.py --project both
python scripts/run_sensitivity.py --project both
python scripts/create_reports.py
```

公开仓库以来源链接和SHA-256校验值提供两份第三方原始数据，不重新分发ZIP／XLSX。首次运行测试或完整实验前执行上述下载命令；脚本按`data_sources/source_manifest.json`下载至实验使用的原路径，校验内容后才原子替换，已有匹配文件保持不变。下载失败或校验不符会报错并保留已有文件。

单项目包将`--project both`替换为对应项目名；不传项目时自动检测可用配置。主结果写入`reports/`；单独重跑一个项目会覆盖该目录中主实验汇总，完整包可用`--project both`重新生成双方结果。

## 模型

- 每期决策：各SKU、各已合格路线的整数发货量。
- 状态：仓库现货、未满足订单及按派发期提前期计算的在途货物。
- 成本：运费＋在途资金占用＋到仓后资金与仓储持有成本。
- 排放：运输质量×距离×模式因子＋库存相关的仓储分配排放。
- 服务：每期期末积压为0，期末库存至少恢复至共同初始库存。周末无积压不等于24小时交付KPI。
- 容量：每条运输路线容量及同一供货池跨路线共享的释放容量。
- 碳预算：分别要求比同一实例成本最优参照低10%、25%、50%；不可行则明确报告，不自动松弛。

SKU名称、需求、价值、质量、运价、容量、时间粒度、仓储边际排放均为可修改的仿真假设。官方排放因子、路线几何和类比需求来源单独保存于`data_sources/`。航空因子已包含8%距离修正，代码不重复增加。

## 实验与LLM边界

主实验包含两个项目×3类已公告情景×10个订单种子×6类策略，另加10组真实汽车备件月度需求压力测试，共400次求解。真实月度数据保留月份，未冒充半导体周需求。另运行24次参数敏感性和40个数值实例的信息处理对照。

公开仓库的逐次结果、订单实例及逐期计划仅发布`demand_set=synthetic_weekly`的合成实验：360条求解记录、60份实例和339份可行计划。`summary.json`、运行清单及完整报告保留原400次实验的汇总，因此包含外部汽车备件压力测试的聚合统计；外部实测需求序列、选中序列ID和逐实例结果不在公开明细中。下载原始公开数据后执行`python scripts/run_experiments.py --project both`，可在本地重新生成含外部压力测试的完整明细。

LLM示例由会话中的独立助手根据`llm/extraction_prompt.txt`读取12条合成通知，未读取参考标签，输出保存在`llm/extracted_notices.json`。本代码重放保存的抽取结果，不调用外部API，也不把规则解析器输出标成LLM推理。该小样本示例不构成模型泛化、延迟或费用评测；后续应接入固定模型API并扩展留出文本集。

## 输出

- `reports/episodes.json/csv`：360次合成实验求解的成本、排放、服务、可行性和最优间隙。
- `reports/instances.json`：60份可重放的合成订单、参数与扰动实例，不包含外部实测需求或选中序列ID。
- `reports/plans.json`：339份合成实验可行计划的未压缩整数发货、库存及积压轨迹；从原压缩结果解压后，仅保留合成实验记录。重跑脚本仍输出`reports/plans.json.gz`，不会自动更新发布的`plans.json`。
- `reports/summary.json`、`reports/run_manifest.json`：原400次实验的归档聚合结果及运行来源，包含外部压力测试统计；与公开合成明细的范围不同。
- `reports/notice_pilot.json`：保存LLM输出的抽取校验及数值重放。
- `reports/sensitivity.json`：资金占用、仓储参数及航空RF边界敏感性。
- `reports/study_report.html`：可直接在浏览器阅读的原始完整实验报告，外部压力测试仅展示汇总。

详见[数据审计：ASML](data_sources/data_audit_asml.md)、[数据审计：Marvell](data_sources/data_audit_marvell.md)。有界检索未发现完整商业联合记录，不代表所有企业都不存在公开数据。

第三方数据分别适用其原许可证：Monash Car Parts为CC BY4.0；UK Government因子按原发布页的Open Government Licence归属声明；机场坐标为OurAirports公开数据。公开仓库保留来源链接和哈希，原ZIP／XLSX由下载脚本按需获取。未加入任何账户凭据。

第三方数据的署名、许可证链接及处理说明见[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
