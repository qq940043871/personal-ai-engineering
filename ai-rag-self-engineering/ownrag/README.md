# ownrag · 自研 RAG 工程（代码骨架）

> **口径先读**：本工程 = 个人实战骨架（Python + FastAPI），与 `../../../personal-investment-notes/02-AI智能体/01-认知框架/Harness-详细设计与项目落地.md` 同一条个人线；**不是公司平台技术栈**（公司 = Java 中台 + Dify 智能层）。设计文档见上级目录 `00`–`06`，模块与文档一一对应；`06` 是全链路环节×可验证性清单与「视频 RAG」问题逐条对照。

## 一句话

不使用 Dify、不引入 LangChain：**云-本地可切的模型层 + 配置驱动管道 DSL + 三条解析链路（MinerU PDF / ffmpeg+本地ASR 音视频 / Excel 临时表）+ 混合检索（向量+关键词双通道）+ 重排 + 两道纯代码闸门 + 评测脚本**。当前为云端档（推理 agnes-3.0-flash、嵌入/重排 SiliconFlow bge-m3 系，全免费档）；每个环节都可一键切回本地 Ollama 档（见下表）。

## 模型与服务商（当前档位）

全部密钥只放 `.env`（已 gitignore），不进代码与配置文件；三层供应商分派（chat / embed / rerank）让云-本地切换只改 `.env`，代码零改动。

| 环节 | 当前档位 | 服务商 / 端点 | 模型 | 本地 Ollama 档 |
|---|---|---|---|---|
| PDF 解析 | `MINERU_MODE=cli`（本地 CLI） | mineru.net 开放平台可选（`MINERU_MODE=open`，已实测 2 页冒烟） | MinerU pipeline / vlm 双后端 | CLI 本身即本地 |
| 推理（chat 生成） | `OWNRAG_CHAT_PROVIDER=openai` | agnes apihub `https://apihub.agnes-ai.com/v1`（OpenAI 兼容，SSE 流式） | `agnes-3.0-flash` | Ollama `qwen2.5:7b-instruct-q4_K_M`（provider 不设即默认） |
| 嵌入（向量） | `OWNRAG_EMBED_PROVIDER=openai` | SiliconFlow `https://api.siliconflow.cn/v1`（OpenAI 兼容 `/embeddings`，免费） | `BAAI/bge-m3`（1024 维） | Ollama `bge-m3`（`/api/embed`） |
| 重排 | `OWNRAG_RERANK_PROVIDER=siliconflow` | SiliconFlow `/v1/rerank`（免费） | `BAAI/bge-reranker-v2-m3` | Ollama `qllama/bge-reranker-v2-m3`（GGUF，`/api/embed` 标量分数） |
| 向量库 / 关键词 | 本地 | chromadb（持久化）+ SQLite FTS5 | — | 同左 |
| 音视频 ASR | 本地 | — | faster-whisper（medium） | FunASR 降级档 |

实测状态【2026-11-14 已实测】：SF 嵌入 1024 维 + 重排区分度（相关块 0.9888 / 无关块 0.0）、`/chat` SSE 端到端（引用回答、闸门全过）、MinerU 开放平台冒烟、`eval_recall` 8/8 判中 + 2/2 拒答。**魔搭 API-Inference 不 served 任何嵌入模型**（实测全变体 `Invalid model id`），勿再尝试。

注意：
- SiliconFlow 免费模型也要求账户有赠金/余额（新用户 14 元赠金需实名认证后发放），否则 HTTP 402。
- 换嵌入模型/供应商 = 必须换 `OWNRAG_EMBED_VERSION`（跨版本向量禁止混用）= 全量重灌索引。
- 换 reranker 模型需重新校准 `gates._MIN_RERANK_SCORE`（`data/eval/` 评测集就是校准数据）。
- 本地 Ollama 档的切换块已注释在 `.env` 对应小节，放开即切；Ollama 无原生 rerank 端点，本地重排走 reranker GGUF 的 `/api/embed` 标量分数模式（非 1 维输出会显式报错降级）。

