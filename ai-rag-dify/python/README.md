# ai-rag-dify / python

基于 **Dify 知识库 API** 的文档导入工具集，核心目标是：把一份**中文 Markdown 长文档**（如《郑大乾坤鉴》类中医典籍/资料），按**自定义分隔符**切成"父分段 + 子分段"的**层级结构（hierarchical model）**，再灌入 Dify 知识库，从而精确控制 RAG 检索时的切块粒度。

> 之所以要自己写脚本，是因为 Dify 内置的自动切分对中文长文控制力弱。这里的思路是：**用特殊符号（`@!@`、`@@`）在原文里预埋切分标记**，再让 Dify 按这些标记切分。

---

## 一、整体思路

```
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

## 二、文件清单与作用

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

### 其他

| 文件 | 作用 |
|------|------|
| `document.json` | 一份 `create-by-file` 请求体的**完整示例 JSON**，可作为切分/检索参数模板参考。 |

---

## 三、典型使用流程

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

---

## 四、使用前须知

- **必须替换占位符**：所有脚本中的 `dataset-REPLACE_WITH_YOUR_KEY` 与硬编码的 `dataset_id` / `document_id` / 文件路径（如 `D:\郑大乾坤鉴\1.md`）都需改成自己的值。
- **服务地址**：默认指向内网 Dify，如 `http://10.17.1.134:30001`。
- **依赖**：`requests`；GUI 工具额外用到标准库 `tkinter`（Windows 自带）；打包需 `pyinstaller`。
  ```bash
  pip install requests
  ```
- **`05_post_segments.py`、`06_post_child_chunks.py`** 中的 URL 仍是 `{dataset_id}` 占位符，属未填好的示例，实际用 GUI 工具或有完整参数的 `process_segments.py` 更省事。

---

## 五、一句话总结

**这个文件夹做的事是：为 Dify 知识库准备了一套"用分隔符精确控制层级切块"的导入方案 —— 本地脚本负责给 Markdown 预埋/切片/补标题，API 脚本 + GUI 工具负责按"父分段 `@!@` / 子分段 `@@`"的规则把文档灌进 Dify，并配置好混合检索 + 重排的 RAG 参数。**
