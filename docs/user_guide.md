# 使用手册 / User guide

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

### 1. 用途与适用场景

这是一个半导体物流决策的研究系统。输入一条运输公告或一个扰动假设，它解析出参数并说明依据，由计划员确认，然后用混合整数规划求解正常方案和扰动方案，对比成本、服务水平和排放，最后生成决策备忘录。

适合用来：

- 演示和研究“公告 → 参数 → 优化 → 备忘录”的流程；
- 比较运输中断、碳上限和对冲决策的代价；
- 比较规则解析和大模型在理解业务问题、选择工具、提取参数上的差别；
- 复算项目已保存的实验。

**它不是**企业生产系统。网络的 SKU、需求、运力、费率和扰动幅度都是合成假设；ASML、Marvell 只是启发案例，不是这些公司的数据。距离和排放因子来自公开来源。

### 2. 支持与不支持的功能

| 支持 | 不支持或尚未完成 |
|---|---|
| 两个启发网络：ASML 备件（荷兰→新加坡）、Marvell 芯片（台湾、马来西亚→新加坡） | 接入企业订单、ERP 或真实运价 |
| 单一场景求解、碳上限、碳价、服务水平下限、碳前沿、两阶段随机对冲 | 多目的仓和选址；十万变量以上的实例；分解算法；商业求解器对比 |
| 规则解析、公告检索、录制回放、实时大模型四种参数来源 | 公告自动对应到内部线路：真实公告里的区间和近似值只作参考，不自动变成参数 |
| 命令行和 Streamlit 网页；Markdown 备忘录下载 | 多用户账号、跨进程记忆；公开在线应用尚未部署 |
| 可分享的图、动画和 PDF 导出 | 经过人工标注的真实公告金标准；非作者出题的独立评测 |

### 3. 环境要求

| 项目 | 要求 |
|---|---|
| Python | 3.12（锁文件按 3.12 解析；`pyproject.toml` 允许 3.10 以上，其他版本未验证） |
| 操作系统 | Windows 10：本文所有命令实际运行过。Linux：CI 在 `ubuntu-latest` 上跑规划测试。macOS 未验证 |
| 依赖 | `requirements/planning.txt`（85 个包，带哈希，含开发工具）；只运行网页可以用 `planning_agent/requirements.txt`（45 个包） |
| 硬件 | 不需要 GPU。在 i7-10870H、16 GB 内存的 Windows 上，走完三种离线模式内存峰值约 158 MB，最重的一次请求（碳上限 + 对冲）约 8 秒 |
| 磁盘 | 依赖约 600 MB（Windows 测得的公开部署依赖 584 MB） |
| 网络 | 只有安装依赖、`corpus fetch` 和实时模型模式需要 |

### 4. 安装

**Linux**

```bash
git clone https://github.com/nomoretry/semiconductor-logistics-decarbonization.git
cd semiconductor-logistics-decarbonization
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements/planning.txt
python -m pip install --no-deps --no-build-isolation -e .
```

**Windows（PowerShell）**

```powershell
git clone -c core.autocrlf=false https://github.com/nomoretry/semiconductor-logistics-decarbonization.git
cd semiconductor-logistics-decarbonization
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
python -m pip install --require-hashes -r requirements/planning.txt
python -m pip install --no-deps --no-build-isolation -e .
```

在 Windows 上每个新终端都要设置 `PYTHONUTF8=1`。部分早期研究代码读文件时没有写明编码。`core.autocrlf=false` 保持文件原样，否则早期研究的证据哈希校验会失败。

### 5. 四种模式

| 模式 | 命令行 | 参数从哪里来 | 是否调用模型 | 是否求解 |
|---|---|---|---|---|
| 离线规则 | `flow` | `rules.py` 的正则解析 | 否 | 确认后求解 |
| 公告检索 | `flow --mode notice` | 同上，并检索真实公告，列出出处和公告缺少的信息 | 否 | 确认后求解 |
| 录制回放 | `flow --mode replay --case D13` | 真实模型在历史评测中提出的参数（D13、H05） | 否，本次不调用 | 确认后求解 |
| 实时模型 | `flow --mode live` | 大模型经 LangGraph 提出参数，任何场景工具执行前暂停 | 是，付费 | 确认后求解 |

