# ai-rag-dify / python

基于 **Dify 知识库 API** 的文档导入工具集，核心目标是：把一份**中文 Markdown 长文档**（如《郑大乾坤鉴》类中医典籍/资料），按**自定义分隔符**切成"父分段 + 子分段"的**层级结构（hierarchical model）**，再灌入 Dify 知识库，从而精确控制 RAG 检索时的切块粒度。

> 之所以要自己写脚本，是因为 Dify 内置的自动切分对中文长文控制力弱。这里的思路是：**用特殊符号（`@!@`、`@@`）在原文里预埋切分标记**，再让 Dify 按这些标记切分。

---

## 一、整体思路

```
PDF / 扫描件
   │
   │ ⓿ MinerU 解析为 md  (00_pdf_to_md_mineru.py)
   │    调 MinerU CLI 或 HTTP 服务，并做结构归一化（补齐 # / ## / ###）
   ▼
原始 Markdown
   │
   │ ① 预埋标记  (02_add_split_to_periods.py)
   │    在编号小节(如 3.2.1)前插入 @@  ← 作为「子分段」边界
   ▼
带 @@ 标记的 md
   │
   │ ② 切片 + 补标题  (01_main_append_title / 01_main_append_improve)
   │    按 @!@ 切段，每段自动补上「一级/二级/三级标题 + (第N部分)[共M部分]」
   ▼
切好的分段文件 (sliced_output.md / 1_1_new_process.md)
   │
   │ ③ 灌库 (08_create_by_file.py / knowledge_base_uploader.py / process_segments.py)
   │    用 Dify API 上传，切分规则：
   │      separator = @!@  → 父分段(parent chunk)，max_tokens 2000
   │      subchunk separator = @@ → 子分段(child chunk)，max_tokens 1000
   │      检索: hybrid_search + bge-reranker-v2-m3 重排 top_k=8
   ▼
Dify 知识库（层级分段）
```

**关键约定：**

| 符号 | 含义 | Dify 对应参数 |
|------|------|--------------|
| `@!@` | 父分段（分段）分隔符 | `segmentation.separator` |
| `@@` | 子分段（子块）分隔符 | `subchunk_segmentation.separator` |

---

## 二、第 0 步：MinerU 把 PDF 解析成 Markdown

`00_pdf_to_md_mineru.py` 负责把 **PDF / 扫描件 → 带标题层级的中文 md**，是上面三步之前的一环。之所以单独成脚本：`01_main_append_title.py` 找不到 `# ` 会直接抛「未找到一级标题」，找不到 `## ` 会**静默产出空文件**，所以必须保证 MinerU 的产物有 H1/H2/H3 结构。

```bash
# 电子版 PDF（快）
python 00_pdf_to_md_mineru.py 结算细则.pdf -o ./mineru_out

# 扫描件 / 多栏复杂版式（准，吃显存）
python 00_pdf_to_md_mineru.py 结算细则.pdf -b vlm

# 目录批量
python 00_pdf_to_md_mineru.py ./pdfs -o ./mineru_out

# 走 MinerU 服务化部署（不装本地 CLI）
python 00_pdf_to_md_mineru.py 结算细则.pdf --base-url http://127.0.0.1:8888
```

**两种接入形态（接口契约与 `ai-rag-self-engineering/ownrag/ownrag/ingest/pdf_mineru.py` 对齐）：**

| 形态 | 调用 | 说明 |
|------|------|------|
| CLI（默认） | `mineru -p <pdf> -o <out_dir> [-b pipeline\|vlm] [-l ch]` | 在 `out_dir` 下 `rglob("*.md")` 取第一个 md，同目录的 `*.png/jpg` 即图片资源 |
| HTTP | `POST {base}/file_parse`，multipart 传 `file` + `backend`/`lang` | 期望返回 `{"markdown": str, "pages": int, "assets": dict}`；本地服务不穿代理 |

**产物**：`<out>/<pdf名>/<MinerU 原始 md>` 与 `<pdf名>_norm.md`（归一化结果，喂给 `02_add_split_to_periods.py`）。

**归一化做了什么（只做结构保底，不改写正文）：**

