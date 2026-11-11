# MinerU 转换正确性校验完整指南

> 适用场景：使用 MinerU 将 PDF 批量/单文件转换为 Markdown、结构化 JSON、表格、公式、图片后，对转换结果的**完整性**与**准确性**进行系统化校验。
> 核心思路：**结构校验 → 指标校验 → 内容核对 → 抽样校验 → 回归校验**，由自动到人工、由粗到细层层收敛。

---

## 一、认识 MinerU 的输出产物

运行示例：

```bash
mineru -p test.pdf -o ./output
```

正常输出目录通常包含以下产物，校验前先理解每个产物的作用：

| 文件 / 目录 | 作用 | 检查点 |
|---|---|---|
| `output.md` | 最终合并的 Markdown 结果 | 能否正常打开、渲染 |
| `pages/page_*.json` | 每页结构化数据（文本块/坐标/类型/置信度） | 页数是否与原 PDF 一致 |
| `images/` | 提取出的图片 | 图片是否存在、是否为 0 字节或空白 |
| `tables/` | 表格（CSV / PNG） | 表格行列是否完整 |
| `formulas/` | 公式 LaTeX 与渲染图 | 公式是否缺失或乱码 |
| `meta.json` | 元信息 | 总页数、耗时、模型版本是否正常 |

> 判断原则：如果 `output.md` 里大量图片引用，但 `images/` 对应文件缺失、大小为 0 或空白，说明转换不完整。

---

## 二、校验分层总览

文件多时，不可能靠肉眼逐个点开。推荐把校验拆成多层，逐层过滤：

```text
PDF → MinerU 批量转换
      ├─ ① 结构校验（硬校验）：产物是否完整产出
      ├─ ② 指标校验（统计）：关键结构数量是否合理
      ├─ ③ 内容准确性核对（人工）：正文/表格/公式
      ├─ ④ 风险评分 + 抽样校验：挑高风险人工复核
      └─ ⑤ 回归校验（黄金样本）：防止解析质量退化
```

**设计哲学：不追求每个文件都完美，而是先把明显坏掉的挑出来，再只对高风险文件做人工确认。**

---

## 三、第 1 层：结构校验（硬校验）

批量跑完后，先用脚本检查每个 PDF 是否生成了完整输出。这一步快速筛掉"根本没转成功"的文件。

检查项：

- `xxx.md` 是否存在；
- `pages/page_*.json` 数量是否等于 PDF 页数；
- `images/`、`tables/`、`formulas/` 目录是否存在；
- 图片文件是否为 0 字节；
- 转换日志里是否有异常退出。

---

## 四、第 2 层：指标校验（脚本统计）

对每个生成的 Markdown 做统计，异常者丢进"可疑清单"。

| 指标 | 说明 |
|---|---|
| 标题数量 | `#`、`##`、`###` 是否合理 |
| 表格数量 | 是否出现 `|---|` 或 HTML 表格 |
| 公式数量 | `$$` / `$` 包裹的 LaTeX 是否出现 |
| 图片引用数量 | `![]()` 是否正常 |
| 重复行比例 | 页眉页脚是否大量重复 |
| 空段落比例 | 是否出现大量无效空白内容 |

---

## 五、第 3 层：内容准确性人工核对

自动指标只能筛出"可疑"，真正判断"对不对"仍需在 Markdown 预览器（**Typora / VS Code / Obsidian**，切勿直接当纯文本看）中肉眼核对。

### 5.1 正文与版式

- **阅读顺序**：双栏、多栏是否没有左右乱拼；
- **标题层级**：章节、小节层级是否正确；
- **段落完整性**：有无整段、整页丢失；
- **页眉页脚**：是否被正确清理，而非混入正文；
- **图片位置**：是否缺失、错位或变成空白占位。

### 5.2 重点检查表格（最易暴露问题）

- 表头是否完整；
- 行列是否对齐；
- 合并单元格是否保留；
- 数字、单位、负号、千分位是否准确；
- 跨页表格是否被正确拼接。

> 若 Markdown 里表格结构混乱，可到 `tables/` 查看对应 CSV 与 PNG 预览，判断是"表格结构识别问题"还是"Markdown 渲染问题"。

### 5.3 重点检查公式

查看 `formulas/` 目录：

- 公式是否被转成 LaTeX；
- 上下标、分式、积分、求和符号是否正确；
- 公式编号是否丢失；
- 渲染图是否与原文一致。