## 模块 ↔ 文档映射

| 代码 | 设计文档 |
|---|---|
| `ownrag/core/`（registry / pipeline / tasks / trace / db） | `02-低代码编排与中台机制.md`（DSL + 六机制承接表） |
| `ownrag/ingest/`（base 契约 / pdf_mineru / mineru_openapi / av_asr / excel_staging） | `03-解析管道-PDF音视频Excel.md` |
| `ownrag/index/`（chunker / embedder / store） | `04-索引检索生成与闸门.md` §一§二 |
| `ownrag/retrieve/`（hybrid / rerank / direct_hit） | 同上 §三§四 |
| `ownrag/generate/`（ollama_client / openai_client / client 分派 / prompts / gates） | 同上 §五§六（两道闸门） |
| `ownrag/api/` + `main.py` | `01-总体架构.md`（五层架构 L1） |
| `scripts/eval_recall.py` + `data/eval/` | `05-评测运维与路线图.md` §一 |
| `ownrag/configs/`（models / pipelines / apps / prompts） | `02-低代码编排与中台机制.md`（低代码两层） |

## 技术栈

| 层 | 技术 |
|---|---|
| 语言 / 服务 | Python ≥3.10 · FastAPI + uvicorn（SSE 流式问答）· pydantic · python-multipart |
| 存储 | SQLite（任务表 / trace / qa_log / chunks / 直击库）+ FTS5 关键词通道 · chromadb 向量库（本地持久化） |
| 模型接入 | httpx 薄客户端 + 自研三层供应商分派（chat / embed / rerank：`ollama \| openai \| siliconflow`）——无模型 SDK、无 LangChain；具体服务商与模型见上节 |
| 解析链路（可选 extras） | MinerU（cli / http 服务 / mineru.net 开放平台）· PyMuPDF（页级路由探测 + 纯文本降级）· ffmpeg（抽音轨 + 关键帧，subprocess）· faster-whisper / FunASR（本地 ASR）· pandas + openpyxl（Excel staging 临时表） |
| 配置 / 编排 | PyYAML 管道 DSL（`configs/*.yaml` 即低代码入口）· python-dotenv（`.env`） |
| 前端 | 单文件 HTML 控制台（零构建、零 CDN，随包分发） |
| 测试 / 打包 | pytest（外部 HTTP/子进程全打桩，零出网）· setuptools wheel——重依赖全部做成可选 extra（`pdf / excel / vector / asr / funasr`），缺省时对应步骤按接口契约失败并进待办表，绝不静默 |

## 快速开始

```bash
cd ownrag
python -m venv .venv && .venv\Scripts\activate      # Windows；Linux: source .venv/bin/activate
pip install -e ".[pdf,excel,vector,asr]"            # 全组件；最小化 pip install -e . 也可（降级链会显式失败）
# 要复现"本机验证过的那套版本"（推荐，尤其半年后）：pip install -r requirements.lock.txt

copy .env.example .env                              # 复制即生效（python-dotenv 加载，不覆盖已有环境变量）
# .env 默认云端档：填 SiliconFlow key（嵌入+重排共用）与 agnes key（推理）即可，无需本地模型
# 本地 Ollama 档才需要拉模型（切换块见 .env 对应小节）：
ollama pull bge-m3                                  # 嵌入（OWNRAG_EMBED_PROVIDER=ollama 时）
ollama pull qwen2.5:7b-instruct-q4_K_M              # 推理（OWNRAG_CHAT_PROVIDER 未设时的默认档）
uvicorn ownrag.main:app --port 8420                 # 启动期校验：建表 + DSL 全量类型检查
# 控制台：http://127.0.0.1:8420/ui    API 文档：http://127.0.0.1:8420/docs
```

配置随包分发：`ownrag/configs/`（源码树与 wheel 安装同一路径）。运维改配置两种方式——
`OWNRAG_CONFIG_DIR` 指向自定义目录（不动包），或挂载覆盖。数据目录默认 `./data`（跟随工作目录，
不写进包目录）；`pip install ownrag==x.y.z` 装到只读镜像层也能正常起服务。