1. 重复出现 ≥5 次的短行（页眉/页脚/页码）删除，`--dedup-repeat 0` 可关闭；
2. 多个 `# ` 一级标题时保留第一个，其余降级为 `## `（MinerU 常把每章识别成 H1）；
3. 全文没有 `# ` 时，用文件名（或 `--title`）补一行 H1；
4. 完全没有 `## ` 时，把顶层编号行 `1. 总则` 提升为 `## `；完全没有 `### ` 时，把 `1.1. 制定目的` 提升为 `### `；
5. **不动正文行首编号**（如 `2.1.1. 按照规则…`）——那是留给 `02_add_split_to_periods.py` 插 `@@` 的锚点；
6. 代码块（``` / `~~~`）与 Markdown 表格行一律跳过，避免误判。

**注意事项：**

- MinerU 可能把正文粗体句误判成标题，也可能漏掉编号标题；跑完看脚本打印的结构统计（H1/H2/H3/行首编号），**H2=0 或行首编号=0 时会给出警告**，此时需人工抽查后再进下一步。
- 图片：`create-by-file` 上传时 md 里的相对图片路径不会带走图片，需要留图就改用 `create-by-text` 并在正文里拼图片地址，或接受图片丢失。
- 需本机装 MinerU（`pip install -U "mineru[core]"`），或使用 `--base-url` 指向已部署服务。

---

## 三、文件清单与作用

### PDF → Markdown（第 0 步）

| 文件 | 作用 |
|------|------|
| `00_pdf_to_md_mineru.py` | 调 MinerU（CLI 或 HTTP）把 PDF/扫描件解析成 md，并做结构归一化（补 H1/H2/H3、去重复页眉页脚、保护行首编号），保证下游 `01_`/`02_` 能跑通。详见上节。 |

### 文本预处理（在本地切分 Markdown）

| 文件 | 作用 |
|------|------|
| `02_add_split_to_periods.py` | 在 `3.2.1` 这类编号小节前插入 `@@`，作为**子分段边界**。避免重复添加（负向后顾 `(?<!@@)`）。 |
| `01_main_append_title.py` | **按 `@!@` 把 Markdown 切成若干段**，并为每段补回上下文标题：`# 主标题(第N部分)[共M部分]`、`## H2...`、`### H3...`。这样每个分段都自带标题语境，减少检索时"断章取义"。 |
| `01_main_append_improve.py` | 同上，改进版：保留 H2/H3 两级标题结构，输出更细的层级与统计（打印一级标题总数）。 |

用法：
```bash
python 01_main_append_title.py <input.md> [output.md]
python 02_add_split_to_periods.py <input.md> [output.md]
```

### 直接调 Dify API 的示例脚本（编号 03~08）

这些是**按 API 类型拆分的独立示例**，不是必须按顺序执行的流水线，改一下 `dataset_id` / `document_id` / `api_key` 即可单独使用：

| 文件 | 对应 Dify API | 说明 |
|------|--------------|------|
| `03_request_datasets.py` | `GET /v1/datasets` | 列出知识库 |
| `03_create_by_file.py` | `POST .../document/create-by-text` | 用**纯文本**创建文档（自动/层级切分） |
| `04_get_documents.py` | `GET .../documents` | 列出知识库下的文档 |
| `05_post_segments.py` | `POST .../documents/{id}/segments` | 手工创建**父分段** |
| `06_post_child_chunks.py` | `POST .../segments/{id}/child_chunks` | 手工创建**子分段** |
| `07_delete_segments.py` | `GET/DELETE .../segments` | 拉取文档全部分段并**逐个删除**（清库/重灌用） |
| `08_create_by_file.py` | `POST .../document/create-by-file` | 用**文件**创建文档，自定义切分规则（`@!@` + `@@`，见下方 payload） |

`08_create_by_file.py` 中最关键的切分配置：
```python
"segmentation":          {"separator": "@!@", "max_tokens": 2000},  # 父分段
"subchunk_segmentation": {"separator": "@@",  "max_tokens": 500},   # 子分段
"doc_form": "hierarchical_model"
```

### 批量灌库脚本

| 文件 | 作用 |
|------|------|
| `process_segments.py` | 读取 md → 按 `@!@` 切段 → 逐个调用 segments 接口上传父分段（无 GUI 的批量版本）。 |

### GUI 工具（重点）

