# OpenCode Go 接入 WorkBuddy —— 最终方案（全部实测通过）✅

**更新**：2026-10-05（第六版，代理 v1.4：**补齐工具调用 + 支持 Anthropic 协议**）
**状态**：DeepSeek V4.1 Flash ✅ / GPT-6 Luna ✅ / Muse Spark 1.3 Contributor ✅ /
**Qwen3.8 Flash ✅ / Qwen3.8 Max ✅ / MiniMax M3 ✅**（三种协议全部实测 HTTP 200）

**默认思考档位**：`medium`（各条目统一；UI 下拉仍可临时切 low / high）

**v1.4 修掉了两个真问题**（详见第十一节）：

| # | 问题 | 原因 |
|---|---|---|
| 1 | **Responses 模型（Luna / Grok / Muse）不会调用工具** | 代理只翻译了文本，`tools` 没往 `/responses` 传、`function_call` 也没回译成 `tool_calls` |
| 2 | **不支持 Anthropic 协议模型（Qwen / MiniMax）** | 走 `/messages`，代理直接返回 501 |

**顺带挖出一个隐蔽的坑**：上游前置了 Cloudflare，**默认的 `Python-urllib` UA 会被封**（HTTP 403 / `error code: 1010`）。
代理一直自带 UA 所以没暴露，但任何**直连探测脚本**只要没设 UA 就会莫名 403。见第十一节。

> **两个必做的动作**：① **重启代理**（旧进程还占着 8787，跑的还是 v1.3）
> ② **完全重启 WorkBuddy**（加载新写入的模型条目）

---

## 一、两个 400 的真因（这一版才是完整的）

接通过程中撞了**两个** 400，第二个被第一个挡住了，所以是分层暴露的：

| # | 报错 | 真因 |
|---|---|---|
| 1 | `400 MissingSessionID` | OpenCode Go 强制要求每个请求带 `x-opencode-session` 头，而 **WorkBuddy 没有自定义请求头的入口** |
| 2 | `400 Model is unavailable` | **WorkBuddy 把 `models.json` 里的 `id` 字段原样当模型名发给上游**（models.json 里根本没有独立的 `model` 字段，`id` 就是模型名）。我写的 `id = opencode-go-deepseek-v4.1-flash` 上游不认识 |

第 2 个之所以被藏住：**上游是先校验 session 头、后校验模型名**。头不对时直接返回 MissingSessionID，根本走不到模型校验那一步。

### 决定性证据

```
用 models.json 的 id 当模型名打上游：
  {"error":{"type":"server_error","message":"Upstream request failed: Model is unavailable."}}
  >>> HTTP 400        ← 与 WorkBuddy 里看到的报错一字不差

用真实模型名 deepseek-v4.1-flash：
  >>> HTTP 200        ← 正常
```

**结论：直连这条路是死的（两个坑都躲不过），必须走本地代理。** 代理要同时干两件事：① 注入 session 头 ② 翻译模型名。

---

## 二、已为你完成的配置

`~/.workbuddy/models.json` 中三条已改为走本地代理：

| 显示名称 | url | 状态 |
|---|---|---|
| OpenCode Go · DeepSeek V4.1 Flash (代理) | `http://127.0.0.1:8787/v1` | ✅ 实测通过 |
| OpenCode Go · GPT-6 Luna (代理) | `http://127.0.0.1:8787/v1` | ✅ 实测通过 |
| OpenCode Go · Muse Spark 1.3 Contributor (代理) | `http://127.0.0.1:8787/v1` | ✅ 已放行 |

你原有的 6 个模型完全没动（改前已备份 `models.json.bak-*`）。

三个条目都已经带上了**思考配置**（`onlyReasoning: true` + `reasoning: {...}`），
所以「Deep Thinking」下拉里会出现它们，并且默认就是开启状态。见第五节。

---

## 三、你现在的操作步骤

### 第 1 步：确认没有旧代理在跑 ⚠️

**这一步很关键。** Windows 允许重复绑定同一端口（SO_REUSEADDR），
如果旧代理还开着，新代理会**"假绑定"成功但请求仍被旧代理接走** —— 表现为"改了代码却毫无变化"。

- 关掉之前那个代理窗口
- 或在 CMD 里：`netstat -ano | findstr :8787` 找到 PID，再 `taskkill /PID <pid> /F`

新版代理启动时会**自动探测**，发现端口已被占用会明确报错并退出，不会再静默失效。

### 第 2 步：启动代理

双击 `start_proxy.bat`，**或在 Git Bash 里**：

```bash
cd "D:/ai_person/opencode-go-proxy"
export OPENCODE_API_KEY=oc_sk_你的密钥
"C:/Users/qq940/.workbuddy/binaries/python/versions/3.13.12/python.exe" oc_session_proxy.py
```

看到这个就是成功了（**这个窗口不能关**）：

```
======================================================================
  OpenCode Go  -  Unified Adapter Proxy
======================================================================
  Listen    : http://127.0.0.1:8787
  Upstream  : https://opencode.ai/zen/go/v1
  ...
  [OK] Proxy is running. Waiting for requests...
```

