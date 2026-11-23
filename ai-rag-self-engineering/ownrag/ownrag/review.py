"""解析复核（入库前的第三道闸）：把"解析成了什么 + 切成了什么"落盘给人看，通过才写索引。

为什么必须有这一步：解析是 RAG 链路里最不可控的一段（版式识别、扫描件、表格还原），
而且**错在解析**这件事在问答阶段几乎无法回溯——答案不对时你只能看到"召回块很怪"，
看不到"这一页本来就没解析出来"。所以在 chunk 之后、embed/index 之前插一道人工确认：

  prepare_review  解析产物 + 切分结果落盘 + 自动质量检查（阻断项 / 提示项）+ 写状态机
  review_gate     状态机闸门：pending / rejected 一律不许进索引，approved 才放行

三道闸门的分工（本工程当前口径）：
  ① 解析闸 validate_parsed（自动：空/过短/页缺失 → 与解析失败同待遇）
  ② 复核闸 prepare_review + review_gate（人工：产物给人看，通过才入库）
  ③ 生成闸 gates（自动：候选不足拒答、引用与数字可核验）

落盘结构（data/review/<doc_id>/）：
  parsed.md     解析中间态全文（复核对象原貌，不经任何裁剪）
  chunks.json   切分预览（块序号 / 块头 / 锚点 / 字数 / 前若干字）
  report.json   页级明细 + 解析步骤 + 质量检查 + 本次参数
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from ownrag.core.pipeline import StepContext
from ownrag.core.registry import Step, StepResult, register
from ownrag.tokens import est_tokens as _est_tokens

STATUSES = ("pending", "approved", "rejected")
PREVIEW_CHARS = 160                     # 切分预览里每块保留的正文长度
_PAGE_MARK = re.compile(r"<!--\s*page:(\d+)\s*-->")
_BAD_CHARS = re.compile(r"[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]")   # 替换符 + 控制字符


# ---------------------------------------------------------------- 质量检查
def _page_details(markdown: str, structures: list[dict]) -> tuple[list[dict], int]:
    """页级明细：只在 markdown 带 `<!--page:N-->` 标记时算得出来（降级链的 pymupdf 路径会带）。
    MinerU 产出的 Markdown 大多无页标记——那就不编造，返回空列表并在报告里标明。"""
    marks = [(m.start(), m.end(), int(m.group(1))) for m in _PAGE_MARK.finditer(markdown)]
    if not marks:
        return [], 0

    kind_by_page: dict[int, dict[str, int]] = {}
    for s in structures:
        loc = str(s.get("location") or "")
        m = re.match(r"page:(\d+)", loc)
        if not m:
            continue
        bucket = kind_by_page.setdefault(int(m.group(1)), {})
        bucket[str(s.get("kind") or "other")] = bucket.get(str(s.get("kind") or "other"), 0) + 1

    pages: list[dict] = []
    for idx, (_start, end, page_no) in enumerate(marks):
        stop = marks[idx + 1][0] if idx + 1 < len(marks) else len(markdown)
        body = markdown[end:stop].strip()
        kinds = kind_by_page.get(page_no, {})
        pages.append({"page": page_no, "chars": len(body),
                      "tables": kinds.get("table", 0),
                      "images": kinds.get("image", 0) + kinds.get("keyframe", 0),
                      "empty": len(body) == 0})
    return pages, len(marks)


def quality_checks(parsed: dict, chunks: list[dict], *,
                   min_chars_per_page: int = 20,
                   max_chunk_tokens: int = 512,
                   oversized_ratio: float = 1.5) -> dict:
    """自动质量检查：blocking（阻断，不允许放行）/ warn（提示，复核重点）/ stats（可量化事实）。

    刻意不把"能不能入库"压成单一分数——阻断项是硬事实（空正文、几乎无字），
    提示项是"这里通常意味着解析出了问题，你自己看一眼"。
    """
    markdown: str = parsed.get("markdown") or ""
    metadata: dict = parsed.get("metadata") or {}
    stats_in: dict = parsed.get("stats") or {}
    structures: list[dict] = parsed.get("structures") or []

    declared_pages = int(stats_in.get("pages") or 0)
    pages, marker_count = _page_details(markdown, structures)
    chars = len(markdown)
    headings = len(re.findall(r"^#{1,6}\s+", markdown, flags=re.MULTILINE))
    tables = sum(1 for s in structures if s.get("kind") == "table")
    pipe_lines = len(re.findall(r"^\s*\|.*\|\s*$", markdown, flags=re.MULTILINE))
    bad = len(_BAD_CHARS.findall(markdown))
    bad_rate = round(bad / chars, 5) if chars else 0.0
    empty_pages = [p["page"] for p in pages if p["empty"]]

    blocking: list[dict] = []
    warn: list[dict] = []

    if not markdown.strip():
        blocking.append({"code": "empty_markdown", "detail": "解析产物为空 Markdown"})
    else:
        per_page = chars / declared_pages if declared_pages else chars
        if per_page < min_chars_per_page:
            blocking.append({"code": "too_few_chars",
                             "detail": f"字符密度过低：{chars} 字符 / {declared_pages or '未知'} 页"
                                       f"（阈值 {min_chars_per_page}/页），疑似扫描件未 OCR 或文本层缺失"})

    if marker_count and declared_pages and marker_count != declared_pages:
        warn.append({"code": "page_marker_mismatch",
                     "detail": f"页标记 {marker_count} 个 ≠ 解析声明 {declared_pages} 页——"
                               f"引用页码可能错位"})
    if empty_pages:
        warn.append({"code": "empty_pages",
                     "detail": f"{len(empty_pages)} 页无可提取文本：第 {empty_pages[:10]} 页"
                               f"{'（等）' if len(empty_pages) > 10 else ''}"})
    if bad_rate > 0.005:
        warn.append({"code": "mojibake",
                     "detail": f"乱码/控制字符占比 {bad_rate:.2%}（{bad} 个），疑似编码或 OCR 质量差"})
    if headings == 0 and chars > 200:
        warn.append({"code": "no_headings",
                     "detail": "正文超过 200 字符但没有任何标题行——结构丢失，切分只能按长度硬切"})
    if tables == 0 and pipe_lines >= 3:
        warn.append({"code": "table_flattened",
                     "detail": f"正文有 {pipe_lines} 行表格行文，但 structures 里 0 张表——"
                               f"表格可能被拍平成普通段落"})
    oversized = [c for c in chunks
                 if _est_tokens(c.get("text") or "") > max_chunk_tokens * oversized_ratio]
    if oversized:
        warn.append({"code": "oversized_chunk",
                     "detail": f"{len(oversized)} 个块超过 {int(max_chunk_tokens * oversized_ratio)} tokens"
                               f"（表格/超长段独立成块，属预期则忽略）"})
    if metadata.get("degraded"):
        warn.append({"code": "degraded_path", "detail": f"走了降级链：{metadata['degraded']}"})

    verdict = "fail" if blocking else ("warn" if warn else "pass")
    return {
        "verdict": verdict,
        "blocking": blocking,
        "warn": warn,
        "stats": {"chars": chars, "pages": declared_pages, "page_markers": marker_count,
                  "headings": headings, "tables": tables, "structures": len(structures),
                  "bad_char_rate": bad_rate, "chunks": len(chunks),
                  "backend": stats_in.get("backend") or metadata.get("degraded") or "unknown"},
        "pages": pages,
    }


# ---------------------------------------------------------------- 工件落盘
def write_artifacts(review_dir: Path, *, markdown: str, chunks: list[dict],
                    report: dict) -> dict[str, str]:
    """三份工件落盘（全量，不截断）：给人看的原件、切分预览、结构化报告。"""
    review_dir.mkdir(parents=True, exist_ok=True)
    parsed_md = review_dir / "parsed.md"
    parsed_md.write_text(markdown, encoding="utf-8")

    preview = [{"ordinal": c.get("ordinal"), "chunk_id": c.get("chunk_id"),
                "chars": len(c.get("text") or ""),
                "tokens": _est_tokens(c.get("text") or ""),
                "anchors": c.get("anchors") or {},
                "has_table": bool((c.get("meta") or {}).get("has_table")),
                "head": (c.get("text") or "")[:PREVIEW_CHARS]} for c in chunks]
    chunks_js = review_dir / "chunks.json"
    chunks_js.write_text(json.dumps(preview, ensure_ascii=False, indent=1), encoding="utf-8")

    report_js = review_dir / "report.json"
    report_js.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"parsed_md": str(parsed_md), "chunks": str(chunks_js), "report": str(report_js)}


# ---------------------------------------------------------------- 状态机
def get_review(conn: sqlite3.Connection, doc_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM parse_reviews WHERE doc_id=?", (doc_id,)).fetchone()


def list_reviews(conn: sqlite3.Connection, status: str = "", limit: int = 50) -> list[sqlite3.Row]:
    q = "SELECT * FROM parse_reviews"
    args: tuple = ()
    if status:
        q, args = q + " WHERE status=?", (status,)
    return conn.execute(q + " ORDER BY created_at DESC LIMIT ?", (*args, max(1, min(limit, 200)))
                        ).fetchall()


def save_review(conn: sqlite3.Connection, *, doc_id: str, kb: str, task_id: str | None,
                trace_id: str | None, pipeline: str, source_file: str, checks: dict,
                report_path: str) -> str:
    """写复核记录并返回状态。

    已 approved 的记录不因重跑而回落 pending——人工审批过的事实不该被一次 resume 抹掉。
    """
    stats = checks["stats"]
    existing = get_review(conn, doc_id)
    status = "approved" if (existing and existing["status"] == "approved") else "pending"
    conn.execute(
        "INSERT INTO parse_reviews(doc_id, kb, task_id, trace_id, pipeline, source_file, backend,"
        " status, verdict, pages, chars, tables, structures, blocking_json, warn_json, pages_json,"
        " report_path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(doc_id) DO UPDATE SET kb=excluded.kb, task_id=excluded.task_id,"
        " trace_id=excluded.trace_id, pipeline=excluded.pipeline, source_file=excluded.source_file,"
        " backend=excluded.backend, verdict=excluded.verdict, pages=excluded.pages,"
        " chars=excluded.chars, tables=excluded.tables, structures=excluded.structures,"
        " blocking_json=excluded.blocking_json, warn_json=excluded.warn_json,"
        " pages_json=excluded.pages_json, report_path=excluded.report_path,"
        " updated_at=datetime('now','localtime')",
        (doc_id, kb, task_id, trace_id, pipeline, source_file, stats.get("backend"),
         status, checks["verdict"], stats.get("pages", 0), stats.get("chars", 0),
         stats.get("tables", 0), stats.get("structures", 0),
         json.dumps(checks["blocking"], ensure_ascii=False),
         json.dumps(checks["warn"], ensure_ascii=False),
         json.dumps(checks["pages"], ensure_ascii=False), report_path),
    )
    conn.commit()
    return status


def set_status(conn: sqlite3.Connection, doc_id: str, status: str,
               note: str | None = None) -> bool:
    if status not in STATUSES:
        raise ValueError(f"非法复核状态：{status}")
    cur = conn.execute(
        "UPDATE parse_reviews SET status=?, note=?, reviewed_at=datetime('now','localtime'),"
        " updated_at=datetime('now','localtime') WHERE doc_id=?", (status, note, doc_id))
    conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------- 步骤
@register("prepare_review")
class PrepareReview(Step):
    """解析 + 切分产物复核：落盘三份工件、跑自动检查、置 pending。

    放在 chunk_markdown 之后：复核要能同时看到"解析成了什么"和"切成了什么"，
    否则人工只能凭 Markdown 想象切分效果。
    """

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        parsed: dict = ctx.data.get("parsed") or {}
        chunks: list[dict] = ctx.data.get("chunks") or []
        if not parsed.get("markdown"):
            return StepResult.fail("无 parsed.markdown——上游解析步骤缺失或未产出")
        if not chunks:
            return StepResult.fail("无 chunks——prepare_review 必须排在 chunk_markdown 之后")

        checks = quality_checks(
            parsed, chunks,
            min_chars_per_page=int(params.get("min_chars_per_page", 20)),
            max_chunk_tokens=int(params.get("max_chunk_tokens", 512)),
            oversized_ratio=float(params.get("oversized_ratio", 1.5)))

        auto_approve = bool(params.get("auto_approve", False))
        report: dict[str, Any] = {
            "doc_id": ctx.doc_id, "kb": ctx.kb, "pipeline": ctx.data.get("_pipeline"),
            "source_file": (parsed.get("metadata") or {}).get("source_file"),
            "parse_route": ctx.data.get("page_route"),      # detect_pages 的页级路由结论
            "params": {k: v for k, v in params.items()},
            "stats": parsed.get("stats") or {},
            "metadata": parsed.get("metadata") or {},
            "assets": sorted((parsed.get("assets") or {}).keys())[:20],
            "checks": checks,
        }
        paths = write_artifacts(ctx.settings.review_dir / ctx.doc_id,
                               markdown=parsed["markdown"], chunks=chunks, report=report)

        status = save_review(
            ctx.conn, doc_id=ctx.doc_id, kb=ctx.kb, task_id=ctx.data.get("_task_id"),
            trace_id=ctx.trace_id, pipeline=str(ctx.data.get("_pipeline") or ""),
            source_file=str(report["source_file"] or ctx.doc_id), checks=checks,
            report_path=paths["report"])

        # 自动放行只对"无阻断项"生效；auto_approve=False（默认）时一律等人看
        if auto_approve and checks["verdict"] != "fail":
            set_status(ctx.conn, ctx.doc_id, "approved", "auto_approve：无阻断项，自动放行")
            status = "approved"

        counters = {"verdict": checks["verdict"], "status": status,
                    "chars": checks["stats"]["chars"], "pages": checks["stats"]["pages"],
                    "blocking": len(checks["blocking"]), "warn": len(checks["warn"])}
        if checks["blocking"]:
            detail = "；".join(f"{b['code']}:{b['detail']}" for b in checks["blocking"])
            return StepResult.fail(f"解析质量检查未通过（已落盘待复核）：{detail}", **counters)
        return StepResult.ok(review=f"{ctx.doc_id}:{status}", **counters)


@register("review_gate")
class ReviewGate(Step):
    """入库闸门：复核未通过（pending / rejected）一律不许写索引。"""

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        row = get_review(ctx.conn, ctx.doc_id)
        if row is None:
            return StepResult.fail(
                "复核记录缺失：管道里应有 prepare_review 且已执行（否则无人看过就入库）")
        status = row["status"]
        if status == "approved":
            return StepResult.ok(gate="approved", verdict=row["verdict"])
        if status == "rejected":
            note = row["note"] or "无原因"
            return StepResult.fail(f"解析产物已驳回，拒绝入库：{note}")
        return StepResult.fail(
            f"解析产物待人工复核（自动结论 verdict={row['verdict']}，"
            f"阻断项 {len(json.loads(row['blocking_json'] or '[]'))} 条）："
            f"到 /ui 的「解析复核」页看产物，通过后重试本任务")