## 控制台（`/ui`）：操作 + 验证 + 14 天路线

单文件 HTML（零构建、零 CDN，随包分发），所有数据都来自真实接口，和线上链路同一批函数：

| 页签 | 用途 | 对应接口 |
|---|---|---|
| 概览 | 组件就绪、分块规模、待办数、部署自检 | `/admin/health` `/admin/metrics` `/admin/config` |
| 入库 | 拖拽上传 → 实时步骤时间线 → 失败重试 → 待办关闭 | `POST /docs/upload` `GET /admin/tasks/{id}` `POST /docs/tasks/{id}/retry` |
| 问答 | SSE 实时事件流（hit/ctx/gate/token/error），右栏是**模型真正看到的块** | `POST /chat` |
| 检索调试 | 只跑检索：双通道原始命中 → RRF → rerank → 预算裁剪 → 闸门一 | `POST /admin/retrieve` |
| 知识库 | 分块浏览 / FTS 关键词查询 / 直击库增删 | `GET /admin/chunks` `/admin/direct_hits` |
| 观测 | trace 逐步复盘、运行计数、问答日志 | `/admin/trace/{id}` `/admin/qa_log` |
| 14 天路线 | 每天一个目标 + 三个动作 + 一条验收标准，进度存本机 | — |

调试接口与问答共用 `hybrid / rerank / budget / gates`，所以**页面看到的预算与闸门结果就是线上跑的**，
不存在两套口径。

embedding 侧带熔断：后端不可达（本地 Ollama 没起 / 远程端点不通）时 20 秒内快速失败（此前每个请求要连撞两次、每次约 2 秒，
一次问答白等 4 秒以上），`/admin/health` 的 `embed_backend` 会显示熔断剩余时间。

### 端到端 demo（不起服务）

```bash
python scripts/run_demo.py --file 样例.pdf --question "报告里的报销口径是什么"
# 失败会看到：哪一步、什么原因、已入待办——"失败可见"是设计不是口号
```

### 召回测试

```bash
python scripts/eval_recall.py --qa data/eval/qa.example.jsonl --kb policy_v1
# 任何切分/embedding/解析器变更，先跑这个再合入（评测先行；全判中退出码 0，否则 1）
```

评测资产已入库（`data/eval/`）：`corpus_policy_example.md` 小语料 + 8 题问答集，判中口径三选一——
`expect` 任一关键词（找对）/ `expect_all` 全部要件（找全）/ `expect_empty` 无答案题（该拒答的拒答）。
拒答与生产同路径判定：检索 → 重排 → 闸门一。向量通道开启后检索层永远捞得回语义邻近块，
拒答语义从「零召回」迁移到「重排分不足」（`gates._MIN_RERANK_SCORE`，随本评测集校准）。
离线等价回归：`tests/test_eval_chain.py`（嵌入打桩为不可用，BM25 单路，不依赖外部服务）。

### 质量门禁（一个键，替代 CI）

```bash
check.bat               # Windows：ruff -> mypy -> pytest + coverage（覆盖率门槛 70%，当前 72%）
check.bat eval          # 再加召回回归（需 data/ 已有 policy_v1 语料；全新 clone 上 0 命中属正常）
```

```bash
python -m pytest        # 104 例：契约/执行器/闸门/切分/存储生命周期/检索融合/问答编排/评测链路/三层供应商分派打桩，全程不依赖外部服务
python -m ruff check .  # lint（E/F/W/I/B；中文长句注释不折行）
python -m mypy          # 类型检查（口径见 pyproject [tool.mypy]）
```

当前值：覆盖率 74.55%（门槛 70%）。依赖版本走 `requirements.lock.txt`（钉直接依赖到实测通过的版本，
传递依赖不锁）——升级流程是「改 pyproject → 装上去跑 `check.bat` → 绿了再同步 lock 版本号」。

口径：**骨架不追平台件**（无 Docker/K8s/CI 流水线/多租户鉴权/限流），但**已有的代码必须可验证** ——
lint、类型、测试、覆盖率四道闸全部本地一键跑，跑不过就修，不加 ignore 阈值放水。