### 第 3 步：重启 WorkBuddy

必须**完全退出**再打开，让它重新加载模型配置。

### 第 4 步：选模型

底部模型选择器 → 自定义模型分组 →

- **`OpenCode Go · DeepSeek V4.1 Flash (代理)`** ← 日常用这个，快、便宜
- **`OpenCode Go · GPT-6 Luna (代理)`** ← 需要更强推理时用，配额紧
- **`OpenCode Go · Muse Spark 1.3 Contributor (代理)`** ← 超低价换数据训练，**先读第七节**

---

## 四、实测证据

### 真实上游

| 测试项 | 结果 |
|---|---|
| 发**错误的**模型名 `opencode-go-deepseek-v4.1-flash` | ✅ 被代理翻译 → `回复: "修好了"` |
| 发正确模型名 `deepseek-v4.1-flash` | ✅ `回复: "正常"` |
| 流式 SSE（DeepSeek） | ✅ 标准 chunk（含 reasoning_content 增量） |
| **工具调用**（DeepSeek） | ✅ 返回 `tool_calls`，`get_weather({"city":"北京"})` |
| Luna 非流式 / 流式 | ✅ `回复: "收到"` / Responses → SSE 回放正常 |
| Muse 模型名翻译 | ✅ 上游报**隐私错误**而非 `Model is unavailable` → 证明名字译对了 |
| 模型翻译单测 `test_resolve.py` | ✅ **25/25** 通过 |

代理日志实例：

```
[oc-proxy] model-in='opencode-go-deepseek-v4.1-flash'      -> upstream='deepseek-v4.1-flash'      protocol=chat
[oc-proxy] model-in='opencode-go-gpt-6-luna'               -> upstream='gpt-6-luna'               protocol=responses
[oc-proxy] model-in='opencode-go-muse-spark-1.3-contributor' -> upstream='muse-spark-1.3-contributor' protocol=responses
```

### mock 上游验证（`test_muse_protocol.py`）

因为 Muse 被账户隐私开关挡着，无法端到端跑通，**改用 mock 上游记录代理实际打出的路径**：

| 输入模型 | 上游实际收到 | 结果 |
|---|---|---|
| `opencode-go-muse-spark-1.3-contributor` | `POST /v1/responses` | ✅ |
| `muse`（只写系列名） | `POST /v1/responses` | ✅ |
| `opencode-go-gpt-6-luna`（回归） | `POST /v1/responses` | ✅ |
| `opencode-go-deepseek-v4.1-flash`（回归） | `POST /v1/chat/completions` | ✅ |
| `qwen3.8-max`（Anthropic 协议） | **不打上游**，直接 501 | ✅ |
| session 头注入 | 4/4 请求均带 `x-opencode-session` | ✅ |

---

## 五、思考（Deep Thinking）为什么之前没开 —— 已修复

三个模型的思考现在都通了。原因有**两层**，一层在 models.json 的配置，一层在代理。

### 5.1 第一层：models.json 缺字段（WorkBuddy 侧）

WorkBuddy 判断"这个模型要不要思考"的逻辑（从打包产物 `codebuddy-lite-wb.mjs` 里读出来的）：

```js
// configureThinkingSettings()
if (!modelInfo.supportsReasoning) { 删除 reasoning; return }
let on     = (会话override ?? 全局alwaysThinkingEnabled ?? false) || 有token预算;
let effort = 会话overrideEffort ?? 全局reasoningEffort
             ?? cfg.reasoning?.defaultEffort ?? cfg.reasoning?.effort;
if (effort) { reasoning.effort = ...; reasoning.summary ||= cfg.reasoning?.summary ?? "auto" }

// canDisableThinking()
return !cfg.onlyReasoning && cfg.reasoning?.canDisableThinking !== false;
```

**只写 `supportsReasoning: true` 是不够的。** 内置推理模型（`product.json` 实测）写的是：

```json
"supportsReasoning": true,
"onlyReasoning": true,
"reasoning": { "effort": "high", "summary": "auto" }
```

而我们原来的条目只有 `supportsReasoning: true`，于是：

1. 没有 `cfg.reasoning` → 请求里**根本不会附加任何 reasoning 参数**
2. 没有 `onlyReasoning` → `canDisableThinking` 返回 true → 模型被判定为"思考可以关"
   → 一旦会话里存在"关闭思考"的覆盖，`reconcileThinkingOverrideAfterModelChange`
     就**不会**把它重置回开启（而内置推理模型会被重置）

### 决定性证据（WorkBuddy 日志原话）

```
[ModelConfig] Thinking explicitly disabled (session/global override)
[ModelConfig] resolved model=custom-local:opencode-go-deepseek-v4.1-flash for agent=cli
```

每次解析到 opencode 模型，上一行必然是 `Thinking explicitly disabled`；
而内置的 `hy4-preview` 走的是 `Extended thinking enabled`。8 次对 8 次，一一对应。

**已修**：`enable_thinking.py` 给三个条目补上
`onlyReasoning: true` + `reasoning: {defaultEffort, effort, summary, supportedEfforts, canDisableThinking}`。

