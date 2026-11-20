# ownrag-java

Python 版 [ownrag](../ownrag)（Self RAG）的 **Java 平移**：JDK 1.8 + Spring Boot 2.7.18，重点移植**文档解析三链路**（MinerU PDF / ffmpeg+ASR 音视频 / Excel）。无 Spring AI（需 Boot 3 + JDK 17），延续 Python 版「无模型 SDK、全部手写 HTTP 薄客户端」的口径，只用 OkHttp + Jackson。

## 快速开始

```bash
# 密钥：复制 .env.example → .env 填 key（.env 已 gitignore；restart 脚本启动前自动注入，
# 已存在的真实环境变量优先，不被覆盖）

# 一键重启（停旧实例 → 打包 → 注入 .env → 后台启动 → 等 /health → 打印关键启动日志）
# Windows：双击 restart.bat，或 .\restart.ps1；-NoBuild 只重启不打包，-WithTests 先跑测试
.\restart.ps1

# 编译 + 全量测试（83 例）
mvn test

# 启动（端口 8420；环境变量优先级 > classpath configs/*.yaml）
mvn spring-boot:run
```

当前档位（`src/main/resources/configs/models.yaml`，换模型只改这一个文件）：

| 用途 | 供应商 | 端点 | 模型 |
|---|---|---|---|
| 生成 | agnes（OpenAI 兼容） | `https://apihub.agnes-ai.com/v1` | `agnes-3.0-flash`（512k 输入 / 64k 输出） |
| Embedding | SiliconFlow | `https://api.siliconflow.cn/v1` | `BAAI/bge-large-zh-v1.5`（1024 维） |
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

打开控制台：<http://127.0.0.1:8420/ui>（复用 Python 版 8 页面，API 契约不变）。

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

页面改动：`review.html`（产物全文 + 切分预览渲染）、`kb.html`（块正文渲染 + 音视频块播放按钮）、
`chat.html`（回答/上下文渲染 + 引用锚点播放）、`retrieve.html`（候选预览渲染）。

## 首屏性能（本地实测，2026-11-20 优化）

打开任一页面都要先过 `app.js boot()`（`/admin/health` → `/admin/config` → `pageInit()` 取数据），
所以"打开路径后明显停顿"几乎总是这三个接口的问题。优化前后的实测（`data/ownrag.db` 1.0GB、
tasks 4799 行 / `state_json` 合计 734MB）：

| 请求 | 优化前 | 优化后 | 根因 |
|---|---|---|---|
| `/admin/tasks?limit=12` | **9.50s / 538KB** | 0.02s / 2.3KB | `SELECT *` 把 `state_json`（检查点，单行几十 KB）一起取；且 `ORDER BY created_at` 无索引 → SQLite 把整行塞进临时排序器，等于每次翻页读 734MB |
| `/admin/health` | **2.28s**（每 20s 轮询一次） | 0.03s（进程首探 ~1s，之后走缓存） | 探本地 Ollama（没装 → 白等 connectTimeout 2s）+ 每次跨公网打 `/models` |
| `/admin/metrics` | 0.58s | 0.02s | `GROUP BY status` 全表扫描，同样把 `state_json` 大列读进来 |
| 单页首屏合计 | ≈11.8s | ≈0.1s | 上述三项叠加 |

对应改动（都可回归）：

1. `TaskStore.listTasks` 改成显式列投影（不含 `state_json`），检查点只在 `getTask` / 任务详情里读；
   DDL 补 `idx_tasks_created(created_at DESC, id DESC)` 让 `ORDER BY ... LIMIT n` 走索引直取 n 行。
2. DDL 补 `idx_tasks_status(status)`：`metrics` 的 `GROUP BY status` 变 index-only scan。
3. `/admin/health`：ollama 只在真有 provider 用它时才探（否则返回 `used=false`，前端顶部首灯按
   `chat_backend` 显示 **LLM 可用/不可达**，不再出现与当前档位无关的 "Ollama 未使用" 告警）；
   远端 chat `/models` 探测改为**进程首探同步 + 之后 15s TTL 后台单飞刷新**，请求永远拿缓存立即返回；
   `@PostConstruct` 里预热，重启后第一个页面也不用等。

页面本身与静态资源不是瓶颈（本地均为 3~12ms）：HTML 5~10KB、`app.js` 12KB、`md.js` 14KB、
`katex.min.js` 275KB（仅 review/kb/chat/retrieve 页面需要）。`/ui/assets/**` 设了 `no-store`，
所以 app.js/menu.js 不依赖 `?v=` 破缓存；`md.js` 仍带 `?v=YYYYMMDD`（改它时同步 bump）。

