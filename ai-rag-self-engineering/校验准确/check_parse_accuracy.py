#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MinerU PDF 解析准确性校验工具（配套《PDF解析准确性校验方法论.md》）。

三层校验，无需人工标注即可跑：

  auto    水位闸门：页覆盖 / 空页 / 乱码 / 重复行 / Markdown 结构 / 附件引用
  align   与 PDF 文本层对账：字符召回率、序列近似 CER、缺失片段定位（仅电子版 PDF 有效）
  tables  与 PDF 表格结构对账：单元格召回率、行列数一致性（伪真值，仅供参考）

用法：
  python check_parse_accuracy.py --pdf a.pdf --md a.md
  python check_parse_accuracy.py --pdf a.pdf --md outdir/ --out ./report --bucket multi_col
  python check_parse_accuracy.py --manifest samples.jsonl --out ./report
  python check_parse_accuracy.py --self-test          # 生成内置样例并自检

manifest 每行一个 JSON：{"bucket": "嵌套表", "pdf": "a.pdf", "md": "a.md"}

退出码：0=PASS/WARN，1=FAIL（可直接进 CI 或批量脚本的闸门）。
依赖：pymupdf（可选；缺失则 align/tables 跳过，auto 仍可跑）。
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

# --------------------------------------------------------------------------- 阈值
# 均为【经验基线，需按自有语料校准】：分桶（电子版/扫描件/多栏/嵌套表）应各有一套。
TH = {
    "min_page_coverage": 1.0,      # 页覆盖：md 覆盖到的页 / PDF 总页数
    "max_empty_page_ratio": 0.02,  # 空页占比
    "min_char_recall": 0.98,       # 序列字符召回（电子版 PDF 校验收成区）
    "max_cer": 0.05,               # 近似字符错误率
    "max_mojibake_ratio": 0.001,   # 乱码/替换符占比
    "max_dup_line_run": 3,         # 同一行连续重复次数上限
    "min_table_cell_recall": 0.95, # 表格单元格召回
    "max_char_ratio_dev": 0.35,    # md 字符数 / 文本层字符数 的偏离容忍（超出=疑似漏页或多吐）
}

MOJIBAKE_CHARS = "\ufffd\x00\u200b\u200e\u200f\ufeff"
PAGE_ANCHOR = re.compile(r"<!--\s*page\s*[:：]\s*(\d+)\s*-->", re.I)
HEADING = re.compile(r"^(#{1,6})\s+\S", re.M)
IMG_REF = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
MD_IMG_OR_LINK = re.compile(r"!\[[^\]]*\]\([^)]*\)|\[([^\]]*)\]\([^)]*\)")
HTML_TABLE = re.compile(r"<table\b.*?</table>", re.S | re.I)
PIPE_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$", re.M)


# --------------------------------------------------------------------------- 数据结构
@dataclass
class Check:
    name: str
    level: str          # PASS | WARN | FAIL | SKIP
    value: object
    threshold: object = None
    detail: str = ""


@dataclass
class Report:
    pdf: str
    md: str
    bucket: str = ""
    checks: list[Check] = field(default_factory=list)
    missing_spans: list[dict] = field(default_factory=list)
    page_rows: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        levels = {c.level for c in self.checks}
        if "FAIL" in levels:
            return "FAIL"
        if "WARN" in levels:
            return "WARN"
        return "PASS"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["verdict"] = self.verdict
        return d


# --------------------------------------------------------------------------- 归一化
_TRANS = str.maketrans({
    "\u00a0": " ", "\u3000": " ", "\u2002": " ", "\u2003": " ",
    "\uff0c": ",", "\u3002": ".", "\uff1b": ";", "\uff1a": ":",
    "\uff08": "(", "\uff09": ")", "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"', "\uff5e": "~",
})


def normalize(text: str, keep_lines: bool = False) -> str:
    """NFKC + 标点统一 + 去空白。keep_lines=True 时保留换行（用于页眉页脚剔除）。"""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).translate(_TRANS)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    # 断行连字符：pdf 文本层常见 "infor-\nmation"
    t = re.sub(r"-\n(?=[A-Za-z])", "", t)
    if keep_lines:
        return "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in t.split("\n"))
    return re.sub(r"\s+", "", t)