### 5.2 第二层：代理把推理摘要吃了（OpenCode Go 侧）

两类模型各有各的毛病，而且都是代理的锅：

| 模型 | 原来发生了什么 |
|---|---|
| DeepSeek（chat 协议） | 上游本来就返回 `reasoning_content`，**代理透传没问题**，不显示纯粹是第一层的配置问题 |
| Luna / Muse（responses 协议） | 代理**两处都错**：① `chat_to_responses` 没把 `reasoning` 参数传给 `/responses`；② `extract_text()` 只挑 `output_text`，把 `type:"reasoning"` 的块整个扔掉 |

**还有一个上游的坑**：`/responses` 的 `reasoning.summary` 传 `auto` / `detailed` 时，
返回的 summary 是**空数组**（真实内容只在 `encrypted_content` 里，加密的、解不开）；
**只有传 `concise` 才会真的返回可读摘要文本**。

```
reasoning: {"summary": "auto"}      -> summary: []                             ❌
reasoning: {"summary": "detailed"}  -> summary: []                             ❌
reasoning: {"summary": "concise"}   -> [{"type":"summary_text","text":"..."}]  ✅
```

**已修**（代理 v1.3）：
- `chat_to_responses` 转发 reasoning，并把 `auto` / `detailed` 自动收敛成 `concise`
- 新增 `extract_reasoning()`，把 `output[].summary[].text` 抽出来放进 `message.reasoning_content`
- 流式改为**真正的 SSE 翻译**（原来是"先非流式拉完、再假装流式吐出来"）：
  - `response.reasoning_summary_text.delta` → `delta.reasoning_content`
  - `response.output_text.delta` → `delta.content`

### 5.3 实测结果（真实上游）

```
Luna 非流式  reasoning_content = "**Answering in Chinese**\n\nI'll provide a simple sentence..."
Luna 流式    delta.reasoning_content = "**Comparing decimal values**"  + 正文增量
DeepSeek     带 reasoning + reasoning_summary 的完整请求体也不报错，reasoning_content 正常
mock 端到端  test_reasoning.py 18/18 通过
```

`test_reasoning.py` 覆盖：参数翻译、summary 收敛、摘要抽取、mock 上游的流式思考转发。

### 5.4 想调整思考行为

| 想做什么 | 改哪里 |
|---|---|
| 恢复「Off」选项（允许关闭思考） | models.json 条目去掉 `onlyReasoning`，并把 `reasoning.canDisableThinking` 设为 `true` |
| 限制可选思考档位 | 改 `reasoning.supportedEfforts`，例如 `["low","high"]` |
| 改默认档位 | 改 `reasoning.defaultEffort` / `reasoning.effort`（当前均为 `medium`） |
| 换代理侧摘要级别 | 启动前设环境变量 `REASONING_SUMMARY=concise`（置空则关闭） |
| 换代理侧推理强度 | 启动前设环境变量 `REASONING_EFFORT=medium`（当前默认值） |

> 改了 `models.json` 必须**重启 WorkBuddy** 才生效；改了代理脚本则要**重启代理**。两个都改就两个都重启。

---

## 六、代理是怎么工作的

```
WorkBuddy ──POST /v1/chat/completions──▶ 本地代理 :8787
                                          │
                                          ├─ 1. 翻译模型名（本地 id → 上游真名）
                                          ├─ 2. 注入 x-opencode-session 头
                                          └─ 3. 按协议分流
                                               ├─ chat 模型（deepseek/glm/kimi…）
                                               │    → 原样透传 /chat/completions
                                               ├─ responses 模型（luna/grok/muse）
                                               │    → 翻译成 Responses 协议
                                               │    → POST /responses → 回译成 chat 结构
                                               └─ anthropic 模型（qwen/minimax）
                                                    → 翻译成 Messages 协议
                                                    → POST /messages → 回译成 chat 结构

三种协议都做**工具调用（function calling）**双向翻译：
  请求：tools / tool_choice / 历史里的 tool_calls 与 tool 结果
  响应：function_call 或 tool_use  →  chat 的 tool_calls（含流式增量）
```

**模型名翻译规则**（`resolve_model()`）：

| 收到 | 翻译成 | 协议 |
|---|---|---|
| 上游真名作为**子串**出现（如 `opencode-go-gpt-6-luna`） | 该真名（长的优先匹配） | 按真名定 |
| 只写 `luna` | `LUNA_DEFAULT`（默认 `gpt-6-luna`） | responses |
| 只写 `grok` | `grok-4.7` | responses |
| 只写 `muse` | `MUSE_DEFAULT`（默认 `muse-spark-1.3-contributor`） | responses |
| 只写 `qwen` | `qwen3.8-flash` | anthropic |
| 只写 `minimax` | `minimax-m3` | anthropic |
| Qwen / MiniMax 系列（含真名） | 原样 | **anthropic ✅（v1.4 起已支持）** |
| 其他（含认不出的本地 id / 显示名） | `deepseek-v4.1-flash` | chat |

