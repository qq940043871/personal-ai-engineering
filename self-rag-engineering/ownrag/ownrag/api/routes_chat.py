"""问答路由（SSE 流式）：意图分流 → 直击库 → 混合检索 → rerank → 闸门 → 流式生成。

SSE 事件：hit（直击库命中）/ ctx（候选依据）/ token（流式增量）/ gate（闸门结果）
        / no_evidence（无依据，合法答案）/ done（引用元数据）/ error。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ownrag.config import get_settings
from ownrag.core import trace
from ownrag.core.db import connect
from ownrag.generate import budget as budget_mod
from ownrag.generate import gates
from ownrag.generate.ollama_client import OllamaError, chat, chat_stream
from ownrag.generate.prompts import render
from ownrag.retrieve import direct_hit, hybrid, rerank as rerank_mod

router = APIRouter(tags=["chat"])


class ChatReq(BaseModel):
    app: str = "policy_qa"
    question: str
    top_n: int | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
def chat_api(req: ChatReq) -> StreamingResponse:
    settings = get_settings()
    app_cfg = settings.apps.get(req.app)
    if app_cfg is None:
        raise HTTPException(404, f"应用未定义：{req.app}（configs/apps.yaml）")
    if not req.question.strip():
        raise HTTPException(422, "问题为空")

    return StreamingResponse(_stream(req, app_cfg), media_type="text/event-stream")


def _stream(req: ChatReq, app_cfg: dict) -> Iterator[str]:
    settings = get_settings()
    conn = connect(settings.db_path)
    trace_id = trace.new_trace_id()
    kbs: list[str] = app_cfg.get("knowledge_bases", ["default"])
    gen_cfg = app_cfg.get("generation", {})
    ret_cfg = app_cfg.get("retrieval", {})

    def log_qa(answer: str, hits: list[dict], feedback: str | None = None) -> None:
        conn.execute("INSERT INTO qa_log(app, question, hit_chunks_json, answer, feedback, trace_id) "
                     "VALUES (?,?,?,?,?,?)",
                     (req.app, req.question, json.dumps([h["chunk_id"] for h in hits],
                                                        ensure_ascii=False),
                      answer, feedback, trace_id))
        conn.commit()

    try:
        # ---- 直击库：高频题不进 RAG（零检索零生成，答案完全可控）----
        dh_on = app_cfg.get("direct_hit", {}).get("enabled", True)
        # 关闭时不查库：L1 会为每条候选 embed 一次，关掉的开关不该还收这笔开销
        hit = direct_hit.match(conn, kbs, req.question) if dh_on else None
        if hit:
            trace.log(conn, trace_id, "direct_hit", "ok", counters={"level": hit.level})
            yield _sse("hit", {"level": hit.level, "question": hit.question,
                               "answer": hit.answer, "score": hit.score, "trace_id": trace_id})
            yield _sse("done", {"citations": [], "source": "direct_hit"})
            log_qa(hit.answer, [])
            return

        # ---- 混合检索（先过滤后召回的过滤位在 M2 接权限字段）----
        result = hybrid.search(conn, settings, kbs[0], req.question,
                               vector_topk=ret_cfg.get("vector_topk", 20),
                               bm25_topk=ret_cfg.get("bm25_topk", 20),
                               top_n=ret_cfg.get("top_n", 12))
        if result["vector_skipped_reason"]:
            yield _sse("gate", {"stage": "retrieval_degraded",
                                "note": result["vector_skipped_reason"]})

        # ---- rerank（可选；未启用 = RRF 兜底，说明随事件可见）----
        candidates, rerank_note = rerank_mod.rerank(
            settings, req.question, result["candidates"],
            top_n=req.top_n or ret_cfg.get("top_n", 12) // 2 * 2 or 8)
        trace.log(conn, trace_id, "retrieve", "ok", counters={
            "candidates": len(candidates), "rerank": rerank_note,
            **result["retrieval_path"]})

        # ---- 闸门一（生成前）：候选不足不进模型 ----
        pre = gates.sufficiency_check(candidates)
        if not pre.passed:
            yield _sse("no_evidence", {"reason": pre.reason,
                                       "path": result["retrieval_path"], "trace_id": trace_id})
            yield _sse("done", {"citations": [], "source": "gate"})
            log_qa("（无依据，未生成）", [])
            return

        # ---- 上下文预算：num_ctx 是输入+输出总窗，先给输出留位再装候选（超预算砍候选）----
        num_ctx, max_new = budget_mod.resolve_limits(settings, gen_cfg)
        plan = budget_mod.plan_context(candidates, question=req.question,
                                       prompt_name=gen_cfg.get("prompt", "policy_strict_v1"),
                                       num_ctx=num_ctx, max_new_tokens=max_new)
        fitted = plan.fitted
        if fitted.dropped or fitted.truncated:
            # 降级可见：丢了几块、截了多少、预算怎么算的，全部随事件回传
            yield _sse("gate", {"stage": "context_budget", "kept": len(fitted.blocks),
                                "dropped": len(fitted.dropped), "truncated": fitted.truncated,
                                "ctx_tokens": fitted.tokens, "num_ctx": num_ctx,
                                "prompt_overhead": plan.prompt_overhead,
                                "available": plan.available, "reserved_output": max_new})
        candidates = fitted.blocks  # 闸门二与引用只认模型真正看到的块

        yield _sse("ctx", {"candidates": [
            {"ordinal": c.get("ordinal"), "chunk_id": c["chunk_id"],
             "doc_id": c.get("doc_id"), "anchors": c.get("anchors"),
             "score": c.get("rrf"), "channels": c.get("channels"),
             "preview": (c.get("text") or "")[:160]} for c in candidates]})

        messages = render(plan.prompt_name, question=req.question, context_blocks=fitted.text)

        answer_parts: list[str] = []
        try:
            for piece in chat_stream(settings, messages, model=gen_cfg.get("model"),
                                     num_ctx=num_ctx, num_predict=max_new):
                answer_parts.append(piece)
                yield _sse("token", {"t": piece})
        except OllamaError as exc:
            yield _sse("error", {"message": str(exc), "trace_id": trace_id})
            trace.log(conn, trace_id, "generate", "fail", error=str(exc))
            return
        answer = "".join(answer_parts)

        # ---- 闸门二（生成后）：引用真实性；违规带错误反馈重答一次（Harness ④）----
        post = gates.citation_check(answer, candidates)
        yield _sse("gate", {"stage": "post", "passed": post.passed,
                            "reason": post.reason, "violations": post.violations})
        if not post.passed:
            repair = [*messages,
                      {"role": "assistant", "content": answer},
                      {"role": "user", "content": "你的上一版回答存在以下问题："
                       + "；".join(post.violations)
                       + "。请重答：只保留能被候选块支持的结论，每个结论标注 [来源: 块N]。"}]
            try:
                answer2 = chat(settings, repair, model=gen_cfg.get("model"),
                               num_ctx=num_ctx, num_predict=max_new)
                post2 = gates.citation_check(answer2, candidates)
                if post2.passed or len(post2.violations) < len(post.violations):
                    answer, post = answer2, post2
                    yield _sse("token", {"t": answer2, "repaired": True})
            except OllamaError as exc:
                yield _sse("gate", {"stage": "repair_failed", "note": str(exc)})
                answer = "（引用校验未通过，已按规则拒答原答案。请缩小问题范围重试。）"

        yield _sse("done", {"trace_id": trace_id, "answer": answer,
                            "citations": [{"ordinal": c.get("ordinal"),
                                           "doc_id": c.get("doc_id"),
                                           "anchors": c.get("anchors")}
                                          for c in candidates if c.get("ordinal")]})
        trace.log(conn, trace_id, "generate", "ok", counters={
            "chars": len(answer), "gate_post": post.passed,
            "ctx_blocks": len(candidates), "ctx_tokens": fitted.tokens,
            "num_ctx": num_ctx, "reserved_output": max_new})
        log_qa(answer, candidates)
    finally:
        conn.close()