无论哪种模式，所有数字都来自求解器；确认之前不求解。页面和备忘录都写明参数来源。

### 6. API Key 与模型选择

默认不调用：只设置密钥不会发出任何请求，还需要模型名和限额。完整说明见[实时模型调用的配置与限额](live_model_safety.md)。

**PowerShell**（隐藏输入，不进命令历史）：

```powershell
$s = Read-Host "LLM_API_KEY" -AsSecureString
$env:LLM_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
$env:LLM_MODEL_ID = "gpt-6-luna"
$env:LLM_API_STYLE = "responses"
$env:LLM_MAX_REQUESTS = "10"
$env:LLM_MAX_TOTAL_TOKENS = "100000"
$env:LLM_MAX_OUTPUT_TOKENS = "4000"
python -m planning_agent llm-check
```

**Linux**：

```bash
read -rs LLM_API_KEY && export LLM_API_KEY
export LLM_MODEL_ID=gpt-6-luna LLM_API_STYLE=responses
export LLM_MAX_REQUESTS=10 LLM_MAX_TOTAL_TOKENS=100000 LLM_MAX_OUTPUT_TOKENS=4000
python -m planning_agent llm-check
```

`llm-check` 不联网，不显示密钥，只列出缺什么；配置齐全时退出码为 0。如果用 `eval-v2 run --prompt-key` 的隐藏输入，Windows 控制台不支持 Ctrl+V，粘贴也可能失败；这时按上面的方法设置环境变量。其他 OpenAI 兼容服务设置 `LLM_BASE_URL`（必须是 https，本机地址除外）。

把密钥放在环境变量或托管平台的 Secrets 里，不要写进文件、命令行参数或聊天。`.env`、`.env.*`、`.streamlit/secrets.toml` 和 `artifacts/` 不进 Git。公开部署要用单独的密钥，并在服务商处设额度上限。

### 7. 命令行操作

下面的例子是**离线规则模式**，不调用模型。

```bash
python -m planning_agent flow
```

1. **输入公告**：默认用内置示例；自己的公告用 `--notice "..."`，例如 `--notice "第5到8周海运延误1周，舱位削减20%：对 ASML 备件有什么影响？"`。
2. **确认参数**：程序列出参数、原文依据和默认假设，然后询问 `[y] 确认  [e] 修改第一个扰动  [n] 取消`。选 `n` 不做任何求解。脚本里可以加 `--yes`。
3. **可选约束**：`--carbon-cap 80`（排放不超过不设上限方案的 80%）、`--probability 25`（中断概率 25%，做两阶段对冲）、`--network marvell`。
4. **查看结果**：终端打印方案对比。备忘录写到 `artifacts/planning_agent/flow/memo-<编号>.md`，也可以用 `--output` 指定目录。

其他常用命令：

```bash
python -m planning_agent flow --mode notice
python -m planning_agent flow --mode replay --case D13
python -m planning_agent --agent rule ask "红海中断对 ASML 备件成本有什么影响？" --show-tools
python -m planning_agent corpus search "鹿特丹码头罢工"
python -m network_planning solve --network asml --scenario red_sea --explain
python -m network_planning frontier --network marvell
python -m network_planning stochastic --network asml --reveal-week 3
```

全部命令见[命令参考](commands.md)。

### 8. 网页操作

```bash
python -m streamlit run planning_agent/app.py
```

1. 在侧栏选参数来源（手机上侧栏默认收起，当前模式也写在标题下方）。
2. 在文本框输入公告，选网络，点“解析参数”；公告检索模式点“检索公告并解析参数”。
3. 看“参数与默认假设”：原文依据、参数依据和默认假设都列出来。可以直接改表格，也可以设排放上限和中断概率。此时还没有求解。
4. 点“② 确认并求解”。
5. 看方案对比：扰动方案的总成本、服务水平、排放和空运占比，相对正常方案的变化。
6. 看决策备忘录，点“下载备忘录（Markdown）”。方案对比表右上角可以下载 CSV。
7. 工具调用记录在页面最下方。