**两个要点：**
- 第 1 条用**子串匹配 + 长度降序**，所以本地 id 带前缀（`opencode-go-`）也能认出来；
  长度降序是为了避免 `mimo-v2.5` 抢先命中 `mimo-v2.5-pro`。
- 最后一条兜底规则保证**不管 WorkBuddy 发的是 `id` 还是 `name`，都能落到正确模型上。**

### 怎么在 gpt-5.6-luna / gpt-6-luna 之间切换

三种方式，任选其一：

1. **改配置条目**：把 `models.json` 里 Luna 条目的 `id` 写成目标型号
   （`opencode-go-gpt-6-luna` / `opencode-go-gpt-5.6-luna`），代理按子串自动识别。
2. **只写 `luna`**：`id` 里不带版本号时，走 `LUNA_DEFAULT`（现为 `gpt-6-luna`）。
3. **环境变量**：启动代理前 `set LUNA_DEFAULT=gpt-5.6-luna` 临时改默认。

> 本机当前：条目 `OpenCode Go · GPT-6 Luna (代理)`，`id=opencode-go-gpt-6-luna`。

### OpenCode Go 的协议分布

| 协议 | 端点 | 模型 | 代理支持 |
|---|---|---|---|
| Chat Completions | `/chat/completions` | DeepSeek 全系、GLM、Kimi、MiMo、Hy、LongCat、Space Bunny | ✅ 透传（工具调用原生支持） |
| Responses | `/responses` | GPT Luna、Grok、**Muse Spark 1.2/1.3 Contributor** | ✅ 翻译（含工具调用） |
| Anthropic | `/messages` | MiniMax、Qwen | ✅ 翻译（含工具调用，v1.4 起） |

> ⚠️ **注意**：`Muse Spark` 早期版本曾被误归到 chat 组（因为隐私错误挡住了协议校验，掩盖了分类错误）。
> 官方文档确认它走 `/responses`，本版已修正。若你用的是 v1.1 及更早的代理，Muse 会走错协议。

> ✅ **Qwen / MiniMax 需要额外鉴权头**：上游的 `/messages` 只认 Anthropic 风格的 **`x-api-key`**，
> 光带 `Authorization: Bearer` 会返回 `401 {"type":"AuthError","message":"Missing API key."}`。
> 代理已自动补上 `x-api-key` 与 `anthropic-version`，你不用管。

---

## 七、Muse Spark 1.3 Contributor：已放行 ✅

### 当前状态（2026-10-01 实测）

直连 `https://opencode.ai/zen/go/v1/responses` 返回 **HTTP 200**，
`usage.output_tokens_details.reasoning_tokens` 有值，思考正常。
**不需要再做任何开关操作。**

> 早期这里卡着 `400 Upstream request failed: This Go model trains on request data.`
> 现在对当前这个 key 已经不报。原报错全文留着，方便以后对照：
>
> ```
> {"error":{"type":"server_error","message":"Upstream request failed: This Go model
>  trains on request data. Allow paid endpoints that train on request data in your
>  workspace's Privacy settings to use it."}}
> ```

### 如果哪天又冒出这个 400，开关在这里

1. 登录 https://opencode.ai → 进入 **Console / 工作区设置**
2. 找 **Privacy（隐私设置）** 区域
3. 打开 **「Allow models that train on request data」**（允许使用请求数据训练的模型）
4. 保存后等 1–2 分钟，再跑下面的 `verify_muse.py` 确认

> 备选入口：装了 OpenCode 客户端的话，也可以在 **Settings → Providers（提供商）**
> 区域找同名开关（与「启用部署在中国的模型」相邻）。
> 社区两种说法都有，别争菜单文字 —— **跑 `verify_muse.py` 最准**。

### 怎么验证（一键）

```bash
cd D:/ai_person/opencode-go-proxy
PYTHONUTF8=1 "C:/Users/qq940/.workbuddy/binaries/python/versions/3.13.12/python.exe" verify_muse.py
```

脚本直连上游发一个最小请求，然后给出分类结论：

| 结论 | 含义 |
|---|---|
| `[OK] 已放行` | 开关生效，能用 |
| `[PRIVACY]` | 上游仍要求开训练授权 → 见上一节 |
| `[REGION]` | 卡在 Meta 地域限制，设置里解决不了 |
| `[KEY]` / `[QUOTA]` | key 失效 / 余额不足 |

它还会回显上游接受的思考档位（`reasoning.effort`），可确认 `medium` 是否生效。

### 两个必须知道的限制

| 项 | 说明 |
|---|---|
| **数据用于训练** | 官方 Privacy 表：Muse Spark 1.3 / 1.2 Contributor = `Model training: Yes`、`Retention: Not ZDR`。**Go 里唯一会拿你数据训练的模型。** |
| **地域限制** | 官方原文 "Availability is limited to regions permitted by Meta's Geographic Use Policy"。当前实测可通，但这是账户/地区相关的，换环境未必。 |

### 规格（来自 OpenCode Go 定价页）