> 若 Markdown 里公式显示异常，但 `formulas/` 有对应图片，说明识别到了公式，只是文本转换不理想，可对照图片手动修正。

---

## 六、第 4 层：利用 JSON 中间结果定位问题

打开 `pages/page_000.json`，可查看每页文本块、类型、坐标与置信度。这比只看 `output.md` 更能精确定位"哪一页、哪一块"出错。

检查项：

- 每页是否有 `blocks`；
- 表格块是否识别为 `table`；
- 公式块是否识别为 `equation`；
- 图片块是否识别为 `figure`；
- 页码是否连续；
- 是否有页面完全没有内容块。

> 某页 JSON 里文本块很少、坐标异常或类型识别明显错误，说明该页解析质量可能有问题。

---

## 七、第 5 层：黄金样本回归校验

若有已人工确认过的 PDF 作为"黄金样本"，每次升级 MinerU、换模型、改配置后重跑并对比：

- 标题结构是否变化；
- 表格数量是否减少；
- 公式是否丢失；
- 图片引用是否变少；
- 正文关键词是否仍能命中；
- 页眉页脚是否重新污染正文。

适合接入 CI/CD，防止解析质量退化。

**最稳妥的一页抽检法（复杂页面黄金样本）：**

- 原文含公式、表格、图片、脚注；
- 逐段对照文字是否一致；
- 检查数字是否被改错；
- 检查跨页内容是否断裂；
- 检查图片和表格是否都能对应上。

这一页通过后，再批量处理其他文档会更放心。

---

## 八、第 6 层：无黄金样本时的风险抽样

没有标准答案时，用"风险分"排序，只人工看风险最高的 5%–10%：

- 页数特别多的；
- 表格、公式数量异常的；
- 重复行比例高的；
- 图片引用特别多的；
- Markdown 特别短的；
- JSON 里识别块特别少的。

其余只要通过硬校验和指标阈值，即可认为基本可用。

---

## 九、接入知识库 / RAG 的额外校验

若转换结果要入库或接 RAG，还需额外检查：

- 分块后语义是否完整；
- 表格是否还能被正确检索；
- 公式是否没有变成乱码；
- 图片引用路径是否仍然有效；
- 是否出现页眉页脚、页码污染正文。

---

## 十、自动化校验脚本参考

### 10.1 流水线设计

```text
PDF → MinerU 批量转换 → 结构校验 → 指标校验 → 风险评分 → 抽样人工复核 → 入库
```

大部分文件自动通过，只有少数可疑文件需要人工处理。

### 10.2 伪代码逻辑

```python
for pdf in pdfs:
    md = read_md(pdf)
    json_pages = load_pages(pdf)

    checks = {
        "md_exists": md is not None,
        "page_count_match": len(json_pages) == pdf_page_count,
        "tables": count_tables(md),
        "formulas": count_formulas(md),
        "images": count_images(md),
        "headers": count_headers(md),
        "noise_ratio": count_repeated_lines(md) / len(md_lines),
        "empty_blocks": count_empty_blocks(json_pages),
    }

    if any_check_failed(checks):
        mark_as_suspicious(pdf)
```

### 10.3 可直接运行的校验脚本（Python）

> 适配 MinerU 输出目录结构，对单个输出目录做结构 + 指标 + JSON 校验，输出可疑清单。

