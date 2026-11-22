# 实时模型调用的配置与限额 / Live model calls: configuration and limits

本文提供中英文版本，中文在前，英文在后。
This document provides Chinese first and English second.

## 中文

**问题**：规划 Agent 可以调用付费的大模型。只在调用之后比较用量和预算，钱已经花出去了，所以限额必须在请求发出之前生效；公开网页也不能让访客自己决定花多少钱。

**默认行为**：没有配置就不调用。只设置 `LLM_API_KEY` 不会产生任何请求：`--agent auto` 退回离线规则 Agent，`--agent llm`、`--agent graph` 和 `flow --mode live` 直接拒绝，网页上不出现实时模式。

### 配置

| 变量 | 必需 | 含义 |
|---|---|---|
| `LLM_API_KEY` | 是 | 服务商密钥。只从环境变量读取（托管平台的 Secrets 顶层字符串也会进入环境变量） |
| `LLM_MODEL_ID` | 是 | 模型名，没有内置默认值 |
| `LLM_BASE_URL` | 否 | OpenAI 兼容接口地址，默认 `https://api.openai.com/v1`。必须是 https（本机地址除外），不能带账号、查询串 |
| `LLM_API_STYLE`、`LLM_REASONING_EFFORT`、`LLM_REASONING_MODE`、`LLM_SERVICE_TIER`、`LLM_TIMEOUT` | 否 | 接口类型、推理强度、推理模式、处理档位、单次超时 |
| `LLM_MAX_REQUESTS` | 是 | 发出的 HTTP 请求总数，重试和回退都计入 |
| `LLM_MAX_TOTAL_TOKENS` | 是 | 输入加输出的总 token（`eval`、`flow` 的 `--max-tokens` 可覆盖） |
| `LLM_MAX_OUTPUT_TOKENS` | 是 | 每次请求的输出上限，随请求发给服务商 |
| `LLM_MAX_INPUT_TOKENS` | 否 | 单次请求输入上界超过它就不发送 |
| `LLM_MAX_USD`、`LLM_INPUT_USD_PER_M`、`LLM_OUTPUT_USD_PER_M` | 否 | 美元上限和每百万 token 单价；单价由使用者按服务商价目填写 |
| `LLM_LEDGER_PATH` | 否 | 账本文件；设置后总额度跨多次运行累计 |

检查当前配置（不联网，不显示密钥）：

```bash
python -m planning_agent llm-check
```

在 Windows PowerShell 里用隐藏输入设置密钥，避免写进命令历史：

```powershell
$s = Read-Host "LLM_API_KEY" -AsSecureString
$env:LLM_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
```

### 限额怎样生效（`planning_agent/spending.py`）

1. 每个请求发送前先预留最坏情况：输入上界（请求体字节数加一个小常数，一个 token 至少对应一个字节）加输出上限。任何一项限额可能被突破，请求就不发送。
2. 收到回复后，用服务商报告的用量替换预留量。
3. 超时、5xx、回复里没有用量、程序中途退出时不知道是否计费，预留量保持计入。4xx（含 429）视为没有运行模型，只计请求次数。
4. 账本只记次数、token 和金额，不记提示词、回复或密钥。账本损坏时拒绝调用。
5. 输出达到上限时丢弃整个回复并报错，不使用被截断的工具参数。

**已知边界**：

- 输入上界假定请求体反映全部输入。Responses 接口回传推理条目时，服务端可能计入请求体之外的 token；这时只能在回复后发现超出（`overrun_tokens`），并拒绝后续请求。
- 两个进程同时写同一账本，最多可能多出一次预留量；单个网页进程和依次运行的命令行不会。
- 单价由使用者填写，美元数是按单价折算的估算，不是账单。

### 密钥

密钥只放在请求头里。错误信息先做脱敏（密钥原文、`sk-…`、`Bearer …`、`api_key=…`）再截断；客户端的 `repr` 不含密钥；不跟随重定向，因为 urllib 会把请求头带到重定向目标；`.env`、`.env.*`、`.streamlit/secrets.toml` 和 `artifacts/` 不进 Git。

### 公开网页（`llm.LiveAccess`）

实时模式默认不存在。只有下面这些设置**全部**在服务端配置好才开放；访客只能输入访问码，不能修改任何额度。

| 变量 | 含义 |
|---|---|
| `LLM_WEB_LIVE=on` | 显式开关 |
| `LLM_API_KEY`、`LLM_MODEL_ID` | 同上 |
| `LLM_WEB_ACCESS_CODE_SHA256` | 访问码的 SHA-256；访问码本身不保存 |
| `LLM_WEB_MAX_REQUESTS`、`LLM_WEB_MAX_TOTAL_TOKENS` | 每日（UTC）所有访客合计 |
| `LLM_WEB_MAX_OUTPUT_TOKENS` | 每次请求 |
| `LLM_WEB_SESSION_MAX_REQUESTS` | 每个浏览器会话 |
| `LLM_WEB_MAX_INPUT_TOKENS`、`LLM_WEB_MAX_USD`、`LLM_WEB_LEDGER_PATH`、`LLM_WEB_TIMEOUT` | 可选 |

网页不重试。访问码连续错误 5 次后锁定 15 分钟，锁定只影响实时模式。

三层限额各有弱点：新开会话可以绕过会话限额；托管平台重启可能清空每日账本。因此要给公开部署单独建一把密钥，并在服务商处设置该密钥的额度上限。

### 三种证据要分开

| 标签 | 含义 | 出现位置 |
|---|---|---|
| `real` | 访问外部模型服务，可能计费 | 评测汇总 `call_kind`、方案来源、备忘录 |
| `local` | 请求发到本机地址（测试用的假服务或本机模型），没有访问外部服务 | 同上 |
| `replay` | 重放录制的历史输出，没有调用模型 | 同上 |
| `simulated` | 测试脚本客户端，没有 HTTP | 同上 |