| 项 | 值 |
|---|---|
| 上下文 | **1M tokens** |
| 最大输出 | 32000（保守值） |
| 多模态 | Image / Video / Audio / Docs |
| 价格 | 输入 $0.1 / 输出 $0.2 per 1M（Go 里属 $60·6× 档） |

**建议**：涉及代码机密、客户数据的活儿别放这个模型上。它的机制就是"用隐私换便宜"。

---

## 八、文件清单

| 文件 | 作用 |
|---|---|
| `oc_session_proxy.py` | ⭐ **当前方案（v1.4）**：注入 session 头 + 模型名翻译 + 三协议分流 + 工具调用翻译 |
| `start_proxy.bat` | Windows 双击启动（ASCII + CRLF，已修乱码） |
| `start_proxy.sh` | Git Bash 启动（双击 bat 不行时用这个） |
| `add_anthropic_models.py` | ⭐ **把 Qwen / MiniMax 条目写进两个客户端**（幂等 + 备份 + 原子写，默认预演） |
| `test_tools_anthropic.py` | ⭐ **v1.4 主测试**：工具调用 + Anthropic 协议（纯函数 + mock 上游端到端，40+ 断言） |
| `test_live_tool_calling.py` | ⭐ **真实上游**端到端：三种协议的工具调用 + 两轮工具闭环 |
| `add_muse.py` | 追加/更新 Muse Spark 1.3 条目（幂等 + 备份 + 原子写入） |
| `test_muse_protocol.py` | **mock 上游**验证协议路由（muse/luna→`/responses`、anthropic→`/messages`） |
| `switch_to_proxy.py` | 把 models.json 改走代理的脚本 |
| `switch_luna_to_6.py` | 把 Luna 条目从 gpt-5.6-luna 切到 gpt-6-luna（幂等 + 备份） |
| `enable_thinking.py` | ⭐ **给模型条目补 reasoning 配置**（幂等 + 备份），开启思考用 |
| `add_models.py` | 最初写入条目的脚本（已被 switch 取代） |
| `test_reasoning.py` | 思考链路测试（单测 + mock 上游端到端） |
| `verify_muse.py` | ⭐ **直连上游验证 Muse 是否放行**（含思考档位回显），开完隐私开关后跑它 |
| `test_resolve.py` | 模型名翻译逻辑单测（无需网络，25 例） |
| `probe_tools_anthropic.py` | 诊断：一次性摸清 `/messages` 与工具调用的真实协议形状 |
| `probe_ua.py` | 诊断：证明 **403/1010 是 UA 被 Cloudflare 封**（不是 key 失效） |
| `probe_auth_tools.py` | 诊断：定位 `/messages` 需要 `x-api-key` + 取回 `function_call` 完整结构 |
| `probe_stream_tools.py` | 诊断：抓工具调用的流式事件名 |
| `probe_fc_raw.py` | 诊断：打印 `function_call` 事件的完整 JSON（确认 `call_id` 出现时机） |
| `probe_reasoning.py` | 诊断脚本：对比两个上游网关返回的推理字段名 |
| `scan_modelconfig_log.py` | 诊断脚本：按时间序抽取 WorkBuddy 的 `[ModelConfig]` 日志 |
| `find_reasoning_field.py` / `find_thinking_toggle.py` / `dump_thinking_logic.py` / `find_custom_model_schema.py` / `find_settings_default.py` | 诊断脚本：在 WorkBuddy 打包产物里检索思考相关逻辑 |
| `_catalog.txt` | OpenCode Go 模型目录快照（30 个） |
| `luna_proxy.py` | 早期 Luna 专用协议翻译代理（功能已并入主代理） |
| `test_e2e.py` | 协议翻译代理的端到端测试 |
| `配置完成-README.md` | 本文件 |

> `probe_*.py` 是**一次性取证脚本**（跑一次拿到协议形状就够了），留着当文档看；
> 嫌乱可以直接删，不影响代理运行。

---

## 九、安全提醒 🔴

**你的 API Key 已在聊天中明文暴露多次，务必去 OpenCode Console 吊销重发。**

换新 key 后：改 `start_proxy.bat` 里的 key，或用 `export OPENCODE_API_KEY=...` 启动。

models.json 里的 key 是占位符 `local-proxy`，**真正的 key 只在代理进程内**。

---

## 十、排错

