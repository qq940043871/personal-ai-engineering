"""文档接入路由：上传 → 任务表 → 后台执行管道（失败入待办，绝不静默丢文档）。"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from ownrag.config import get_settings
from ownrag.core import tasks as taskstore
from ownrag.core import trace
from ownrag.core.db import connect, init_schema
from ownrag.core.pipeline import run_pipeline
from ownrag.core.registry import STEP_REGISTRY

router = APIRouter(prefix="/docs", tags=["docs"])

# 扩展名 → 管道路由键（02 文档 §1.2 pipelines.yaml）
EXT_PIPELINE = {
    ".pdf": "pdf_v1",
    ".mp4": "av_v1", ".mkv": "av_v1", ".mov": "av_v1", ".mp3": "av_v1",
    ".wav": "av_v1", ".m4a": "av_v1", ".flac": "av_v1",
    ".xlsx": "excel_v1", ".xlsm": "excel_v1", ".csv": "excel_v1",
}


CHUNK = 1024 * 1024


def _save_upload(src, dest: Path, limit_bytes: int) -> int:
    """分块落盘并计数：超限即中止并清理，不留半截文件。
    直接 copyfileobj 的写法等于把磁盘交给客户端——生产入口必须有体积上限。"""
    total = 0
    with open(dest, "wb") as f:
        while True:
            part = src.read(CHUNK)
            if not part:
                return total
            total += len(part)
            if limit_bytes and total > limit_bytes:
                raise HTTPException(
                    413, f"文件超过上限 {limit_bytes // (1024 * 1024)} MB"
                         f"（OWNRAG_MAX_UPLOAD_MB / configs/models.yaml: max_upload_mb）")
            f.write(part)


@router.post("/upload")
def upload(background: BackgroundTasks, file: UploadFile = File(...),
           kb: str = Form("default")) -> dict:
    settings = get_settings()
    suffix = Path(file.filename or "").suffix.lower()
    pipeline = EXT_PIPELINE.get(suffix)
    if pipeline is None:
        raise HTTPException(415, f"不支持的扩展名 {suffix}（支持：{sorted(EXT_PIPELINE)}）；"
                                 f"新类型 = pipelines.yaml 加一段配置 + 步骤类型注册")
    # kb 白名单：只收 apps.yaml 声明过的库，避免任意字符串落成孤立 collection
    if settings.known_kbs and kb not in settings.known_kbs:
        raise HTTPException(422, f"未声明的知识库 {kb!r}（apps.yaml knowledge_bases："
                                 f"{sorted(settings.known_kbs)}）")

    doc_id = uuid.uuid4().hex[:12]
    trace_id = trace.new_trace_id()
    src_path = settings.files_dir / doc_id / f"source{suffix}"
    src_path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        size = _save_upload(file.file, src_path, settings.max_upload_mb * 1024 * 1024)
    except HTTPException:
        src_path.unlink(missing_ok=True)
        try:  # 连空目录一起清掉，失败上传不留痕迹
            src_path.parent.rmdir()
        except OSError:
            pass
        raise

    conn = connect(settings.db_path)
    try:
        task_id = taskstore.create_task(
            conn, doc_id, pipeline, trace_id, kb=kb,
            state={"source_path": str(src_path),
                   "source_meta": {"source_file": file.filename or src_path.name,
                                   "size_bytes": size}})
    finally:
        conn.close()

    background.add_task(_run_task, task_id)  # 线程池执行；执行器自带检查点与失败入待办
    return {"doc_id": doc_id, "task_id": task_id, "trace_id": trace_id,
            "pipeline": pipeline, "size_bytes": size, "status": "pending"}


@router.get("/{doc_id}/status")
def status(doc_id: str) -> dict:
    settings = get_settings()
    conn = connect(settings.db_path)
    try:
        row = conn.execute(
            "SELECT * FROM tasks WHERE doc_id=? ORDER BY created_at DESC LIMIT 1", (doc_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"doc 不存在：{doc_id}")
        steps = [dict(r) for r in trace.by_trace(conn, row["trace_id"])]
        return {"task": dict(row), "steps": steps}
    finally:
        conn.close()


@router.post("/tasks/{task_id}/retry")
def retry(task_id: str) -> dict:
    """重跑 = 同一入口 resume：检查点在任务表里，幂等键 doc_id+step。"""
    settings = get_settings()
    conn = connect(settings.db_path)
    try:
        task = taskstore.get_task(conn, task_id)
        if task is None:
            raise HTTPException(404, f"任务不存在：{task_id}")
        status = run_pipeline(conn, get_settings(), task_id, resume=True)
        return {"task_id": task_id, "status": status}
    finally:
        conn.close()


def _run_task(task_id: str) -> None:
    """后台执行体：独立连接（线程安全边界）；任何未捕获异常也归到任务失败。"""
    settings = get_settings()
    conn = connect(settings.db_path)
    try:
        run_pipeline(conn, settings, task_id)
    except Exception as exc:  # 执行器已兜步骤异常；这里是最后一道网
        from ownrag.core import tasks as ts
        ts.update_task(conn, task_id, status="failed", error=f"executor: {exc}")
        ts.add_todo(conn, task_id, None, f"执行器异常：{exc}")
    finally:
        conn.close()