实时模型模式默认不出现。开放它需要在服务端配置开关、访问码和每日额度，见[配置与限额](live_model_safety.md)。

### 9. 完整示例

- **模式**：离线规则解析 + 实时优化，不调用模型。
- **场景假设**：ASML 启发的备件网络，12 个合成 SKU、16 周。公告：第 4 到 12 周亚欧航线绕行好望角，海运延误 2 周，舱位削减 30%。
- **命令**：

```bash
python -m planning_agent flow --yes --output artifacts/guide_example
```

- **解析结果**：海运线路，第 4–12 周，延误 2 周，运力 −30%，距离系数 1.4183（经好望角与经苏伊士的距离比）。公告没有说运价，默认不变，并列为假设。
- **输出**（终端）：

```text
方案：P1（正常）  总成本（美元）：55253  成本变化：+0.00%  服务水平：100.0%  排放（吨）：20.82  排放变化：+0.00%  空运占比：19.8%
方案：P2（扰动）  总成本（美元）：60711  成本变化：+9.88%  服务水平：100.0%  排放（吨）：27.12  排放变化：+30.26%  空运占比：26.2%
```

- **结果文件**：`artifacts/guide_example/memo-<编号>.md`，包含结论、方案对比、驱动因素、假设与局限和参数来源。
- **怎样理解**：在这组合成假设下，扰动让成本上升约 9.88%，排放上升约 30.26%。服务水平保持 100%，代价是更多货改走空运（占比提高 6.4 个百分点）和绕行带来的距离。这是比较策略的依据，不是企业的实际节省或损失。

### 10. 测试、复算与排错

```bash
make planning-test
make quality
make lock-check
python -m planning_agent replay
python -m planning_agent --agent rule eval --output artifacts/planning_agent/eval
python -m planning_agent corpus evaluate --check
python -m planning_agent eval-v2 verify
python -m network_planning report --quick --output artifacts/planning/report
make verify-final
```

`make` 需要 GNU Make（Windows 上可用 Git Bash 环境里的 make，或者直接运行 Makefile 中的命令）。各研究的复算命令见[研究说明](research_guide.md)。

| 现象 | 原因与处理 |
|---|---|
| `UnicodeDecodeError`、GBK 报错 | Windows 没有设置 `PYTHONUTF8=1` |
| `没有调用模型：no spending limit configured` | 只设了密钥，没有设限额；运行 `llm-check` 看缺什么 |
| 网页没有实时模式 | 正常现象，默认关闭 |
| 参数不可用：`没有可用的扰动参数` | 公告没有周次和幅度，规则解析不出来；在 `--notice` 里写明，或者在网页表格里填写 |
| `output stopped at the cap` | 输出上限太小，推理 token 也算在内；调高 `LLM_MAX_OUTPUT_TOKENS` |
| `pip` 报路径太长（WinError 206） | 把虚拟环境放在较短的路径下 |
| 指定只影响一条线路，结果却多了同类线路 | 已知缺陷：`create_scenario` 把 `mode` 和 `lanes` 相加。手工调用时只传 `lanes`；大模型会两个都传，见[评测报告](results/planning_agent_v2.md) |
| 全量 `make test` 在 Windows 上有 17 个失败 | 已知问题，来自冻结模块的路径和源码身份检查；规划相关测试不受影响 |

### 11. 获取可分享的成果

```bash
python -m pip install imageio-ffmpeg
python scripts/export_presentation.py
```

文件写到 `artifacts/share/`：图（PNG、SVG）、逐周发运动画（MP4、GIF 预览、JSON 数据）、示例备忘录（HTML、PDF）、`00_README.md` 和带 SHA-256 的 `manifest.json`。每份文件都标明数据来源、代码版本和展示模式。这些文件可以直接发送，不需要接收者安装任何东西。`imageio-ffmpeg` 只在导出 MP4 时需要，不在锁文件里；PDF 需要本机有 Chromium 内核的浏览器（Edge 或 Chrome），没有时跳过。

