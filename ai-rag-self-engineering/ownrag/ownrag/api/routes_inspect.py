"""调试/巡检路由（教学与排障用）：把"检索内部发生了什么"直接暴露成 JSON。

与问答链路共用同一批函数（hybrid / rerank / budget / gates），保证调试页看到的就是线上跑的：
  配置视图   GET  /admin/config
  分块浏览   GET  /admin/chunks
  直击库     GET/POST/DELETE /admin/direct_hits
  纯检索调试 POST /admin/retrieve      （不调生成模型，只看召回/融合/重排/预算）
  任务详情   GET  /admin/tasks/{task_id}
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ownrag.config import get_settings, load_yaml
from ownrag.core import tasks as taskstore
from ownrag.core import trace
from ownrag.core.db import connect
from ownrag.generate import budget as budget_mod
from ownrag.generate import gates
from ownrag.index.store import keyword_search, read_chunks
from ownrag.retrieve import direct_hit, hybrid, rerank as rerank_mod

router = APIRouter(prefix="/admin", tags=["inspect"])

VIEW_CHARS = 600      # 列表页正文截断长度（原文仍在库里，按 chunk_id 可查）


def _conn() -> sqlite3.Connection:
    return connect(get_settings().db_path)


# ---------------------------------------------------------------- 配置视图
@router.get("/config")
def get_config() -> dict:
    s = get_settings()
    return {"config_dir": str(s.config_dir), "data_dir": str(s.data_dir),
            "known_kbs": sorted(s.known_kbs),
            "pipelines": s.pipelines, "apps": s.apps,
            "models": load_yaml(s.config_dir / "models.yaml"),
            "prompts": sorted(p.stem for p in s.prompts_dir.glob("*.yaml")),
            "limits": {"num_ctx": s.num_ctx, "max_new_tokens": s.max_new_tokens,
                       "max_upload_mb": s.max_upload_mb}}


# ---------------------------------------------------------------- 分块浏览
def _chunk_row(row: sqlite3.Row) -> dict:
    text = row["text"] or ""
    return {"chunk_id": row["chunk_id"], "doc_id": row["doc_id"], "kb": row["kb"],
            "ordinal": row["ordinal"], "source_type": row["source_type"],
            "anchors": json.loads(row["anchors_json"] or "{}"),
            "meta": json.loads(row["meta_json"] or "{}"),
            "embed_version": row["embed_version"], "created_at": row["created_at"],
            "chars": len(text), "text": text[:VIEW_CHARS],
            "truncated_view": len(text) > VIEW_CHARS}


@router.get("/chunks")
def list_chunks(kb: str = "", q: str = "", doc_id: str = "", limit: int = 20) -> dict:
    """q 非空走 FTS5（与线上关键词通道同一函数），否则按库/文档倒序列出。"""
    limit = max(1, min(int(limit), 100))
    conn = _conn()
    try:
        if q.strip():
            kb_for_search = kb or next(iter(sorted(get_settings().known_kbs)), "default")
            t0 = time.perf_counter()
            hits = keyword_search(conn, kb_for_search, q.strip(), limit)
            ms = round((time.perf_counter() - t0) * 1000, 1)
            mapped = read_chunks(conn, [h["chunk_id"] for h in hits])
            chunks = []
            for h in hits:
                c = mapped.get(h["chunk_id"])
                if not c:
                    continue
                text = c["text"]
                chunks.append({**c, "chars": len(text), "text": text[:VIEW_CHARS],
                               "truncated_view": len(text) > VIEW_CHARS,
                               "bm25_score": h["score"]})
            return {"mode": "fts", "kb": kb_for_search, "q": q.strip(),
                    "ms": ms, "total": len(chunks), "chunks": chunks}

        where, args = [], []
        if kb:
            where.append("kb=?")
            args.append(kb)
        if doc_id:
            where.append("doc_id=?")
            args.append(doc_id)
        sql_where = f"WHERE {' AND '.join(where)}" if where else ""
        total = conn.execute(f"SELECT COUNT(*) n FROM chunks {sql_where}", args).fetchone()["n"]
        rows = conn.execute(
            f"SELECT * FROM chunks {sql_where} ORDER BY created_at DESC, ordinal LIMIT ?",
            (*args, limit)).fetchall()
        return {"mode": "list", "kb": kb, "total": total,
                "chunks": [_chunk_row(r) for r in rows]}
    finally:
        conn.close()


# ---------------------------------------------------------------- 直击库（只读之外补上维护面）
class DirectHitIn(BaseModel):
    kb: str
    question: str
    answer: str
    level: str = "L0"
    aliases: list[str] = []


@router.get("/direct_hits")
def list_direct_hits(kb: str = "") -> dict:
    conn = _conn()
    try:
        sql = "SELECT * FROM direct_hits"
        args: tuple = ()
        if kb:
            sql += " WHERE kb=?"
            args = (kb,)
        rows = conn.execute(sql + " ORDER BY created_at DESC", args).fetchall()
        return {"hits": [{**dict(r), "aliases": json.loads(r["aliases_json"] or "[]")}
                         for r in rows]}
    finally:
        conn.close()


@router.post("/direct_hits")
def create_direct_hit(body: DirectHitIn) -> dict:
    s = get_settings()
    if s.known_kbs and body.kb not in s.known_kbs:
        raise HTTPException(422, f"未声明的知识库 {body.kb!r}（{sorted(s.known_kbs)}）")
    if body.level not in {"L0", "L1", "L2"}:
        raise HTTPException(422, "level 只能是 L0/L1/L2")
    if not body.question.strip() or not body.answer.strip():
        raise HTTPException(422, "question 与 answer 不能为空")
    hit_id = uuid.uuid4().hex[:10]
    conn = _conn()
    try:
        conn.execute("INSERT INTO direct_hits(id,kb,level,question,aliases_json,answer,enabled) "
                     "VALUES (?,?,?,?,?,?,1)",
                     (hit_id, body.kb, body.level, body.question.strip(),
                      json.dumps(body.aliases, ensure_ascii=False), body.answer))
        conn.commit()
        return {"id": hit_id, "status": "created"}
    finally:
        conn.close()


@router.delete("/direct_hits/{hit_id}")
def delete_direct_hit(hit_id: str) -> dict:
    conn = _conn()
    try:
        cur = conn.execute("DELETE FROM direct_hits WHERE id=?", (hit_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, f"直击条目不存在：{hit_id}")
        return {"id": hit_id, "status": "deleted"}
    finally:
        conn.close()


# ---------------------------------------------------------------- 纯检索调试
class RetrieveReq(BaseModel):
    question: str
    app: str = "policy_qa"
    kb: str | None = None
    vector_topk: int | None = None
    bm25_topk: int | None = None
    top_n: int | None = None
    rerank_top_n: int | None = None


@router.post("/retrieve")
def debug_retrieve(req: RetrieveReq) -> dict:
    """只跑检索侧：直击库 → 双通道 → RRF → rerank → 预算 → 闸门一。不调用生成模型。"""
    if not req.question.strip():
        raise HTTPException(422, "问题为空")
    s = get_settings()
    app_cfg = s.apps.get(req.app)
    if app_cfg is None:
        raise HTTPException(404, f"应用未定义：{req.app}")
    kbs: list[str] = app_cfg.get("knowledge_bases") or ["default"]
    kb = req.kb or kbs[0]
    ret_cfg = app_cfg.get("retrieval") or {}
    gen_cfg = app_cfg.get("generation") or {}

    conn = _conn()
    try:
        t0 = time.perf_counter()
        hit = direct_hit.match(conn, kbs, req.question)
        direct = ({"hit": True, "level": hit.level, "question": hit.question,
                   "score": hit.score} if hit else {"hit": False})

        result = hybrid.search(
            conn, s, kb, req.question,
            vector_topk=int(req.vector_topk or ret_cfg.get("vector_topk", 20)),
            bm25_topk=int(req.bm25_topk or ret_cfg.get("bm25_topk", 20)),
            top_n=int(req.top_n or ret_cfg.get("top_n", 12)))
        cands, rerank_note = rerank_mod.rerank(
            s, req.question, result["candidates"],
            top_n=int(req.rerank_top_n or max(4, (req.top_n or ret_cfg.get("top_n", 12)) // 2)))
        num_ctx, max_new = budget_mod.resolve_limits(s, gen_cfg)
        plan = budget_mod.plan_context(cands, question=req.question,
                                       prompt_name=gen_cfg.get("prompt", "policy_strict_v1"),
                                       num_ctx=num_ctx, max_new_tokens=max_new)
        pre = gates.sufficiency_check(cands)
        ms = round((time.perf_counter() - t0) * 1000, 1)
    finally:
        conn.close()

    def brief(c: dict) -> dict:
        return {"chunk_id": c.get("chunk_id"), "doc_id": c.get("doc_id"),
                "ordinal": c.get("ordinal"), "rrf": round(float(c.get("rrf") or 0), 6),
                "rerank_score": c.get("rerank_score"),
                "channels": c.get("channels") or [],
                "anchors": c.get("anchors"),
                "chars": len(c.get("text") or ""),
                "preview": (c.get("text") or "")[:200]}

    return {"question": req.question, "app": req.app, "kb": kb, "ms": ms,
            "direct_hit": direct,
            "vector_skipped_reason": result["vector_skipped_reason"],
            "retrieval_path": result["retrieval_path"],
            "channels": {"bm25": result["channels"]["bm25"],
                         "vector": result["channels"]["vector"]},
            "candidates": [brief(c) for c in cands],
            "budget": {"num_ctx": plan.num_ctx, "reserved_output": plan.max_new_tokens,
                       "prompt_overhead": plan.prompt_overhead, "available": plan.available,
                       "kept": len(plan.fitted.blocks), "dropped": len(plan.fitted.dropped),
                       "dropped_ids": plan.fitted.dropped,
                       "truncated": plan.fitted.truncated, "ctx_tokens": plan.fitted.tokens,
                       "blocks": [brief(c) for c in plan.fitted.blocks]},
            "rerank": {"note": rerank_note},
            "gate_pre": {"name": pre.name, "passed": pre.passed, "reason": pre.reason}}


# ---------------------------------------------------------------- 任务详情
@router.get("/tasks/{task_id}")
def task_detail(task_id: str) -> dict:
    conn = _conn()
    try:
        row = taskstore.get_task(conn, task_id)
        if row is None:
            raise HTTPException(404, f"任务不存在：{task_id}")
        steps = [dict(r) for r in trace.by_trace(conn, row["trace_id"])]
        for st in steps:
            st["counters"] = json.loads(st.pop("counters_json") or "{}")
        return {"task": dict(row), "steps": steps}
    finally:
        conn.close()
