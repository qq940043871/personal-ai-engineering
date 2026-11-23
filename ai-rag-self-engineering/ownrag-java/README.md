# ownrag-java

Python 版 [ownrag](../ownrag)（Self RAG）的 **Java 平移**：JDK 1.8 + Spring Boot 2.7.18，重点移植**文档解析三链路**（MinerU PDF / ffmpeg+ASR 音视频 / Excel）。无 Spring AI（需 Boot 3 + JDK 17），延续 Python 版「无模型 SDK、全部手写 HTTP 薄客户端」的口径，只用 OkHttp + Jackson。

## 快速开始

```bash
# 密钥：复制 .env.example → .env 填 key（.env 已 gitignore；restart 脚本启动前自动注入，
# 已存在的真实环境变量优先，不被覆盖）

# 一键重启（停旧实例 → 打包 → 注入 .env → 后台启动 → 等 /health → 打印关键启动日志）
# Windows：双击 restart.bat，或 .\restart.ps1；-NoBuild 只重启不打包，-WithTests 先跑测试
.\restart.ps1

# 编译 + 全量测试（162 例）
mvn test

# 启动（端口 8420；环境变量优先级 > classpath configs/*.yaml）
mvn spring-boot:run
```

当前档位（`src/main/resources/configs/models.yaml`，换模型只改这一个文件）：

| 用途 | 供应商 | 端点 | 模型 |
|---|---|---|---|
| 生成 | agnes（OpenAI 兼容） | `https://apihub.agnes-ai.com/v1` | `agnes-3.0-flash`（512k 输入 / 64k 输出） |
| Embedding | SiliconFlow | `https://api.siliconflow.cn/v1` | `BAAI/bge-m3`（1024 维 / 8192 token 上下文；`bge-large-zh-v1.5` 只有 512 token，长块会 400） |
| Rerank | SiliconFlow | `https://api.siliconflow.cn/v1` | `BAAI/bge-reranker-v2-m3` |
| ASR | SiliconFlow | `https://api.siliconflow.cn/v1` | `FunAudioLLM/SenseVoiceSmall` |

密钥变量：`OWNRAG_CHAT_API_KEY` / `OWNRAG_EMBED_API_KEY` / `OWNRAG_RERANK_API_KEY` / `OWNRAG_ASR_API_KEY`、
`MINERU_OPEN_TOKEN`。不经 restart 脚本启动时（`mvn spring-boot:run`）自己注入，例如 PowerShell：

```powershell
Get-Content .env | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2; [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), 'Process')
}
mvn spring-boot:run
```

**换 embedding 模型 = 必须重建向量**（`embed_version` 变值后检索侧按版本隔离旧向量，
重建前向量通道为空、退化为 BM25 单路）：

```bash
# 原地按 chunks.text 重算向量（不重跑解析/切分），幂等、可 limit 分批续跑
curl -X POST "http://127.0.0.1:8420/admin/kbs/kb_interview/reembed?batch=16"
# 查进度：chunks_by_embed_version
curl "http://127.0.0.1:8420/admin/metrics"
```

打开控制台：<http://127.0.0.1:8420/ui>（Python 版 8 页面 + Java 侧新增「资源 / 对话 / 评测集」共 11 页，API 契约不变）；
登录页 <http://127.0.0.1:8420/ui/login>。

