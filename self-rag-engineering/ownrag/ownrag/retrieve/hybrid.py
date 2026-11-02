"""混合检索（04 文档 §三）：先过滤后召回 → 向量+BM25 双路 → RRF 名次融合。

RRF 等权起步——没有评测集之前调权重都是猜（评测先行原则）。
候选池宁窄勿宽：宽了就是给模型编造的机会。
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from ownrag.index.store import keyword_search, read_chunks, vector_search

if TYPE_CHECKING:
    from ownrag.config import Settings


def rrf_fuse(*result_lists: list[dict], k: int = 60, top_n: int = 10) -> list[dict]:
    """名次融合：score = Σ 1/(k + rank)。不比分数免量纲问题；附各路命中详情。"""
    fused: dict[str, dict] = {}
    for results in result_lists:
        for rank, r in enumerate(results):
            cid = r["chunk_id"]
            entry = fused.setdefault(cid, {"chunk_id": cid, "doc_id": r.get("doc_id"),
                                           "rrf": 0.0, "channels": []})
            entry["rrf"] += 1.0 / (k + rank + 1)
            entry["channels"].append({"channel": r.get("channel"), "score": r.get("score")})
    ordered = sorted(fused.values(), key=lambda x: -x["rrf"])[:top_n]
    return ordered


def search(conn: sqlite3.Connection, settings: "Settings", kb: str, query: str,
           vector_topk: int = 20, bm25_topk: int = 20, top_n: int = 10,
           metadata_filter: dict | None = None) -> dict:
    """一次混合检索。metadata_filter 保留参数位（M2 接密级/时间过滤——权限在中台执行，
    此处只做 kb 内检索；过滤责任不进 Prompt）。"""
    from ownrag.index.embedder import EmbedError, embed_query

    bm25_hits = keyword_search(conn, kb, query, bm25_topk)

    vec_hits: list[dict] = []
    vector_skipped_reason = None
    try:
        q_emb = embed_query(settings, query)
        vec_hits = vector_search(settings, kb, q_emb, vector_topk)
        if not vec_hits:
            vector_skipped_reason = "向量通道未启用（chromadb 未安装），BM25 单路"
    except EmbedError as exc:
        vector_skipped_reason = f"向量召回跳过：{exc}"

    fused = rrf_fuse(vec_hits, bm25_hits, top_n=top_n)
    chunks = read_chunks(conn, [f["chunk_id"] for f in fused])
    candidates = [{**f, **chunks.get(f["chunk_id"], {})} for f in fused
                  if f["chunk_id"] in chunks]
    return {"candidates": candidates, "vector_skipped_reason": vector_skipped_reason,
            # 两路原始命中（调试页要看"是哪一路把它捞上来的"，融合后的分数看不出通道贡献）
            "channels": {"bm25": bm25_hits, "vector": vec_hits},
            "retrieval_path": {"kb": kb, "vector_topk": vector_topk, "bm25_topk": bm25_topk,
                               "bm25_hits": len(bm25_hits), "vector_hits": len(vec_hits)}}
