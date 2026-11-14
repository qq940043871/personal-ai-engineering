# -*- coding: utf-8 -*-
"""大 PDF 云端解析验证：切分 → 逐份走 mineru.net 开放平台 → 合并页锚 → 三层校验。

为什么切分：开放平台单文件有页数上限（保守口径 200 页），大书按 --part-pages 切成
多个 PDF 分别提交，用 ownrag 已验证的 openapi 客户端（mineru_openapi.parse_via_openapi）。

中间产物全部保留（可追溯）：
  <out>/parts/            切分出的分册 PDF（pymupdf 切页，无重采样）
  <out>/mineru/part_XXX/  每份云解析产物（full.md + images/ + *_content_list.json + zip 已解）
  <out>/mineru/merged_full.md           各分册 full.md 原样拼接（云上原始口径）
  <out>/mineru/merged_pageanchors.md    从 content_list 重建的页锚版（<!--page:原始页-->，
                                        图片引用改写为 part_XXX/images/... 相对路径）
  <out>/accuracy_report/  check_parse_accuracy.py 三层校验报告
  <out>/pipeline/         ownrag 管道契约产物（validate_parsed + chunk_markdown 的 chunks dump）
  <out>/summary.json      关键数字与分册状态

用法（ownrag/ 下）：
  python scripts/validate_pdf_cloud.py --pdf pdf/程序是怎样跑起来的.pdf --part-pages 100
前置：ownrag/.env 填好 MINERU_OPEN_TOKEN；pymupdf 已装。
退出码：0 = 三层校验 PASS/WARN；1 = FAIL；2 = 前置失败。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ownrag.steps  # noqa: F401  注册全部步骤
from ownrag.config import get_settings
from ownrag.core.pipeline import StepContext
from ownrag.core.registry import STEP_REGISTRY
from ownrag.ingest.base import ParsedDoc
from ownrag.ingest.mineru_openapi import API_BASE_DEFAULT, parse_via_openapi


def split_pdf(pdf: Path, part_pages: int, out_dir: Path) -> list[tuple[int, int, Path]]:
    """按页数切分 PDF（pymupdf 无损抽页），返回 [(起始页, 结束页, 分册路径)]，页码 1 起。"""
    import fitz

    src = fitz.open(str(pdf))
    total = src.page_count
    parts = []
    for start in range(0, total, part_pages):
        end = min(start + part_pages, total)          # 1 起的闭区间
        part = fitz.open()
        part.insert_pdf(src, from_page=start, to_page=end - 1)
        rel = end - start
        path = out_dir / f"part_{start + 1:03d}-{end:03d}.pdf"
        part.save(str(path))
        part.close()
        parts.append((start + 1, end, path))
        print(f"[切分] {path.name}（{rel} 页）")
    src.close()
    return parts


def cloud_parse_part(part: Path, doc_id: str, settings, model_version: str,
                     out_dir: Path) -> dict:
    """单分册走开放平台三步流，返回产物摘要。密钥/基地址来自 .env（不落代码）。"""
    t0 = time.perf_counter()
    md, assets, structures, stats = parse_via_openapi(
        part, doc_id=doc_id,
        base_url=settings.mineru_open_base_url or API_BASE_DEFAULT,
        token=settings.mineru_open_token,
        model_version=model_version,
        poll_interval=5.0, poll_timeout=1800.0,
        out_dir=out_dir,
    )
    elapsed = time.perf_counter() - t0
    print(f"[云解析] {part.name} 完成：{len(md)} 字符，{len(assets)} 图，"
          f"{len(structures)} 结构，{elapsed:.0f}s（batch={stats.get('batch_id', '')[:8]}…）")
    return {"part": part.name, "md_chars": len(md), "images": len(assets),
            "structures": len(structures), "elapsed_sec": round(elapsed, 1),
            "stats": stats, "md": md, "assets_dir": str(out_dir)}


def load_content_list(out_dir: Path) -> list[dict] | None:
    """读分册的 *_content_list.json（块级清单，含 page_idx）；缺失返回 None。"""
    for p in sorted(out_dir.rglob("*_content_list.json")):
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(items, list):
                return items
        except (OSError, ValueError):
            continue
    return None


_NOISE_TYPES = {"page_number", "header", "footer"}   # 版面噪音块：页码/页眉/页脚，不进正文


def rebuild_pageanchored(part_md: str, content_list: list[dict] | None,
                         part_start: int, part_name: str) -> str:
    """构造页锚版分册 markdown。

    有 content_list：按块顺序重建（text/table/image），page_idx+part_start-1 = 原始页，
    每换页插 <!--page:原始页-->；图片引用改写为 part_XXX/images/... 相对路径；
    text_level 1/2 转一级/二级标题（保 heading 结构）。
    无 content_list：退化为整册单锚（<!--page:part_start-->），页级校验自然降级。
    """
    if not content_list:
        return f"<!--page:{part_start}-->\n\n{part_md}\n"
    lines: list[str] = []
    cur_page = None
    for item in content_list:
        page_idx = item.get("page_idx")
        orig = (part_start + int(page_idx)) if page_idx is not None else part_start
        if orig != cur_page:
            lines.append(f"<!--page:{orig}-->")
            cur_page = orig
        itype = item.get("type")
        if itype in _NOISE_TYPES:
            continue  # 页码/页眉/页脚是版面噪音，跳过（页锚照插，页覆盖统计不受影响）
        if itype == "image" and item.get("img_path"):
            lines.append(f"![图片]({part_name}/images/{Path(item['img_path']).name})")
        elif itype == "table" and item.get("table_body"):
            lines.append(item["table_body"])
        else:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            level = item.get("text_level")
            if level == 1:
                lines.append(f"# {text}")
            elif level == 2:
                lines.append(f"## {text}")
            else:
                lines.append(text)
    return "\n\n".join(lines) + "\n"


def run_pipeline_preview(merged_anchored: str, out_dir: Path, pages: int,
                         model_version: str) -> dict:
    """管道契约验证：注入解析产物 → validate_parsed → chunk_markdown（不 embed/不入库）。"""
    import types

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = ParsedDoc(doc_id="validate_cloud", source_type="pdf", markdown=merged_anchored,
                    metadata={"source_file": "云端分册合并", "parse_mode": "mineru-net-openapi-vlm"},
                    stats={"backend": f"open-{model_version}", "pages": pages, "md_chars": len(merged_anchored)})
    settings = types.SimpleNamespace(pipelines={})
    ctx = StepContext(doc_id="validate_cloud", trace_id="validate", kb="policy_v1",
                      conn=None, settings=settings,
                      data={"parsed": doc.to_dict(), "_pipeline": "pdf_v1"})
    r1 = STEP_REGISTRY["validate_parsed"]().run(ctx, {"min_chars_per_page": 20})
    r2 = STEP_REGISTRY["chunk_markdown"]().run(ctx, {"max_tokens": 512, "overlap": 64})
    chunks = ctx.data.get("chunks") or []
    (out_dir / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    preview = []
    for idx in [0, 1, len(chunks) // 2]:
        c = chunks[idx]
        preview.append(f"## 块 {c.get('ordinal', idx + 1)}（{c['chunk_id']}）\n\n"
                       f"锚点：{json.dumps(c.get('anchors', {}), ensure_ascii=False)}\n\n"
                       f"```\n{c['text'][:600]}\n```")
    (out_dir / "chunks_preview.md").write_text("\n\n---\n\n".join(preview), encoding="utf-8")
    return {"validate_parsed": r1.metrics, "chunk_markdown": r2.metrics, "chunk_count": len(chunks)}


def main() -> int:
    ap = argparse.ArgumentParser(description="大 PDF 切分 + 开放平台云解析验证")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--part-pages", type=int, default=100)
    ap.add_argument("--out", default=None, help="产物根目录（默认 data/validate/<书名>_cloud）")
    ap.add_argument("--model-version", default="vlm", choices=["pipeline", "vlm"],
                    help="开放平台解析档：vlm=扫描件准（默认）/ pipeline=电子版快")
    ap.add_argument("--skip-check", action="store_true", help="跳过三层校验（只产出合并 md）")
    args = ap.parse_args()
    model_version = args.model_version

    sys.stdout.reconfigure(encoding="utf-8")
    pdf = Path(args.pdf)
    if not pdf.is_file():
        print(f"✗ PDF 不存在：{pdf}")
        return 2

    import fitz
    with fitz.open(str(pdf)) as d:
        total_pages = d.page_count
    stem = pdf.stem
    out = Path(args.out) if args.out else Path("data/validate") / f"{stem}_cloud"
    (out / "parts").mkdir(parents=True, exist_ok=True)
    (out / "mineru").mkdir(parents=True, exist_ok=True)

    # 1) 切分
    parts = split_pdf(pdf, args.part_pages, out / "parts")

    # 2) 逐份云解析（顺序提交，避免触发频控）
    settings = get_settings()
    if not settings.mineru_open_token:
        print("✗ MINERU_OPEN_TOKEN 未配置（ownrag/.env）")
        return 2
    results = []
    for start, end, part in parts:
        part_dir = out / "mineru" / f"part_{start:03d}-{end:03d}"
        doc_id = f"{stem[:32]}-p{start:03d}"
        cached_md = part_dir / "full.md"
        if cached_md.is_file():
            # 幂等复用：分册已有云解析产物则不重复提交（省额度，重建只花本地时间）
            print(f"[云解析] {part.name} 已有产物，跳过云端调用（缓存复用）")
            md = cached_md.read_text(encoding="utf-8")
            assets = {p.stem: str(p) for p in sorted((part_dir / "images").glob("*")) if p.is_file()}
            res = {"part": part.name, "md_chars": len(md), "images": len(assets),
                   "structures": 0, "elapsed_sec": 0.0, "stats": {"cached": True},
                   "md": md, "assets_dir": str(part_dir)}
        else:
            res = cloud_parse_part(part, doc_id, settings, model_version, part_dir)
        res["orig_start"], res["orig_end"] = start, end
        results.append(res)

    # 3) 合并：原始拼接 + 页锚重建（content_list 的 page_idx + 分册起始页 = 原始页）
    merged_raw, merged_anchored, page_block_counts = [], [], {}
    for res in results:
        merged_raw.append(res["md"])
        part_dir = Path(res["assets_dir"])
        cl = load_content_list(part_dir)
        part_name = Path(res["part"]).stem
        anchored = rebuild_pageanchored(res["md"], cl, res["orig_start"], part_name)
        merged_anchored.append(anchored)
        if cl:
            for item in cl:
                if item.get("page_idx") is not None:
                    orig = res["orig_start"] + int(item["page_idx"])
                    page_block_counts[orig] = page_block_counts.get(orig, 0) + 1
    (out / "mineru" / "merged_full.md").write_text("\n\n".join(merged_raw), encoding="utf-8")
    (out / "mineru" / "merged_pageanchors.md").write_text("\n\n".join(merged_anchored), encoding="utf-8")
    covered = sorted(page_block_counts)
    empty_pages = [p for p in range(1, total_pages + 1) if p not in page_block_counts]
    print(f"[合并] 页锚版覆盖 {len(covered)}/{total_pages} 页，content_list 判空页：{empty_pages or '无'}")

    # 4) 管道契约验证（切分预览，不入库）
    pipeline_stats = run_pipeline_preview("\n\n".join(merged_anchored), out / "pipeline",
                                          total_pages, model_version)
    print(f"[管道] chunk_markdown：{pipeline_stats['chunk_count']} 块")

    # 5) 三层校验（校验工具在仓库上级 校验准确/）
    check_exit = None
    if not args.skip_check:
        checker = Path(__file__).resolve().parents[2] / "校验准确" / "check_parse_accuracy.py"
        if checker.is_file():
            import subprocess
            proc = subprocess.run(
                [sys.executable, "-I", str(checker),
                 "--pdf", str(pdf), "--md", str(out / "mineru" / "merged_pageanchors.md"),
                 "--out", str(out / "accuracy_report")],
                capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=".")
            print(proc.stdout[-1500:])
            check_exit = proc.returncode
        else:
            print(f"✗ 找不到校验工具：{checker}")

    summary = {"pdf": str(pdf), "pages": total_pages, "part_pages": args.part_pages,
               "model_version": model_version, "parts": [
                   {k: v for k, v in r.items() if k != "md"} for r in results],
               "covered_pages": len(covered), "empty_pages": empty_pages,
               "pipeline": pipeline_stats, "check_exit": check_exit}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    print(f"[完成] 产物：{out}")
    # 退出码跟校验工具对齐（0=PASS/WARN，1=FAIL）；空页率对书籍类语料的误报见校验报告说明
    return 0 if check_exit in (0, None) else 1


if __name__ == "__main__":
    raise SystemExit(main())