**登录与文档权限**：未登录即可用（只能检索/访问公开文档）；需要看全部文档时去 `/ui/login` 登录。
首次启动会自动创建默认管理员 `admin`，口令取环境变量 `OWNRAG_ADMIN_PASSWORD`（未设置则为 `ownrag`，
启动日志会提示改密）；`OWNRAG_ADMIN_USER` 可改用户名。详见[用户登录与文档权限](#用户登录与文档权限)。

端到端样例：`e2e/e2e_policy.pdf`（差旅政策）、`e2e/e2e_expense.csv`（报销明细）、
`e2e/e2e_rich.pdf`（内嵌图片 + LaTeX 公式）、`e2e/e2e_talk.mp4`（语音 + 时间码，ASR 链路样例）。
样例生成器：`mvn test-compile` 后用 `com.ownrag.tools.E2ePdfGen` / `E2eRichPdfGen`；
语音视频：`powershell -File e2e/gen_speech.ps1` 生成 wav，再 ffmpeg 合成 mp4（见 e2e 目录）。

## UI 渲染能力（Java 版增强）

三处正文均走共享渲染器 `assets/md.js`（零 CDN：KaTeX 已本地内联到 `assets/katex/`，含字体）：

| 能力 | 实现 | 说明 |
|---|---|---|
| Markdown | `Md.render()` | 标题/列表/表格/代码围栏/引用/粗斜体；HTML 先转义再变换 |
| 图片 | `GET /media/{docId}/**` | MinerU 产物里的 `![](images/x.jpg)` 相对引用解析到该端点（白名单防逃逸）；点击放大 |
| 公式 | KaTeX auto-render | `$$..$$` / `$..$` / `\(..\)` / `\[..\]`；先摘出占位保护再排版，避免数学里的 `* _ [ ]` 被 Markdown 吞掉；自动还原 MinerU 的 `\$`/`\_` 转义 |
| 视频/音频 | `GET /source/{docId}` | 返回 Resource 由 Spring MVC 自动处理 **HTTP Range**（拖动进度条可 seek）；块锚点 `anchors.t`（`mm:ss-mm:ss`）→ 播放按钮 → 弹层 `<video src="...#t=start,end">` |

页面改动：`review.html`（**三栏对照**：原文档 / 解析后 / 清洗后 + 切分预览）、`kb.html`（块正文渲染 + 音视频块播放按钮）、
`chat.html`（回答/上下文渲染 + 引用锚点播放）、`retrieve.html`（候选预览渲染）。

## 解析三栏对照（原文档 / 解析后 / 清洗后）

复核页 `/ui/review` 把一条文档的解析链摊成三栏并排，任一处"内容去哪了"都能当场对上账：

| 栏 | 数据来源 | 说明 |
|---|---|---|
| ① 原文档 | `GET /source/{docId}` | PDF 内嵌查看器、图片/音视频直出、md/txt 直读文本；**docx/xlsx 浏览器渲染不了就如实给下载**，不假装能看 |
| ② 解析后 | `data/review/{docId}/parsed.md` | 解析器产出原样，不经任何裁剪（页标记、页码行都还在） |
| ③ 清洗后 | `data/review/{docId}/cleaned.md` | **真正送去切分与入库的正文**（`CleanMarkdown` 产物） |

三栏之间是因果链，不是三份并列的快照：③ 就是 `chunk_markdown` 的输入（同一纯函数 + 同一组参数），
所以"清洗删了什么"与"块里有什么"永远对得上。顶部一行统计写明删了多少：

```
原文 12,340 字 → 清洗后 11,980 字（-2.92%） · 页标记 6 · 页码行 6 · 注释 0 · 空行折叠 41 · 行尾空白 812 · NBSP 3 · 零宽 0
```

清洗规则（`index/CleanMarkdown`，纯函数、幂等、逐条计数）：

| 规则 | 默认 | 说明 |
|---|---|---|
| 换行统一 CRLF→LF | 总是 | 否则行尾判据与空行折叠全部失效 |
| NBSP → 空格；零宽字符/BOM/控制字符删除 | 总是 | NBSP 会让关键词两侧粘连，FTS 与嵌入都吃亏 |
| 页标记 `<!--page:N-->` | `page_markers: drop` | 换成换行而非空串（避免"结论/下一步"粘成一词） |
| 成行的页码（`12` / `- 12 -` / `第 3 页 / 共 20 页` / `Page 3 of 20`） | `page_numbers: true` | **代码围栏内一律不生效**；原生 md/txt、ASR、Excel 卡片链路默认关（裸数字可能就是正文） |
| 其余 HTML 注释 | `comments: true` | 正则显式排除页标记，避免 `page_markers: keep` 被这一步悄悄删掉 |
| 行尾空白、连续 3+ 空行折叠、首尾裁剪 | 总是 / `blank_lines: true` | 只动空白，不动标点、不断行、不合并段落 |

刻意不做：删重复页眉页脚（识别不可靠，误删等于丢正文）、繁简与全半角转换、任何重排。

两处安全阀：清洗把正文洗空时**回退未清洗正文**并在统计里写 `fallback`；移除比例 > 25% 时自动进
复核「提示项」（`clean_removed_lots`），提醒对着 ②③ 两栏确认不是规则误伤。

`clean_markdown` 是独立的管道步骤（排在 `validate_parsed` 之后、`chunk_markdown` 之前），
它只把**统计与归一化后的参数**写进黑板，**不写清洗后全文**——`tasks.state_json` 已经是全表最大的列，
再存一份正文等于把检查点体积翻倍；切分与工件两侧都用同一纯函数现算。

> 老库里的历史文档没有 `cleaned.md`（当时还没有这一步）：③ 栏会显式标注"按旧管道处理，重新上传即可对照"，
> 不拿解析原样冒充清洗结果。

## 文档统计与存疑清单（2026-11-22）

复核页多一张「文档统计」：这份文档**到底解析出了多少东西**，以及**哪些地方不能信**。统计在
`prepare_review` 里算（`review/DocStats`，纯函数），随 `report.json`、`parse_reviews` 表一起落库，
列表页与详情页用的是同一份数字（不用再读 report.json）。

| 指标 | 口径 | 拿不到时 |
|---|---|---|
| 格式 | `metadata.format` > `source_type` > 扩展名 | `unknown` |
| 页数 | **只对 PDF 有意义**：解析器声明页数（MinerU = content_list 最大页号+1，PDFBox = 实际页数）> 正文 `<!--page:N-->` 个数 | docx/xlsx/md/txt/av 显式 `pages=null` + `pages_supported=false`（不按字符数估）；PDF 两处都没有则 `null` + 存疑 `pages_unknown` |
| 文字 | `chars`=Markdown 字符数（含标记）、`text_chars`=去标记/空白后的正文、`chars_clean`=清洗后（切分入库用的就是这份） | — |
| 图片 | 正文 `![]()` 引用数 ∪ structures 里 `image`/`keyframe`，取大者；同时给「引用/结构/产物」三个数交叉核对 | — |
| 公式 | structures 里 `formula`/`equation` ∪ Markdown 公式语法（`$$…$$`、`$…$`、`\(…\)`、`\[…\]`），取大者 | — |
| 表格 | 正文管道表块（**必须带 `\| --- \|` 分隔行**才算表）∪ structures 里 `table`，取大者 | — |
| extra | 非分页格式的替代规模：xlsx 的 sheet 数 / 文本化行数 / 跳过行数、docx 段落数、音视频时长 | — |

存疑清单（`doc_stats.suspects[]`，每条 `{code, level, detail, pages?}`，`level` 只有 `warn`/`info`，
**不参与 verdict、不阻断放行**）：

| code | 含义 | level |
|---|---|---|
| `table_cross_page` | 上一页末尾与下一页开头都是表格行且该页表格 ≥3 行——同一张表被页边界切断 | warn |
| `table_touches_page_break` | 页边界两侧紧贴表格行，但行数太少判不出是跨页还是一张新表 | info |
| `table_split_across_pages` | structures 里相邻两页各登记一张表——疑似同一张跨页表被拆成两张 | warn |
| `table_no_separator` / `table_struct_missing` / `table_body_missing` | 管道表缺分隔行（渲染不成表）/ 正文有表但清单没登记 / 清单有表但正文没写出来 | warn |
| `formula_as_text` / `formula_no_structure` / `formula_not_rendered` | 正文有 LaTeX 命令但统计不到公式 / 有公式语法无清单 / 清单有公式但正文没写出来（Word 的 OMML 常见） | warn / info / warn |
| `image_ref_missing` / `image_unreferenced` | 图引用在产物里找不到（裂图）/ 解析出图但正文没有引用 | warn |
| `page_count_mismatch` / `pages_unknown` / `no_page_marks` | 声明页数≠页标记数 / 页数不可知 / 无页标记（页级与跨页判断不可用） | warn / info / info |
| `page_chars_outlier_high` / `page_chars_outlier_low` | 某页字符数 > 中位数 5 倍（两页被合并）/ < 10%（整页没解析出来） | info / warn |

解析器侧配套：`MineruOpenClient` 的 content_list 现在把 `equation`/`interline_equation` 登记为
`formula` 结构（否则公式数永远是 0）；`ParseDocx` 用 OMML XPath 数公式、把内嵌图片登记为 `image` 结构
（内容仍不索引，但"原件有 N 张图/N 个公式"从此可数、可比对）。

> 历史记录（`doc_stats_json` 为 NULL）在页面上标注"旧管道产物，重新上传即可生成"，**不拿 0 冒充"没有图片/公式"**。

## 首屏性能（本地实测，2026-11-20 优化）

打开任一页面都要先过 `app.js boot()`（`/admin/health` → `/admin/config` → `pageInit()` 取数据），
所以"打开路径后明显停顿"几乎总是这三个接口的问题。优化前后的实测（`data/ownrag.db` 1.0GB、
tasks 4799 行 / `state_json` 合计 734MB）：

| 请求 | 优化前 | 优化后 | 根因 |
|---|---|---|---|
| `/admin/tasks?limit=12` | **9.50s / 538KB** | 0.02s / 2.3KB | `SELECT *` 把 `state_json`（检查点，单行几十 KB）一起取；且 `ORDER BY created_at` 无索引 → SQLite 把整行塞进临时排序器，等于每次翻页读 734MB |
| `/admin/health` | **2.28s**（每 20s 轮询一次） | 0.03s（进程首探 ~1s，之后走缓存） | 探一个没启的本地服务（白等 connectTimeout 2s；该 Ollama 探活分支 2026-11-22 已整体移除）+ 每次跨公网打 `/models` |
| `/admin/metrics` | 0.58s | 0.02s | `GROUP BY status` 全表扫描，同样把 `state_json` 大列读进来 |
| 单页首屏合计 | ≈11.8s | ≈0.1s | 上述三项叠加 |

对应改动（都可回归）：

1. `TaskStore.listTasks` 改成显式列投影（不含 `state_json`），检查点只在 `getTask` / 任务详情里读；
   DDL 补 `idx_tasks_created(created_at DESC, id DESC)` 让 `ORDER BY ... LIMIT n` 走索引直取 n 行。
2. DDL 补 `idx_tasks_status(status)`：`metrics` 的 `GROUP BY status` 变 index-only scan。
3. `/admin/health`：生成后端只有 OpenAI 兼容一种形态（Ollama 探活分支已整体移除），顶部首灯按
   `chat_backend` 显示 **LLM 可用/不可达**，不再出现与当前档位无关的告警；
   远端 chat `/models` 探测为**进程首探同步 + 之后 15s TTL 后台单飞刷新**，请求永远拿缓存立即返回；
   `@PostConstruct` 里预热，重启后第一个页面也不用等。

页面本身与静态资源不是瓶颈（本地均为 3~12ms）：HTML 5~10KB、`app.js` 12KB、`md.js` 14KB、
`katex.min.js` 275KB（仅 review/kb/chat/retrieve 页面需要）。`/ui/assets/**` 设了 `no-store`，
所以 app.js/menu.js 不依赖 `?v=` 破缓存；`md.js` 仍带 `?v=YYYYMMDD`（改它时同步 bump）。

## HTTP 接口一览

端口默认 8420。**文档级权限已内置**（见[用户登录与文档权限](#用户登录与文档权限)）：未登录访客只能检索与访问
`access_level=public` 的文档；需登录文档只有持有效会话的用户可见。控制台配置、任务重试等运维接口未做角色隔离
（个人部署口径），对外暴露前仍应加反代鉴权。

| 方法 | 路径 | 用途 | 关键参数 |
|---|---|---|---|
| POST | `/auth/login` | 登录：校验通过下发 HttpOnly Cookie `ownrag_session`（7 天），失败 401（不区分用户不存在/口令错）、连续失败 429 | body `{username, password}` |
| POST | `/auth/logout` | 登出：删服务端会话行 + 清 Cookie（不只是让浏览器忘掉） | — |
| GET | `/auth/me` | 登录态（未登录也返回 200 + `logged_in:false`，附 `access` 说明） | — |
| POST | `/auth/password` | 自助改密（需登录，校验原口令；旧会话全部失效） | body `{old_password, new_password}` |
| GET/POST/DELETE | `/auth/users`、`/auth/users/{username}` | 账号清单 / 建号或重置口令 / 删号（需登录，写操作限 admin） | body `{username, password, display_name?, role?}` |
| POST | `/chat` | 问答，SSE 流式（事件顺序 `hit?`→`route?`→`gate(access_limited)`→`rewrite`→`gate`→`retrieval?`→`fuse?`→`rerank?`→`ctx`→`prompt?`→`token*`→`done`，异常 `error`，无依据 `no_evidence`） | body `{app, question, top_n?, metadataFilter?, history?, debug?, rewrite?, route?}`；`route = auto\|rag\|sql\|multi`（auto=按规则判定）；`metadataFilter = {sensitivity, topic, date_from, date_to}`；**未登录时服务端强制只检索公开文档**；`debug=true` 才下发带问号的事件（含 `route.detail` 里的 SQL 全文） |
| POST | `/docs/upload` | 上传即建任务；按扩展名选管道（pdf/av/excel/md/txt/docx）；同 SHA-256 且在库 → `status=deduplicated` | multipart `file`、`kb`、`topic`/`sensitivity`/`doc_date`/`origin`、`access_level`（public\|protected；未登录不允许传 protected）；`sensitivity` 白名单 public/internal/restricted |
| POST | `/docs/{docId}/access` | 改文档访问权限（需登录）；改一行即对检索/原件/分块/复核四处同时生效 | body `{access_level: public\|protected}` |
| GET | `/docs/{docId}/status` | 文档任务状态（含当前步骤）；受限文档未登录 403 | — |
| DELETE | `/docs/{docId}` | 删文档：chunks + FTS + 向量 + 文件/块指纹五处一起清（受限文档未登录 403） | — |
| POST | `/docs/tasks/{taskId}/retry` | 任务重试（从检查点续跑，不重跑已完成步骤） | — |
| GET | `/admin/kbs` | 库列表（apps.yaml 声明 ∪ kb_registry ∪ 有数据的库，带文档/块/向量计数） | — |
| POST | `/admin/kbs` | 运行时新建空库（写 `kb_registry`，上传白名单立即生效） | body `{kb, description?}`，kb 限 `[A-Za-z0-9_-]{1,64}` |
| DELETE | `/admin/kbs/{kb}` | 删运行时登记的库（apps.yaml 声明的库、还有文档的库拒删） | — |
| POST | `/admin/kbs/{kb}/purge` | 库级清空（替代易漏表的手工 SQL） | — |
| POST | `/admin/kbs/{kb}/reembed` | 按 `chunks.text` 原地重建向量（换 embed 模型后必做） | `batch`（≤32，默认 16）、`limit`（0=全量） |
| GET | `/admin/kbs/{kb}/documents`、`/admin/documents` | 文档清单（文件名/块数/向量数/任务状态/`access_level`）；**未登录只列公开文档** | `q`、`limit`、`offset` |
| GET | `/admin/documents/{docId}/chunks` | 单文档的块与向量概览（dim/模长/前几维）；受限文档未登录 403 | — |
| GET | `/admin/chunks` | 检索调试：`q` 非空走 FTS5，否则按 kb/docId 翻块；未登录只出公开文档的块 | `kb`、`q`、`docId`、`limit` |
| POST | `/admin/retrieve` | 只跑检索侧全链路（直击→改写→双路→RRF→rerank→预算→闸门一），**不调生成模型**；响应含 `rewrite`/`channels`/`candidates`。`route=true`（或 `?route=1`）切换成**路由回归台**：只跑"判定 + 选表"，不检索不执行 SQL，响应含 `route`/`picked_tables`/`catalog` | body `{app, question, kb?, top_n?, rerank_top_n?, metadataFilter?, rewrite?, route?, force_route?}` |
| GET/POST/DELETE | `/admin/direct_hits` | 直击库增删查（L0/L1/L2 + 别名）；POST 可带 `access_level`（public\|protected，缺省 public），protected 条目未登录不会被命中 | — |
| GET | `/admin/reviews`、`/admin/reviews/{docId}` | 复核队列与详情（详情含 `markdown`/`cleaned` 全文、`original` 原件信息、`report.clean` 清洗统计、`doc_stats` 文档统计与存疑清单）；未登录时队列不列受限文档、详情 403 | `md`、`offset`、`maxChars` |
| POST | `/admin/reviews/{docId}/approve`、`/reject` | 复核放行/驳回（approved 才进 `index_upsert`） | — |
| GET | `/admin/tasks`、`/admin/todos`、`/admin/trace/{traceId}`、`/admin/qa_log` | 任务 / 待办 / 单次追踪 / 问答日志 | `limit` 等 |
| POST | `/admin/todos/{todoId}/resolve` | 处理待办（open → done） | — |
| GET | `/admin/metrics` | 运行计数：任务状态、块数、**按 embed_version 分桶**、待办数 | — |
| GET | `/admin/config` | 回显 `configs/*.yaml`（含 models.yaml 全文，不含 key） | — |
| GET | `/admin/eval-set` | 评测集列表 + KPI（总数/好/坏/待判、来源与库分布）；空表时自动导入直击库题作种子 | `kb`、`source`、`verdict`、`limit` |
| POST | `/admin/eval-set/run` | 跑评测：检索→重排→闸门一（**不调生成模型**），按来源口径判好/坏并把证据落库 | body `{kb?, ids?, top_n?}` |
| POST/DELETE | `/admin/eval-set/cases`、`/cases/{id}`、`/cases/{id}/expect`、`/cases/{id}/verdict` | 增题 / 删题 / 补期望或标应拒答 / 人工改判 | body `{question, kb, expect_all, expect_empty, expect_route, note}`；`expect_route` 取 `rag\|sql\|multi`，留空=不判路由 |
| POST | `/admin/eval-set/import/qa-log` | 问答日志回流：最近 N 条去重问题入评测集（来源标 `qa_log`，可回查 trace） | body `{limit}` |
| POST | `/admin/eval-set/import/golden` | 一键导入黄金集（classpath `eval/golden-set.json`，42 题，按库+题目幂等） | — |
| GET | `/health`、`/admin/health` | 存活 / 后端连通性（chat 探 OpenAI 兼容 `/models`、rerank 启用状态、预算口径） | — |
| GET | `/media/{docId}/**`、`/source/{docId}` | MinerU 图片产物 / 原始音视频（自动支持 HTTP Range）；受限文档未登录 403 | — |
| GET | `/ui`、`/ui/login` | 控制台（11 页面）+ 登录页（独立页面，`?next=` 回跳原页） | — |

> 评测集默认 50 题 = **8 条直击库回归**（空表时 `ensureSeed` 自动导入）+ **42 条黄金题**
> （题库 `src/main/resources/eval/golden-set.json`：6 类题型 + 拒答，期望词已逐条校验确实存在于 `chunks`；
> 页面「导入黄金集」或 `POST /admin/eval-set/import/golden` 可一键重建，幂等不重复）。
> 页面按**题型 / 难度分桶**显示通过率——只看总分会掩盖"事实题全过、跨文档全挂"这类结构性缺陷。

## 用户登录与文档权限

**一句话口径**：登录只决定"能看多少文档"，不改变检索算法——未登录访客照常可用（只看公开文档），
登录后可见全部。权限过滤发生在 **SQL 候选池**，不是 Prompt 里的叮嘱。

### 登录

- 入口 `/ui/login`（也可从任一页面侧边栏底部的账号区进入；`?next=` 登录后回原页）。
  登录页同时承担三种状态：未登录表单、已登录（显示会话到期 + 登出）、错误反馈（口令错 / 缺字段 / 试太多次）；
  表单上方直接写着首次部署的默认账号 `admin` / `ownrag`（点一下即填入，但不自动提交——用不用默认口令由人决定）。
- 会话 = **HttpOnly Cookie `ownrag_session`**（随机 32 字节，`Path=/; SameSite=Lax; Max-Age=7天`），
  服务端 `user_sessions` 表存 token→用户与到期时间。所以**页面跳转、SSE 检索、curl 联调看到的是同一个登录态**；
  重启服务不掉线（token 落库），登出会删行（不只是清 Cookie）。
- 口令只存 PBKDF2-HmacSHA256（12 万次迭代 + 每账号随机盐，`auth/PasswordHasher`），
  失败提示统一为"用户名或口令不正确"（不泄露账号是否存在）；同一用户名 60 秒内失败 8 次短时拒绝（429）。
- 首次启动（`users` 表为空）自动建默认管理员：用户名 `admin`，口令取 `OWNRAG_ADMIN_PASSWORD`
  （缺省 `ownrag`），日志会明确提示去改密；可用 `OWNRAG_ADMIN_USER` 指定用户名。

### 文档权限（`documents.access_level`）

| 级别 | 未登录 | 已登录 | 用途 |
|---|---|---|---|
| `public`（缺省） | 可检索、可分块、可看原件 | 同左 | 存量文档迁移后一律是这个值，行为与升级前完全一致 |
| `protected` | **不可**（检索不召回、分块/原件/复核/状态接口 403） | 可 | 内部资料、个人信息、未公开内容 |

- 上传时指定（`ingest` 页下拉框 / `access_level` 表单字段）；建好后在「资源」页或「知识库」页点
  「设为需登录 / 设为公开」即可切换（`POST /docs/{docId}/access`，需登录）。
- **单一事实源**：只存在 `documents` 一行上，`chunks` 不冗余该列——检索、原件、分块、复核、列表
  全部通过 `documents` 子查询判断（`ChunkStore.publicOnlySql`），改一行全链路同时生效，没有第二份副本要同步。
- 过滤**先于召回**：`AuthService.accessFilter` 给 metadataFilter 打 `public_only` 标记 →
  关键词通道与向量通道各自在 SQL 里过滤，没权限的块根本不进候选池，RRF/rerank/上下文都看不到它。
  用户清空或伪造 `metadataFilter.sensitivity` 也绕不过（这是服务端强制的，不是调用方可选项）。
- 与 `sensitivity` 的区别：`sensitivity` 是"内容分级"，过滤由**调用方自选**（影响召回范围）；
  `access_level` 是"谁能看"，过滤由**服务端强制**。两者分列分道，避免"清空过滤条件就绕过权限"。

### 越权二次校验（模型返回后还会再查一遍）

"先过滤后召回"保证了**正常情况下**上下文里没有受限内容，但它依赖"每条召回 SQL 都写对了过滤条件"。
新增一条通道（向量/SQL/直击/外部 API）忘了带条件，越权内容就会安静地进候选池。所以除了检索过滤，
还有一道**独立的、fail-closed 的**复核（`auth/AccessPostCheck`，不信任上游，自己回查 `documents`）：

| 时机 | 校验什么 | 命中后的动作 |
|---|---|---|
| **进模型前**（`gate: access_precheck`） | 候选池里每个块的 `doc_id` 拿去 `documents` 再问一遍"当前会话能不能读" | 越权块**直接剔除**，再走闸门一；播报"剔除了 N 块需登录内容" |
| **生成后**（`gate: access_blocked`） | 答案是否点名了"当前会话读不到的文档"（比对受限文档的文件名，≥4 字、排除已在候选里的） | `done.retracted=true` + `citations` 清空 + `answer` 换成撤回话术；首答不进 trace/qa_log |

为什么必须分两个时机：**流式 token 一旦发出去就收不回来**。生成后的校验挡不住已经吐到页面上的字，
它的价值是「不写进 citations/trace/qa_log、给客户端一个明确的撤回信号」；真正能挡住内容的是进模型前那一刀。
前端（`chat.html` / `talk.html`）收到 `retracted` 会把流式期间显示的正文整段盖成撤回提示，不留残余。

同时补掉两条**绕开 RAG** 的通道（它们都不经过 `chunks`，检索过滤对它们无效）：

- **SQL 通道**：`TableCatalog.list(conn, kbs, loggedIn)` —— 未登录时受限 Excel 表不进目录，
  于是它也就不在 `SqlPlanner` 的表白名单里（SQL 出的是整表聚合数字，泄漏比片段更彻底）。
  路由可用性判断同上：否则路由会说"SQL 可用"却一张表都选不出来，用户看到"库里没有数据"的假结论。
- **直击库**：`direct_hits` 新增 `access_level` 列（缺省 `public`，老库启动补列），
  `DirectHit.match(..., loggedIn)` 未登录只命中公开条目——直击库是"零检索零生成直达用户"的答案，
  不挂在 `documents` 上，没有自己的权限列就是绕开文档权限的后门。

> 边界（诚实说明）：二次校验判的是"来源是否有权"，不判"内容本身敏不敏感"（那是 `sensitivity` 与红线词的事）。
> `/admin/*` 观测接口（qa_log / trace）未做角色隔离，属运维面；对外暴露前仍应加反代鉴权。

### 明确提示（不是干巴巴的 403）

- 未登录时每个页面顶部有黄色提示条（`#authStrip`）："当前只能查看公开文档…" + 一键登录；
  侧边栏账号区常驻显示"未登录/已登录 + 可访问范围"。
- 检索：SSE 先发 `gate{stage:access_limited, protected_docs:N, note}`，让用户知道"本轮少看了 N 篇"；
  若因此候选为空，`no_evidence.reason` 会追加"当前未登录，只检索了公开文档…登录后可检索全部"——
  避免用户误以为知识库缺内容而重复上传。
- 访问受限文档：403 + 一句话说清"权限级别 + 为什么被拒 + 去哪个地址登录"（`AuthService.deniedMessage`）。
- 检索调试台（`/ui/retrieve`）响应带 `access{logged_in, public_only, protected_docs}`，
  与线上同口径——否则"调试能搜到、问答搜不到"无从解释。

## 问答调试（八步全可见）

`/ui/chat` 是**问答调试页**：一次提问把八个环节按执行顺序自上而下摊开（单列，不做左右分栏），
任何"答案不对"都能定位到具体一步。界面上的 ①-⑧ 与 SSE 事件一一对应，
其中 ②-⑦ 只在 `debug=true` 时下发（普通对话页不背这几十 KB）。

| # | 页面面板 | SSE 事件 | 载荷要点 |
|---|---|---|---|
| ① | 查询改写 | `rewrite`（始终下发） | `triggered/method(none\|delexical\|llm\|fallback)/original/rewritten/reason/history_turns/ms` |
| ② | 关键词召回 | `retrieval` | `bm25[]`：`rank/chunk_id/ordinal/score(-bm25)/chars/preview` |
| ③ | 向量召回 | `retrieval` | `vector[]`：同结构，`score=cosine`；空则带 `vector_skipped_reason` |
| ④ | 混合排序 | `fuse` | `order[]`：`rank/rrf/channels[{channel,score}]/preview`（rerank **之前**的快照） |
| ⑤ | 重排序 | `rerank` | `note/before/after/dropped` + `order[]`：`rank/prev_rank/rerank_score/rrf`（`prev_rank` 画名次升降） |
| ⑥ | 进入上下文的块 | `ctx` | `candidates[]`：`ordinal/chunk_id/anchors/rrf/channels/preview`（预算裁剪后） |
| ⑦ | 发给模型的内容 | `prompt` | `phase(generate\|repair)/prompt/ctx_tokens/num_ctx/messages[{role,content,chars}]` 全文 |
| ⑧ | 大模型应答 | `done` | `answer`（最终交付）+ `raw_answer`（闸门二重答前的首答，debug 才有） |

改写口径（`retrieve/QueryRewriter`）：**规则闸门决定要不要改写，命中才花钱**——
含指代词（它/该标准/上面…）且带 `history` → 调一次短模型做指代消解（失败降级为「上一轮问题 + 本轮问题」拼接）；
含提问套话（请问/帮我/麻烦…）→ 纯规则剥离。不触发时 `rewritten == original` 且 `reason` 写明原因。
开关三层：`apps.yaml retrieval.query_rewrite`（默认 true）→ 请求体 `rewrite`（true 强制 / false 关闭）→ 页面下拉框。
直击库始终用原问题精确匹配；`{question}` 占位符也始终是**原问题**——改写只作用于召回通道。

## 数据模型（18 表 + FTS5）

事实源是 `core/Db.java` 的 `DDL` 常量（幂等 `CREATE TABLE IF NOT EXISTS` + 启动期 `migrate()` 按列名探测补列 +
`probeFts5()` 探测），**没有独立 `.sql` 文件或迁移工具**。2026-11-20 用 `sqlite3 .schema` 与线上库逐表核对：
库结构与代码 DDL 完全一致，无漂移。

| 表 | 归属 | 写入方 | 作用 / 关键列 |
|---|---|---|---|
| `tasks` | 任务 | TaskStore / PipelineExecutor | 一次解析一行：`pipeline`/`kb`/`status`/`current_step`/`state_json`（检查点）/`trace_id` |
| `todos` | 任务 | TaskStore / ColumnMappingStep | 失败入待办：`reason`/`payload_json`/`status`(open\|done)/`resolved_at` |
| `traces` | 观测 | TraceLog | 每步一行：`step`/`status`/`ms`/`counters_json`/`error` |
| `chunks` | 索引 | IndexUpsertStep / reembed | 块正文与元数据：`text`/`ordinal`/`anchors_json`/`meta_json`/`embed_version`/`sensitivity`/`topic`/`doc_date`/`origin` |
| `chunks_fts` | 关键词通道 | ChunkStore.keywordUpsert | FTS5 虚表 `(text, chunk_id/doc_id/kb UNINDEXED)`，CJK 逐字切分；另带 5 张 shadow 表（勿手工维护） |
| `chunk_vectors` | 向量通道 | ChunkStore.vectorUpsert / reembed | `embedding` BLOB（小端 float[]）+ `dim`；替代 chromadb，检索时全量暴力余弦 |
| `direct_hits` | 检索 | InspectController | 直击库：`level`(L0/L1/L2)/`question`/`aliases_json`/`answer`/`enabled`/**`access_level`**（直达用户，权限自带一列） |
| `qa_log` | 问答 | ChatController | 问答日志：`app`/`question`/`hit_chunks_json`/`answer`/`feedback`/`trace_id` |
| `staging_registry` | Excel | ExcelStageStep / SchemaInferStep | sheet 级 staging 表登记：`(doc_id, table_name)` 主键 + `sheet`/`schema_json`（原始列名、物理列名、类型、`sql_expr`、主键候选、`swap_at`） |
| `staging_<docId8>_<sheet>_v<epoch>` | Excel（**动态表**） | ExcelStageStep | 每个 sheet 一张实体表：全列 `TEXT` + `_src_file`/`_sheet`/`_rownum` 溯源列。**换表原子**：先建新版并灌数 → 单事务删旧登记行 + 写新行 → 提交后才 DROP 旧表；删文档/purge 由 `StagingStore` 按登记行 + 前缀扫兜底清（不在 DDL 里） |
| `parse_reviews` | 复核 | ReviewStore | 解析质量复核：`status`/`verdict`/`pages`/`chars`/`tables`/`structures`/`blocking_json`/`warn_json`/`report_path`；文档统计列 `format`/`images`/`formulas`/`suspects`/`doc_stats_json`（见[文档统计](#文档统计与存疑清单2026-11-22)） |
| `doc_fingerprints` | 幂等 | FingerprintStore | 文件级 SHA-256 → doc_id（同文件重传直接 dedup） |
| `chunk_hashes` | 去重 | FingerprintStore / IndexUpsertStep | 块级内容指纹（跨文档去重）；复核 reject 的文档不登记 |
| `kb_registry` | 管理 | KbManageController | 运行时新建的空库（apps.yaml 之外的库，上传白名单立即生效） |
| `documents` | 管理 | DocumentStore | 文档实体，管理页唯一只读口径：`chunk_count`/`vector_count`/`chars`/`review_status`/`task_status`/**`access_level`**（public\|protected，文档级权限的唯一事实源） |
| `users` | 登录 | UserStore | 账号：`username` 主键 + `password_hash`/`salt`（PBKDF2，无明文）+ `display_name`/`role`(admin\|user)/`last_login_at` |
| `user_sessions` | 登录 | UserStore | 登录会话：`token` 主键（随机 32 字节 hex）+ `username` + `expires_at`（本地时间字符串，过期即失效并清行） |
| `eval_cases` | 评测 | EvalStore / EvalController | 评测集：`question` + `source`(manual\|qa_log\|direct_hit) + `source_ref` + `expect_all`/`expect_empty` + `expect_route`/`route_actual`（路由回归：期望通道 vs 实跑通道，不符即 fail） + `category`(fact\|concept\|compare\|troubleshoot\|multi\|cross\|reject\|direct\|sql) + `difficulty`(easy\|medium\|hard) + `verdict`(pass\|fail\|pending) + `last_detail`（路由/闸门结论/命中缺失词/Top 候选） |
| `sql_failures` | 路由 | ChatController / SqlFailureTracker | SQL 通道**连续失败计数**（跨请求跨重启）：`(app, question_norm)` 唯一 + `count`/`last_note`/`todo_id`；到 2 次开待办，成功一次自动关账并清零 |

索引：`idx_tasks_doc(doc_id,created_at,id)`、`idx_tasks_created(created_at DESC,id DESC)`、
`idx_tasks_status(status)`、`idx_traces_tid`、`idx_chunks_doc`、`idx_chunks_kb`、
`idx_vectors_doc`、`idx_vectors_kb`、`idx_chunk_hashes_doc`、`idx_documents_kb`、`idx_documents_task`、
`idx_eval_cases_kb_q(kb,question)`（同库同题唯一）、`idx_eval_cases_verdict(verdict)`、
`idx_sql_failures_key(app, question_norm)`（同题唯一，upsert 依赖它）。

> 后两个 tasks 索引是性能修复的配套（列表 `ORDER BY created_at DESC LIMIT n`、metrics `GROUP BY status`）：
> 没有它们时 SQLite 要把整行（含最大列 `state_json`）读进临时排序器，见[首屏性能](#首屏性能本地实测2026-11-20-优化)。

改表前必须知道的口径约束：

- **时间列全是 `TEXT` + `datetime('now','localtime')`**，日期过滤就是字符串比较（`doc_date` 同理）。
- **`chunks.embed_version` 是向量空间的版本戳**：检索按它与 `settings.embedVersion` 精确匹配才召回。
  换 embed 模型必须改值并重建，否则向量通道直接空（bge-m3 与 bge-large-zh-v1.5 同为 1024 维，
  **维度相同不会报错，只会静默错分**）。
- **`documents.vector_count` / `chunk_count` 是派生值**，只在 `IndexUpsertStep`、`reembed`、`DocumentStore.backfill`
  里刷新；绕开接口手写 SQL 删块会让管理页数字失真。
- **全库没有声明外键**（`PRAGMA foreign_keys=ON` 只是与 Python 版对齐的开关）：级联清理靠
  `DELETE /docs/{docId}` 与 `purge` 里的显式多表删除，**六处一起清**：`chunks` + `chunks_fts` +
  `chunk_vectors` + `doc_fingerprints` + `chunk_hashes` + Excel 动态 `staging_*`/`staging_registry`，
  外加 `documents` 实体行（漏清 `chunk_hashes` 会让重灌的块被误判重复丢弃；漏清 `documents`
  会让 purge 后管理页仍显示幽灵文档——两处都是 2026-11-20 审查补的）。
- **事务口径**：`autocommit=false`（须在 WAL PRAGMA 之后设），写方法自带 `commit()`；读后要写的路径
  必须先 `Db.endRead(conn)` 收尾读事务，否则撞 `SQLITE_BUSY_SNAPSHOT`（见踩坑记录）。

## 模块映射（Python → Java）

| Python | Java | 说明 |
|---|---|---|
| core/registry.py + pipeline.py | core/Step, StepRegistry, PipelineExecutor | 步骤接口 + 注册表 + fallback 链/检查点/失败入待办，语义逐行对齐 |
| core/db.py | core/Db | Python 版 8 表 + FTS5 平移，Java 侧扩到 **18 表**（新增 `chunk_vectors` / `doc_fingerprints` / `chunk_hashes` / `kb_registry` / `documents` / `eval_cases` / `sql_failures` / `users` / `user_sessions`），见[数据模型](#数据模型18-表--fts5) |
| —（Python 版无登录） | auth/PasswordHasher, UserStore, AuthService | 登录会话（Cookie + 落库 token）与文档级权限过滤；见[用户登录与文档权限](#用户登录与文档权限) |
| configs/*.yaml | resources/configs/*.yaml | pipelines/apps/prompts 原样平移（parse_pymupdf → parse_pdfbox） |
| ingest/mineru_openapi.py | ingest/MineruOpenClient | 三步流契约逐行对齐：裸 PUT 零附加头、code!=0、状态机、zip-slip |
| ingest/pdf_mineru.py | ingest/DetectPages, ParseMineru, ParsePdfbox | PDFBox 替代 pymupdf；open/http/cli 三模同接口 |
| ingest/av_asr.py | ingest/FfExtractAudio, AsrTranscribe, SegmentByTime, OcrKeyframes | **ASR 改走 OpenAI 兼容 HTTP**（本地 whisper.cpp-server 或云端皆可） |
| ingest/excel_staging.py | ingest/ExcelStage…Textualize, StagingStore | POI + commons-csv 替代 pandas；staging 全 TEXT 保真；动态表清理收口到 StagingStore |
| index/chunker.py | index/Chunker | 结构感知切分：块头注入/表格不跨块/整段重叠，est_tokens 同口径 |
| —（Python 版无清洗层） | index/CleanMarkdown, CleanMarkdownStep | 解析后 → 清洗后：页标记/页码行/不可见字符/空白归一，逐条计数；**清洗后正文才是切分输入**，见[解析三栏对照](#解析三栏对照原文档--解析后--清洗后) |
| index/embedder.py | index/Embedder | OpenAI 兼容单分派 + 20s 连接级熔断（4xx/5xx 不熔断；Ollama 原生分支已移除） |
| index/store.py | index/ChunkStore | FTS5 CJK 逐字切分 + 查询阶梯；**向量通道改为 SQLite BLOB + 暴力余弦**（替代 chromadb，万级块毫秒级、精确召回） |
| retrieve/* | retrieve/HybridSearch, QueryRewriter, RerankClient, DirectHit | RRF k=60 名次融合；两路原始命中回填正文预览；rerank 两供应商（service / siliconflow）降级可见；直击库 L0/L1/L2；**QueryRewriter 为 Java 侧新增**（Python 版无改写层）；`HybridSearch.ragFilter` 统一追加 `source_type NOT IN ('excel')` |
| —（Python 版无路由层） | router/QueryRouter, TableCatalog, SqlPlanner, SqlChannel, SqlExecutor | **查询期路由（Java 新增，2026-11-23）**：规则打分 → 可用性掩码 → SQL/RAG/MULTI；Text2SQL 走 SELECT-only + 表名白名单 + 只读连接 + LIMIT 钳制。口径见 [`docs/10-Excel通道口径`](../10-Excel通道口径.md)、[`docs/11-查询路由与多源编排`](../11-查询路由与多源编排.md) |
| generate/* | generate/Budget, Gates, PromptRenderer, ChatClient | 上下文预算/两道闸门/Prompt 版本化/SSE 流式，语义逐行对齐 |
| review.py | review/ReviewStore, PrepareReview, ReviewGate, DocStats | 质量检查（阻断项/提示项）+ 工件落盘 + approved 才放行；`DocStats` 为 Java 侧新增的文档统计与存疑清单 |
| api/routes_*.py | api/*Controller | 路径与请求/响应契约一致（原 SSE 事件顺序仍是产品契约，新增 `rewrite` 与 4 个调试事件为**追加**，不破坏旧消费端） |
| web/ | resources/static/ | Python 版 8 页面原样复制；Java 侧新增 `resources`（资源/向量化）、`talk`（多轮会话演示）、`evalset`（评测集） |

## 与 Python 版的差异点

1. **ASR 走 HTTP**：JDK 8 无法进程内跑 faster-whisper/funasr。`models.yaml asr.base_url` 指向 OpenAI 兼容 `/audio/transcriptions`（本地 whisper.cpp-server：`http://127.0.0.1:8081/v1`，model=whisper-1；或 SiliconFlow SenseVoiceSmall）。未配置时 av_v1 失败入待办，绝不静默。
2. **向量通道**：chromadb 无 JDK 8 等价物，改为 `chunk_vectors` 表（BLOB 小端 float[]）+ 查询时全量暴力余弦。个人规模（万级块）毫秒级，精确召回优于近似索引；规模上来再换 pgvector。
3. **PDF 兜底**：parse_pymupdf → `parse_pdfbox`（PDFBox 2.0.31），同样产出 `<!--page:N-->` 页锚。
4. **ocr_keyframes**：Java 版无进程内 PaddleOCR，恒显式 skipped（降级可见）；后续可接 HTTP OCR。
5. **JDK 8 语法面**：无 records/var/List.of，黑板统一 JSON 原生类型（Map/List/标量），检查点序列化零损耗。
6. **向量版本隔离 + 重建通道**：`chunk_vectors` 不按模型分表，靠 `chunks.embed_version` 隔离——检索只召回
   与当前 `embed_version` 完全一致的向量，换 embed 模型后旧向量立即失效（不再静默混算），并由
   `POST /admin/kbs/{kb}/reembed` 原地重建（不重跑解析/切分，幂等可续跑）。
7. **配置与密钥分层**：`models.yaml` 只放端点/模型/默认值；key 一律走环境变量，`restart.ps1` 从 gitignored
   的 `.env` 注入进程环境。优先级 **真实环境变量 > .env > `models.yaml`**；用 `mvn spring-boot:run`
   直接起服务时不会读 `.env`（见快速开始里的 PowerShell 片段）。
8. **重排走云 API**：`rerank.provider=siliconflow` 时打 `/v1/rerank`（平铺 documents + `results[].index` 回映）；
   自建 service / siliconflow 两种 provider 保留，失败一律降级为 RRF 顺序并在响应 `rerank.note` / trace 里写明。
9. **问句改写层（Java 新增）**：Python 版"只进生成不进检索"的历史策略保留，但含指代/套话的追问会把召回带偏；
   新增 `retrieve/QueryRewriter`——规则闸门触发、可关、失败降级，「改没改、改成什么、为什么」随 `rewrite` 事件外发。
10. **问答调试事件（Java 新增）**：`debug=true` 时下发行级明细 `retrieval/fuse/rerank/prompt` + `done.raw_answer`，
   回答"是哪一路捞上来的、融合与重排怎么变的、模型到底看到什么"——这三件事 Python 版只能翻 trace 与日志。
11. **Ollama 已整体下线（2026-11-22）**：chat / embed / rerank 三处不再有 Ollama 原生协议分支，也不再读
   `endpoints.ollama`、`OWNRAG_CHAT_PROVIDER`、`OWNRAG_EMBED_PROVIDER`、`/api/tags`。需要本地模型就起
   OpenAI 兼容服务（vLLM / llama.cpp-server / LM Studio 等），把 `base_url` 指过去即可；本地重排则起
   bge-reranker HTTP 服务走 `rerank.provider=service`。
12. **解析后新增清洗层 + 三栏对照（2026-11-22）**：六条管道都在 `validate_parsed` 与 `chunk_markdown` 之间插入
   `clean_markdown`；复核页把**原文档 / 解析后 / 清洗后**三栏并排（含清洗逐条计数与同步滚动）。
   Python 版只有"解析产物"一份，因此"这块正文为什么少了页码、为什么没清页眉"只能靠猜。
13. **评测集进控制台（Java 新增，2026-11-22）**：Python 版只有 `scripts/eval_recall.py` + jsonl 文件，
   评分靠命令行看；Java 侧落成 `eval_cases` 表 + `/ui/evalset` 页面——**来源**（人工 / 问答日志回流 / 直击库回归）、
   **内容**（问题 + 期望关键词 / 应拒答）、**好坏**（跑检索判定并留证据：闸门结论、命中和缺失的词、Top 候选）三列同屏。
   口径：无期望词的题只观察不判定（保持 `pending`），不拿"有依据"冒充"答对了"。
  2026-11-23 起多第四个维度**路由**：`expect_route`（期望通道）vs `route_actual`（实跑通道），
  不符直接 fail、分数归零（原检索结论保留在 `reason` 里），KPI 出 `route_mismatch` 与 `by_route` 分桶——
  这样调路由权重才有依据，而不是"看着差不多就改"。
   **黄金集**：50 题（8 直击 + 42 人工，题库在 `src/main/resources/eval/golden-set.json`，可一键导入），
   按题型 / 难度分桶；
   首轮基线 **47/50**，3 个 fail 都是真实缺陷（清单/简历类块抢占召回 2 例、同主题跨文档竞争 1 例），
   并暴露一个检索 bug：问题里带 `NOT` 时 FTS5 把裸词当运算符，整条 BM25 语法报错→零召回
   （`ChunkStore` 的 OR 阶梯改为逐 token 加引号后修复，该题从 fail 转 pass）。
14. **查询期路由 + Excel 走 SQL（Java 新增，2026-11-23）**：改造前 `/chat` 只有 RAG 一条路，
   Excel 明细被 `textualize(row_card)` 渲染成块再嵌入——聚合题必错（`SUM` 不在向量能力里）。
   现在 ①`excel_v1` 去掉 `embed`，只把「一 sheet 一块目录」写进 FTS（`source_type='excel_catalog'`），
   行数据留在 `staging_*`；②`router/` 规则分诊（`rag|sql|multi`）+ 可用性掩码，
   "判成 SQL 却没表"时如实拒答，不回落 RAG 编答案；③SQL 通道 SELECT-only + 表名白名单 +
   `PRAGMA query_only=1` 只读连接 + `LIMIT` 钳制，数字只来自结果集并带 SQL 全文口径。
   配套四件事：④`/admin/retrieve?route=1` 路由回归台（只判不跑，不调生成模型）；
   ⑤`eval_cases.expect_route`+`route_actual`，**路由错但答案对记 fail**，KPI 出 `route_mismatch` 与
   `by_route` 分桶；⑥同一题 SQL 连续失败 2 次入 `todos`（成功一次自动关账）；
   ⑦Excel 换表原子化（`_v<epoch>` 新表 → 单事务切登记行 → 提交后删旧表），刷新期间不再出现"中途 0 行"。
   联网（`web`）本期只留契约位，不实现。

## 踩坑记录（已回归测试锁死）

- **MinerU 裸 PUT**：预签名 URL 多一个头（含 Content-Type）即 OSS 403——OkHttp `RequestBody.create(bytes, null)` 不发 Content-Type，且不得带 Authorization。
- **zip-slip 防护的相对路径坑**：`data-dir=./data` 时 target（相对）对比 base（绝对）恒 false，**全部产物被静默跳过**（表现为"解析成功但产出空 Markdown"）。已统一转绝对路径再比较。
- **业务错误是 HTTP 200 + code!=0**：`-60018`=每日页额度耗尽；必须检查 code 字段。
- **Windows GBK 控制台**：日志强制 UTF-8；curl 发中文 JSON 要 `--data-binary @file`（UTF-8 文件），直接 `-d '中文'` 会按 GBK 编码发出导致 400。
- **SQLite 事务**：sqlite-jdbc 默认 autocommit，`commit()` 会抛异常；已统一 `setAutoCommit(false)`（须在 WAL PRAGMA 之后）+ 写方法内显式 commit。
- **SQLite 读后写会撞 BUSY_SNAPSHOT**：autocommit=false 下一条 SELECT 就开启 deferred 读事务，同连接随后要写时必须把读快照升级成写锁；
  若这期间别的连接提交过，SQLite 立即抛 `[SQLITE_BUSY] The database file is locked`，**不走 busy handler**
  （`busy_timeout` 调到 15s 也没用）。批量灌库时表现为成批 failed 任务（实测 1100 条）。
  规则：读方法末尾调 `Db.endRead(conn)`，执行器在每步边界收尾；回归见
  `SqliteConcurrencyTest`（根因）与 `PipelineConcurrencyTest`（4 并发管道 + 外部噪声写）。
- **String.repeat**：JDK 8 无此 API（Java 11+）。
- **UI 资源前缀**：前端沿用 Python 版路由 `/ui/assets/**`，Spring 默认静态映射在 `/assets/**`——
  必须补 ResourceHandler，否则页面无样式无脚本（全 404）。
- **前端脚本缓存**：改 md.js 后浏览器内存缓存顽固复用旧版；`/ui/assets/**` 已设 `Cache-Control: no-store`
  （app.js / menu.js 靠它强制校验），`md.js` 另带 `?v=YYYYMMDD`（改它时同步 bump）。
- **`tasks.state_json` 是性能陷阱**：检查点里存着整份文档的块，单行几十 KB、全表 734MB。
  `SELECT * FROM tasks ORDER BY created_at DESC LIMIT 12` 实测 9.5s（临时排序器要存整行），
  列表查询必须显式投影列并依赖 `idx_tasks_created`；同理 `/admin/health` 探一个没启的本地服务
  会白等 2s（Ollama 探活分支已随下线移除），而每个页面 `boot()` 都先 await 它——两处曾共同造成"打开页面停顿 10 秒"。
- **Prompt 占位符校验误判**：原逻辑扫"渲染后的完整消息"，资料正文里的 LaTeX `\frac{1}{2}` 的 `{1}{2}`
  会被当成未填占位符 → 问答 500。改为只校验**模板本身**（Python 版同源隐患，Java 已修 + 回归）。
- **SiliconFlow SenseVoice 无段时间戳**：该端点不认 `response_format`（只回 `{"text":...}`）；whisper-large-v3
  不可用。ASR 回退阶梯：verbose_json → srt 自解析 → **纯文本按句切分 + 按字符占比估算时间**
  （`ts_approximated=true` 写入块 meta 与 trace，锚点为近似值）。需要精确对齐请换回本地 whisper.cpp-server。
- **媒体片段锚点**：`<video src="...#t=0,28">` 在 Chrome/Edge 可用；非 Chromium 内核需 JS seek 兜底。
- **Windows 上 `java -jar` 占着 target 里的 jar**：运行中的实例会锁住 `ownrag-java-*.jar`，repackage 的
  "改名成 `.original`" 步骤直接失败，**而且失败后 target 里只剩 thin jar（可运行产物被毁，下次 `java -jar` 起不来）**。
  `restart.ps1` 已改为「先备份上一版 fat jar（`Test-FatJar` 校验，thin jar 不备份）→ 停旧实例 → 构建 → 失败自动回滚」。
- **换 embedding 模型会静默脏召回**：`bge-m3` 与 `bge-large-zh-v1.5` 都是 1024 维，旧代码只按 `dim` 存 BLOB、
  检索不比版本，两套向量空间混算不报错只降质。修法：`ChunkStore.vectorSearch(..., embedVersion)` 精确匹配
  `chunks.embed_version`，版本不符即该通道为空并在检索侧播报（降级可见），再用 `reembed` 补齐。
- **embed 模型换了但 chunk 太长 → `reembed` 直接 400**：SiliconFlow 的 `BAAI/bge-large-zh-v1.5` 上下文只有
  512 token，本库 1000+ 块超 1500 字（最长 9737 字），整批请求返回 `HTTP 400 / code 20015 参数无效`，
  而报错信息里看不出是长度问题。同 1024 维但 8192 token 上下文的 `BAAI/bge-m3` 实测 9737 字也能过；
  真要留在 `bge-large-zh-v1.5` 上，得先在 embedding 侧按 token 截断再送。
- **`RerankClient` 的 provider 推断陷阱**：`provider` 留空但 `base_url` 非空会被推断成自建 `service`，
  走 `{query, documents:[[q,d]...]}` 的老 pairs 协议——对着 SiliconFlow 打过去只会 4xx 然后静默降级。
  配云 API 必须显式写 `provider: siliconflow`。
- **`apps.yaml` 的 `retrieval.rerank.enabled` 是死配置**：`AppDef.rerankEnabled` 解析后无人读取，
  rerank 是否生效只由 `endpoints.rerank.provider` / `base_url` + `OWNRAG_RERANK_API_KEY` 决定。
  想真正按 app 开关重排，需要在 `ChatController.rerankTopN` 里接上这个字段。
- **purge / 删文档漏清第六通道（2026-11-20 审查发现）**：`purge` 原本不清 `documents`（purge 后
  管理页仍按 `documents` 聚合出幽灵文档）也不清 Excel 动态 `staging_*` 表与 `staging_registry`。
  已统一收口：`StagingStore.dropByDoc` + `DocumentStore.delete` 进两条删除路径，
  回归见 `StagingStoreTest`；向量版本隔离回归见 `EmbedVersionGuardTest`。

## 后续演进项

- pgvector（规模 > 10 万块时）
- 鉴权与外部队列（Python 版同为未实现项）
- HTTP OCR 服务接入 ocr_keyframes
- 路由侧：LLM 归类（低置信）、网页通道（`route=web`，含 SSRF/红线/网页引用契约）、
  跨 doc JOIN 策略、SQL 结果缓存与失效
- 行文本向量（Excel 备注列，召回结果只作行定位线索，数字仍回 SQL 重算）
