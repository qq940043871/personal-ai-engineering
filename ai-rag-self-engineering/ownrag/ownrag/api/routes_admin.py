"""管理路由（JSON API，页面壳后置）：任务/待办/trace/问答日志/健康。

最低观测标准（05 文档 §二）：任何一次"答案不对"，10 分钟内答出——
召回给了什么块、模型看到了什么上下文、闸门放过了什么。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from ownrag.config import get_settings
from ownrag.core import tasks as taskstore
from ownrag.core import trace
from ownrag.core.db import connect
from ownrag.core.registry import STEP_REGISTRY, validate_pipeline_steps

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/tasks")
def list_tasks(limit: int = 50) -> dict:
    conn = connect(get_settings().db_path)
    try:
        return {"tasks": [dict(r) for r in taskstore.list_tasks(conn, limit)]}
    finally:
        conn.close()


@router.get("/todos")
def list_todos(only_open: bool = True) -> dict:
    conn = connect(get_settings().db_path)
    try:
        return {"todos": [dict(r) for r in taskstore.list_todos(conn, only_open)]}
    finally:
        conn.close()


@router.post("/todos/{todo_id}/resolve")
def resolve_todo(todo_id: int) -> dict:
    """人工处理完待办后关闭；重跑走 /docs/tasks/{task_id}/retry。"""
    conn = connect(get_settings().db_path)
    try:
        if not taskstore.resolve_todo(conn, todo_id):
            raise HTTPException(404, "待办不存在或已关闭")
        return {"todo_id": todo_id, "status": "done"}
    finally:
        conn.close()


@router.get("/trace/{trace_id}")
def get_trace(trace_id: str) -> dict:
    conn = connect(get_settings().db_path)
    try:
        rows = [dict(r) for r in trace.by_trace(conn, trace_id)]
        for r in rows:
            r["counters"] = json.loads(r.pop("counters_json") or "{}")
        if not rows:
            raise HTTPException(404, f"trace 不存在：{trace_id}")
        return {"trace_id": trace_id, "steps": rows}
    finally:
        conn.close()


@router.get("/qa_log")
def qa_log(limit: int = 50) -> dict:
    conn = connect(get_settings().db_path)
    try:
        rows = conn.execute("SELECT * FROM qa_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return {"qa_log": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/metrics")
def metrics() -> dict:
    """骨架期聚合口径（05 文档：全部指标【待实测】，先立分母再谈数字）。"""
    conn = connect(get_settings().db_path)
    try:
        tasks_total = conn.execute("SELECT status, COUNT(*) n FROM tasks GROUP BY status").fetchall()
        todos_open = conn.execute("SELECT COUNT(*) n FROM todos WHERE status='open'").fetchone()[0]
        chunks = conn.execute("SELECT kb, COUNT(*) n FROM chunks GROUP BY kb").fetchall()
        by_embed = conn.execute(
            "SELECT embed_version, COUNT(*) n FROM chunks GROUP BY embed_version").fetchall()
        return {"tasks_by_status": {r["status"]: r["n"] for r in tasks_total},
                "todos_open": todos_open,
                "chunks_by_kb": {r["kb"]: r["n"] for r in chunks},
                "chunks_by_embed_version": {r["embed_version"]: r["n"] for r in by_embed},
                "note": "解析成功率/命中率等业务指标待评测集基线（M2），此处只给运行计数"}
    finally:
        conn.close()


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    conn = connect(settings.db_path)
    try:
        missing = validate_pipeline_steps(settings.pipelines)
        ollama = {"ok": False, "detail": ""}
        try:
            import httpx
            # trust_env=False：本地模型服务不穿代理；连接超时压到 2s，健康检查不能拖住页面
            resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=2, trust_env=False)
            ollama = {"ok": resp.ok, "detail": "" if resp.ok else f"HTTP {resp.status_code}"}
        except Exception as exc:
            ollama = {"ok": False, "detail": str(exc)[:120]}
        from ownrag.index.embedder import breaker_open, breaker_remaining
        embed_backend = {"breaker_open": breaker_open(), "retry_in": breaker_remaining()}
        return {"steps_registered": sorted(STEP_REGISTRY),
                "pipeline_missing_steps": missing,
                "ollama": ollama,
                "embed_backend": embed_backend,
                "rerank_enabled": bool(settings.rerank_base_url),
                "mineru_mode": settings.mineru_mode,
                "asr_engine": settings.asr_engine,
                # 部署自检：配置/数据目录是否按预期解析（源码树 vs wheel 安装的常见坑）
                "config_dir": str(settings.config_dir),
                "data_dir": str(settings.data_dir),
                "known_kbs": sorted(settings.known_kbs),
                "limits": {"max_upload_mb": settings.max_upload_mb,
                           "num_ctx": settings.num_ctx,
                           "max_new_tokens": settings.max_new_tokens}}
    finally:
        conn.close()