| 文件 | 作用 |
|------|------|
| `knowledge_base_uploader.py` | **Tkinter 图形化上传工具**，把整套流程做成一个可操作的界面，是这套脚本的"成品"：<br>1. 配置访问地址 / 密钥 / 知识库ID；<br>2. 选择本地 md 文件并读取；<br>3. **「创建」按钮**：调用 `create-by-text` 建一个**空文档**，拿到 `document_id`（同时预设 embedding=`qwen3-embedding-8b-vllm`、rerank=`bge-reranker-v2-m3`、`hybrid_search`、`top_k=8`、父子分段规则）；<br>4. **「上传分段」按钮**：按分隔符切分文件内容，逐条 POST 到 `.../segments` 上传父分段；<br>5. 线程化执行（界面不卡死）、进度条、可取消、实时日志。 |
| `knowledge.spec` | PyInstaller 打包配置，把 `knowledge_base_uploader.py` 打包成无控制台的 `knowledge.exe`。 |

打包命令：
```bash
pyinstaller knowledge.spec
```

### 质量门禁（A 解析 + B 分片）

| 文件 | 作用 |
|------|------|
| `09_quality_gate.py` | 把"MinerU 解析准不准"和"分片准不准"变成可重复的指标检查，输出 PASS/WARN/FAIL 报告与退出码（详见第六节）。 |

### 其他

| 文件 | 作用 |
|------|------|
| `document.json` | 一份 `create-by-file` 请求体的**完整示例 JSON**，可作为切分/检索参数模板参考。 |

---

## 四、典型使用流程

**方式 A：用 GUI 工具（推荐）**
1. `python knowledge_base_uploader.py`
2. 填入访问地址、密钥、知识库ID
3. 选择已预处理好（含 `@!@` / `@@` 标记）的 md 文件
4. 点「创建」建空文档 → 拿到文档ID
5. 点「上传分段」→ 自动逐段上传

**方式 B：命令行流水线**
```bash
# 1. 预埋 @@ 子分段标记
python 02_add_split_to_periods.py 原文.md 1_1_new_process.md
# 2. 切片并补标题
python 01_main_append_title.py 1_1_new_process.md sliced_output.md
# 3. 上传（改成自己的 dataset_id / api_key）
python 08_create_by_file.py
```

**方式 C：从 PDF 一路到底（新增第 0 步）**
```bash
# 0. PDF → 结构化 md（MinerU）+ 结构归一化
python 00_pdf_to_md_mineru.py 结算细则.pdf -o ./mineru_out
#    产物：./mineru_out/结算细则/结算细则_norm.md

# 1. 预埋 @@ 子分段标记
python 02_add_split_to_periods.py ./mineru_out/结算细则/结算细则_norm.md 1_1_new_process.md
# 2. 按 @!@ 切片并补回标题
python 01_main_append_title.py 1_1_new_process.md sliced_output.md
# 3. 灌库（推荐用 GUI 工具，见方式 A）
python knowledge_base_uploader.py
```

---

## 五、使用前须知

- **必须替换占位符**：所有脚本中的 `dataset-REPLACE_WITH_YOUR_KEY` / `ragflow-REPLACE_WITH_YOUR_KEY` 与硬编码的 `dataset_id` / `document_id` / 文件路径（如 `D:\郑大乾坤鉴\1.md`）都需改成自己的值。
- **服务地址**：默认指向内网 Dify，如 `http://10.17.1.134:30001`。
- **依赖**：`requests`；GUI 工具额外用到标准库 `tkinter`（Windows 自带）；打包需 `pyinstaller`；`00_pdf_to_md_mineru.py` 需要 MinerU 本体（`pip install -U "mineru[core]"`）或一个已部署的 MinerU 服务地址。
  ```bash
  pip install requests
  pip install -U "mineru[core]"    # 仅第 0 步（PDF 解析）需要
  ```
- **`05_post_segments.py`、`06_post_child_chunks.py`** 中的 URL 仍是 `{dataset_id}` 占位符，属未填好的示例，实际用 GUI 工具或有完整参数的 `process_segments.py` 更省事。

---

## 六、质量门禁：怎么判断解析准不准、分片准不准

链路上任何一层出错，最终都表现为"检索不准"，无法归因。`09_quality_gate.py` 把 A、B 两层的判断固化成可重复的指标，输出 PASS / WARN / FAIL / SKIP 与 markdown 报告，**有 FAIL 时退出码为 1**，可直接接在流水线里当前置门禁。