`tests/test_llm_safety.py` 用本机假服务走真实的 HTTP 路径，不访问外部模型。它验证的是限额、脱敏和开关，不说明模型的质量。

## English

**Problem.** The planning agent can call a paid model. Comparing usage with a budget after the call cannot stop anything, so limits must apply before a request is sent, and a public page must not let visitors decide how much is spent.

**Default.** No configuration, no call. `LLM_API_KEY` alone sends nothing: `--agent auto` falls back to the offline rule agent; `--agent llm`, `--agent graph` and `flow --mode live` refuse to start; the live mode does not appear on the web page.

### Configuration

| Variable | Required | Meaning |
|---|---|---|
| `LLM_API_KEY` | Yes | Provider key. Read from the environment only (root-level strings in a host's Secrets also reach the environment) |
| `LLM_MODEL_ID` | Yes | Model id; there is no built-in default |
| `LLM_BASE_URL` | No | OpenAI-compatible endpoint, default `https://api.openai.com/v1`. Must be https (loopback excepted), with no credentials or query |
| `LLM_API_STYLE`, `LLM_REASONING_EFFORT`, `LLM_REASONING_MODE`, `LLM_SERVICE_TIER`, `LLM_TIMEOUT` | No | API style, reasoning effort, reasoning mode, processing tier, per-request timeout |
| `LLM_MAX_REQUESTS` | Yes | HTTP requests sent, retries and fallbacks included |
| `LLM_MAX_TOTAL_TOKENS` | Yes | Input plus output tokens (`--max-tokens` on `eval` and `flow` overrides it) |
| `LLM_MAX_OUTPUT_TOKENS` | Yes | Output cap of each request, sent to the provider |
| `LLM_MAX_INPUT_TOKENS` | No | A request whose input bound is above this is not sent |
| `LLM_MAX_USD`, `LLM_INPUT_USD_PER_M`, `LLM_OUTPUT_USD_PER_M` | No | USD limit and prices per million tokens; the user fills in the provider's prices |
| `LLM_LEDGER_PATH` | No | Ledger file; when set, the totals carry over between runs |

Check the configuration (no network, the key is never shown):

```bash
python -m planning_agent llm-check
```

In Windows PowerShell, enter the key with hidden input so that it stays out of the command history:

```powershell
$s = Read-Host "LLM_API_KEY" -AsSecureString
$env:LLM_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
```

### How limits apply (`planning_agent/spending.py`)

1. Before a request is sent it reserves its worst case: an input bound (body bytes plus a small constant, since a token covers at least one byte) plus the output cap. If any limit could be passed, the request is not sent.
2. The usage the provider reports replaces the reservation.
3. After a timeout, a 5xx, a reply without usage or a crash, billing is unknown and the reservation stays charged. A 4xx (429 included) means the model did not run; only the request count grows.
4. The ledger holds counts, tokens and amounts, never prompts, replies or keys. An unreadable ledger refuses calls.
5. Output that reaches the cap discards the whole reply with an error; truncated tool arguments are never used.

**Known boundaries.**

- The input bound assumes the body shows all of the input. When the Responses API replays reasoning items, the service may count tokens outside the body; this is only seen after the reply (`overrun_tokens`), and further requests are refused.
- Two processes writing one ledger at the same moment can pass a limit by one reservation; a single web process and sequential command-line runs cannot.
- Prices are entered by the user, so USD figures are estimates at those prices, not an invoice.

### The key

The key goes only in the request header. Error text is redacted (the key itself, `sk-…`, `Bearer …`, `api_key=…`) before it is truncated; the client's `repr` does not show the key; redirects are not followed, because urllib would carry the header to the target; `.env`, `.env.*`, `.streamlit/secrets.toml` and `artifacts/` stay out of Git.

### The public page (`llm.LiveAccess`)

The live mode does not exist by default. It opens only when **all** of these are set on the server; visitors can enter the access code but cannot change any limit.

| Variable | Meaning |
|---|---|
| `LLM_WEB_LIVE=on` | Explicit switch |
| `LLM_API_KEY`, `LLM_MODEL_ID` | As above |
| `LLM_WEB_ACCESS_CODE_SHA256` | SHA-256 of the access code; the code itself is not stored |
| `LLM_WEB_MAX_REQUESTS`, `LLM_WEB_MAX_TOTAL_TOKENS` | Per day (UTC), all visitors together |
| `LLM_WEB_MAX_OUTPUT_TOKENS` | Per request |
| `LLM_WEB_SESSION_MAX_REQUESTS` | Per browser session |
| `LLM_WEB_MAX_INPUT_TOKENS`, `LLM_WEB_MAX_USD`, `LLM_WEB_LEDGER_PATH`, `LLM_WEB_TIMEOUT` | Optional |

The page does not retry. Five wrong codes lock the live mode for 15 minutes; the lock affects nothing else.

Each layer has a weakness: a new session avoids the session limit, and a host restart may wipe the daily ledger. A public deployment therefore needs its own key with a spending cap set at the provider.

### Keep three kinds of evidence apart

| Label | Meaning | Where |
|---|---|---|
| `real` | Reached an external model service; may be billed | `call_kind` in evaluation summaries, plan source, memo |
| `local` | Sent to a loopback address (a test server or a local model); no external service | Same |
| `replay` | Replayed recorded output; no model call | Same |
| `simulated` | A scripted test client; no HTTP | Same |

`tests/test_llm_safety.py` uses a local fake server over the real HTTP path and reaches no external model. It checks limits, redaction and the switch; it says nothing about model quality.