系统架构图见 [SVG](figures/system_architecture.svg) 和 [PDF](figures/system_architecture.pdf)。

**在线应用：待部署**。目前没有公开的 HTTPS 链接；本机运行的 Streamlit 地址只能自己打开，不能发给别人。

## English

### 1. Purpose and fit

This is a research system for semiconductor logistics decisions. Given a carrier notice or a disruption assumption, it extracts parameters and shows their basis, a planner confirms them, and mixed-integer optimisation solves the normal and disrupted plans. It then compares cost, service level and emissions and writes a decision memo.

Use it to:

- demonstrate and study the notice → parameters → optimisation → memo flow;
- compare the cost of transport disruptions, emission caps and hedging decisions;
- compare rule parsing and a large model on understanding requests, choosing tools and extracting parameters;
- reproduce the project's saved experiments.

**It is not** a production system. SKUs, demand, capacities, rates and disruption sizes are synthetic; ASML and Marvell are inspirations, not those companies' data. Distances and emission factors come from public sources.

### 2. Supported and not supported

| Supported | Not supported or not finished |
|---|---|
| Two inspired networks: ASML spare parts (Netherlands→Singapore), Marvell chips (Taiwan, Malaysia→Singapore) | Company orders, ERP or real rates |
| Single-scenario solves, emission caps, carbon prices, service floors, carbon frontier, two-stage hedging | Multiple destinations and siting; instances above 100,000 variables; decomposition; commercial solver comparison |
| Rule parsing, notice retrieval, recorded replay and live model as parameter sources | Mapping a notice to internal lanes automatically: ranges and approximations in real notices are shown for reference and do not become parameters |
| Command line and Streamlit page; Markdown memo download | User accounts and memory across processes; the public online app is not deployed yet |
| Exports of shareable figures, animation and PDF | Human-labelled gold answers for real notices; an independent evaluation by other authors |

### 3. Requirements

| Item | Requirement |
|---|---|
| Python | 3.12 (the locks resolve for 3.12; `pyproject.toml` allows 3.10 and up, other versions are not verified) |
| Operating system | Windows 10: every command here was run. Linux: CI runs the planning tests on `ubuntu-latest`. macOS is not verified |
| Dependencies | `requirements/planning.txt` (85 packages with hashes, developer tools included); for the page alone, `planning_agent/requirements.txt` (45 packages) |
| Hardware | No GPU. On Windows with an i7-10870H and 16 GB of memory, going through the three offline modes peaked at about 158 MB, and the heaviest request (emission cap plus hedge) took about 8 seconds |
| Disk | About 600 MB for dependencies (584 MB measured on Windows for the public deployment set) |
| Network | Only for installing dependencies, `corpus fetch` and the live model mode |

### 4. Installation

**Linux**

```bash
git clone https://github.com/nomoretry/semiconductor-logistics-decarbonization.git
cd semiconductor-logistics-decarbonization
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements/planning.txt
python -m pip install --no-deps --no-build-isolation -e .
```

**Windows (PowerShell)**

```powershell
git clone -c core.autocrlf=false https://github.com/nomoretry/semiconductor-logistics-decarbonization.git
cd semiconductor-logistics-decarbonization
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
python -m pip install --require-hashes -r requirements/planning.txt
python -m pip install --no-deps --no-build-isolation -e .
```

On Windows, set `PYTHONUTF8=1` in every new terminal: some early research code opens files without naming an encoding. `core.autocrlf=false` keeps files as they are; otherwise the evidence hash checks of the early studies fail.

### 5. The four modes

| Mode | Command line | Where parameters come from | Calls a model | Solves |
|---|---|---|---|---|
| Offline rule | `flow` | Regular expressions in `rules.py` | No | After confirmation |
| Notice retrieval | `flow --mode notice` | The same, plus retrieved real notices with their sources and what they leave out | No | After confirmation |
| Recorded replay | `flow --mode replay --case D13` | Parameters a real model proposed in an earlier evaluation (D13, H05) | No, not in this run | After confirmation |
| Live model | `flow --mode live` | A large model through LangGraph, paused before any scenario tool runs | Yes, paid | After confirmation |

