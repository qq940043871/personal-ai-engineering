# -*- coding: utf-8 -*-
"""A + B 质量门禁：MinerU 解析保真（parse）与分片合法（chunk）。

为什么需要：
    链路是 PDF → MinerU → md → 预埋 @@ → 按 @!@ 切片 → 灌 Dify。
    任何一层出错，下游都表现成「检索不准」，无法归因。本脚本把 A/B 两层的
    质量指标固化成可重复的检查，输出 PASS / WARN / FAIL / SKIP 与 markdown 报告。

A 层（--stage parse）：PDF 与 md 对照
    字符保真度   PDF 文本层字符数 / md 正文字符数            0.80~1.25 为 PASS
    目录对齐率   PDF 书签标题在 md 中按 #/##/### 出现的比例    >=90% PASS（无书签 SKIP）
    页覆盖       content_list.json 的 page_idx 去重数 / PDF 页数   100% PASS
    表格完整性   content_list 的 table 数 vs md 表格块数      差 <=10% PASS
    公式完整性   content_list 的 equation 数 vs md $$ 块数    >=95% PASS
    乱码率       U+FFFD + 私用区字符占比                     <0.1% PASS
    页眉页脚残留 重复 >=5 次的短行占比                        <1% PASS

B 层（--stage chunk）：最终切片 md（含 @!@ / @@）
    未切分       有 @!@ 但只切出 1 段                      必须为否
    标题前缀     每段首行是 "# ...(第N部分)[共M部分]"        100% PASS
    二级标题     每段含 "## "                              100% PASS
    父/子超限    父段 <=2000 token、子块 <=1000 token        超限率 0
    句尾完整性   段尾不是 "，、；：的了吗" 等断句符          <2% PASS
    代码块配对   每段 ``` 数量为偶数                        100% PASS
    标记误插     "@@/@!@" 前是非空白字符（插在句中）         0 处
    体量分布     token 的 p50 / p95                         仅报告

用法：
    python 09_quality_gate.py parse --pdf 结算细则.pdf --md ./mineru_out/结算细则/结算细则_norm.md
    python 09_quality_gate.py chunk --md 1_1_new_process.md
    python 09_quality_gate.py all   --pdf x.pdf --md y.md

退出码：0 = 无 FAIL；1 = 存在 FAIL（便于接流水线前置门禁）；--strict 时 WARN 也算失败。
依赖：标准库 + 可选 pymupdf（A 层字符/目录）、可选 tiktoken（更准的 token 估算）。
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
_FENCE = re.compile(r"^\s*(```|~~~)")
_HEAD = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE = re.compile(r"^\s*\|")
_SHORT = 60


@dataclass
class Metric:
    name: str
    value: str
    grade: str
    note: str = ""


# ------------------------------------------------------------------ 通用工具
def _read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _norm_title(s: str) -> str:
    """标题归一化：去空白与中英文标点，便于"包含"式比对。"""
    return re.sub(r"[\s\u3000\.、,，:：;；·\-—_()（）\[\]【】“”\"'‘’]", "", s).lower()


def _md_head_titles(md: str) -> list[str]:
    return [m.group(2) for m in (_HEAD.match(l.strip()) for l in md.splitlines()) if m]


def _md_body_chars(md: str) -> int:
    """md 正文去空白后的字符数（跳过代码块，保留标题文字与表格文字）。"""
    buf, in_fence = [], False
    for line in md.splitlines():
        t = line.strip()
        if _FENCE.match(t):
            in_fence = not in_fence
            continue
        if in_fence or not t:
            continue
        m = _HEAD.match(t)
        buf.append(m.group(2) if m else t)
    return len(re.sub(r"\s", "", "".join(buf)))


def _tokens(text: str, mode: str) -> int:
    if mode == "tiktoken":
        try:
            import tiktoken
            return len(tiktoken.get_encoding("cl100k_base").encode(text))
        except Exception:
            pass  # 降级到 simple
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return int(cjk + (len(text) - cjk) / 4) + 1


def _repeat_short_lines(md: str, min_repeat: int = 5):
    """返回 (重复短行集合, 被判定为重复的行数, 非空行总数)。"""
    counts, total, in_fence = {}, 0, False
    for line in md.splitlines():
        t = line.strip()
        if _FENCE.match(t):
            in_fence = not in_fence
            continue
        if in_fence or not t or t.startswith("#") or t.startswith("|"):
            continue
        total += 1
        if len(t) <= _SHORT:
            counts[t] = counts.get(t, 0) + 1
    dup = {s for s, n in counts.items() if n >= min_repeat}
    hit = sum(n for s, n in counts.items() if s in dup)
    return dup, hit, total


def _table_blocks(md: str) -> int:
    blocks, run = 0, 0
    for line in md.splitlines():
        if _TABLE.match(line):
            run += 1
        else:
            if run >= 2:
                blocks += 1
            run = 0
    if run >= 2:
        blocks += 1
    return blocks


def _formula_blocks(md: str) -> int:
    return md.count("$$") // 2


def _pdf_facts(pdf_path: Path):
    """读取 PDF 页数 / 文本层字符数 / 书签标题；未装 pymupdf 返回 None。"""
    try:
        import fitz
    except ImportError:
        return None
    with fitz.open(str(pdf_path)) as doc:
        pages = doc.page_count
        chars = sum(len(re.sub(r"\s", "", p.get_text("text"))) for p in doc)
        toc = [t[1].strip() for t in doc.get_toc(simple=True) if t and t[1].strip()]
    return {"pages": pages, "chars": chars, "toc": toc}


def _find_layout_json(md_path: Path):
    for pat in ("*content_list*.json", "*middle*.json"):
        hits = sorted(p for p in md_path.parent.glob(pat) if p.is_file())
        if hits:
            return hits[0]
    return None


def _layout_facts(json_path: Path):
    """MinerU content_list / middle json → 页覆盖、表格数、公式数。"""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    items = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("pdf_info", "content_list", "pages"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
    if not items:
        return None
    pages, tables, equations = set(), 0, 0
    for it in items:
        if not isinstance(it, dict):
            continue
        for k in ("page_idx", "page", "page_no", "page_id"):
            if isinstance(it.get(k), int):
                pages.add(it[k])
                break
        typ = str(it.get("type", "")).lower()
        if typ == "table":
            tables += 1
        elif typ in ("equation", "interline_equation"):
            equations += 1
    return {"pages": len(pages), "tables": tables, "equations": equations}


# ------------------------------------------------------------------ A 层
def check_parse(md_path: Path, pdf_path: Path | None, layout_json: Path | None) -> list[Metric]:
    md = _read(md_path)
    ms: list[Metric] = []
    pdf = _pdf_facts(pdf_path) if pdf_path else None
    layout = _layout_facts(layout_json) if layout_json else None

    # 1) 字符保真度
    md_chars = _md_body_chars(md)
    if pdf and pdf["chars"] > 200:
        ratio = md_chars / pdf["chars"]
        grade = PASS if 0.80 <= ratio <= 1.25 else (WARN if 0.65 <= ratio <= 1.45 else FAIL)
        ms.append(Metric("字符保真度", f"{ratio:.3f}（md {md_chars} / pdf {pdf['chars']}）", grade,
                         "比值偏低多是漏页/丢段，偏高多是页眉页脚重复"))
    else:
        ms.append(Metric("字符保真度", f"md {md_chars} 字符", SKIP,
                         "PDF 无文本层（扫描件）或未装 pymupdf → 改用页级抽样人工核对"))

    # 2) 目录对齐率
    if pdf and pdf["toc"]:
        heads = [_norm_title(t) for t in _md_head_titles(md)]
        hit = [t for t in pdf["toc"] if (nt := _norm_title(t)) and any(nt in h or h in nt for h in heads if h)]
        rate = len(hit) / len(pdf["toc"])
        grade = PASS if rate >= 0.9 else (WARN if rate >= 0.75 else FAIL)
        missing = [t for t in pdf["toc"] if t not in hit][:5]
        ms.append(Metric("目录对齐率", f"{rate:.1%}（{len(hit)}/{len(pdf['toc'])}）", grade,
                         "缺失示例：" + "；".join(missing) if missing else "书签标题均已出现在 md 标题中"))
    else:
        ms.append(Metric("目录对齐率", "—", SKIP, "PDF 无书签或未装 pymupdf，无法比对"))

    # 3) 页覆盖
    if pdf and layout and pdf["pages"]:
        rate = layout["pages"] / pdf["pages"]
        grade = PASS if rate >= 0.999 else (WARN if rate >= 0.95 else FAIL)
        ms.append(Metric("页覆盖", f"{layout['pages']}/{pdf['pages']}（{rate:.1%}）", grade,
                         "有页缺失说明整页被丢弃（扫描件/加密页常见）"))
    else:
        ms.append(Metric("页覆盖", "—", SKIP, "需要 MinerU 的 content_list/middle json 与 PDF 页数"))

    # 4) 表格完整性
    if layout and layout["tables"]:
        md_t = _table_blocks(md)
        diff = abs(md_t - layout["tables"]) / layout["tables"]
        grade = PASS if diff <= 0.10 else (WARN if diff <= 0.25 else FAIL)
        ms.append(Metric("表格完整性", f"md {md_t} 块 / layout {layout['tables']} 个", grade,
                         "差值大说明表格被拆成散文本，或 md 表格未成块"))
    else:
        ms.append(Metric("表格完整性", f"md {_table_blocks(md)} 块", SKIP,
                         "layout json 中无表格信息，仅报告 md 侧数量"))

    # 5) 公式完整性
    if layout and layout["equations"]:
        md_f = _formula_blocks(md)
        rate = min(1.0, md_f / layout["equations"])
        grade = PASS if rate >= 0.95 else (WARN if rate >= 0.80 else FAIL)
        ms.append(Metric("公式完整性", f"md {md_f} 块 / layout {layout['equations']} 个", grade,
                         "公式丢失通常出现在扫描件与双栏版式"))
    else:
        ms.append(Metric("公式完整性", f"md {_formula_blocks(md)} 块", SKIP,
                         "layout json 中无公式信息，仅报告 md 侧数量"))

    # 6) 乱码率
    body = re.sub(r"\s", "", md)
    bad = sum(1 for c in body if c == "\ufffd" or "\ue000" <= c <= "\uf8ff")
    rate = bad / max(1, len(body))
    grade = PASS if rate < 0.001 else (WARN if rate < 0.005 else FAIL)
    ms.append(Metric("乱码率", f"{rate:.4%}（{bad}/{len(body)}）", grade, "U+FFFD 与私用区字符"))

    # 7) 页眉页脚残留
    _, hit, total = _repeat_short_lines(md)
    rate = hit / max(1, total)
    grade = PASS if rate < 0.01 else (WARN if rate < 0.03 else FAIL)
    ms.append(Metric("页眉页脚残留", f"{rate:.2%}（{hit}/{total} 行）", grade,
                     "重复短行会跟着每个分段进水，污染检索"))
    return ms


# ------------------------------------------------------------------ B 层
def check_chunk(md_path: Path, max_parent: int, max_child: int, token_mode: str) -> list[Metric]:
    md = _read(md_path)
    ms: list[Metric] = []
    at_marks = md.count("@!@")
    segments = [s.strip("\n") for s in md.split("@!@")]
    segments = [s for s in segments if s.strip()]

    # 1) 是否真的切过：正常产物应有多个父段；只有 1 段基本可判定没走 01_ 切片
    if len(segments) <= 1:
        if at_marks:
            ms.append(Metric("未切分检测", f"含 {at_marks} 个 @!@ 却只切出 {len(segments)} 段", FAIL,
                             "标记未生效，检查 01_main_append_title.py 的输出"))
        elif len(md) > 2000:
            ms.append(Metric("未切分检测", f"仅 1 段、无 @!@、{len(md)} 字符", FAIL,
                             "文件没有切片标记：漏了 01_main_append_title.py，或上传了 _norm.md"))
        else:
            ms.append(Metric("未切分检测", f"仅 1 段、{len(md)} 字符", SKIP, "短文档，单段属正常"))
    else:
        ms.append(Metric("未切分检测", f"{len(segments)} 段 / {at_marks} 个 @!@", PASS, ""))

    if not segments:
        return ms

    no_head, no_h2, over_p, over_c, bad_tail, odd_fence = [], [], [], [], [], []
    parent_tokens, child_tokens = [], []
    child_total = 0
    for i, seg in enumerate(segments, 1):
        lines = [l for l in seg.splitlines() if l.strip()]
        if not lines or not lines[0].startswith("# "):
            no_head.append(i)
        if not any(l.startswith("## ") for l in lines):
            no_h2.append(i)

        pt = _tokens(seg, token_mode)
        parent_tokens.append(pt)
        if pt > max_parent:
            over_p.append((i, pt))

        children = [c.strip() for c in seg.split("@@") if c.strip()]
        child_total += len(children)
        for c in children:
            ct = _tokens(c, token_mode)
            child_tokens.append(ct)
            if ct > max_child:
                over_c.append((i, ct))

        if seg.count("```") % 2:
            odd_fence.append(i)

        tail = lines[-1].rstrip() if lines else ""
        if tail and not tail.startswith("|") and tail[-1] in "，、；：,;:（(的了吗呢":
            bad_tail.append(i)

    def rate_metric(name, bad_list, total, pass_r, warn_r, note=""):
        r = len(bad_list) / max(1, total)
        g = PASS if r <= pass_r else (WARN if r <= warn_r else FAIL)
        if bad_list:
            shown = bad_list[:5] if isinstance(bad_list[0], int) else [f"段{i}({t}tok)" for i, t in bad_list[:5]]
            note += "；示例 " + "、".join(str(x) for x in shown)
        ms.append(Metric(name, f"{r:.2%}（{len(bad_list)}/{total}）", g, note))

    rate_metric("标题前缀完整", no_head, len(segments), 0, 0, "每段首行应是 # 主标题(第N部分)[共M部分]")
    rate_metric("二级标题存在", no_h2, len(segments), 0, 0, "01_main_append_title.py 缺 ## 会漏内容")
    rate_metric("父段超限", over_p, len(segments), 0, 0.02, f"上限 {max_parent} token")
    rate_metric("子块超限", over_c, max(1, child_total), 0, 0.02, f"上限 {max_child} token")
    rate_metric("句尾完整性", bad_tail, len(segments), 0.02, 0.05, "段尾落在逗号/顿号上=切在句中")
    rate_metric("代码块配对", odd_fence, len(segments), 0, 0, "``` 数量为奇数说明切进了代码块")

    # 标记误插：@@ / @!@ 紧贴非空白字符（插在句子里）
    bad_marks = len(re.findall(r"\S@@", md)) + len(re.findall(r"\S@!@", md))
    ms.append(Metric("标记误插", f"{bad_marks} 处", PASS if bad_marks == 0 else FAIL,
                     "标记应独占行首，插在句中会把段落切碎"))

    # 体量分布（仅报告）
    def dist(vals):
        if not vals:
            return "无"
        vals = sorted(vals)
        p95 = vals[min(len(vals) - 1, int(len(vals) * 0.95))]
        return f"n={len(vals)} p50={statistics.median(vals):.0f} p95={p95} max={vals[-1]}"

    ms.append(Metric("父段 token 分布", dist(parent_tokens), SKIP, "参考值，不判定"))
    ms.append(Metric("子块 token 分布", dist(child_tokens), SKIP, f"子块总数 {child_total}，参考值"))
    return ms


# ------------------------------------------------------------------ 输出
def render(metrics: list[Metric], title: str, inputs: dict) -> str:
    lines = [f"# 质量门禁报告 — {title}", "", f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}", ""]
    lines += [f"- {k}：`{v}`" for k, v in inputs.items()]
    lines += ["", "| 指标 | 实测 | 判定 | 说明 |", "|------|------|------|------|"]
    lines += [f"| {m.name} | {m.value} | {m.grade} | {m.note} |" for m in metrics]
    counts = {g: sum(1 for m in metrics if m.grade == g) for g in (PASS, WARN, FAIL, SKIP)}
    lines += ["", f"**汇总**：PASS {counts[PASS]} / WARN {counts[WARN]} / FAIL {counts[FAIL]} / SKIP {counts[SKIP]}", ""]
    return "\n".join(lines)


def print_metrics(metrics: list[Metric]):
    print(f"\n{'指标':<16}{'实测':<42}{'判定':<8}说明")
    print("-" * 110)
    for m in metrics:
        print(f"{m.name:<16}{m.value:<42}{m.grade:<8}{m.note}")


def summarize(metrics: list[Metric], strict: bool) -> int:
    counts = {g: sum(1 for m in metrics if m.grade == g) for g in (PASS, WARN, FAIL, SKIP)}
    print(f"汇总：PASS {counts[PASS]} / WARN {counts[WARN]} / FAIL {counts[FAIL]} / SKIP {counts[SKIP]}")
    if counts[FAIL] or (strict and counts[WARN]):
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="A+B 质量门禁：MinerU 解析保真 + 分片合法")
    ap.add_argument("stage", nargs="?", default="all", choices=["parse", "chunk", "all"])
    ap.add_argument("--pdf", help="原始 PDF（parse 阶段的对照基准）")
    ap.add_argument("--md", required=True, help="待检查的 Markdown（parse 用 _norm.md，chunk 用切片后 md）")
    ap.add_argument("--layout-json", default=None, help="MinerU content_list/middle json（默认自动查找）")
    ap.add_argument("--report", default=None, help="报告输出路径（默认 quality_report_<stage>.md）")
    ap.add_argument("--max-parent", type=int, default=2000, help="父段 token 上限（对齐 Dify max_tokens）")
    ap.add_argument("--max-child", type=int, default=1000, help="子块 token 上限")
    ap.add_argument("--tokenizer", choices=["simple", "tiktoken"], default="simple", help="token 估算方式")
    ap.add_argument("--strict", action="store_true", help="WARN 也返回非 0 退出码")
    ap.add_argument("--json", action="store_true", help="额外打印 JSON 便于 CI 采集")
    args = ap.parse_args()

    md_path = Path(args.md)
    if not md_path.is_file():
        sys.exit(f"md 不存在：{md_path}")
    pdf_path = Path(args.pdf) if args.pdf else None
    if pdf_path and not pdf_path.is_file():
        sys.exit(f"pdf 不存在：{pdf_path}")

    def report_path(name: str) -> Path:
        """--report 指定时按层生成文件名，避免 all 模式下两层互相覆盖。"""
        if not args.report:
            return Path(f"quality_report_{name}.md")
        p = Path(args.report)
        return p.with_name(f"{p.stem}_{name}{p.suffix or '.md'}") if args.stage == "all" else p

    metrics: list[Metric] = []
    inputs = {"md": str(md_path)}
    code = 0

    if args.stage in ("parse", "all"):
        if not pdf_path:
            print("[提示] 未提供 --pdf，A 层只能检查 md 侧指标（乱码、页眉、表格数量）")
        layout = Path(args.layout_json) if args.layout_json else _find_layout_json(md_path)
        ms = check_parse(md_path, pdf_path, layout)
        print("\n=== A 层：MinerU 解析保真 ===")
        print_metrics(ms)
        p = report_path("parse")
        p.write_text(render(ms, "A 层 MinerU 解析保真", {**inputs, "pdf": str(pdf_path or "—"),
                                                          "layout_json": str(layout or "—")}), encoding="utf-8")
        print(f"报告：{p.resolve()}")
        code = max(code, summarize(ms, args.strict))
        metrics += ms

    if args.stage in ("chunk", "all"):
        ms = check_chunk(md_path, args.max_parent, args.max_child, args.tokenizer)
        print("\n=== B 层：分片合法性 ===")
        print_metrics(ms)
        p = report_path("chunk")
        p.write_text(render(ms, "B 层分片合法性",
                            {**inputs, "max_parent": args.max_parent, "max_child": args.max_child,
                             "tokenizer": args.tokenizer}), encoding="utf-8")
        print(f"报告：{p.resolve()}")
        code = max(code, summarize(ms, args.strict))
        metrics += ms

    if args.json:
        print(json.dumps([m.__dict__ for m in metrics], ensure_ascii=False, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
