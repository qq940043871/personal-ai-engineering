# 06 · RAG 全链路梳理与「视频 RAG」问题逐条对照

> **输入**：① 对本仓库三个 RAG 子工程的全链路梳理要求——每个环节都要有可运行的验证手段；
> ② 博主文章：吴师兄大模型《视频 RAG 怎么做：为什么 PDF 能搜，视频不能直接入库》
> <https://www.wushixiongai.com/questions/project/rag/video-ingestion>（2026-07-14）。
>
> **产出**：三个子工程的环节×可验证性清单（§1）、博主问题逐条对照与本次改进（§2/§3）、
> 验证手册（§4）、剩余缺口（§5）。指标口径不变：一概 `【设计】`/`【待实测】`，本文不填任何实测数字。

---

## 1. 三个子工程：环节 × 可验证性

三个子工程定位不同，可验证性的目标线也不同：

| 子工程 | 定位 | 可验证性目标线 |
|---|---|---|
| `ai-rag-ollama/` | LangChain 入门教程代码（Flask + Chroma） | 能跑通即验证；**不补工程化测试**（补了反而失真） |
| `ai-rag-dify/` | Dify/RAGFlow 的预处理 + 灌库工具（检索/生成托管服务端） | 预处理环节离线可验（质量门禁）；API 脚本靠内网手工跑 |
| `ai-rag-self-engineering/ownrag/` | 自研 RAG 工程（本文主线） | **每个环节都有自动化验证**：pytest 全离线 + 评测脚本 + 质量闸门 |

### 1.1 环节清单（ownrag 主链路，含本次改进后状态）

| 环节 | 实现 | 离线可验证手段 |
|---|---|---|
| 解析（PDF） | `ingest/pdf_mineru.py` + 页级路由 | 契约测试（ParsedDoc）；真实解析靠 MinerU（`ai-rag-dify/01-minerU-block/09_quality_gate.py` 同口径门禁） |
| 解析（音视频） | `ingest/av_asr.py`：ffmpeg 抽流 → ASR → **语义切分** | `tests/test_av_chain.py`：切分/锚点/结构全离线（ASR/ffmpeg 本体不测，属外部依赖） |
| 解析（Excel） | `ingest/excel_staging.py` staging 临时表 | `tests/test_api.py` CSV 入库用例 |
| 校验 | `validate_parsed` 步骤：产出不可用 = 解析失败同待遇 | 契约测试 + 执行器测试 |
| 切分 | `index/chunker.py`：结构感知、表格永不跨块、**AV 时间锚结构化** | `test_contract.py`（表格）+ `test_av_chain.py`（时间锚） |
| 向量化 | `index/embedder.py`（Ollama bge-m3，20s 熔断） | `test_embedder.py`（httpx 打桩） |
| 入库 | `index/store.py`：SQLite FTS5 + Chroma 双通道，**按 doc_id 幂等替换** | `test_store_lifecycle.py`（重灌/删除/版本链） |
| 检索 | `retrieve/hybrid.py`：双路 → RRF，通道贡献可追溯 | `test_retrieve.py` + `test_eval_chain.py`（BM25 单路端到端） |
| 重排 | `retrieve/rerank.py`（可选服务） | `test_retrieve.py`：未启用兜底 / 成功重排 / 失败降级三态 |
| 直击库 | `retrieve/direct_hit.py` L0/L1/L2 | `test_ui.py` 增删与白名单用例 |
| 生成前闸门 | `generate/gates.py` sufficiency_check | `test_contract.py` + `test_eval_chain.py`（无答案题必须拒答） |
| 上下文预算 | `generate/budget.py` | `test_budget.py` 6 例 |
| 生成后闸门 | citation_check（引用存在 + 数字在原文） | `test_contract.py`（假引用/无引用数字） |
| 引用溯源 | SSE `ctx`/`done` 事件携带 `anchors`（PDF 页码 / **AV `t:08:12-08:27`**） | anchors 从切分层一路透传，`test_av_chain.py` 锁锚点正确性 |
| 评测 | `scripts/eval_recall.py` + `data/eval/`（语料+问答集，**已入库**） | `test_eval_chain.py`（判中口径三选一）+ 脚本端到端 |
| 删除退出 | `DELETE /docs/{doc_id}`：chunks/FTS/向量三通道一次清 | `test_store_lifecycle.py` |
| 观测 | `core/trace.py` 每步一行；块上留**版本链**（pipeline/chunker 参数/split_params/embed_version） | `test_pipeline.py` + `test_store_lifecycle.py` |
| 权限过滤 | **设计位（M2）**：`hybrid.search` metadata_filter 参数位 | 未实现 = 诚实清单，不做假验证 |