def strip_md_noise(md: str) -> tuple[str, list[str], list[list[list[str]]]]:
    """从 Markdown 中剥离结构语法，返回 (纯正文, html 表格列表, 管道表格矩阵列表)。"""
    html_tables = HTML_TABLE.findall(md)
    body = HTML_TABLE.sub("\n", md)
    body = re.sub(r"```[a-zA-Z0-9_-]*", " ", body)          # 代码块围栏
    body = MD_IMG_OR_LINK.sub(lambda m: m.group(1) or " ", body)
    pipe_tables: list[list[list[str]]] = []
    kept: list[str] = []
    block: list[str] = []
    for line in body.split("\n"):
        if PIPE_TABLE_LINE.match(line):
            block.append(line)
            continue
        if block:
            pipe_tables.append(_parse_pipe_table(block))
            block = []
        kept.append(line)
    if block:
        pipe_tables.append(_parse_pipe_table(block))
    body = "\n".join(kept)
    body = re.sub(r"^\s{0,3}#{1,6}\s*", " ", body, flags=re.M)   # 标题符号
    body = re.sub(r"^\s*([-*+]|\d+[.)])\s+", " ", body, flags=re.M)  # 列表符号
    body = re.sub(r"[*_`~]{1,3}", "", body)                        # 强调/行内代码
    body = re.sub(r"^\s{0,3}>\s?", " ", body, flags=re.M)          # 引用
    body = re.sub(r"^\s*([-*_]\s*){3,}$", " ", body, flags=re.M)   # 分隔线
    return body, html_tables, pipe_tables


def _parse_pipe_table(lines: list[str]) -> list[list[str]]:
    rows = []
    for ln in lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue  # 对齐行
        rows.append(cells)
    return rows


