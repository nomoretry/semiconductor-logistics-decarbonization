# 首期动作实验时间预算修订 / First-action experiment wall-time budget amendment

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

正式运行的估计墙钟门槛和 A+B 的共享墙钟上限均从 5,400 秒调至 10,800 秒。沿用 45 秒余量、累计求解失败率严格超过 5% 即结束的门槛，以及单进程顺序执行。

第一次试算估计正式墙钟为 6,066.942 秒，超过原上限，正式求解次数为零。用户仅依据该次试算计时，决定按原设计完成 44 个观测。沿用原协议的观测、种子、档位、容差、两条稳定判据、实质判定和汇总方式。

第一次试算证据保存在 [A 试算归档](../benchmark_results/rolling_tree_materiality_gate1/) 和 [B 试算归档](../benchmark_results/rolling_tree_consensus_gate1/)。重做同样 12 个观测的试算，再用原公式和修订后的门槛决定是否启动正式运行。

原协议 `docs/rolling_tree_consensus_protocol.md` 的 SHA256 为 `1f419a3dfea40d299e1ce906623838a033b194210fecddac9b93f52e5feb674f`，与第一次试算的 `config.json` 一致。[原协议](rolling_tree_consensus_protocol.md)

## English

The estimated wall-time gate for the formal run and the shared A+B wall-time cap both increase from 5,400 to 10,800 seconds. Keep the 45-second reserve, end the run if cumulative solve failures strictly exceed 5% of attempts, and run sequentially in a single process.

The first trial estimated 6,066.942 seconds of formal wall time, exceeding the original cap. Formal solves totaled zero. The user chose to evaluate all 44 observations under the original design based only on the first trial's timing. Use the original protocol's observations, seeds, tiers, tolerance, two stability criteria, materiality rules and summaries.

The first trial evidence is available in the [A trial archive](../benchmark_results/rolling_tree_materiality_gate1/) and [B trial archive](../benchmark_results/rolling_tree_consensus_gate1/). Repeat the trial on the same 12 observations and apply the original formula and amended gate before starting the formal run.

The original protocol, `docs/rolling_tree_consensus_protocol.md`, has SHA256 `1f419a3dfea40d299e1ce906623838a033b194210fecddac9b93f52e5feb674f`, matching the first trial's `config.json`. [Original protocol](rolling_tree_consensus_protocol.md)