| 现象 | 原因 | 处理 |
|---|---|---|
| **模型只会"说"要调工具，但不真的调** | 代理是 v1.3 及更早（没翻译 tools / function_call） | 升级到 v1.4 并**重启代理** |
| **Qwen / MiniMax 报 501 protocol_not_supported** | 代理是 v1.3 及更早 | 升级到 v1.4 并重启；外加 `add_anthropic_models.py --apply` 写条目 |
| **403 `error code: 1010`** | 请求的 User-Agent 被 Cloudflare 判为脚本（默认 `Python-urllib` 必封） | 用浏览器 UA；**别改掉代理自带的 UA**，或 `PROXY_USER_AGENT=xxx` 覆盖 |
| `/messages` 返回 `401 Missing API key.` | 只带了 `Authorization`，没带 Anthropic 的 `x-api-key` | 代理 v1.4 已自动补；直连探测时要自己加 |
| **工具有 tool_calls 但客户端不执行** | 客户端该条目的 `supportsToolCall` 不为 true | 用 `add_anthropic_models.py --apply` 重新写入条目 |
| `400 ... trains on request data` | **Muse 的账户级隐私开关没开** | 见第七节，去 OpenCode 控制台开启 |
| **不显示思考 / 没有思考块** | models.json 缺 `reasoning` 配置，或代理是 v1.2 及更早 | 跑 `enable_thinking.py` + 重启 WorkBuddy；代理升到 v1.3+ 并重启 |
| 思考摘要为空 | `/responses` 的 summary 传了 `auto`/`detailed` | 代理 v1.3 已自动收敛为 `concise`；也可设 `REASONING_SUMMARY=concise` |
| 回答为空 / 只有思考没正文 | `max_tokens` 太小被 thinking 吃掉（Qwen 尤其明显） | 调大到 ≥1500；Anthropic 协议可用 `ANTHROPIC_MAX_TOKENS` 兜底 |
| `400 Model is unavailable` | 代理没做模型名翻译（旧版代理） | 用新版 `oc_session_proxy.py`，并确认旧代理已关 |
| `400 MissingSessionID` | 直连了，没走代理 | 确认 url 是 `http://127.0.0.1:8787/v1` |
| 改了代码但行为没变 | **Windows 端口复用，旧代理仍占着 8787** | 关掉旧窗口 / `taskkill`，再重启 |
| 连接被拒绝 / ECONNREFUSED | 代理没启动 | 双击 `start_proxy.bat`，或 `bash start_proxy.sh` |
| 窗口乱码 / 启动不起来 | bat 曾用 LF 换行 + 中文 | **已修**：ASCII + CRLF |
| 模型列表看不到 | WorkBuddy 没重启 | 完全退出重开 |
| 401 Invalid API key | key 错/已吊销 | 检查 key |
| 端口 8787 被占用 | 已有代理在跑 | 关掉旧的，或改 `LUNA_PROXY_PORT` |

### 关于"乱码"的说明（已修复）

1. **bat 文件曾是 LF 换行** —— Windows 批处理**必须用 CRLF**。Unix 换行会让 cmd.exe 把多行读串。
   → 已转 CRLF（43 处，0 处残留 LF）。
2. **中文输出 + 控制台编码不匹配** —— 启动横幅原为中文，控制台若是 GBK(936) 就乱码。
   → 代理**所有控制台输出改为英文 ASCII**。

**验证**：`start_proxy.bat` 现为纯 ASCII、无 BOM、全 CRLF。


---

## 十、CodeBuddy 也接上了同一套代理

### 两个客户端的配置差异（实测，别想当然）

| 项 | WorkBuddy | CodeBuddy |
|---|---|---|
| 配置文件 | `~/.workbuddy/models.json` | `~/.codebuddy/models.json` |
| 顶层结构 | **数组** `[{...}]` | **对象** `{"models": [{...}]}` |
| `url` 写法 | 只填到 `/v1`（客户端自己拼 `/chat/completions`） | **必须写完整路径**，以 `/chat/completions` 结尾 |
| 改完生效 | 要**重启客户端** | **热重载**（1 秒防抖，保存即生效） |
| 思考字段 | `supportsReasoning` + `onlyReasoning` + `reasoning{...}` | **完全相同**（同一份打包代码） |

> CodeBuddy 的思考逻辑与 WorkBuddy 同源：`canDisableThinking()`、
> `configureThinkingSettings()`、`reconcileThinkingOverrideAfterModelChange()`
> 在两边代码里逐字一致，所以思考配置可以直接照搬。
> 官方文档：`<codebuddy包>/dist/web-ui/docs/cn/cli/models.md`。

### CodeBuddy 里已写入的模型

| 显示名 | id | 上游模型（协议） |
|---|---|---|
| OpenCode Go · DeepSeek V4.1 Flash (代理) | `opencode-go-deepseek-v4.1-flash` | `deepseek-v4.1-flash`（chat） |
| OpenCode Go · GPT-6 Luna (代理) | `opencode-go-gpt-6-luna` | `gpt-6-luna`（responses） |
| OpenCode Go · Muse Spark 1.3 Contributor (代理) | `opencode-go-muse-spark-1.3-contributor` | `muse-spark-1.3-contributor`（responses） |

三个都指向 `http://127.0.0.1:8787/v1/chat/completions`，
`apiKey` 填占位符 `local-proxy`（真正的 key 由代理从环境变量注入）。

顺带移除了一个**坏条目**：原来的 `deepseek-v4.1-flash` 直连 `opencode.ai`，
缺 `x-opencode-session` 头，必然 400 —— 已删除，改走代理。

另外给 `qwen3.8-max` / `qwen3.8-flash` / `mimo-v2.6-pro` 补了 `reasoning` 配置
（它们原来只有 `supportsReasoning: true`，在 CodeBuddy 里同样不会真正开思考）。

### 写入 / 校验脚本

