# 10 · Excel 通道口径（行不嵌入，目录可检索）

> 定位：本文只回答一件事——**Excel 数据在本工程里，什么进关系表、什么进检索、什么绝不做**。
> 查询期怎么判定走不走 Excel，见 `11-查询路由与多源编排.md`。
> 文中任何未实测的数字都标 【设计】/【待实测】，不拿估算冒充结论（沿用 `00-总览与口径.md`）。

---

## 一、一句话口径

```
Excel 的「行」留在 SQLite 影子表里，只走 SQL；
Excel 的「表目录」（sheet / 列名 / 类型 / 样本 / 行数）可进 FTS5，不进向量；
Excel 的「注释、备注类长文本列」可选进独立向量表，召回结果只是行定位线索，数字回 SQL 重算。
```

推论（本文最重要的一条）：**"向量库 vs 关系表"不是二选一。** 真正要选的是「向量化到什么粒度」。
把整行卡片向量化是"同一份事实存两份"——两份必然漂移，而聚合题必错。这不是理论洁癖，本工程已经踩过：
`textualize(row_card)` 把每行渲染成块送进向量库，结果是黄金集里出现的"清单/简历类块抢占召回"。

---

## 二、现状（改造前）与三处问题

### 2.1 管道现状

```yaml
excel_v1:
  steps:
    - excel_stage      # 逐 sheet → staging_<docId8>_<sheet>（全列 TEXT + 三个溯源列）
    - schema_infer     # 列名/非空率/样本/类型推断
    - column_mapping   # 恒等映射起步
    - textualize       # row_card：每行一张"字段: 值"卡片
    - clean_markdown
    - chunk_markdown
    - dedupe_chunks
    - embed            # ← 行卡片进向量库
    - index_upsert     # ← 行卡片进 chunks/FTS
```

三处问题，按严重度排：

| # | 问题 | 证据 | 后果 |
|---|---|---|---|
| P1 | 行卡片被当语料嵌入 | `pipelines.yaml` excel_v1 的 `embed`/`index_upsert` | 语义召回能捞到"某一行明细"，答不了 `SUM()`；数字靠模型抄，闸门二拦下 |
| P2 | 聚合策略未实现 | `TextualizeStep`：`aggregate` 直接 `fail("属 M2")` | 统计类问题连"降级回答"都没有，整条任务失败 |
| P3 | staging 表建了但查询期没人用 | 全库 `StagingStore` 只被删文档/purge 调用 | 付了落库成本，但拿不到"精确查询"的收益 |

### 2.2 结论

Excel 不是"另一种 RAG 语料"，而是**已入库的结构化数据**。它的问答路径是 Text2SQL，不是向量召回。

---

## 三、决策表：什么进哪

| 数据 | 落在哪 | 进 FTS5 | 进向量 | 查询期用途 |
|---|---|---|---|---|
| 行数据 | 持久化 `staging_*` 表 | ❌ | ❌ | SQL 精确取数 / 聚合 |
| 表目录（sheet、列名、类型、样本、行数、主键列） | `staging_registry` | ✅（目录块） | ❌ | 路由定位目标表 + schema/value linking |
| 备注/说明类长文本列 | 可选 `row_text_vectors` | ✅ | ✅ **仅此一处** | 召回行 → 拿 `_rownum` 回 SQL 取整行 |
| 元数据（文件名/主题/敏感级/日期） | `documents` + `chunks.meta_json` | —— | —— | 表级鉴权与过滤 |

**为什么目录也不进向量**：目录块是"结构化路由表"，数量是"几张表"量级，BM25 足够；而向量化会引入
"语义相似但结构不符"的错表（"费用表"与"报销表"余弦很近，但列完全不同），错表生成的 SQL 一定错。
语义该用在**值链接**（把"华东"映射到 `地区='华东'`），不是用在选表上。

---

## 四、staging 表语义：是影子表，不是 SQL 临时表