In every mode the numbers come from the solver and nothing is solved before confirmation. The page and the memo say where the parameters came from.

### 6. API key and model choice

Nothing is called by default: a key alone sends no request; a model id and limits are also needed. See [live model calls: configuration and limits](live_model_safety.md).

**PowerShell** (hidden input, stays out of the history):

```powershell
$s = Read-Host "LLM_API_KEY" -AsSecureString
$env:LLM_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
$env:LLM_MODEL_ID = "gpt-6-luna"
$env:LLM_API_STYLE = "responses"
$env:LLM_MAX_REQUESTS = "10"
$env:LLM_MAX_TOTAL_TOKENS = "100000"
$env:LLM_MAX_OUTPUT_TOKENS = "4000"
python -m planning_agent llm-check
```

**Linux**:

```bash
read -rs LLM_API_KEY && export LLM_API_KEY
export LLM_MODEL_ID=gpt-6-luna LLM_API_STYLE=responses
export LLM_MAX_REQUESTS=10 LLM_MAX_TOTAL_TOKENS=100000 LLM_MAX_OUTPUT_TOKENS=4000
python -m planning_agent llm-check
```

`llm-check` does not touch the network or show the key; it lists what is missing and exits with 0 when the configuration is complete. The hidden input of `eval-v2 run --prompt-key` does not accept Ctrl+V in a Windows console, and pasting may fail; set the environment variable as above instead. For another OpenAI-compatible service, set `LLM_BASE_URL` (https is required except for loopback addresses).

Keep the key in the environment or the host's Secrets, never in a file, a command-line argument or a chat. `.env`, `.env.*`, `.streamlit/secrets.toml` and `artifacts/` stay out of Git. A public deployment needs its own key with a spending cap at the provider.

### 7. Command line

This example uses the **offline rule mode** and calls no model.

```bash
python -m planning_agent flow
```

1. **Enter a notice**: the built-in example is the default; pass your own with `--notice "..."`, for example `--notice "Weeks 5-8 ocean delayed 1 week, capacity cut 20%: impact on ASML?"`.
2. **Confirm the parameters**: the program lists parameters, source text and default assumptions, then asks `[y] confirm  [e] edit the first disruption  [n] cancel` (in Chinese). `n` solves nothing. Scripts can pass `--yes`.
3. **Optional constraints**: `--carbon-cap 80` (emissions at most 80% of the uncapped plan), `--probability 25` (25% disruption probability, with a two-stage hedge), `--network marvell`.
4. **See the results**: the terminal prints the comparison. The memo goes to `artifacts/planning_agent/flow/memo-<id>.md`, or to the folder given by `--output`.

Other common commands:

```bash
python -m planning_agent flow --mode notice
python -m planning_agent flow --mode replay --case D13
python -m planning_agent --agent rule ask "红海中断对 ASML 备件成本有什么影响？" --show-tools
python -m planning_agent corpus search "Rotterdam strike"
python -m network_planning solve --network asml --scenario red_sea --explain
python -m network_planning frontier --network marvell
python -m network_planning stochastic --network asml --reveal-week 3
```

All commands are in the [command reference](commands.md).

### 8. Web page

```bash
python -m streamlit run planning_agent/app.py
```

The page text is in Chinese.

1. Choose the parameter source in the sidebar (it starts collapsed on a phone, and the current mode is also stated under the title).
2. Enter a notice, choose a network and click "解析参数" (parse); in notice mode, "检索公告并解析参数" (retrieve and parse).
3. Review parameters and default assumptions, with source text and basis for each. You can edit the table and set an emission cap and a disruption probability. Nothing has been solved yet.
4. Click "② 确认并求解" (confirm and solve).
5. Read the comparison: total cost, service level, emissions and air share of the disrupted plan, with the change from the normal plan.
6. Read the memo and click "下载备忘录（Markdown）" to download it. The comparison table can be downloaded as CSV from its top-right corner.
7. The tool call record is at the bottom of the page.

