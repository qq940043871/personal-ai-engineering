"""问答路由（SSE 流式）：直击库 → 混合检索 → rerank → 闸门一 → 预算 → 流式生成 → 闸门二 → 修复。

SSE 事件：hit（直击库命中）/ ctx（候选依据）/ token（流式增量）/ gate（闸门与降级）
        / no_evidence（无依据，合法答案）/ done（引用元数据）/ error。

分层（_stream 只管"发什么事件、按什么顺序"，动作各自成函数便于单测与替换）：
  _search     混合检索（双通道 + RRF）           → 检索结果 + 降级事件
  _rerank     重排（未启用 = RRF 兜底）          → 候选 + trace 计数
  _fit_context 上下文预算裁剪 + prompt 渲染       → Context + 预算事件
  _answer_stream 流式生成（薄封装，异常仍抛 ChatError）
  _repair_answer 闸门二违规后带反馈重答一次
  _log_qa     问答落库（评测集与直击库回流的原料）

事件顺序是产品契约（前端按序消费），重构不得调整：降级事件先于 rerank 发出。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ownrag.config import get_settings
from ownrag.core import trace
from ownrag.core.db import connect
from ownrag.generate import budget as budget_mod
from ownrag.generate import gates
from ownrag.generate.client import ChatError, chat, chat_stream
from ownrag.generate.prompts import render
from ownrag.retrieve import direct_hit, hybrid
from ownrag.retrieve import rerank as rerank_mod

router = APIRouter(tags=["chat"])

Event = tuple[str, dict]  # (SSE 事件名, 载荷)


class ChatReq(BaseModel):
    app: str = "policy_qa"
    question: str
    top_n: int | None = None


@dataclass
class Context:
    """预算裁剪后的上下文装配结果：模型看到什么，由这里决定。"""
    blocks: list[dict]      # 真正进模型的块（闸门二与引用只认这批）
    text: str               # 拼好的上下文正文
    tokens: int             # 估算 token 数
    messages: list[dict]    # 渲染后的对话消息
    num_ctx: int            # 窗口
    max_new: int            # 输出预留
    prompt_name: str


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------- 单步动作
def _log_qa(conn: sqlite3.Connection, app: str, question: str, answer: str,
            hits: list[dict], trace_id: str, feedback: str | None = None) -> None:
    """问答留痕：问题 / 命中块 / 答案 / trace_id —— 评测集与直击库回流的唯一原料。"""
    conn.execute("INSERT INTO qa_log(app, question, hit_chunks_json, answer, feedback, trace_id) "
                 "VALUES (?,?,?,?,?,?)",
                 (app, question,
                  json.dumps([h["chunk_id"] for h in hits], ensure_ascii=False),
                  answer, feedback, trace_id))
    conn.commit()


def _search(conn: sqlite3.Connection, settings, question: str, kb: str,
            ret_cfg: dict) -> tuple[dict, list[Event]]:
    """混合检索（FTS5 + 向量，RRF 融合）。向量通道不可用时返回降级事件，绝不静默。"""
    result = hybrid.search(conn, settings, kb, question,
                           vector_topk=ret_cfg.get("vector_topk", 20),
                           bm25_topk=ret_cfg.get("bm25_topk", 20),
                           top_n=ret_cfg.get("top_n", 12))
    events: list[Event] = []
    if result["vector_skipped_reason"]:
        events.append(("gate", {"stage": "retrieval_degraded",
                                "note": result["vector_skipped_reason"]}))
    return result, events


def _rerank(settings, question: str, result: dict, ret_cfg: dict,
            top_n: int | None) -> tuple[list[dict], dict]:
    """重排（可选）。未启用或服务挂掉时退回 RRF 顺序，降级说明进 trace 计数。"""
    candidates, rerank_note = rerank_mod.rerank(
        settings, question, result["candidates"],
        top_n=top_n or ret_cfg.get("top_n", 12) // 2 * 2 or 8)
    counters = {"candidates": len(candidates), "rerank": rerank_note,
                **result["retrieval_path"]}
    return candidates, counters


def _fit_context(settings, question: str, candidates: list[dict],
                 gen_cfg: dict) -> tuple[Context, list[Event]]:
    """上下文预算：num_ctx 是输入+输出总窗，先给输出留位再装候选（超预算砍尾块）。"""
    num_ctx, max_new = budget_mod.resolve_limits(settings, gen_cfg)
    plan = budget_mod.plan_context(candidates, question=question,
                                   prompt_name=gen_cfg.get("prompt", "policy_strict_v1"),
                                   num_ctx=num_ctx, max_new_tokens=max_new)
    fitted = plan.fitted

    events: list[Event] = []
    if fitted.dropped or fitted.truncated:
        # 降级可见：丢了几块、截了多少、预算怎么算的，全部随事件回传
        events.append(("gate", {"stage": "context_budget", "kept": len(fitted.blocks),
                                "dropped": len(fitted.dropped), "truncated": fitted.truncated,
                                "ctx_tokens": fitted.tokens, "num_ctx": num_ctx,
                                "prompt_overhead": plan.prompt_overhead,
                                "available": plan.available, "reserved_output": max_new}))

    messages = render(plan.prompt_name, question=question, context_blocks=fitted.text)
    return Context(blocks=fitted.blocks, text=fitted.text, tokens=fitted.tokens,
                   messages=messages, num_ctx=num_ctx, max_new=max_new,
                   prompt_name=plan.prompt_name), events


def _answer_stream(settings, ctx: Context, gen_cfg: dict) -> Iterator[str]:
    """流式生成入口（单点接缝：换供应商只改 generate.client，不动本函数）。"""
    return chat_stream(settings, ctx.messages, model=gen_cfg.get("model"),
                       num_ctx=ctx.num_ctx, num_predict=ctx.max_new)


def _repair_answer(settings, ctx: Context, answer: str, post: gates.GateResult,
                   candidates: list[dict], gen_cfg: dict) -> tuple[str, gates.GateResult, list[Event]]:
    """闸门二违规 → 带错误反馈重答一次（Harness ④ 的问答版）。

    只有"通过"或"违规更少"才采纳重答；修复请求本身失败则按规则拒答原答案。
    """
    events: list[Event] = []
    repair = [*ctx.messages,
              {"role": "assistant", "content": answer},
              {"role": "user", "content": "你的上一版回答存在以下问题："
               + "；".join(post.violations)
               + "。请重答：只保留能被候选块支持的结论，每个结论标注 [来源: 块N]。"}]
    try:
        answer2 = chat(settings, repair, model=gen_cfg.get("model"),
                       num_ctx=ctx.num_ctx, num_predict=ctx.max_new)
        post2 = gates.citation_check(answer2, candidates)
        if post2.passed or len(post2.violations) < len(post.violations):
            events.append(("token", {"t": answer2, "repaired": True}))
            return answer2, post2, events
    except ChatError as exc:
        events.append(("gate", {"stage": "repair_failed", "note": str(exc)}))
        return "（引用校验未通过，已按规则拒答原答案。请缩小问题范围重试。）", post, events
    return answer, post, events


def _ctx_event(candidates: list[dict]) -> Event:
    """候选依据事件：前端右栏展示"模型真正看到的块"。"""
    return ("ctx", {"candidates": [
        {"ordinal": c.get("ordinal"), "chunk_id": c["chunk_id"],
         "doc_id": c.get("doc_id"), "doc_name": c.get("doc_name"),
         "anchors": c.get("anchors"),
         "score": c.get("rrf"), "channels": c.get("channels"),
         "preview": (c.get("text") or "")[:160]} for c in candidates]})


# ---------------------------------------------------------------- 路由
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
            _log_qa(conn, req.app, req.question, hit.answer, [], trace_id)
            return

        # ---- 检索 → （降级可见）→ 重排 ----
        result, events = _search(conn, settings, req.question, kbs[0], ret_cfg)
        for name, payload in events:
            yield _sse(name, payload)

        candidates, counters = _rerank(settings, req.question, result, ret_cfg, req.top_n)
        trace.log(conn, trace_id, "retrieve", "ok", counters=counters)

        # ---- 闸门一（生成前）：候选不足不进模型 ----
        pre = gates.sufficiency_check(candidates)
        if not pre.passed:
            yield _sse("no_evidence", {"reason": pre.reason,
                                       "path": result["retrieval_path"], "trace_id": trace_id})
            yield _sse("done", {"citations": [], "source": "gate"})
            _log_qa(conn, req.app, req.question, "（无依据，未生成）", [], trace_id)
            return

        # ---- 上下文预算 + 渲染 ----
        ctx, events = _fit_context(settings, req.question, candidates, gen_cfg)
        for name, payload in events:
            yield _sse(name, payload)
        candidates = ctx.blocks  # 闸门二与引用只认模型真正看到的块
        yield _sse(*_ctx_event(candidates))

        # ---- 流式生成 ----
        answer_parts: list[str] = []
        try:
            for piece in _answer_stream(settings, ctx, gen_cfg):
                answer_parts.append(piece)
                yield _sse("token", {"t": piece})
        except ChatError as exc:
            yield _sse("error", {"message": str(exc), "trace_id": trace_id})
            trace.log(conn, trace_id, "generate", "fail", error=str(exc))
            return
        answer = "".join(answer_parts)

        # ---- 闸门二（生成后）：引用真实性；违规带反馈重答一次 ----
        post = gates.citation_check(answer, candidates)
        yield _sse("gate", {"stage": "post", "passed": post.passed,
                            "reason": post.reason, "violations": post.violations})
        if not post.passed:
            answer, post, events = _repair_answer(settings, ctx, answer, post, candidates, gen_cfg)
            for name, payload in events:
                yield _sse(name, payload)

        yield _sse("done", {"trace_id": trace_id, "answer": answer,
                            "citations": [{"ordinal": c.get("ordinal"),
                                           "doc_id": c.get("doc_id"),
                                           "doc_name": c.get("doc_name"),
                                           "anchors": c.get("anchors")}
                                          for c in candidates if c.get("ordinal")]})
        trace.log(conn, trace_id, "generate", "ok", counters={
            "chars": len(answer), "gate_post": post.passed,
            "ctx_blocks": len(candidates), "ctx_tokens": ctx.tokens,
            "num_ctx": ctx.num_ctx, "reserved_output": ctx.max_new})
        _log_qa(conn, req.app, req.question, answer, candidates, trace_id)
    finally:
        conn.close()