| 对比项 | MySQL `CREATE TEMPORARY TABLE` | 本工程 `staging_<docId8>_<sheet>` |
|---|---|---|
| 生命期 | 会话结束即消失 | **随文档版本存续**，删文档/purge 时清 |
| 可见性 | 单会话可见 | 全进程可查（查询期 SQL 直接读） |
| 落盘 | 可能内存 | 落在同一个 `ownrag.db`（WAL） |
| 登记 | 无 | `staging_registry(doc_id, table_name, sheet, schema_json)` |
| 清理责任 | 引擎自动 | `StagingStore.dropByDoc`（第六处清理） |

所以文档里出现的"临时表"一律读作**隔离区/影子表**：它存在的理由是"清洗期不污染主表 + 查询期可直读"，
不是"会话级临时对象"。

### 4.1 命名规则

```
staging_<docId 前 8 位>_<sanitize(sheet)>
sanitize：只保留 [0-9a-zA-Z_] 与 CJK，其余替换为 '_'，最长 40 字符，空则 "sheet"
```

### 4.2 换表是原子的（2026-11-23 已实现）

旧实现是 `DROP TABLE IF EXISTS` → `CREATE TABLE` → `INSERT`：重传同一份 Excel 时，中间窗口里
查询会打到空表（返回 0 行，看起来像"数据没了"）。现在的三段式：

1. 建 `staging_<doc8>_<sheet>_v<epoch秒>` 并灌数 —— 读者仍打旧表，完全无感（`conn.commit()` 落定新表）；
2. **单事务**：`DELETE FROM staging_registry WHERE doc_id=? AND sheet=?` + `INSERT` 新登记行
   —— 切换点是原子的，读者要么看到旧表、要么看到新表，不会两者都有；
3. 提交后再 `DROP` 旧表。这一步失败只是留垃圾，不影响正确性。

两个实现细节必须记住：

- 登记表 PK 是 `(doc_id, table_name)`，新表名不同 → **必须先 DELETE 旧行再 INSERT**。
  只写 `INSERT OR REPLACE` 会留下两行，目录里同一 sheet 出现两次（查询会随机挑到旧表）。
- 并发重传 / 换表后 DROP 失败会留下"不在登记行里"的 `_v` 表：`StagingStore.dropByDoc` 因此
  除了按登记行删，还会按前缀扫 `sqlite_master`（`LIKE 'staging_<doc8>_%' ESCAPE '\'`）兜底。
  注意 `_` 在 LIKE 里是通配符，不转义会误伤同前缀的别的 doc。

---

## 五、入库前置：表头与列名规范（阻断级）

不修这一节，SQL 通道第一天就跑不通——因为 `CREATE TABLE` 会因重名列直接报错，任务失败入待办。

| 规则 | 说明 | 现状 |
|---|---|---|
| R1 表头行探测 | 扫描前 5 行，取"非空单元格最多 + 后续行类型与它最一致"的一行作表头；跳过其上标题行 | ❌ 只取第 1 行 |
| R2 列名去重 | 同名/去空白后同名 → 追加 `_2`、`_3`；空列名 → `col_N` | ❌ 无去重（SQLite duplicate column 报错） |
| R3 合并单元格填充 | 表头区横向合并：向右填充；纵向合并在数据区的业务含义不做猜测，只记 `merged_cells` 计数进 report | ❌ 只有左上角有值 |
| R4 多级表头合并 | 检测到连续 2 行都是"短文本且无数字"→ 视为多级表头，用 `父级_子级` 拼成单行列名 | ❌ 第 2 行被当数据行 |
| R5 列名截断保护 | 原列名单独存 `schema_json.columns`，表名/列名的 `sanitize` 结果只用于 DDL | ⚠️ 截断到 40 字符会撞名，靠 R2 兜 |
| R6 空行/全空行 | 跳过（已有） | ✅ |

口径：**`schema_json.columns` 里的原始列名是唯一真相**，DDL 里的 `sanitize` 名字只是物理名；
SQL 生成只允许使用物理名，展示/引用一律用原始列名。

---

## 六、schema_infer 的产出必须补 `sql_expr`

staging 表**全列 TEXT**（保真优先）。这带来一个后果：`SUM(金额)` 恒为 0，中文日期字符串比较恒为假。
所以每个列除类型外，必须给出"可安全用于 SQL 的表达式"：

