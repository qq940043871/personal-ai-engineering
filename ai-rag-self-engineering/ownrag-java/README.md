# ownrag-java

Python 版 [ownrag](../ownrag)（Self RAG）的 **Java 平移**：JDK 1.8 + Spring Boot 2.7.18，重点移植**文档解析三链路**（MinerU PDF / ffmpeg+ASR 音视频 / Excel）。无 Spring AI（需 Boot 3 + JDK 17），延续 Python 版「无模型 SDK、全部手写 HTTP 薄客户端」的口径，只用 OkHttp + Jackson。

## 快速开始

```bash
# 一键重启（打包 → 停旧实例 → 后台启动 → 等 /health → 打印关键启动日志）
# Windows：双击 restart.bat，或 .\restart.ps1；-NoBuild 只重启不打包，-WithTests 先跑测试
.\restart.ps1

# 编译 + 全量测试（60 例）
mvn test

# 启动（端口 8420；环境变量优先级 > classpath configs/*.yaml）
mvn spring-boot:run

# 云端档位示例（与 Python 版 .env 同一套变量名，可直接 source ../ownrag/.env）
export OWNRAG_CHAT_PROVIDER=openai OWNRAG_CHAT_BASE_URL=https://apihub.agnes-ai.com/v1
export OWNRAG_CHAT_API_KEY=... OWNRAG_CHAT_MODEL=agnes-3.0-flash
export OWNRAG_EMBED_PROVIDER=openai OWNRAG_EMBED_BASE_URL=https://api.siliconflow.cn/v1
export OWNRAG_EMBED_API_KEY=... OWNRAG_EMBED_MODEL=BAAI/bge-m3 OWNRAG_EMBED_VERSION=bge-m3@siliconflow
export MINERU_MODE=open MINERU_OPEN_TOKEN=...
export OWNRAG_NUM_CTX=8192
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

## 模块映射（Python → Java）

| Python | Java | 说明 |
|---|---|---|
| core/registry.py + pipeline.py | core/Step, StepRegistry, PipelineExecutor | 步骤接口 + 注册表 + fallback 链/检查点/失败入待办，语义逐行对齐 |
| core/db.py | core/Db | 同一套 9 表 DDL + `chunk_vectors`（Java 新增） |
| configs/*.yaml | resources/configs/*.yaml | pipelines/apps/prompts 原样平移（parse_pymupdf → parse_pdfbox） |
| ingest/mineru_openapi.py | ingest/MineruOpenClient | 三步流契约逐行对齐：裸 PUT 零附加头、code!=0、状态机、zip-slip |
| ingest/pdf_mineru.py | ingest/DetectPages, ParseMineru, ParsePdfbox | PDFBox 替代 pymupdf；open/http/cli 三模同接口 |
| ingest/av_asr.py | ingest/FfExtractAudio, AsrTranscribe, SegmentByTime, OcrKeyframes | **ASR 改走 OpenAI 兼容 HTTP**（本地 whisper.cpp-server 或云端皆可） |
| ingest/excel_staging.py | ingest/ExcelStage…Textualize | POI + commons-csv 替代 pandas；staging 全 TEXT 保真 |
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

## 踩坑记录（已回归测试锁死）

- **MinerU 裸 PUT**：预签名 URL 多一个头（含 Content-Type）即 OSS 403——OkHttp `RequestBody.create(bytes, null)` 不发 Content-Type，且不得带 Authorization。
- **zip-slip 防护的相对路径坑**：`data-dir=./data` 时 target（相对）对比 base（绝对）恒 false，**全部产物被静默跳过**（表现为"解析成功但产出空 Markdown"）。已统一转绝对路径再比较。
- **业务错误是 HTTP 200 + code!=0**：`-60018`=每日页额度耗尽；必须检查 code 字段。
- **Windows GBK 控制台**：日志强制 UTF-8；curl 发中文 JSON 要 `--data-binary @file`（UTF-8 文件），直接 `-d '中文'` 会按 GBK 编码发出导致 400。
- **SQLite 事务**：sqlite-jdbc 默认 autocommit，`commit()` 会抛异常；已统一 `setAutoCommit(false)`（须在 WAL PRAGMA 之后）+ 写方法内显式 commit。
- **String.repeat**：JDK 8 无此 API（Java 11+）。
- **UI 资源前缀**：前端沿用 Python 版路由 `/ui/assets/**`，Spring 默认静态映射在 `/assets/**`——
  必须补 ResourceHandler，否则页面无样式无脚本（全 404）。
- **前端脚本缓存**：改 md.js 后浏览器内存缓存顽固复用旧版；`/ui/assets/**` 已设 `Cache-Control: no-store`，
  页面引用脚本统一带 `?v=` 版本参数（改前端资源时同步 bump）。
- **Prompt 占位符校验误判**：原逻辑扫"渲染后的完整消息"，资料正文里的 LaTeX `\frac{1}{2}` 的 `{1}{2}`
  会被当成未填占位符 → 问答 500。改为只校验**模板本身**（Python 版同源隐患，Java 已修 + 回归）。
- **SiliconFlow SenseVoice 无段时间戳**：该端点不认 `response_format`（只回 `{"text":...}`）；whisper-large-v3
  不可用。ASR 回退阶梯：verbose_json → srt 自解析 → **纯文本按句切分 + 按字符占比估算时间**
  （`ts_approximated=true` 写入块 meta 与 trace，锚点为近似值）。需要精确对齐请换回本地 whisper.cpp-server。
- **媒体片段锚点**：`<video src="...#t=0,28">` 在 Chrome/Edge 可用；非 Chromium 内核需 JS seek 兜底。

## 后续演进项

- pgvector（规模 > 10 万块时）
- 鉴权与外部队列（Python 版同为未实现项）
- HTTP OCR 服务接入 ocr_keyframes
- Excel aggregate 策略（问题→SQL→结果直入答案，M2）