def parse_html_table(fragment: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in re.findall(r"<tr\b.*?</tr>", fragment, re.S | re.I):
        cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        if cells:
            rows.append([html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in cells])
    return rows


def md_plain_text(md: str) -> str:
    """md 的信息量口径：正文 + 表格单元格文本（表格文字也是信息，不能在对账时丢）。"""
    body, html_tables, pipe_tables = strip_md_noise(md)
    rows = [parse_html_table(t) for t in html_tables] + pipe_tables
    cells = " ".join(c for t in rows for r in t for c in r)
    return f"{body}\n{cells}"


# --------------------------------------------------------------------------- PDF 读取
def read_pdf(path: Path) -> tuple[list[str], bool, object]:
    """返回 (每页文本, 是否有文本层, fitz.Document 或 None)。"""
    try:
        import fitz  # pymupdf
    except ImportError:
        return [], False, None
    doc = fitz.open(str(path))
    pages = [p.get_text("text") for p in doc]
    chars = sum(len(normalize(t)) for t in pages)
    return pages, chars > max(50, 20 * len(pages)), doc


def read_md(path: Path) -> tuple[str, Path]:
    if path.is_dir():
        mds = sorted(path.rglob("*.md"))
        if not mds:
            raise SystemExit(f"[x] 目录里没有 .md：{path}")
        if len(mds) > 1:
            print(f"[!] 目录内 {len(mds)} 个 md，取排序首个：{mds[0].name}", file=sys.stderr)
        path = mds[0]
    return path.read_text(encoding="utf-8", errors="replace"), path


# --------------------------------------------------------------------------- 切页
def split_md_pages(md: str, page_count: int) -> list[str] | None:
    """优先按 <!--page:n--> 锚点切页；无锚点返回 None（页级指标降级为 SKIP）。"""
    marks = list(PAGE_ANCHOR.finditer(md))
    if not marks:
        return None
    pages = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        pages.append(md[m.end():end])
    return pages if pages else None


def drop_running_heads(pages: list[str], edge: int = 2, ratio: float = 0.6) -> list[str]:
    """剔除页眉页脚：在多数页面首/末 edge 行重复出现的短行。两侧各自独立执行。"""
    if len(pages) < 3:
        return pages
    edge_lines: Counter[str] = Counter()
    for p in pages:
        lines = [normalize(ln, keep_lines=True) for ln in normalize(p, keep_lines=True).split("\n")]
        lines = [ln for ln in lines if ln]
        for ln in lines[:edge] + lines[-edge:]:
            if 0 < len(ln) <= 40:
                edge_lines[ln] += 1
    repeats = {ln for ln, c in edge_lines.items() if c >= max(3, int(len(pages) * ratio))}
    if not repeats:
        return pages
    out = []
    for p in pages:
        kept = [ln for ln in p.split("\n") if normalize(ln) not in repeats]
        out.append("\n".join(kept))
    return out


# --------------------------------------------------------------------------- 对齐算法
def seq_stats(truth: str, pred: str) -> dict:
    sm = SequenceMatcher(None, truth, pred, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    lt, lp = max(1, len(truth)), max(1, len(pred))
    return {
        "truth_chars": len(truth),
        "pred_chars": len(pred),
        "matched_chars": matched,
        "recall": round(matched / lt, 4),
        "precision": round(matched / lp, 4),
        "cer": round((len(truth) - matched) / lt, 4),
    }


def multiset_recall(truth: str, pred: str) -> float:
    """顺序不敏感的字量召回：判断"字在不在"，与 seq_stats 的顺序指标互补。"""
    if not truth:
        return 1.0
    ct, cp = Counter(truth), Counter(pred)
    common = sum(min(ct[c], cp[c]) for c in ct)
    return round(common / len(truth), 4)


def missing_spans(truth: str, pred: str, top: int = 5) -> list[dict]:
    """定位真值中整段缺失（delete/replace 操作）的最长片段，供人工复核。"""
    sm = SequenceMatcher(None, truth, pred, autojunk=False)
    out: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("delete", "replace") and (i2 - i1) >= 8:
            out.append((i2 - i1, i1))
    out.sort(reverse=True)
    res = []
    for size, start in out[:top]:
        s = max(0, start - 12)
        res.append({
            "missing_chars": size,
            "truth_excerpt": truth[s:start + size + 12],
        })
    return res


# --------------------------------------------------------------------------- 检查项
def check_auto(rep: Report, md: str, md_pages: list[str] | None,
               pdf_pages: list[str], has_text: bool) -> None:
    md_norm = normalize(md_plain_text(md))
    rep.stats["md_chars"] = len(md_norm)

    # 1) 页覆盖
    if md_pages:
        anchors = [int(m) for m in PAGE_ANCHOR.findall(md)]
        covered = len(set(anchors))
        total = len(pdf_pages) or max(anchors or [0])
        cov = round(covered / total, 4) if total else None
        rep.checks.append(Check("页覆盖", "PASS" if (cov or 0) >= TH["min_page_coverage"] else "FAIL",
                                cov, TH["min_page_coverage"],
                                f"锚点页 {covered} / PDF {total} 页" if total else "无法确认 PDF 页数"))
        empty = [i + 1 for i, p in enumerate(md_pages) if len(normalize(md_plain_text(p))) < 20]
        ratio = round(len(empty) / max(1, len(md_pages)), 4)
        rep.checks.append(Check("空页率", "PASS" if ratio <= TH["max_empty_page_ratio"] else "FAIL",
                                ratio, TH["max_empty_page_ratio"],
                                f"空页：{empty[:20]}" if empty else ""))
    else:
        rep.checks.append(Check("页覆盖", "SKIP", None, TH["min_page_coverage"],
                                "Markdown 无 <!--page:n--> 锚点——建议在中间态注入页码锚点后重跑"))

    # 2) 乱码
    bad = sum(md.count(c) for c in MOJIBAKE_CHARS)
    ctrl = len(re.findall(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", md))
    bad += ctrl
    ratio = round(bad / max(1, len(md_norm)), 5)
    rep.checks.append(Check("乱码率", "PASS" if ratio <= TH["max_mojibake_ratio"] else "FAIL",
                            ratio, TH["max_mojibake_ratio"], f"替换符/控制符 {bad} 处"))

    # 3) 连续重复行（解析器死循环 / 页脚灌水）
    run, prev, worst, worst_line = 1, None, 0, ""
    for ln in md.split("\n"):
        key = normalize(ln)
        if key and key == prev:
            run += 1
            if run > worst:
                worst, worst_line = run, ln.strip()[:40]
        else:
            run, prev = 1, key
    rep.checks.append(Check("重复行", "PASS" if worst <= TH["max_dup_line_run"] else "FAIL",
                            worst, TH["max_dup_line_run"], f"最长连续重复：{worst_line}" if worst_line else ""))

    # 4) Markdown 结构
    fences = md.count("```")
    levels = [len(m.group(1)) for m in HEADING.finditer(md)]
    jumps = sum(1 for a, b in zip(levels, levels[1:]) if b > a + 1)
    struct_bad = (fences % 2) + jumps
    rep.checks.append(Check("MD 结构", "PASS" if struct_bad == 0 else "WARN",
                            {"代码块围栏配对": fences % 2 == 0, "标题层级跳变": jumps},
                            "围栏配对 & 无跳级", f"### 数量 {len(levels)}"))

    # 5) 图片引用落地
    refs = [r for r in IMG_REF.findall(md) if not r.startswith(("http://", "https://", "asset:"))]
    if refs:
        base = Path(rep.md).parent if not Path(rep.md).is_dir() else Path(rep.md)
        missing = [r for r in refs if not (base / r).exists() and not (base.parent / r).exists()]
        rep.checks.append(Check("图片落地", "PASS" if not missing else "WARN",
                                f"{len(missing)}/{len(refs)} 缺失",
                                "全部可访问", f"缺失示例：{missing[:3]}"))
    else:
        rep.checks.append(Check("图片落地", "SKIP", None, None, "正文无本地图片引用"))

    # 6) 字符量水位（与文本层比）
    if has_text:
        truth_chars = len(normalize("\n".join(pdf_pages)))
        rep.stats["pdf_text_chars"] = truth_chars
        if truth_chars:
            dev = round(abs(len(md_norm) - truth_chars) / truth_chars, 4)
            rep.checks.append(Check("字量水位", "PASS" if dev <= TH["max_char_ratio_dev"] else "WARN",
                                    dev, TH["max_char_ratio_dev"],
                                    f"md {len(md_norm)} vs 文本层 {truth_chars}"))


def check_align(rep: Report, md: str, pdf_pages: list[str], has_text: bool,
                md_pages: list[str] | None = None) -> None:
    if not has_text:
        rep.checks.append(Check("文本层对账", "SKIP", None, TH["min_char_recall"],
                                "该 PDF 无文本层（扫描件）——跳层改用人工标注或工具交叉验证，"
                                "不能用『自己比自己』"))
        return
    truth_pages = drop_running_heads([normalize(p, keep_lines=True) for p in pdf_pages])
    truth = normalize("\n".join(truth_pages))
    body = md_plain_text(md)
    pred = normalize("\n".join(drop_running_heads([normalize(body, keep_lines=True)])))
    s = seq_stats(truth, pred)
    rep.stats.update(s)
    rep.stats["multiset_recall"] = multiset_recall(truth, pred)

    if len(truth) < 80:
        rep.checks.append(Check("文本层对账", "SKIP", None, None,
                                f"文本层仅 {len(truth)} 字符，样本不足以计算召回"))
        return
    rep.checks.append(Check("字符召回", "PASS" if s["recall"] >= TH["min_char_recall"] else "FAIL",
                            s["recall"], TH["min_char_recall"],
                            f"字量召回 {rep.stats['multiset_recall']}（顺序不敏感）"))
    rep.checks.append(Check("近似 CER", "PASS" if s["cer"] <= TH["max_cer"] else "FAIL",
                            s["cer"], TH["max_cer"], f"匹配 {s['matched_chars']} 字符"))
    rep.missing_spans = missing_spans(truth, pred)

    # 页级对账：只做定位，不做判定（整体指标才判 PASS/FAIL）
    if md_pages and len(md_pages) == len(pdf_pages):
        for i, (t_raw, m_raw) in enumerate(zip(truth_pages, md_pages), start=1):
            t = normalize(t_raw)
            m = normalize(md_plain_text(m_raw))
            if len(t) < 30:
                continue
            ps = seq_stats(t, m)
            flag = "FAIL" if ps["recall"] < 0.85 else ("WARN" if ps["recall"] < 0.95 else "ok")
            rep.page_rows.append({"page": i, "pdf_chars": len(t), "md_chars": len(m),
                                  "recall": ps["recall"], "flag": flag})


def check_tables(rep: Report, md: str, pdf_path: Path, doc) -> None:
    _, html_tables, pipe_tables = strip_md_noise(md)
    md_rows = [parse_html_table(t) for t in html_tables] + pipe_tables
    md_cells = [normalize(c) for t in md_rows for r in t for c in r if normalize(c)]
    rep.stats["md_tables"] = len(md_rows)
    rep.stats["md_table_cells"] = len(md_cells)

    if doc is None:
        rep.checks.append(Check("表格对账", "SKIP", None, TH["min_table_cell_recall"],
                                f"未安装 pymupdf，仅统计到 md 表格 {len(md_rows)} 个"))
        return
    truth_cells: list[str] = []
    table_count = 0
    try:
        for page in doc:
            finder = page.find_tables()
            for tb in finder.tables:
                table_count += 1
                for row in tb.extract():
                    for cell in row:
                        if cell and normalize(str(cell)):
                            truth_cells.append(normalize(str(cell)))
    except Exception as e:  # find_tables 对某些 PDF 会抛
        rep.checks.append(Check("表格对账", "SKIP", None, None, f"结构提取失败：{e}"))
        return
    rep.stats["pdf_tables"] = table_count
    rep.stats["pdf_table_cells"] = len(truth_cells)
    if not truth_cells:
        rep.checks.append(Check("表格对账", "PASS" if not md_cells else "WARN",
                                len(md_cells), TH["min_table_cell_recall"],
                                "文本层未检测到表格结构（扫描件表格需人工抽检）"))
        return
    ct, cp = Counter(truth_cells), Counter(md_cells)
    common = sum(min(ct[c], cp[c]) for c in ct)
    recall = round(common / len(truth_cells), 4)
    rep.checks.append(Check("表格单元格召回", "PASS" if recall >= TH["min_table_cell_recall"] else "FAIL",
                            recall, TH["min_table_cell_recall"],
                            f"真值 {table_count} 表 / {len(truth_cells)} 格，md {len(md_rows)} 表 / {len(md_cells)} 格"
                            "（真值来自 find_tables，复杂表本身也可能错，仅作下限）"))


# --------------------------------------------------------------------------- 单篇 & 批量
def run_one(pdf: Path, md_path: Path, bucket: str = "") -> Report:
    md, md_file = read_md(md_path)
    pdf_pages, has_text, doc = read_pdf(pdf)
    rep = Report(pdf=str(pdf), md=str(md_file), bucket=bucket or guess_bucket(md))
    md_pages = split_md_pages(md, len(pdf_pages))
    to_pages = lambda ps: [normalize(md_plain_text(p)) for p in ps]  # noqa: E731
    try:
        check_auto(rep, md, md_pages, pdf_pages, has_text)
        check_align(rep, md, pdf_pages, has_text, md_pages)
        check_tables(rep, md, pdf, doc)
    finally:
        if doc is not None:
            doc.close()
    return rep


def guess_bucket(md: str) -> str:
    if not md.strip():
        return "unknown"
    if md.count("<table") or re.search(r"^\|.*\|\s*$", md, re.M):
        return "has_table"
    return "text_only"


def render_report(reps: list[Report], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# 解析准确性校验报告", "",
             f"阈值基线：`{json.dumps(TH, ensure_ascii=False)}`（经验值，需按语料校准）", ""]
    lines += ["| 文档 | 分桶 | 结论 | 字符召回 | CER | 页覆盖 | 乱码率 | 表格单元格召回 |",
              "|---|---|---|---|---|---|---|---|"]
    for r in reps:
        get = lambda n: next((c.value for c in r.checks if c.name == n), "—")  # noqa: E731
        tbl = get("表格单元格召回")
        if tbl == "—":
            tbl = f"未检测到表格（md {r.stats.get('md_tables', 0)} 表）"
        lines.append(f"| {Path(r.md).name} | {r.bucket} | **{r.verdict}** | {get('字符召回')} | "
                     f"{get('近似 CER')} | {get('页覆盖')} | {get('乱码率')} | {tbl} |")
    for r in reps:
        lines += ["", f"## {Path(r.md).name} — {r.verdict}", ""]
        lines += ["| 检查项 | 结论 | 实测 | 阈值 | 说明 |", "|---|---|---|---|---|"]
        for c in r.checks:
            detail = str(c.detail).replace("|", "\\|")
            lines.append(f"| {c.name} | {c.level} | {c.value} | {c.threshold or '—'} | {detail} |")
        if r.missing_spans:
            lines += ["", "**缺失片段（真值有、产出无）**：", ""]
            for s in r.missing_spans:
                lines.append(f"- {s['missing_chars']} 字：`{s['truth_excerpt']}`")
        weak = [p for p in r.page_rows if p["flag"] != "ok"]
        if weak:
            lines += ["", "**页级薄弱点（定位用，判定看整体指标）**：", "",
                      "| 页 | PDF 字符 | MD 字符 | 页内召回 | 标记 |", "|---|---|---|---|---|"]
            lines += [f"| {p['page']} | {p['pdf_chars']} | {p['md_chars']} | "
                      f"{p.get('recall', '—')} | {p['flag']} |" for p in weak]
        if r.stats:
            lines += ["", f"<details><summary>stats</summary>\n\n```json\n"
                          f"{json.dumps(r.stats, ensure_ascii=False, indent=2)}\n```\n</details>"]

    md_out = out_dir / "report.md"
    json_out = out_dir / "report.json"
    md_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_out.write_text(json.dumps([r.to_dict() for r in reps], ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return md_out, json_out


# --------------------------------------------------------------------------- 自检
def self_test() -> int:
    """内置样例：造一份双页 PDF + 一份故意有缺陷的 md，验证指标方向正确。"""
    import fitz
    tmp = Path(tempfile.mkdtemp(prefix="parse_check_"))
    pdf = tmp / "sample.pdf"
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 100), "Regulation on Warehouse Receipt Pledging", fontsize=12)
    p1.insert_text((72, 130), "Article 1 This measure applies to all standard", fontsize=10)
    p1.insert_text((72, 145), "warehouse receipts issued within the territory.", fontsize=10)
    p2 = doc.new_page()
    p2.insert_text((72, 100), "Article 2 The pledgor shall deliver the receipt.", fontsize=10)
    doc.save(str(pdf))
    doc.close()

    good = tmp / "good.md"
    good.write_text("<!--page:1-->\n# Regulation on Warehouse Receipt Pledging\n\n"
                    "Article 1 This measure applies to all standard warehouse receipts issued "
                    "within the territory.\n\n<!--page:2-->\nArticle 2 The pledgor shall deliver the receipt.\n",
                    encoding="utf-8")
    bad = tmp / "bad.md"
    bad.write_text("<!--page:1-->\n# Regulation\n\nArticle 1 This measure applies to all standard\n\n"
                   "<!--page:2-->\n\ufffd\ufffd\ufffd\n", encoding="utf-8")

    reps = [run_one(pdf, good, "selftest_good"), run_one(pdf, bad, "selftest_bad")]
    md_out, _ = render_report(reps, tmp / "report")
    print(f"self-test 样例与报告：{tmp}")
    print(f"报告：{md_out}")
    ok = reps[0].verdict in ("PASS", "WARN") and reps[1].verdict == "FAIL"
    print(f"[{'OK' if ok else 'NG'}] good={reps[0].verdict} bad={reps[1].verdict}")
    return 0 if ok else 1


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MinerU PDF 解析准确性校验（三层闸门）")
    ap.add_argument("--pdf", help="源 PDF")
    ap.add_argument("--md", help="MinerU 产出的 markdown（或输出目录）")
    ap.add_argument("--manifest", help="批量清单 jsonl：{bucket,pdf,md}")
    ap.add_argument("--out", default="report", help="报告输出目录（默认 ./report）")
    ap.add_argument("--bucket", default="", help="分桶标签：electronic/scan/multi_col/nested_table/formula")
    ap.add_argument("--min-recall", type=float, help="覆盖 min_char_recall 阈值")
    ap.add_argument("--max-cer", type=float, help="覆盖 max_cer 阈值")
    ap.add_argument("--self-test", action="store_true", help="内置样例自检")
    a = ap.parse_args(argv)

    if a.min_recall is not None:
        TH["min_char_recall"] = a.min_recall
    if a.max_cer is not None:
        TH["max_cer"] = a.max_cer

    if a.self_test:
        return self_test()
    if a.manifest:
        reps = []
        mpath = Path(a.manifest)
        if not mpath.exists():  # 允许 shell 未展开的通配符
            hits = sorted(glob.glob(a.manifest))
            if not hits:
                raise SystemExit(f"[x] manifest 不存在：{a.manifest}")
            mpath = Path(hits[0])
        for line in mpath.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            reps.append(run_one(Path(item["pdf"]), Path(item["md"]), item.get("bucket", "")))
    elif a.pdf and a.md:
        reps = [run_one(Path(a.pdf), Path(a.md), a.bucket)]
    else:
        ap.error("需要 --pdf/--md 或 --manifest 或 --self-test")

    md_out, json_out = render_report(reps, Path(a.out))
    for r in reps:
        print(f"[{r.verdict}] {Path(r.md).name}"
              + "".join(f"  {c.name}={c.value}({c.level})" for c in r.checks if c.level in ("WARN", "FAIL")))
    print(f"报告：{md_out}\n明细：{json_out}")
    return 1 if any(r.verdict == "FAIL" for r in reps) else 0


if __name__ == "__main__":
    sys.exit(main())