| 推断类型 | `sql_expr` | 理由 |
|---|---|---|
| number | `CAST(REPLACE(REPLACE(TRIM("金额"),',',''),'%','') AS REAL)` | 千分位/百分号剥离后才能聚合 |
| date | `date(replace(replace(replace(trim("日期"),'年','-'),'月','-'),'日',''))` | 归一成 `YYYY-MM-DD` 才能比较/按月分组 |
| enum | `TRIM("地区")` | 只做等值/IN |
| text | `TRIM("备注")` | 不做聚合 |

列信息结构（`staging_registry.schema_json`）：

```json
{"columns": [
  {"column": "金额(元)", "physical": "金额_元_", "type": "number",
   "nonnull_rate": 0.99, "samples": ["1,200.00", "980"],
   "sql_expr": "CAST(REPLACE(REPLACE(TRIM(\"金额_元_\"),',',''),'%','') AS REAL)"}
]}
```

> `physical` 与 `column` 分开存，是 R2/R5 的必要条件：去重发生在物理名上，语义映射发生在原始名上。

---

## 七、目录块格式（进 FTS，不进向量）

一张 sheet 一个块，`source_type = 'excel_catalog'`：

```markdown
#### 报销明细.xlsx / Sheet1（1,204 行）

- 列：单据号(text)、申请日期(date)、地区(enum: 华东/华北/华南)、金额(元)(number)、备注(text)
- 主键候选：单据号（非空 100%，唯一 100%）
- 样本（前 3 行）：EXP-0001 / 2024-03-01 / 华东 / 1,200.00
- 查询提示：金额聚合请用 CAST(...AS REAL)；日期请用 date() 归一后比较
```

作用只有一个：让"我们有哪些表、哪些列"可被检索到，支撑路由选表与列链接。
**它不当语料用**——块正文里没有业务结论，模型无法据此编数字。

---

## 八、行指针契约（混合检索的真实坑）

"向量召回 → 按 ID 回查数据库"这句话在工程上最容易崩的地方是 **ID 不稳定**：

| 标识 | 稳定吗 | 说明 |
|---|---|---|
| `doc_id` | ⚠️ 重传即变（同 SHA-256 会 dedup，改一个字节就是新 doc） | 只能由 `staging_registry` 现查 |
| `table_name` | ⚠️ 含 `docId 前 8 位`，重传即变 | 同上 |
| `_rownum` | ❌ **每次重建都变**（读取顺序/跳过空行规则改变即漂移） | 不能单独作行标识 |

结论：

- **允许**：表级指针（`doc_id` + `table_name`），且必须查询期现查，不写死在块 meta 里；
- **禁止**：行级指针，除非业务表有稳定键（单据号/订单号），且该列通过"非空率 100% + 唯一性 100%"探测
  后写入 `schema_json.pk_column`；
- 行文本向量（可选功能）存 `(doc_id, table_name, rownum, column)` 四元组，召回后**必须**用
  `paging` 之外的稳定条件回查；无稳定键时，该功能只用于"提示用户去看哪张表"，不用于直接出答案。

---

## 九、单一真相：目录不落第二份

`staging_registry.schema_json` 是目录的权威来源。若再把目录写进 `chunks`，就有两份：
重灌、改 `schema_infer` 规则、改 `column_mapping` 之后必然不一致 —— 表现为"SQL 报列不存在"，
而排查时会误以为是"模型 SQL 写错了"。

口径（本期采用 A）：

| 方案 | 做法 | 取舍 |
|---|---|---|
| **A（采用）** | 不落索引；路由/链接时读 `staging_registry` 现算 | 零漂移；代价是多一次 DB 读 + prompt 稍长（几张表量级，可忽略） |
| B | 落目录块 + `schema_version` 版本戳校验 | 可被检索发现；需版本比对逻辑 |
| C | 落目录块 + 与建表同事务更新 | 强一致；但 `chunks` 写入与 staging 写入耦合，管道变复杂 |

若后续要做"跨库表发现"（用户不知道有哪些表），再升级到 B。

---

## 十、历史数据迁移（一次性）

改造后，旧的行卡片块仍在库里，会被 RAG 通道召回，路由再准也白搭。必须清：

