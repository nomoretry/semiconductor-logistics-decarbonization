本文先列中文，后列英文。 / Chinese first, English second.

# 闭环配对检验的时间预算修订 / Time budget amendment for the paired closed-loop test

## 中文

第一次试算在路径种子 72019 的四条既有开发路径上运行全部六项策略，采样种子为 924601。下表给出每条路径的墙钟。原门槛估计为 160 × 55.9003285 + 60 = 9,004.052560 秒，超过 7,200 秒。因此首次执行在试算结束，正式路径和正式求解均为 0。计时在共享机器上测得，当时另一项实验也在运行，其影响没有单独测量。

| 需求过程 / Demand profile | 墙钟秒数 / Wall seconds |
|---|---:|
| stable | 10.391134 |
| volatile | 55.900328 |
| upshift | 18.096367 |
| downshift | 20.168151 |

根据这四个计时，将试算估计门槛和正式运行墙钟上限均从 **7,200 秒调至 14,400 秒**，整轮目标从 **4 小时调至 8 小时**。修订在重新计时及生成任何收尾路径前登记。仍以 160 × 四条开发路径中最长墙钟 + 60 秒判定。估计超过新上限即结束，通过后依原顺序执行 160 条合成路径和全部六项策略。路径与采样种子、统计规则、失败处理、30 秒单次求解上限及其余条件均遵循原协议。启用修订预算的命令为 `python -m rolling_tree closing --max-wall-seconds 14400`，省略参数仍使用 7,200 秒。[原协议](rolling_tree_closing_protocol.md)

## English

The first timing run covered all six methods on four existing development paths, using path seed 72019 and sampler seed 924601. The shared table gives wall seconds per path. The estimate was 160 × 55.9003285 + 60 = 9,004.052560 seconds, above the 7,200-second gate. The first run ended after timing with zero formal paths and zero formal solves. Times were measured on a shared machine while another experiment was running. Its timing contribution was unmeasured.

On the basis of these four timings, the estimation gate and formal wall limit both rise from **7,200 to 14,400 seconds**, and the whole-study target rises from **four to eight hours**. This amendment precedes retiming and generation of any closing path. The estimate remains 160 times the maximum wall time across the four development paths plus 60 seconds. End if the estimate exceeds the new limit. Otherwise execute the 160 synthetic paths and all six methods in the original order. Path and sampling seeds, statistics, failure handling, the 30-second per-solve limit and all other conditions follow the original protocol. Use `python -m rolling_tree closing --max-wall-seconds 14400` for the amended budget. Omitting the option retains the 7,200-second default. [Original protocol](rolling_tree_closing_protocol.md)