### 1.2 另两个子工程的环节缺口（按定位处置）

- `ai-rag-ollama/`：解析只有 txt、无清洗/重排/评测，零测试，硬依赖本机 Ollama——**保持教程定位**，
  README 已说明运行前提；`study/` 与根目录脚本的重复以 README「可运行入口」为准。
- `ai-rag-dify/`：解析/分片/质量门禁（`09_quality_gate.py`，PASS/WARN/FAIL + 退出码）离线可验；
  向量化/检索/重排/生成托管在 Dify 服务端，本地**只有配置没有代码**——这部分的可验证性 = 服务端
  配置核对 + 人工问答抽检，写入下方 §5 缺口；03~08 API 脚本硬编码内网地址与占位 Key，离线跑不了
  （符合"内网工具"定位，但 dataset_id 等 UUID 应改为运行时参数）。
- 根 README 提到的 `ai-study-labs/10_docs/`（RAGFlow 部署记录）已随迁移不存在——文档漂移，本次修根 README。

---

## 2. 博主问题 → ownrag 对照总表

博主文章的论点按"入库前 / 检索与回答 / 评测与运维"三组对照。**结论先行**：ownrag 的架构方向
（ParsedDoc 契约、锚点即引用、两道闸门、评测先行）与文章主张一致；本次补齐的是 6 处实现缺口 +
1 个真 bug。

| # | 博主问题 | ownrag 现状（梳理时） | 本次处置 |
|---|---|---|---|
| 1 | 视频不能直接入库：索引的是可搜索、可定位、可核验的内容片段，不是文件名 | `av_v1` 管道链路方向正确（ffmpeg→ASR→切分→索引） | 方向确认，无改动 |
| 2 | ASR 必须带时间戳；时间丢了，字幕和画面"像被打乱的两摞卡片" | 段级时间戳有；**但切分器溢出后 `buf_start` 不重置——第 2 块起块头锚点恒为 `00:00`**，引用跳转会指到视频开头 | **真 bug 修复** + 回归测试（`test_av_chain.py::test_block_anchor_matches_first_segment_start`） |
| 3 | 字幕不能随便切：按标点、停顿、间隔、连贯性合并，"每段独立说清一件事" | 只按 `max_sec` 时长硬切，不看停顿与句尾 | `segment_by_time` 增加 `gap_sec` 停顿切分 + 超限回退最近句尾（不拦腰截断），参数随块存档 |
| 4 | 画面 OCR 不能直接拼到字幕后面：分字段保存、冲突标出来、不让模型自己挑 | 关键帧抽了（`kf_*.jpg`）但 OCR 环节缺失，`Structure` 契约里 keyframe/`t:` 锚点定义了却没人填 | 新增 `ocr_keyframes` 步骤：画面文字进 `structures.ocr_text` 字段（`Structure` 增 `text` 字段），**不拼进正文**；OCR 不可用显式 skipped |
| 5 | 内容 + 来源两类信息缺一不可：视频名/起止时间/章节必须结构化保存 | 时间只内嵌在正文文本里；`Chunk.anchors` 只拷贝 doc 级 page/t/row_range——`base.py`"锚点即引用"的契约对 AV 半实现 | chunker 对 `source_type=av` 提取块内首末 `[mm:ss]` → `anchors["t"]="08:12-08:27"`，随 SSE `ctx`/`done` citations 透传 |
| 6 | 无答案要拒答：门槛不能凭感觉，用"有答案 + 没答案"两类问题测 | 闸门一（sufficiency）存在；评测脚本无拒答口径，无答案题没法测 | `eval_recall.py` 增 `expect_empty` 口径（零召回才算过）；评测集配 2 道无答案题；`test_eval_chain.py` 锁口径 |
| 7 | 评测四项检查：找对、找全、不乱说、指对位置 | `eval_recall` 只有"任一关键词命中"（找对的一半）；评测集文件不存在（开箱跑不了） | 评测资产落地（`data/eval/` 语料 + 8 题问答集，四类题型齐全）；`expect_all`=找全；"不乱说"=闸门二已有；"指对位置"=#5 |
| 8 | 答案错了要能定位到环节：留存问题/实际查询/召回片段/时间范围/上下文/来源 | trace 每步一行 + `hybrid.search` 返回双路原始命中 + SSE `ctx` 事件回传候选与 anchors | 已达标，无改动 |
| 9 | 处理版本链：ASR/合并规则/切分配置变更要有版本，否则引用无法稳定比较 | 只有 `embed_version` 落库 | 版本链补全：块 meta 记录 `pipeline` + `chunker` 参数；AV `metadata.split_params` 随块入 meta（`test_store_lifecycle.py` 锁留痕） |
| 10 | 重灌防旧字幕：幂等替换而非追加；回归后原子切换 | `index_upsert` 先删后插（幂等）**但零测试** | `test_store_lifecycle.py::test_reingest_replaces_old_chunks`：旧内容退出 chunks/FTS 两通道、检索不命中 |
| 11 | 删除/权限：派生数据（字幕/向量/映射）全部退出可检索；权限贯穿文件/索引/缓存 | `keyword_delete_doc`/`vector_delete_doc` 零件存在但 **API 层没有删除端点**——有零件没装配 | 新增 `DELETE /docs/{doc_id}`（三通道一次清 + 404 契约）；权限过滤维持 M2 设计位（诚实清单） |

