# ownrag · 自研 RAG 工程（代码骨架）

> **口径先读**：本工程 = 个人实战骨架（Python + FastAPI），与 `../../../personal-investment-notes/02-AI智能体/01-认知框架/Harness-详细设计与项目落地.md` 同一条个人线；**不是公司平台技术栈**（公司 = Java 中台 + Dify 智能层）。设计文档见上级目录 `00`–`05` 五篇，模块与文档一一对应。

## 一句话

不使用 Dify、不引入 LangChain：**Ollama 本地模型 + 配置驱动管道 DSL + 三条解析链路（MinerU PDF / ffmpeg+本地ASR 音视频 / Excel 临时表）+ 混合检索 + 两道纯代码闸门 + 评测脚本**。

## 模块 ↔ 文档映射

| 代码 | 设计文档 |
|---|---|
| `ownrag/core/`（registry / pipeline / tasks / trace / db） | `02-低代码编排与中台机制.md`（DSL + 六机制承接表） |
| `ownrag/ingest/`（base 契约 / pdf_mineru / av_asr / excel_staging） | `03-解析管道-PDF音视频Excel.md` |
| `ownrag/index/`（chunker / embedder / store） | `04-索引检索生成与闸门.md` §一§二 |
| `ownrag/retrieve/`（hybrid / rerank / direct_hit） | 同上 §三§四 |
| `ownrag/generate/`（ollama_client / prompts / gates） | 同上 §五§六（两道闸门） |
| `ownrag/api/` + `main.py` | `01-总体架构.md`（五层架构 L1） |
| `scripts/eval_recall.py` + `data/eval/` | `05-评测运维与路线图.md` §一 |
| `ownrag/configs/`（models / pipelines / apps / prompts） | `02-低代码编排与中台机制.md`（低代码两层） |

## 快速开始

```bash
cd ownrag
python -m venv .venv && .venv\Scripts\activate      # Windows；Linux: source .venv/bin/activate
pip install -e ".[pdf,excel,vector,asr]"            # 全组件；最小化 pip install -e . 也可（降级链会显式失败）

copy .env.example .env                              # 复制即生效（python-dotenv 加载，不覆盖已有环境变量）
ollama pull bge-m3
ollama pull qwen2.5:7b-instruct-q4_K_M
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

embedding 侧带熔断：Ollama 不可达时 20 秒内快速失败（此前每个请求要连撞两次、每次约 2 秒，
一次问答白等 4 秒以上），`/admin/health` 的 `embed_backend` 会显示熔断剩余时间。

### 端到端 demo（不起服务）

```bash
python scripts/run_demo.py --file 样例.pdf --question "报告里的报销口径是什么"
# 失败会看到：哪一步、什么原因、已入待办——"失败可见"是设计不是口号
```

### 召回测试

```bash
python scripts/eval_recall.py --qa data/eval/qa.example.jsonl --kb policy_v1
# 任何切分/embedding/解析器变更，先跑这个再合入（评测先行）
```

### 测试

```bash
python -m pytest        # 执行器/闸门/切分契约，全程不依赖外部服务
```

## 三条解析链路（ownrag/configs/pipelines.yaml 即低代码入口）

| 管道 | 链路 | 降级链 |
|---|---|---|
| `pdf_v1` | detect_pages 页级路由 → MinerU（pipeline/VLM）→ 校验 → 切分 → 索引 | MinerU↔后端互换 → PyMuPDF 纯文本 → 待办 |
| `av_v1` | ffmpeg 抽音轨+关键帧 → 本地 ASR（faster-whisper）→ 按时间切分（`[mm:ss]` 锚点）→ 索引 | faster-whisper → FunASR → 待办 |
| `excel_v1` | 全 TEXT 落 staging 临时表 → schema 推断 → 列映射（LLM 建议+人工确认）→ row_card 文本化 → 索引 | 映射待办人工确认 |

## 骨架边界（诚实清单，对应 05 文档路线图）

- **已落位**：DSL 执行器（检查点/fallback/待办）、三链路适配、结构感知切分、FTS5 关键词通道、混合检索 RRF、直击库、两道闸门、SSE 问答、trace、评测脚本、契约测试、**控制台 `/ui`（含 14 天路线）**、**上下文预算裁剪（超窗丢块可见）**、**KB 白名单 + 上传体积上限**、**配置随包分发（wheel/只读镜像可解析）**、**embedding 熔断（后端挂掉不再拖慢每个请求）**。
- **显式降级**：chromadb 未装 → 向量通道跳过（BM25 单路，metric 可见）；rerank 未配置 → RRF 兜底；MinerU/ASR 未装 → 降级链穷尽后进待办；候选超上下文预算 → 按序丢尾块并下发 `gate(context_budget)` 事件。
- **M2 待办**：aggregate 文本化的 SQL 路径、元数据权限过滤接线、直击库 L2 回流、评测基线数字、闸门/rerank 编排配置化（当前只读 env 与代码内固定顺序）、鉴权与任务队列（长任务仍在进程内线程池）。
- **不做**：训练微调、多租户 SaaS、复杂前端（管理面 = JSON API，页面壳后置）。

## 口径红线（改代码/写材料前看）

1. 本工程描述与代码**不得写进公司平台能力清单**。
2. 指标一概 `【设计】`/`【待实测】`——评测基线属 M2 产出。
3. 与 288 篇 RAG 语料的原理内容不重复：本仓库只写工程实现，原理指向 `../../../personal-investment-notes/02-AI智能体/00-知识库/RAG/`。