```bash
# A 层：PDF 与 md 对照（需要 pymupdf；有 MinerU 的 content_list.json 时更准）
python 09_quality_gate.py parse --pdf 结算细则.pdf --md ./mineru_out/结算细则/结算细则_norm.md

# B 层：最终切片文件（含 @!@ / @@）
python 09_quality_gate.py chunk --md 1_1_new_process.md

# 两层一起跑（报告自动分文件：xxx_parse.md / xxx_chunk.md）
python 09_quality_gate.py all --pdf x.pdf --md y.md --report quality.md

# WARN 也算失败（严格模式）、CI 采集 JSON
python 09_quality_gate.py chunk --md y.md --strict --json
```

### A 层：MinerU 解析保真（PDF ↔ md）

| 指标 | 判据 | PASS 阈值 | 说明 |
|------|------|-----------|------|
| 字符保真度 | PDF 文本层字符 / md 正文字符 | 0.80~1.25 | 偏低=漏页丢段，偏高=页眉页脚重复；扫描件无文本层则 SKIP |
| 目录对齐率 | PDF 书签标题是否在 md 中按 `#/##/###` 出现 | ≥90% | **最硬的指标**：有书签的 PDF 一测就知道结构对不对 |
| 页覆盖 | `content_list.json` 的 `page_idx` 去重数 / PDF 页数 | 100% | 检出整页丢失（扫描件、加密页） |
| 表格完整性 | layout 的 `table` 数 vs md 表格块数 | 差 ≤10% | 差值大=表格被拆成散文本 |
| 公式完整性 | layout 的 `equation` 数 vs md `$$` 块数 | ≥95% | 扫描件与双栏版式常丢公式 |
| 乱码率 | U+FFFD + 私用区字符占比 | <0.1% | 字体嵌入问题 |
| 页眉页脚残留 | 重复 ≥5 次的短行占比 | <1% | 页眉会跟着每个分段进水，污染检索 |

**已知局限**：字符保真度对"局部漏一段"不敏感（只差几个百分点），所以它必须和目录对齐率、页覆盖一起看；扫描件（无文本层、无书签）这三点都测不了，只能**按页抽样人工核对**——随机 5 页，PDF 渲染图与 md 对应段落并排逐字核，字符错误率 <1% 即通过。

### B 层：分片合法（最终切片 md）

| 指标 | 判据 | PASS 阈值 |
|------|------|-----------|
| 未切分检测 | 有 `@!@` 却只切出 1 段 / 无标记且正文 >2000 字符 | 必须为否（最常见的错误：把 `_norm.md` 直接上传了） |
| 标题前缀完整 | 每段首行是 `# 主标题(第N部分)[共M部分]` | 100% |
| 二级标题存在 | 每段含 `## ` | 100% |
| 父段超限 | 父段 token ≤ `--max-parent`（默认 2000） | 超限率 0 |
| 子块超限 | 子块 token ≤ `--max-child`（默认 1000） | 超限率 0 |
| 句尾完整性 | 段尾不是 `，、；：的了吗` 等断句符 | <2% |
| 代码块配对 | 每段 ` ``` ` 数量为偶数 | 100% |
| 标记误插 | `@@`/`@!@` 前是非空白字符（插在句中） | 0 处 |
| 体量分布 | 父段/子块 token 的 p50、p95、max | 仅报告不判定 |

token 估算默认用 `--tokenizer simple`（中文按字、英文按 4 字符 1 token 的近似，偏保守）；装了 `tiktoken` 可换 `--tokenizer tiktoken` 更准。Dify 实际用的 tokenizer 与两者都不完全相同，所以阈值留了 2% 的 WARN 缓冲带。

**语义层仍需抽样**：结构指标只能保证"切得合法"，保证不了"切得合理"。随机取 20 段自问——只看这一段能不能答出它对应条款的问题——打分 1~5，均值 <3.5 就说明粒度不对（常见病：子块只剩半句话、父段跨了两个不相关小节）。语义层的自动化替代指标是 C 层的 Recall@k。

---

## 七、一句话总结

**这个文件夹做的事是：为 Dify 知识库准备了一套"用分隔符精确控制层级切块"的导入方案 —— MinerU 先把 PDF 解析成带标题层级的 Markdown，本地脚本再预埋/切片/补标题，API 脚本 + GUI 工具按"父分段 `@!@` / 子分段 `@@`"的规则把文档灌进 Dify，并配置好混合检索 + 重排的 RAG 参数。**