**没采纳的一条**：博主建议"片段身份包含视频文件版本 + 内容摘要"做新旧索引 diff 后原子切换——
骨架期重灌即整 doc 替换（`replace_by_doc`），粒度足够；块级 diff 属 M2，不提前实现假接口。

---

## 3. 本次落地清单（文件级）

| 文件 | 改动 |
|---|---|
| `ownrag/ingest/av_asr.py` | ① 修 `buf_start` 锚点 bug；② `segment_by_time` 语义切分（`gap_sec` + 句尾回退）；③ 切分参数写 `metadata.split_params`；④ 关键帧登记 `structures`（带 `t:` 锚点）；⑤ 新增 `ocr_keyframes` 步骤（`_OCR_FN` 注入点，测试可打桩） |
| `ownrag/ingest/base.py` | `Structure` 增 `text` 字段（OCR 画面文字分字段，不拼接进 markdown） |
| `ownrag/index/chunker.py` | ① `source_type=av` 时提取块内首末时间锚 → `anchors["t"]`；② `ChunkMarkdown` 步骤把 `pipeline` 名与切分参数写进块 meta（版本链） |
| `ownrag/core/pipeline.py` | 执行器把 `_pipeline` 写入步骤黑板（版本链源头） |
| `ownrag/api/routes_docs.py` | 新增 `DELETE /docs/{doc_id}`：chunks/FTS/向量三通道一次清，降级可见 |
| `ownrag/configs/pipelines.yaml` | `av_v1` 挂 `ocr_keyframes` 步骤；`segment_by_time` 参数补 `gap_sec: 1.5` |
| `ownrag/retrieve/rerank.py` | `httpx` 提升为模块级导入（可打桩；与 embedder 同风格） |
| `scripts/eval_recall.py` | 判中口径三选一（`expect`/`expect_all`/`expect_empty`）；报告增 `refusal` 统计；退出码改为**全判中才过**（门禁语义） |
| `data/eval/corpus_policy_example.md` | 新增评测语料（年假/报销/考勤，含表格——顺带覆盖表格不跨块） |
| `data/eval/qa.example.jsonl` | 新增 8 题问答集：原话 2 / 换说法 2 / 找全 2 / 无答案 2（`.gitignore` 放行 `data/eval/`，评测资产进 Git） |
| `tests/test_av_chain.py` | 新增 8 例：锚点 bug 回归、停顿切分、句尾回退、版本参数、关键帧结构、OCR 分字段、OCR 降级、AV 块时间锚 |
| `tests/test_store_lifecycle.py` | 新增 4 例：幂等重灌、删除退出可检索、版本链留痕、删除端点 |
| `tests/test_retrieve.py` | 新增 5 例：RRF 融合/通道贡献/top_n、rerank 三态 |
| `tests/test_eval_chain.py` | 新增 5 例：问答集格式契约、有答案题必命中、无答案题必拒答、评测脚本端到端、资产缺失显式失败 |
| `tests/test_contract.py` | 补 `schema_check` 三态直接用例 |