```sql
-- 1) 先看清有多少（只统计，不动手）
SELECT source_type, COUNT(*) FROM chunks GROUP BY source_type;

-- 2) 清行卡片（保留 staging_* 表与 staging_registry！）
DELETE FROM chunks_fts   WHERE doc_id IN (SELECT doc_id FROM chunks WHERE source_type='excel');
DELETE FROM chunk_vectors WHERE doc_id IN (SELECT doc_id FROM chunks WHERE source_type='excel');
DELETE FROM chunks       WHERE source_type='excel';
-- 3) 刷新派生计数
--    走 POST /admin/kbs/{kb}/purge 之外的单文档路径时，由 DocumentStore.refreshStats 负责
```

> 注意顺序：先删 FTS/向量再删 chunks（后两者按 chunk_id 关联），否则会留下孤儿向量。
> 删完要按 doc 逐个 `DocumentStore.refreshStats`，否则管理页 `chunk_count/vector_count` 失真。

检索侧配套（防御性，**已实现**）：`HybridSearch.ragFilter()` 给所有 RAG 检索自动追加
`source_type NOT IN ('excel')`，`/chat` 与 `/admin/retrieve` 同一口径。
所以迁移脚本是"清理空间"，不是"保证正确"——即使漏跑，旧行卡片也不会进候选池。

---

## 十一、改造后的 excel_v1

```yaml
excel_v1:
  source: { type: upload, accept: [.xlsx, .xlsm, .csv] }
  steps:
    - type: excel_stage        # 表头探测 + 列名去重 + 合并单元格
    - type: schema_infer       # 含 sql_expr / physical / pk 候选
    - type: column_mapping     # 恒等映射起步
    - type: textualize         # strategy=catalog：一 sheet 一块目录（不再逐行）
      params: { strategy: catalog }
    - type: clean_markdown
      params: { page_numbers: false }
    - type: chunk_markdown     # overlap=0，目录块不需重叠
      params: { max_tokens: 512, overlap: 0 }
    - type: dedupe_chunks
      params: {}
    - type: index_upsert       # 只写 chunks + FTS；embed 步骤移除 → embed_version 为 NULL
      params: { replace_by_doc: true }
```

关键点：**移除 `embed` 步骤**，`index_upsert` 因 `embeddings` 为空而不写向量、`embed_version` 保持 NULL。
检索侧按 `embed_version` 匹配，天然不会召回目录块的向量（本来也没有）。

---

## 十二、回归清单

| 用例 | 期望 |
|---|---|
| 表头在第 1 行 | 列名与原始一致 |
| 表头前有标题行 | 自动跳过标题行，列名正确 |
| 两列同名（`金额` / `金额 `） | 物理名 `金额` 与 `金额_2`，不报 duplicate column |
| 表头合并单元格（横向 3 列合并为"费用"） | 三列分别为 `费用_1/2/3` 或按 R4 展开，不出现 `col_N` |
| 多级表头（`费用/交通`） | 列名 `费用_交通` |
| 数据行全空 | 跳过，不计入行数 |
| 数值列聚合 | `SUM(sql_expr)` 结果与 Excel 手算一致（±0.01 容差） |
| 日期列按月分组 | `strftime('%Y-%m', date(...))` 分组数与 Excel 透视表一致 |
| 上传后 chunks | `source_type='excel_catalog'`，`chunk_vectors` 中 0 行 |
| 目录块进 FTS | `q=报销 金额` 能命中目录块 |
| 老库行卡片清理后 | `SELECT COUNT(*) FROM chunks WHERE source_type='excel'` = 0 |
| 同一份 Excel 连传两次 | `staging_registry` 该 sheet 只有 1 行；物理表只剩 1 张；行数与最后一份一致 |
| 换表后按 doc 查询 | 任何时刻都能查到数据（不会出现"中途 0 行"） |

---

## 十三、本文不覆盖

- 查询期路由判定与 SQL 生成执行：见 `11-查询路由与多源编排.md`
- 列映射人工确认（HITL）的交互：仍属 M2，本期恒等映射
- 行文本向量（`row_text_vectors`）：接口预留，本期不实现