```bash
cd D:/ai_person/opencode-go-proxy
PY="C:/Users/qq940/.workbuddy/binaries/python/versions/3.13.12/python.exe"

# 幂等写入三个模型（自动备份 + 原子写入）
PYTHONUTF8=1 "$PY" add_codebuddy_models.py

# 给已有模型补思考配置（先预演，再 --apply 真写）
PYTHONUTF8=1 "$PY" enable_thinking_cb.py
PYTHONUTF8=1 "$PY" enable_thinking_cb.py --apply

# 端到端验证：模拟 CodeBuddy 的请求打代理（支持流式）
PYTHONUTF8=1 "$PY" test_via_proxy.py
STREAM=1 PYTHONUTF8=1 "$PY" test_via_proxy.py
```

### 实测结果（2026-10-01）

三个模型经代理全部 **HTTP 200**，正文与思考都正常：

| 模型 | 非流式 | 流式 reasoning 事件数 |
|---|---|---|
| deepseek-v4.1-flash | content + reasoning_content 有 | 6 |
| gpt-6-luna | content + reasoning_content 有 | 1 |
| muse-spark-1.3-contributor | content 有；思考**按需触发** | 0（简单问题） |

> **Muse 的思考是"按需"的**：问"只回复收到"它不思考（`reasoning_content` 为空），
> 换成需要推理的问题（"9.9 和 9.11 哪个大"）就有 **301 字**思考文本。
> 这不是配置问题，是模型自己的行为，别再当 bug 查。

### 顺带发现：另外两个模型余额不足

`qwen3.8-max` / `qwen3.8-flash` 指向的 `tokenrhythm.studio` 返回：

```
HTTP 402 {"code":"INSUFFICIENT_BALANCE","message":"余额不足"}
```

与本次配置无关，是**该服务账户余额用尽**，充值前这两个模型都用不了。
`mimo-v2.6-pro`（xiaomimimo.com）实测 200 正常，且容忍 `reasoning` 参数。

> 📌 **2026-10-05 补充**：上面那个 402 说的是当时**直连 `tokenrhythm.studio`** 的旧条目。
> 现在这两个模型改从 **OpenCode Go 的 `/messages`** 走，实测 **HTTP 200 正常**（见第十一节）。

---

## 十一、v1.4：补齐工具调用 + 支持 Anthropic 协议（2026-10-05）

### 11.1 问题一：Responses 模型不会调用工具

**现象**：Luna / Grok / Muse 这类走 `/responses` 的模型，让它"查天气"它只会用文字说
"我来帮您查询"，然后编一个结果 —— 从来不真的发 `tool_calls`。

**真因**：代理 v1.3 的 Responses 翻译**只处理了文本**，工具相关三处全漏：

| 环节 | v1.3 的行为 | 后果 |
|---|---|---|
| 请求 | `chat_to_responses()` 不翻译 `tools` / `tool_choice` | 上游根本不知道有工具可用 |
| 请求 | 历史里的 `assistant.tool_calls`、`role="tool"` 结果被丢弃 | 多轮工具对话断链 |
| 响应 | `extract_text()` 只挑 `output_text`，`function_call` 块被扔掉 | 就算上游想调工具，客户端也收不到 |

**决定性的协议差异**（实测取证）：

```
chat 协议:        {"type":"function","function":{"name":...,"parameters":{...}}}
Responses 协议:   {"type":"function","name":...,"parameters":{...}}      ← 平铺，不嵌套
Anthropic 协议:   {"name":...,"input_schema":{...}}                      ← 参数键还改名
```

上游返回的工具调用长这样（真实抓包）：

```json
{"id":"fc_06058ec13d177d8d...","type":"function_call","status":"completed",
 "name":"get_weather","call_id":"call_nLKysyCdTK5RMfHTlJ1ZEykZ",
 "arguments":"{\"city\":\"广州\"}"}
```

**已修**：新增 `tools_to_responses()` / `extract_tool_calls()`，
`chat_to_responses()` 补上历史工具消息翻译，流式补上三个事件：

| 上游 SSE 事件 | 翻译成 chat chunk |
|---|---|
| `response.output_item.added`（item.type=function_call） | `delta.tool_calls[].{id,name}`（`call_id` **在这里就有**） |
| `response.function_call_arguments.delta` | `delta.tool_calls[].function.arguments` 增量 |
| `response.output_item.done` | 兜底：万一没发 `added`，这里补完整调用 |

有工具调用时 `finish_reason` 必须是 **`tool_calls`** 而不是 `stop`，否则客户端会把它当最终答案。

### 11.2 问题二：不支持 Anthropic 协议

**现象**：`qwen3.8-max` / `minimax-m3` 一用就报
`501 protocol_not_supported`。

**真因**：这些模型走 `/messages`（Anthropic Messages API），代理压根没实现，
直接返回 501 让用户换模型。

**已修**：新增完整的 `/messages` 双向翻译，含工具调用与思考：

