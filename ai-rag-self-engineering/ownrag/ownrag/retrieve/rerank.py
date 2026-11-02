"""Rerank 适配（可选组件）：Ollama 不支持 rerank——诚实承认并接口化。

未配置时调用方直接走 RRF 顺序兜底；配置了 bge-reranker 独立服务则重排候选。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ownrag.config import Settings


def rerank(settings: "Settings", query: str, candidates: list[dict], top_n: int = 8) -> tuple[list[dict], str]:
    """返回 (重排后的候选, 说明)。无服务时原序返回（rrf 顺序兜底）。"""
    if not settings.rerank_base_url:
        return candidates[:top_n], "rerank 未启用，RRF 顺序兜底"

    import httpx
    pairs = [[query, c.get("text", "")] for c in candidates]
    try:
        resp = httpx.post(f"{settings.rerank_base_url.rstrip('/')}/rerank",
                          json={"query": query, "documents": pairs}, timeout=60,
                          trust_env=False)  # 本地 rerank 服务，不穿代理
        resp.raise_for_status()
        scores = resp.json().get("scores") or resp.json().get("results") or []
    except Exception as exc:
        # rerank 服务挂了不应拖垮问答——降级可见
        return candidates[:top_n], f"rerank 服务失败已降级：{exc}"

    for c, s in zip(candidates, scores):
        c["rerank_score"] = s.get("score", s.get("relevance_score", 0.0)) if isinstance(s, dict) else float(s)
    ordered = sorted(candidates, key=lambda x: -x.get("rerank_score", 0.0))
    return ordered[:top_n], "rerank ok"