## HTTP 接口一览

端口默认 8420；本工程无鉴权（个人部署口径），对外暴露前请自行加反代鉴权。

| 方法 | 路径 | 用途 | 关键参数 |
|---|---|---|---|
| POST | `/chat` | 问答，SSE 流式（事件顺序 `gate`→`ctx`→`token*`→`done`，异常 `error`，无依据 `no_evidence`） | body `{app, question, top_n?, metadataFilter?}`；`metadataFilter = {sensitivity, topic, date_from, date_to}` |
| POST | `/docs/upload` | 上传即建任务；按扩展名选管道（pdf/av/excel/md/txt/docx）；同 SHA-256 且在库 → `status=deduplicated` | multipart `file`、`kb`、`topic`/`sensitivity`/`doc_date`/`origin`（sensitivity 白名单 public/internal/restricted） |
| GET | `/docs/{docId}/status` | 文档任务状态（含当前步骤） | — |
| DELETE | `/docs/{docId}` | 删文档：chunks + FTS + 向量 + 文件/块指纹五处一起清 | — |
| POST | `/docs/tasks/{taskId}/retry` | 任务重试（从检查点续跑，不重跑已完成步骤） | — |
| GET | `/admin/kbs` | 库列表（apps.yaml 声明 ∪ kb_registry ∪ 有数据的库，带文档/块/向量计数） | — |
| POST | `/admin/kbs` | 运行时新建空库（写 `kb_registry`，上传白名单立即生效） | body `{kb, description?}`，kb 限 `[A-Za-z0-9_-]{1,64}` |
| DELETE | `/admin/kbs/{kb}` | 删运行时登记的库（apps.yaml 声明的库、还有文档的库拒删） | — |
| POST | `/admin/kbs/{kb}/purge` | 库级清空（替代易漏表的手工 SQL） | — |
| POST | `/admin/kbs/{kb}/reembed` | 按 `chunks.text` 原地重建向量（换 embed 模型后必做） | `batch`（≤32，默认 16）、`limit`（0=全量） |
| GET | `/admin/kbs/{kb}/documents` | 文档清单（文件名/块数/向量数/任务状态） | `q`、`limit`、`offset` |
| GET | `/admin/documents/{docId}/chunks` | 单文档的块与向量概览（dim/模长/前几维） | — |
| GET | `/admin/chunks` | 检索调试：`q` 非空走 FTS5，否则按 kb/docId 翻块 | `kb`、`q`、`docId`、`limit` |
| POST | `/admin/retrieve` | 只跑检索侧全链路（直击→双路→RRF→rerank→预算→闸门一），**不调生成模型** | body `{app, question, kb?, top_n?, rerank_top_n?, metadataFilter?}` |
| GET/POST/DELETE | `/admin/direct_hits` | 直击库增删查（L0/L1/L2 + 别名） | — |
| GET | `/admin/reviews`、`/admin/reviews/{docId}` | 复核队列与详情 | — |
| POST | `/admin/reviews/{docId}/approve`、`/reject` | 复核放行/驳回（approved 才进 `index_upsert`） | — |
| GET | `/admin/tasks`、`/admin/todos`、`/admin/trace/{traceId}`、`/admin/qa_log` | 任务 / 待办 / 单次追踪 / 问答日志 | `limit` 等 |
| POST | `/admin/todos/{todoId}/resolve` | 处理待办（open → done） | — |
| GET | `/admin/metrics` | 运行计数：任务状态、块数、**按 embed_version 分桶**、待办数 | — |
| GET | `/admin/config` | 回显 `configs/*.yaml`（含 models.yaml 全文，不含 key） | — |
| GET | `/health`、`/admin/health` | 存活 / 后端连通性（chat 按供应商探 `/models` 或 `/api/tags`、rerank 启用状态、预算口径） | — |
| GET | `/media/{docId}/**`、`/source/{docId}` | MinerU 图片产物 / 原始音视频（自动支持 HTTP Range） | — |
| GET | `/ui` | 控制台（8 页面） | — |