| chat 侧 | Anthropic 侧 |
|---|---|
| `system` 消息 | 顶层 `system` 字段（不进 messages） |
| `tools[].function.parameters` | `tools[].input_schema` |
| `tool_choice: "required"` | `{"type":"any"}`（Anthropic 没有 `none`，退化 auto） |
| `assistant.tool_calls` | `tool_use` 内容块（`arguments` 反序列化成 `input`） |
| `role="tool"` | `user` 消息里的 `tool_result` 块 |
| 返回 `tool_use` 块 / `stop_reason:"tool_use"` | `message.tool_calls` / `finish_reason:"tool_calls"` |
| 返回 `thinking` 块 | `message.reasoning_content` |
| 流式 `content_block_start` / `content_block_delta` | `delta.content` / `delta.reasoning_content` / `delta.tool_calls` |

**两个 Anthropic 协议特有的坑（都已处理）**：

1. **`max_tokens` 是必填的**。chat 请求不给的话，用 `ANTHROPIC_MAX_TOKENS`（默认 4096）兜底。
   > 顺带一提：`max_tokens` 给小了（如 32）会被 thinking 吃干净，**正文一个字都不剩** ——
   > Qwen 实测就是这样，返回的 content 里只有 `thinking` 块。这看着像 bug，其实是 token 不够。
2. **`user` / `assistant` 必须严格交替**。代理会把连续同角色的消息**合并**，
   并在首条不是 `user` 时补一条，免得上游直接报错。

### 11.3 顺带挖出的坑：Cloudflare 按 UA 封禁（很隐蔽）

排查时发现**任何直连探测脚本都会莫名 403**：

```
>>> HTTP 403
<<< error code: 1010
```

`1010` 是 Cloudflare 的"浏览器指纹封禁"，**跟 key 没关系**。对照实验：

| 请求用的 User-Agent | 结果 |
|---|---|
| 不设（urllib 默认 `Python-urllib/3.13`） | ❌ **403 / 1010** |
| `workbuddy-oc-proxy/1.3`（代理自带的） | ✅ 200 |
| 伪装 Chrome | ✅ 200 |

**所以**：
- 代理之所以一直没事，纯粹因为它**自带了一个 UA**。这个 UA 千万别删。
- 你要是手写脚本直连上游，**必须设 UA**，否则会误判成"key 失效"或"模型不可用"。
- 想换：`set PROXY_USER_AGENT=你的UA`。

### 11.4 实测证据（2026-10-05，真实上游）

`test_live_tool_calling.py` 全绿：

| 场景 | 结果 |
|---|---|
| Luna 非流式工具调用 | ✅ `get_weather({"city":"北京"})`，`finish_reason=tool_calls` |
| Luna 流式工具调用 | ✅ 参数逐片拼回合法 JSON |
| **两轮完整闭环** | ✅ 要工具 → 回灌 `{"temp_c":25,"weather":"晴"}` → 最终答 **"北京现在晴，气温约 25°C。"** |
| MiniMax M3 非流式 / 流式 | ✅ `{"city":"广州"}` / `{"city":"深圳"}` |
| Qwen3.8 Flash 非流式 / 流式 | ✅ `{"city":"广州"}` / `{"city":"深圳"}` |

`test_tools_anthropic.py`（mock 上游）40+ 断言全过；
既有回归 `test_resolve.py` 25/25、`test_reasoning.py`、`test_muse_protocol.py` 全过。

### 11.5 你要做的两件事

```bash
cd D:/ai_person/opencode-go-proxy
PY="C:/Users/qq940/.workbuddy/binaries/python/versions/3.13.12/python.exe"

# ① 把 Qwen / MiniMax 条目写进两个客户端（已执行过，幂等可重跑）
PYTHONUTF8=1 "$PY" add_anthropic_models.py            # 预演
PYTHONUTF8=1 "$PY" add_anthropic_models.py --apply    # 真写

# ② 自测（可选）
PYTHONUTF8=1 "$PY" test_tools_anthropic.py
OPENCODE_API_KEY=oc_sk_xxx PYTHONUTF8=1 "$PY" test_live_tool_calling.py
```

然后：
1. **关掉旧代理窗口**（它还占着 8787、跑的是 v1.3），重新双击 `start_proxy.bat`
2. **完全退出并重开 WorkBuddy**（加载新条目）

新模型在**自定义模型分组**里：
`OpenCode Go · Qwen3.8 Flash (代理)` / `OpenCode Go · Qwen3.8 Max (代理)` / `OpenCode Go · MiniMax M3 (代理)`

### 11.6 环境变量速查（v1.4 新增）

| 变量 | 默认 | 作用 |
|---|---|---|
| `PROXY_USER_AGENT` | `workbuddy-oc-proxy/1.4` | 发往上游的 UA。**别设成 Python 默认值**，会被 Cloudflare 封 |
| `ANTHROPIC_VERSION` | `2023-06-01` | `/messages` 的 `anthropic-version` 头 |
| `ANTHROPIC_MAX_TOKENS` | `4096` | 客户端没给 `max_tokens` 时的兜底（Anthropic 必填） |
| `REASONING_SUMMARY` | `concise` | Responses 侧思考摘要档位（置空关闭） |
| `REASONING_EFFORT` | `medium` | Responses 侧推理强度 |
