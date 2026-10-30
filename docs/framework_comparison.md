# 与 Agentic Tool RL 的框架对照

参考仓库固定在 [f535724](https://github.com/Iams4kura/agentic-tool-rl/tree/f5357240e66e969a50fe0be126a65c95f77d9e44)，阅读记录和文件身份见[来源清单](../data_sources/framework_reference.json)。本次检查架构、训练、公开输入、环境执行、复算和发布流程；没有重新运行对方的完整训练或验证其 Release。

## 参考项目的组织方式

数据生成器产出按任务分组的 train/dev/test 与专家动作；公开 `PolicyInput` 经特征编码、候选 mask 进入 Actor-Critic。工具注册器独立检查动作并提交状态，轨迹进入 BC/PPO 训练与评估。最后由 checkpoint、轨迹、配置和源码身份共同支撑复算，而不是只发布一张指标表。

| 层 | 参考实现与检查重点 | 本项目的对应实现与差距 |
|---|---|---|
| 任务与划分 | `envs/benchmark.py`、`benchmark_v14.py`；同一世界的反事实目标按组划分，区分开发与正式测试 | 已有场景生成和强规则审计；新增 BC 的 72/18/36 上下文划分。同一情境全部分支留在同一 split，尚无最终千题集 |
| 策略输入 | `policy_input.py` 去除实例身份、隐藏目标、标签；公开信息是唯一决策入口 | `query_policy/features.py` 拒绝额外字段，不接收教师值和真实未观察状态；37维公开特征，不调用求解器 |
| 候选评分 | `models/actor_critic.py` 逐候选评分，候选数可变；state value 独立输出 | 新增共享候选 MLP 与 masked softmax；当前是 NumPy BC，没有 value head 或 PyTorch PPO |
| 专家模仿 | `algorithms/bc.py` 同时支持单标签与多正例集合损失；mask外动作不能成为正例 | 精确 DP 对所有合法历史给出动作成本；同价最优动作都算正例，采用集合 NLL，有限差分检查梯度 |
| 动作执行 | `tools/registry.py` 验证后写入复制状态，拒绝动作不产生部分副作用 | 现有事务工具环境已检查提交；新查询策略受费用/次数 mask 约束，最终运输由整数规划保证可行。不是外部企业系统事务 |
| 强基线 | v1.3 的公开 ready-greedy 审计；v1.4 保存 R0–R6 捷径基线 | 已有信息价值、两步前瞻、精确 DP 和同求解预算比较；新增 BC 继续与强搜索同场评估 |
| PPO | `algorithms/ppo.py` clipped ratio/value、熵项与梯度裁剪；`gae.py` 不跨轨迹传播优势 | 尚未实现和训练。下一项需先定位 BC 的状态误差和轨迹误差，再与同一 BC 起点做配对比较 |
| 势函数奖励 | `rewards/potential.py`、`training.py`；估计器先训练后冻结，终态势为零 | 尚未加入。不能把精确教师价值直接当成策略可见特征，或把实际成本改称学习出来的进度奖励 |
| 训练证据 | 保存 updates、参数摘要、共享 BC 起点，变体身份绑定 checkpoint | 新增初始化、选中检查点、80轮日志、参数变化和验证集选模记录；验证器重新训练并比对 |
| 逐题验证 | `evaluation/integrity.py`、`trace_store.py`；数据/配置/源码/checkpoint 四类身份，按模型重执行动作 | 旧结果已有重放；BC 新增教师重算、训练重执行、检查点逐情境重放。尚无中断续训；非空目录拒绝覆盖 |
| 统计消融 | v1.3 六变体、5种子、1000题，E−B同起点比较与配对区间；v1.4协议进一步收紧 | 本次只有1个训练种子、36个开发评估情境；不报告正式显著性，未完成五种子消融 |
| 分发与发布 | `uv.lock`、Ruff/mypy、隔离分发构建、多平台CI；v0.1.0带固定证据资产与校验入口 | Python包、固定数值依赖、离线CI与wheel检查已有；还缺完整依赖锁、静态检查、跨平台矩阵和经过验收的Release |

## 应当保留的经验

参考仓库的[追加审计](https://github.com/Iams4kura/agentic-tool-rl/blob/f5357240e66e969a50fe0be126a65c95f77d9e44/docs/results/posthoc-v1.3-public-ready.md)记录：公开 ready-greedy 在旧1000题达到1000/1000，说明仅有神经网络提升不能证明模型发现了规划结构。它保留旧结果，并在 v1.4 改成目标条件化的反事实任务。我们的强规则门槛及失败记录继续保留；新实验专门测在线计算替代，不能改写旧实验为“已证明需要RL”。

它的可选 Qwen Adapter 也没有被当成已训练的 GPU PPO。对应地，本项目的固定 LLM 公告抽取与小型查询策略训练分别报告：BC 的结果不是 LLM 微调结果。

## 本轮与后续验收

本轮完成 BC 的生成→训练→评估→检查点重放，并保存失败或成功的全部方法结果，见[协议](query_policy_protocol.md)和[结果](query_policy_results.md)。只借鉴接口划分与研究方法，新的 NumPy 实现没有复制对方源文件。

后续依次补：BC误差诊断和训练规模曲线；同起点 PPO 与奖励消融；冻结约1000个不同测试任务、5个训练种子、配对统计及完整证据包；分发锁与Release；最后加入未知需求和滚动决策。每一步以代码、实际运行和复算为准，不用仓库数量、徽章或README长度表示完成度。

## GitHub 页面差异

仓库列表里的头像、姓名、学校和地区来自个人资料；`Edit profile`是自己的编辑入口，访问别人的主页显示`Follow`。蓝色胶囊来自仓库Topics，许可证来自LICENSE文件。截图中的本项目已经被识别为Python。朋友列表中的部分条目标有`Forked from`，仓库数量包含这些派生仓库。

可在个人主页`Edit profile`修改自己的介绍；仓库首页`About`右侧齿轮可填写Topics，例如`python`、`logistics`、`optimization`、`mixed-integer-programming`。这些元数据不改变算法或测试结果。许可证涉及授权范围，本轮未擅自添加MIT，也未修改个人资料。