测试规模：33 → **56 例**，全部离线（不依赖 ffmpeg/Ollama/MinerU/chromadb，外部依赖一律打桩或降级路径）。

---

## 4. 验证手册（每条都可运行）

```bash
cd ai-rag-self-engineering/ownrag

# 1. 全量契约测试（离线，外部依赖全部打桩）
python -m pytest                                  # 56 例

# 2. 评测门禁（需先灌语料：把 data/eval/corpus_policy_example.md 按 pdf_v1 灌入 policy_v1，
#    或用 /ui 入库页上传；测试内的等价离线回归是 tests/test_eval_chain.py）
python scripts/eval_recall.py --qa data/eval/qa.example.jsonl --kb policy_v1
# 退出码 0 = 8 题全判中（含 2 道无答案题零召回）；任何切分/embedding/解析器变更先跑它

# 3. AV 链路单项（不需要真实音视频——切分与锚点是纯确定性逻辑）
python -m pytest tests/test_av_chain.py -v

# 4. 端到端 demo（需 Ollama + 真实文件；失败可见到哪一步、什么原因）
python scripts/run_demo.py --file 样例.pdf --question "报告里的报销口径是什么"

# 5. 服务启动即门禁（DSL 步骤类型全量校验，av_v1 的 ocr_keyframes 未注册会启动期爆）
uvicorn ownrag.main:app --port 8420
```

---

## 5. 剩余缺口（诚实清单，按 05 文档路线图归位）

1. **评测基线数字**：`qa.example.jsonl` 是示例集；真实评测集扩充与 Top-K 命中率/引用准确率基线仍属 M2
   `【待实测】`。本文与代码不填任何数字。
2. **真实解析器测试**：`pdf_mineru`/`av_asr` 的外部调用（MinerU CLI/HTTP、faster-whisper）只有降级链
   测试，真实解析质量靠 `ai-rag-dify/01-minerU-block/09_quality_gate.py` 门禁手工跑——两处接口契约
   目前靠人工同步，M2 考虑契约测试。
3. **块级 diff 重灌**：博主"新旧索引比对后原子切换"——`replace_by_doc` 整 doc 替换已覆盖骨架期需求，
   块级 diff 归 M2。
4. **权限过滤接线**：`hybrid.search` 的 `metadata_filter` 参数位已留，密级/时间过滤与缓存键带权限属 M2；
   `ai-rag-dify` 侧检索/重排/生成托管在 Dify 服务端，本地无代码——其可验证性 = 服务端配置核对
   （embedding=qwen3-embedding-8b-vllm / hybrid_search top_k=8 / bge-reranker-v2-m3）+ 人工问答抽检。
5. **`ai-rag-ollama`**：保持教程定位不补工程化测试；`02-ocr/` 三个脚本的历史绝对路径在运行前需手改
   （README 已注明）。
6. **密钥卫生**：上传工具内为占位 Key（已脱敏）；本地 `secrets_backup.txt` 存有真实 Key（已 gitignore），
   建议迁移进密码管理器后删除明文文件。