```python
import os
import re
import json
import glob
import fitz  # PyMuPDF
from collections import Counter

def check_output(pdf_path, out_dir):
    report = {}

    # 1. md 文件
    md_files = glob.glob(os.path.join(out_dir, "**", "*.md"), recursive=True)
    report["md_exists"] = len(md_files) > 0
    md_text = ""
    if md_files:
        with open(md_files[0], "r", encoding="utf-8") as f:
            md_text = f.read()

    # 2. 页数匹配
    json_pages = sorted(glob.glob(os.path.join(out_dir, "**", "page_*.json"), recursive=True))
    try:
        pdf_page_count = len(fitz.open(pdf_path))
    except Exception:
        pdf_page_count = None
    report["page_count_match"] = (pdf_page_count == len(json_pages)) if pdf_page_count else None

    # 3. 图片完整性（是否存在 0 字节图片）
    images = glob.glob(os.path.join(out_dir, "**", "images", "*"), recursive=True)
    report["image_total"] = len(images)
    report["empty_images"] = sum(1 for i in images if os.path.getsize(i) == 0)

    # 4. Markdown 指标统计
    report["tables"] = len(re.findall(r"\n\s*\|.*\|\s*\n\s*\|[\s:|-]+\|", md_text))
    report["formulas"] = md_text.count("$$") // 2 + len(
        re.findall(r"(?<!\$)\$(?!\$).+?(?<!\$)\$(?!\$)", md_text))
    report["img_refs"] = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", md_text))
    report["headers"] = len(re.findall(r"^#{1,6}\s", md_text, re.M))

    # 5. 噪声（重复行）比例
    lines = [l.strip() for l in md_text.splitlines() if l.strip()]
    if lines:
        dup = sum(c - 1 for c in Counter(lines).values() if c > 1)
        report["noise_ratio"] = round(dup / len(lines), 3)
    else:
        report["noise_ratio"] = 1.0

    # 6. JSON 空块页面
    empty_pages = 0
    for jp in json_pages:
        try:
            data = json.load(open(jp, encoding="utf-8"))
            blocks = data.get("blocks", data.get("parsing_list", []))
            if not blocks:
                empty_pages += 1
        except Exception:
            empty_pages += 1
    report["empty_pages"] = empty_pages

    # 可疑判定
    suspicious = []
    if not report["md_exists"]:
        suspicious.append("md_missing")
    if report.get("page_count_match") is False:
        suspicious.append("page_count_mismatch")
    if report["empty_images"]:
        suspicious.append("empty_images")
    if report["empty_pages"]:
        suspicious.append("empty_json_pages")
    if report["noise_ratio"] > 0.3:
        suspicious.append("high_noise")
    report["suspicious"] = suspicious
    return report


if __name__ == "__main__":
    pdf_path = "test.pdf"
    out_dir = "./output"
    print(json.dumps(check_output(pdf_path, out_dir), ensure_ascii=False, indent=2))
```

### 10.4 批量运行与风险分排序

```python
import json, glob

pdfs = glob.glob("./pdfs/*.pdf")
results = []
for pdf in pdfs:
    out_dir = "./output/" + pdf.split("/")[-1].replace(".pdf", "")
    r = check_output(pdf, out_dir)
    r["pdf"] = pdf
    # 简单风险分：可疑项数量 + 噪声 + 空页
    r["risk_score"] = len(r["suspicious"]) + r["noise_ratio"] * 2 + r["empty_pages"] * 0.5
    results.append(r)

# 输出可疑清单，按风险分降序，仅人工复核 Top 5%-10%
suspicious = [x for x in results if x["suspicious"]]
suspicious.sort(key=lambda x: x["risk_score"], reverse=True)
with open("suspect_report.json", "w", encoding="utf-8") as f:
    json.dump(suspicious, f, ensure_ascii=False, indent=2)
print(f"共 {len(results)} 份，可疑 {len(suspicious)} 份，需人工复核 Top {max(1, len(suspicious)//10)} 份")
```

---

## 十一、校验清单速查表

| 层级 | 校验对象 | 关键问题 | 方式 |
|---|---|---|---|
| 结构 | 目录产物 | 是否完整产出、0 字节、异常退出 | 脚本（自动） |
| 指标 | Markdown 文本 | 标题/表格/公式/图片/重复行数量是否合理 | 脚本（自动） |
| 内容 | 正文/版式 | 阅读顺序、层级、页眉页脚、图片位置 | 预览器（人工） |
| 内容 | 表格 | 表头、行列、合并单元格、跨页拼接 | 预览 + `tables/`（人工） |
| 内容 | 公式 | LaTeX 正确性、编号、渲染图 | 预览 + `formulas/`（人工） |
| 定位 | `page_*.json` | 块类型、坐标、置信度、空页 | 脚本 + 抽查（半自动） |
| 回归 | 黄金样本 | 升级后结构/数量是否退化 | 脚本（自动） |
| 抽样 | 风险分 Top 5–10% | 复杂页面逐段比对 | 人工 |
| 入库 | RAG 分块 | 语义完整、可检索、路径有效 | 人工 + 脚本 |

---

## 十二、一句话总结

> **先看目录结构是否完整，再用 Markdown 预览核对正文，接着重点抽查表格、公式、图片和跨页内容；文件多时用脚本做"结构校验 + 指标校验 + 风险评分"自动过滤，只把高风险文件交给人工，并用黄金样本做回归校验，防止解析质量退化。**

---

内容由 AI 生成