The live model mode does not appear by default. Opening it requires the switch, an access code and daily limits on the server; see [configuration and limits](live_model_safety.md).

### 9. Complete example

- **Mode**: offline rule parsing with live optimisation; no model call.
- **Assumptions**: the ASML-inspired spare-parts network, 12 synthetic SKUs, 16 weeks. Notice: in weeks 4–12 Asia-Europe sailings divert around the Cape of Good Hope, ocean is delayed 2 weeks and space is cut 30%.
- **Command**:

```bash
python -m planning_agent flow --yes --output artifacts/guide_example
```

- **Parsed**: ocean lane, weeks 4–12, 2 weeks of delay, capacity −30%, distance factor 1.4183 (Cape versus Suez distance). The notice says nothing about rates, so they stay unchanged and this is listed as an assumption.
- **Output** (terminal, labels in Chinese; P1 normal, P2 disrupted):

```text
方案：P1（正常）  总成本（美元）：55253  成本变化：+0.00%  服务水平：100.0%  排放（吨）：20.82  排放变化：+0.00%  空运占比：19.8%
方案：P2（扰动）  总成本（美元）：60711  成本变化：+9.88%  服务水平：100.0%  排放（吨）：27.12  排放变化：+30.26%  空运占比：26.2%
```

- **Result file**: `artifacts/guide_example/memo-<id>.md`, with the conclusion, plan comparison, cost drivers, assumptions and limits, and the parameter source.
- **How to read it**: under these synthetic assumptions, the disruption raises cost by about 9.88% and emissions by about 30.26%. Service stays at 100%, paid for by moving more freight to air (share up 6.4 percentage points) and by the longer route. This supports comparing strategies; it is not a company's actual saving or loss.

### 10. Tests, reproduction and troubleshooting

```bash
make planning-test
make quality
make lock-check
python -m planning_agent replay
python -m planning_agent --agent rule eval --output artifacts/planning_agent/eval
python -m planning_agent corpus evaluate --check
python -m planning_agent eval-v2 verify
python -m network_planning report --quick --output artifacts/planning/report
make verify-final
```

`make` needs GNU Make (on Windows, the one in a Git Bash environment, or run the commands from the Makefile directly). Reproduction commands per study are in the [research guide](research_guide.md).

| Symptom | Cause and fix |
|---|---|
| `UnicodeDecodeError`, GBK errors | `PYTHONUTF8=1` is not set on Windows |
| `没有调用模型：no spending limit configured` | A key without limits; run `llm-check` to see what is missing |
| No live mode on the page | Expected: it is closed by default |
| `参数不可用：没有可用的扰动参数` | The notice has no weeks or sizes for the rule parser; state them in `--notice` or fill in the table on the page |
| `output stopped at the cap` | The output cap is too low, and reasoning tokens count; raise `LLM_MAX_OUTPUT_TOKENS` |
| `pip` says a path is too long (WinError 206) | Put the virtual environment on a shorter path |
| A disruption meant for one lane also affects another lane of that mode | Known defect: `create_scenario` adds `mode` and `lanes`. Pass only `lanes` when calling it by hand; a large model passes both, see the [evaluation report](results/planning_agent_v2.md) |
| 17 failures in the full `make test` on Windows | A known issue from path and source-identity checks of frozen modules; the planning tests are not affected |

### 11. Getting shareable results

```bash
python -m pip install imageio-ffmpeg
python scripts/export_presentation.py
```

Files go to `artifacts/share/`: figures (PNG, SVG), a weekly-flow animation (MP4, GIF preview, JSON data), an example memo (HTML, PDF), `00_README.md` and `manifest.json` with SHA-256 hashes. Each file states its data source, code version and display mode. They can be sent as they are; recipients install nothing. `imageio-ffmpeg` is only needed for MP4 and is not in the locks; the PDF needs a Chromium-based browser (Edge or Chrome) on the machine and is skipped otherwise.

The system architecture figure is available as [SVG](figures/system_architecture.svg) and [PDF](figures/system_architecture.pdf).

**Online app: pending deployment.** There is no public HTTPS link yet; a Streamlit address on your own machine cannot be sent to anyone else.
