"""解析复核路由：把"解析成了什么 / 切成了什么"摆到眼前，人工点头才入库。

  GET  /admin/reviews                 复核队列（按状态过滤，默认全部）
  GET  /admin/reviews/{doc_id}        详情：质量检查 + 页级明细 + 产物全文 + 切分预览 + 解析步骤
  POST /admin/reviews/{doc_id}/approve 通过 → 记录 approved → 自动续跑剩余管道（入库）
  POST /admin/reviews/{doc_id}/reject  驳回（必填原因）→ 拒绝入库，关闭该任务待办

审批与驳回都改状态机，真正拦人的是管道里的 review_gate 步骤——接口本身不"代跑管道逻辑"，
避免出现"页面说入库了、管道其实没跑"的两套口径。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ownrag import review as review_mod
from ownrag.config import get_settings
from ownrag.core import tasks as taskstore
from ownrag.core import trace
from ownrag.core.db import connect
from ownrag.core.pipeline import run_pipeline

router = APIRouter(prefix="/admin", tags=["review"])

MD_VIEW_CHARS = 400_000     # 产物全文单次返回上限（超长文档可按 offset 续读）


class ReviewNote(BaseModel):
    note: str | None = None


class RejectIn(BaseModel):
    note: str


def _conn() -> sqlite3.Connection:
    return connect(get_settings().db_path)


def _row_out(row: sqlite3.Row) -> dict:
    return {"doc_id": row["doc_id"], "kb": row["kb"], "task_id": row["task_id"],
            "trace_id": row["trace_id"], "pipeline": row["pipeline"],
            "source_file": row["source_file"], "backend": row["backend"],
            "status": row["status"], "verdict": row["verdict"],
            "pages": row["pages"], "chars": row["chars"],
            "tables": row["tables"], "structures": row["structures"],
            "blocking": json.loads(row["blocking_json"] or "[]"),
            "warn": json.loads(row["warn_json"] or "[]"),
            "note": row["note"], "reviewed_at": row["reviewed_at"],
            "created_at": row["created_at"]}


@router.get("/reviews")
def list_reviews(status: str = "", limit: int = 50) -> dict:
    settings = get_settings()
    conn = _conn()
    try:
        rows = review_mod.list_reviews(conn, status=status, limit=limit)
        counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM parse_reviews GROUP BY status").fetchall()}
        return {"items": [_row_out(r) for r in rows], "counts": counts,
                "pending_total": counts.get("pending", 0),
                "review_dir": str(settings.review_dir)}
    finally:
        conn.close()


@router.get("/reviews/{doc_id}")
def review_detail(doc_id: str, md: bool = True, offset: int = 0,
                  max_chars: int = MD_VIEW_CHARS) -> dict:
    """详情：DB 摘要 + 落盘工件。产物全文走 offset/max_chars，避免超长文档打爆前端。"""
    conn = _conn()
    try:
        row = review_mod.get_review(conn, doc_id)
        if row is None:
            raise HTTPException(404, f"无复核记录：{doc_id}")
        out = _row_out(row)
        out["pages_detail"] = json.loads(row["pages_json"] or "[]")
        out["steps"] = [dict(r) for r in trace.by_trace(conn, row["trace_id"] or "")]
        task = taskstore.get_task(conn, row["task_id"]) if row["task_id"] else None
        out["task"] = {"status": task["status"], "error": task["error"],
                       "current_step": task["current_step"]} if task else None
    finally:
        conn.close()

    base = get_settings().review_dir / doc_id
    report_path = Path(row["report_path"]) if row["report_path"] else base / "report.json"
    out["report"] = _read_json(report_path)
    chunks_path = base / "chunks.json"
    out["chunks"] = _read_json(chunks_path) or []
    if md:
        md_path = base / "parsed.md"
        if md_path.is_file():
            text = md_path.read_text(encoding="utf-8", errors="replace")
            offset = max(0, min(int(offset), len(text)))
            out["markdown"] = text[offset:offset + max(1, min(int(max_chars), MD_VIEW_CHARS))]
            out["markdown_total_chars"] = len(text)
            out["markdown_offset"] = offset
    return out


@router.post("/reviews/{doc_id}/approve")
def approve(doc_id: str, body: ReviewNote | None = None) -> dict:
    """通过 → approved → 自动续跑管道（从 review_gate 之后继续，检查点在任务表里）。"""
    settings = get_settings()
    conn = _conn()
    try:
        row = review_mod.get_review(conn, doc_id)
        if row is None:
            raise HTTPException(404, f"无复核记录：{doc_id}")
        if row["verdict"] == "fail":
            raise HTTPException(
                409, f"存在阻断项，不能放行：{json.dumps(json.loads(row['blocking_json'] or '[]'), ensure_ascii=False)}"
                     f"；请换解析后端/修正参数后重传文档")

        note = (body.note if body else None) or "人工复核通过"
        review_mod.set_status(conn, doc_id, "approved", note)
        task_id = row["task_id"]
        result: dict = {"doc_id": doc_id, "status": "approved", "note": note}
        if task_id:
            result["task_status"] = run_pipeline(conn, settings, task_id, resume=True)
        else:
            result["task_status"] = "skipped（无关联任务，可能已入库或来自脚本导入）"
        return result
    finally:
        conn.close()


@router.post("/reviews/{doc_id}/reject")
def reject(doc_id: str, body: RejectIn) -> dict:
    """驳回 → rejected：拒绝入库，并关闭该任务的待办（人工已决策，队列不该残留）。"""
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(422, "驳回必须写明原因（会写进待办与复核记录）")
    conn = _conn()
    try:
        row = review_mod.get_review(conn, doc_id)
        if row is None:
            raise HTTPException(404, f"无复核记录：{doc_id}")
        review_mod.set_status(conn, doc_id, "rejected", note)
        closed = 0
        if row["task_id"]:
            cur = conn.execute(
                "UPDATE todos SET status='done', resolved_at=datetime('now','localtime')"
                " WHERE task_id=? AND status='open'", (row["task_id"],))
            closed = cur.rowcount
            conn.commit()
        return {"doc_id": doc_id, "status": "rejected", "note": note,
                "todos_closed": closed}
    finally:
        conn.close()


def _read_json(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
