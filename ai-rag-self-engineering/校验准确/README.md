# 校验准确 · PDF 解析质量验收

回答一个问题：**MinerU 转出来的 Markdown 到底对不对，怎么证明。**
方法见 [PDF解析准确性校验方法论.md](./PDF解析准确性校验方法论.md)，工具是本目录的 `check_parse_accuracy.py`。

| 文件 | 作用 |
|---|---|
| [MinerU转换正确性校验完整指南.md](./MinerU转换正确性校验完整指南.md) | **操作流程视角**：MinerU 产物清单（`pages/` `images/` `tables/` `meta.json`）、六层校验流程、风险分抽样、脚本参考 |
| [PDF解析准确性校验方法论.md](./PDF解析准确性校验方法论.md) | **度量口径视角**：四维定义 / 真值来源与偏差 / 五档手段 / 指标阈值 / 抽样统计 / 错误归因手册 / 八条误区 |
| [check_parse_accuracy.py](./check_parse_accuracy.py) | **可跑的工具**：水位检查（L0）+ 文本层对账（L1）+ 表格对账（L2），出 Markdown/JSON 报告 |

两份文档不重复：指南回答"按什么顺序、看哪些文件、怎么挑高风险样本"，方法论回答"每个指标怎么算、阈值定多少、出问题归因到哪"。工具落地的是后者的 L0–L2。

---

## 一分钟上手

```bash
# 0) 自检：不需要任何素材，验证工具在这台机器上能跑
python check_parse_accuracy.py --self-test

# 1) 单篇校验
python check_parse_accuracy.py --pdf in/a.pdf --md out/a/a.md --bucket electronic

# 2) 批量（manifest 每行一篇）
python check_parse_accuracy.py --manifest samples.jsonl --out report

# 3) 报告在哪
report/report.md     # 人看：总表 + 逐项检查 + 缺失片段 + 页级薄弱点
report/report.json   # 机读：进 CI / 做统计
```

`samples.jsonl`：

```json
{"bucket": "electronic",  "pdf": "in/a.pdf", "md": "out/a/a.md"}
{"bucket": "multi_col",   "pdf": "in/b.pdf", "md": "out/b/b.md"}
{"bucket": "nested_table","pdf": "in/c.pdf", "md": "out/c/c.md"}
```

`--md` 也可以直接给 MinerU 的输出目录（自动取第一个 `.md`）。

**退出码**：`0` = PASS/WARN，`1` = FAIL —— 可直接当批量脚本或 CI 的闸门。

---

## 三层闸门分别在查什么

| 层 | 查什么 | 需要什么 | 失败含义 |
|---|---|---|---|
| **L0 水位** | 页覆盖、空页率、乱码率、连续重复行、Markdown 结构、图片掉链、字量水位 | 只要 md（页覆盖需要 `<!--page:n-->` 锚点） | 产出本身不可用，无需再看 |
| **L1 文本层对账** | 字符召回、近似 CER、字量召回、缺失片段定位、页级薄弱点 | 电子版 PDF（有文本层） | 真漏内容 / 顺序错乱 |
| **L2 表格对账** | 表格单元格召回、行列数一致性 | 电子版 PDF 表格（`find_tables`） | 表格结构丢失或错位 |

扫描件没有文本层时，L1/L2 会显式标记 `SKIP` —— 这是**事实记录**，不是通过。这类文档只能靠人工抽样（方法论 §三 L3）。

---

## 两个前置条件（不满足会白丢一半信息）

1. **中间态要带页码锚点**。MinerU 的 markdown 默认不分页，没有 `<!--page:n-->` 就无法算页覆盖率、无法定位"哪一页坏了"。建议在 `ParsedDoc` 组装时按 `content_list.json` 的 `page_idx` 注入锚点（与 `03-解析管道` §1.1 的"位置锚点"要求一致）。
2. **比对前两侧都要做归一化与页眉页脚剔除**。否则页眉重复、断行连字符、全半角差异会制造大量假缺失，把召回压到 90% 以下，然后你去改解析器——改错方向。工具已内置，自行实现时别漏。

---

## 和 ownrag 管道的关系

```
parse_mineru → validate_parsed（L0，在管道里，失败进待办）
             ↓ 离线批量
        check_parse_accuracy.py（L0+L1+L2，出报告，可进 CI）
             ↓ 上线前
        eval_recall.py + 固定问答集（L4，业务口径）
```

`validate_parsed` 是"能不能入库"，本工具是"改得对不对、哪一页不对"，两者口径不冲突但要分别报。
