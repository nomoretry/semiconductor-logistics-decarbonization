# 下一项：预测与同信息基线 / Next study: forecasts and same-information baselines

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

**状态：已按[固定协议](rolling_forecast_protocol.md)执行，见[352轨迹结果](rolling_forecast_results.md)。以下保留执行前的研究思路。** [敏感性实验](rolling_sensitivity_results.md)已显示，7至21条情景的成本收益跨采样种子不稳定，而下降过程仍有过量库存。因此下一项检查历史信息预测和需求分布设定，再判断是否有适合BC计算替代的教师。

执行前固定预测器及参数选择方式。比较历史EWMA、对变化响应更快的EWMA及季节调整后的短窗预测；如加入过度离散或共同冲击情景，须先写明如何仅从已观察历史估计，不能使用隐藏过程标签或未来需求。现有开发路径可以诊断错误，但不能重新称为未查看的测试集；新比较应另行登记需求种子，保持校准与评估分离。

比较时固定uniform碳分配、ρ=0、6期规划和7条情景，沿用3个采样种子及相同实际需求路径。保留base-stock、原EWMA情景MPC和预知需求下界。先检查预测误差及概率评分，再计算同一控制器下的实际成本、即时履约率、排放、库存和求解时间。预测误差变小并不自动等于库存决策变好，两类结果分别报告。

只有在新路径上得到稳定的同信息教师，并明确在线时限与可接受质量损失后，才启动滚动BC；PPO需进一步说明BC剩余的序列决策损失。预知需求下界不能充当可部署教师。本轮归档完整性问题不改变这些研究判断，也不以开启新训练掩盖证据缺失。

## English

**Status: executed under the [fixed protocol](rolling_forecast_protocol.md); see the [352-trajectory results](rolling_forecast_results.md). The original research rationale follows.** The [sensitivity study](rolling_sensitivity_results.md) shows that the cost benefit of 21 over seven scenarios changes sign across sampling seeds, while downward shifts retain overstocking. The next study should examine history-only forecasts and demand-distribution assumptions before selecting a teacher for BC computation substitution.

Fix predictors and parameter-selection rules before execution. Compare historical EWMA, a faster-response EWMA and a short-window seasonally adjusted forecast. Any overdispersion or common-shock model must specify estimation from observed history only; hidden process labels and future demand are prohibited. Existing development paths may diagnose errors but cannot be relabeled as unseen tests. Register new demand seeds separately and keep calibration and evaluation apart.

Hold uniform carbon allocation, ρ=0, a six-period planning horizon and seven scenarios fixed, retaining three sampling seeds and paired realized demand. Keep base-stock, the original EWMA scenario MPC and the clairvoyant bound. Check forecast errors and probabilistic scores, then measure realized cost, immediate fill, emissions, inventory and planning time under the same controller. Better forecast scores do not automatically imply better inventory decisions; report both.

Start rolling BC only after identifying a stable same-information teacher on new paths and specifying an online time limit and acceptable quality loss. PPO requires evidence of remaining sequential decision loss after BC. The clairvoyant bound is not a deployable teacher. Archive publication issues do not change these criteria, and new training must not substitute for missing evidence.