## 数据模型（13 表 + FTS5）

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
| `direct_hits` | 检索 | InspectController | 直击库：`level`(L0/L1/L2)/`question`/`aliases_json`/`answer`/`enabled` |
| `qa_log` | 问答 | ChatController | 问答日志：`app`/`question`/`hit_chunks_json`/`answer`/`feedback`/`trace_id` |
| `staging_registry` | Excel | ExcelStageStep | sheet 级 staging 表登记：`(doc_id, table_name)` 主键 + `sheet`/`schema_json` |
| `staging_<docId8>_<sheet>` | Excel（**动态表**） | ExcelStageStep | 每个 sheet 一张实体表：全列 `TEXT` + `_src_file`/`_sheet`/`_rownum` 溯源列；建表前 `DROP IF EXISTS`，删文档/purge 由 `StagingStore` 一并清（不在 DDL 里） |
| `parse_reviews` | 复核 | ReviewStore | 解析质量复核：`status`/`verdict`/`pages`/`chars`/`tables`/`structures`/`blocking_json`/`warn_json`/`report_path` |
| `doc_fingerprints` | 幂等 | FingerprintStore | 文件级 SHA-256 → doc_id（同文件重传直接 dedup） |
| `chunk_hashes` | 去重 | FingerprintStore / IndexUpsertStep | 块级内容指纹（跨文档去重）；复核 reject 的文档不登记 |
| `kb_registry` | 管理 | KbManageController | 运行时新建的空库（apps.yaml 之外的库，上传白名单立即生效） |
| `documents` | 管理 | DocumentStore | 文档实体，管理页唯一只读口径：`chunk_count`/`vector_count`/`chars`/`review_status`/`task_status` |

索引：`idx_tasks_doc(doc_id,created_at,id)`、`idx_tasks_created(created_at DESC,id DESC)`、
`idx_tasks_status(status)`、`idx_traces_tid`、`idx_chunks_doc`、`idx_chunks_kb`、
`idx_vectors_doc`、`idx_vectors_kb`、`idx_chunk_hashes_doc`、`idx_documents_kb`、`idx_documents_task`。

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
| core/db.py | core/Db | Python 版 8 表 + FTS5 平移，Java 侧扩到 **13 表**（新增 `chunk_vectors` / `doc_fingerprints` / `chunk_hashes` / `kb_registry` / `documents`），见[数据模型](#数据模型13-表--fts5) |
| configs/*.yaml | resources/configs/*.yaml | pipelines/apps/prompts 原样平移（parse_pymupdf → parse_pdfbox） |
| ingest/mineru_openapi.py | ingest/MineruOpenClient | 三步流契约逐行对齐：裸 PUT 零附加头、code!=0、状态机、zip-slip |
| ingest/pdf_mineru.py | ingest/DetectPages, ParseMineru, ParsePdfbox | PDFBox 替代 pymupdf；open/http/cli 三模同接口 |
| ingest/av_asr.py | ingest/FfExtractAudio, AsrTranscribe, SegmentByTime, OcrKeyframes | **ASR 改走 OpenAI 兼容 HTTP**（本地 whisper.cpp-server 或云端皆可） |
| ingest/excel_staging.py | ingest/ExcelStage…Textualize, StagingStore | POI + commons-csv 替代 pandas；staging 全 TEXT 保真；动态表清理收口到 StagingStore |
| index/chunker.py | index/Chunker | 结构感知切分：块头注入/表格不跨块/整段重叠，est_tokens 同口径 |
| index/embedder.py | index/Embedder | ollama/openai 双分派 + 20s 连接级熔断（4xx/5xx 不熔断） |
| index/store.py | index/ChunkStore | FTS5 CJK 逐字切分 + 查询阶梯；**向量通道改为 SQLite BLOB + 暴力余弦**（替代 chromadb，万级块毫秒级、精确召回） |
| retrieve/* | retrieve/HybridSearch, RerankClient, DirectHit | RRF k=60 名次融合；rerank 三供应商降级可见；直击库 L0/L1/L2 |
| generate/* | generate/Budget, Gates, PromptRenderer, ChatClient | 上下文预算/两道闸门/Prompt 版本化/SSE 流式，语义逐行对齐 |
| review.py | review/ReviewStore, PrepareReview, ReviewGate | 质量检查（阻断项/提示项）+ 工件落盘 + approved 才放行 |
| api/routes_*.py | api/*Controller | 路径与请求/响应契约一致（SSE 事件顺序是产品契约，未动） |
| web/ | resources/static/ | 8 页面原样复制，零改动迁移 |

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
   自建服务/ollama 两种 provider 保留，失败一律降级为 RRF 顺序并在响应 `rerank.note` / trace 里写明。

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
  列表查询必须显式投影列并依赖 `idx_tasks_created`；同理 `/admin/health` 探一个没装的本地 Ollama
  会白等 2s，而每个页面 `boot()` 都先 await 它——两处曾共同造成"打开页面停顿 10 秒"。
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
- Excel aggregate 策略（问题→SQL→结果直入答案，M2）