## 三条解析链路（ownrag/configs/pipelines.yaml 即低代码入口）

| 管道 | 链路 | 降级链 |
|---|---|---|
| `pdf_v1` | detect_pages 页级路由 → MinerU（pipeline/VLM）→ 校验 → 切分 → 索引 | MinerU↔后端互换 → PyMuPDF 纯文本 → 待办 |
| `av_v1` | ffmpeg 抽音轨+关键帧 → 本地 ASR（faster-whisper）→ 语义切分（停顿/句尾优先，`[mm:ss]` 锚点）→ 关键帧 OCR（可选）→ 索引 | faster-whisper → FunASR → 待办；OCR 不可用显式 skipped |
| `excel_v1` | 全 TEXT 落 staging 临时表 → schema 推断 → 列映射（LLM 建议+人工确认）→ row_card 文本化 → 索引 | 映射待办人工确认 |

## 骨架边界（诚实清单，对应 05 文档路线图）

- **已落位**：DSL 执行器（检查点/fallback/待办）、三链路适配、结构感知切分、AV 语义切分（停顿/句尾 + 时间锚结构化 `anchors.t`）、关键帧 OCR 分字段、FTS5 关键词通道、混合检索 RRF、直击库、两道闸门、SSE 问答、trace、**块级版本链（pipeline/chunker/split_params/embed_version）**、评测集与评测脚本、契约测试、**删除端点（三通道退出可检索）**、**控制台 `/ui`（含 14 天路线）**、**上下文预算裁剪（超窗丢块可见）**、**KB 白名单 + 上传体积上限**、**配置随包分发（wheel/只读镜像可解析）**、**embedding 熔断（后端挂掉不再拖慢每个请求）**、**三层供应商分派（chat / embed / rerank：ollama | openai | siliconflow，云-本地 `.env` 一键切）**、**闸门一重排分阈值（拒答语义随向量通道迁移，评测集校准）**。
- **问答编排分层**：`routes_chat._stream` 只负责事件顺序，动作拆成 `_search / _rerank / _fit_context / _answer_stream / _repair_answer / _log_qa` 六个可单测单元（`tests/test_chat_steps.py`），修复分支与预算砍块都有独立断言。
- **显式降级**：chromadb 未装/不可用 → 向量通道跳过（BM25 单路，metric 可见）；rerank 未配置或服务挂 → RRF 兜底（说明随事件/trace 可见）；MinerU/ASR 未装 → 降级链穷尽后进待办；候选超上下文预算 → 按序丢尾块并下发 `gate(context_budget)` 事件；检索只捞回语义邻近块而无实质依据 → 闸门一按重排分下限拒答（`no_evidence`，零模型消耗）。
- **M2 待办**：aggregate 文本化的 SQL 路径、元数据权限过滤接线、直击库 L2 回流、评测基线数字、闸门/rerank 编排配置化（当前只读 env 与代码内固定顺序）、鉴权与任务队列（长任务仍在进程内线程池）。
- **【设计·未实现】**：工具网关（意图分流 + 业务 API 代理）与元数据级 / 工具级权限 —— 代码里只有**知识库级白名单**（`config.known_kbs`），别把它当权限体系；四件套逐项落地进度见 `../02-低代码编排与中台机制.md` §四。
- **不做**：训练微调、多租户 SaaS、复杂前端（管理面 = JSON API，页面壳后置）；平台件（Docker / K8s / CI 流水线 / 限流 / 多租户鉴权）—— 单机私有化定位，本地门禁 `check.bat` 替代 CI。

## 口径红线（改代码/写材料前看）

1. 本工程描述与代码**不得写进公司平台能力清单**。
2. 指标一概 `【设计】`/`【待实测】`——评测基线属 M2 产出。
3. 与 288 篇 RAG 语料的原理内容不重复：本仓库只写工程实现，原理指向 `../../../personal-investment-notes/02-AI智能体/00-知识库/RAG/`。
