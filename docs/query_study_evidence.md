# 证据格式与复现 / Evidence format and reproduction

本文提供中英文版本，中文在前，英文在后。
This document is available in Chinese and English; English follows Chinese.

## 中文

研究协议见[多种子与冻结评测](query_study_protocol.md)。开发训练、冻结任务和最终结果分开保存，不能用新的训练输出替换冻结模型。

| 路径 | 内容 |
|---|---|
| `benchmark_results/query_study_development/` | 配置、训练/验证与开发检查任务、5套BC和15套PPO训练、开发统计 |
| `models/<seed>-bc.json` | BC初始/所选参数、完整epoch日志及配置 |
| `models/<seed>-<variant>.json` | PPO初始/所选/最后参数、共享BC身份、配置、更新与选模日志 |
| `episodes/<seed>-<variant>.jsonl` | 每行一个完整采样episode，原始浮点数无舍入 |
| `benchmarks/query_final_v1/` | 1,000题清单、固定模型索引与训练证据哈希；不包含首次评测前的模型输出 |
| `benchmark_results/query_final_v1/` | 最终逐题结果、动作树、精确参考、配对统计与冻结提交身份 |

训练episode每行是 `[iteration, task_id, repeat, steps]`。每个step是 `[action, answer, reward, old_logp, old_value]`：action=0表示提交，action=i+1表示查询路线i；提交answer为null。初始历史全部为-1，查询答案逐步更新历史；done由action=0确定。恢复GAE时读取该变体自己的gamma和lambda。验证器比较恢复后的完整记录与重新训练所得记录，不只比较文件哈希。

最终动作树的nodes按 `[history, reach_probability, action, milp_calls, commit_plan, terminal_loss]` 保存。这里沿用环境动作编号：action=-1表示提交，非负i表示查询路线i。查询节点的方案与终端成本为null。每棵树绑定公开情境哈希；相同树只存一次，逐题结果中的模型SHA与树SHA保持独立。原始训练编号与环境编号的差异由适配器明确转换。

精确参考用于评测遗憾，不进入PPO输入或训练奖励。确定性强搜索只有每题一条记录，seed为null。学习模型记录包含真实训练seed；同一情境跨seed重复不增加不同任务数。

从头复现使用新的空目录：

```bash
python -m semiconductor_logistics query-study develop --output artifacts/study
python -m semiconductor_logistics query-study verify-development --development artifacts/study
python -m semiconductor_logistics query-study freeze --development artifacts/study --output artifacts/frozen
```

先提交冻结任务、模型和配置，再运行最终评测：

```bash
python -m semiconductor_logistics query-study evaluate --development artifacts/study --frozen artifacts/frozen --freeze-commit <freeze-commit-sha> --output artifacts/final
python -m semiconductor_logistics query-study verify-final --development artifacts/study --frozen artifacts/frozen --output artifacts/final
```

`<freeze-commit-sha>`替换为保存该冻结版本的40位Git提交；它是来源记录，离线程序不替用户联网验证远程Git历史。发布检查会核对提交中的冻结文件。不能为了运行命令填写一个无关提交。

验证仓库归档：

```bash
python -m semiconductor_logistics query-study verify-development
python -m semiconductor_logistics query-study verify-final
```

所有命令均为本地数值实验，不调用模型API。程序拒绝覆盖非空输出目录。当前复算重跑全部训练与评测，不支持中断续训；墙钟时间只作诊断。源码身份变化会阻止重放，旧归档应配合产生它的源码提交使用。

## English

See the [multi-seed protocol](query_study_protocol.md). Development training, frozen tasks and final results are separate bundles. Newly trained outputs must not replace frozen models.

| Path | Contents |
|---|---|
| `benchmark_results/query_study_development/` | Configuration, training/validation/audit contexts, five BC and 15 PPO runs, development statistics |
| `models/<seed>-bc.json` | Initial/selected BC parameters, epoch logs and configuration |
| `models/<seed>-<variant>.json` | Initial/selected/last PPO parameters, shared BC identity, settings, update and selection logs |
| `episodes/<seed>-<variant>.jsonl` | One complete sampled episode per line, without rounding raw floats |
| `benchmarks/query_final_v1/` | The 1,000-task list, fixed model registry and training-evidence hash, before final outputs |
| `benchmark_results/query_final_v1/` | Final per-case outcomes, action trees, exact references, paired statistics and freeze-commit identity |

A training line is `[iteration, task_id, repeat, steps]`. Each step is `[action, answer, reward, old_logp, old_value]`: action=0 commits; action=i+1 queries route i. Commitment has a null answer. History starts with all -1 values and is reconstructed from query answers; action=0 determines termination. Reconstruct GAE using the variant's own gamma and lambda. Verification compares reconstructed complete records against retraining, beyond file hashes.

Evaluation-tree nodes are `[history, reach_probability, action, milp_calls, commit_plan, terminal_loss]`. These use environment action numbering: -1 commits, while nonnegative i queries route i. Query nodes have null plans and terminal losses. Trees bind public-context hashes and are stored once per distinct content. Model hashes and tree hashes are separate outcome fields. Adapters explicitly convert between training and environment action numbering.

Exact references score regret and never enter PPO inputs or rewards. Deterministic search has one record per case with seed=null. Learned outcomes carry actual training seeds; repeated evaluation across seeds does not create more distinct tasks.

Reproduce from scratch in empty output directories:

```bash
python -m semiconductor_logistics query-study develop --output artifacts/study
python -m semiconductor_logistics query-study verify-development --development artifacts/study
python -m semiconductor_logistics query-study freeze --development artifacts/study --output artifacts/frozen
```

Commit frozen tasks, models and settings before final evaluation:

```bash
python -m semiconductor_logistics query-study evaluate --development artifacts/study --frozen artifacts/frozen --freeze-commit <freeze-commit-sha> --output artifacts/final
python -m semiconductor_logistics query-study verify-final --development artifacts/study --frozen artifacts/frozen --output artifacts/final
```

Replace `<freeze-commit-sha>` with the 40-character Git commit containing that freeze. This is a provenance record; the offline program does not access remote Git history. Publication checks compare frozen files against the referenced commit. Do not supply an unrelated commit merely to satisfy the argument.

Verify archived evidence:

```bash
python -m semiconductor_logistics query-study verify-development
python -m semiconductor_logistics query-study verify-final
```

All commands run local numerical experiments without model API calls. Nonempty output directories are rejected. Verification reruns all training and evaluation; interrupted-training resume is not implemented. Wall-clock times are diagnostic. Source-identity changes prevent replay, so historical bundles should be used with the source commit that produced them.
