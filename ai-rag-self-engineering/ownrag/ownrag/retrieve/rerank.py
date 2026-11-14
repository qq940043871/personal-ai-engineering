"""Rerank 适配（可选组件）：无服务时 RRF 顺序兜底；配置了重排后端则重排候选。

三种 provider 同接口（失败降级可见，不拖垮问答）：
  service      自建 bge-reranker 服务（/rerank，pairs 协议）——旧路径，兼容保留
  siliconflow  SiliconFlow 云 API（/v1/rerank，BAAI/bge-reranker-v2-m3 免费）——平铺 documents + index 回映
  ollama       本地 Ollama：无原生 /api/rerank，走社区模式——reranker GGUF
               （如 qllama/bge-reranker-v2-m3）经 /api/embed 输出 1 维标量相关性分数，
               pair 拼接沿用 bge-reranker 官方约定 `query</s></s>doc`；非 1 维输出=该 GGUF
               未按 rank pooling 封装，显式报错降级
provider 未显式声明时沿用旧语义：rerank_base_url 有值即视为 service（兼容既有配置）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from ownrag.config import Settings

_BGE_PAIR_SEP = "</s></s>"   # bge-reranker tokenizer 对 (query, doc) pairs 的拼接约定
_OLLAMA_RERANK_MODEL_DEFAULT = "qllama/bge-reranker-v2-m3"


def rerank(settings: "Settings", query: str, candidates: list[dict], top_n: int = 8) -> tuple[list[dict], str]:
    """返回 (重排后的候选, 说明)。无服务时原序返回（rrf 顺序兜底）。"""
    provider = getattr(settings, "rerank_provider", None) or (
        "service" if getattr(settings, "rerank_base_url", None) else "")
    if provider == "siliconflow":
        return _rerank_siliconflow(settings, query, candidates, top_n)
    if provider == "ollama":
        return _rerank_ollama(settings, query, candidates, top_n)
    return _rerank_service(settings, query, candidates, top_n)


# ---------------------------------------------------------------- 自建服务（旧协议）
def _rerank_service(settings: "Settings", query: str, candidates: list[dict],
                    top_n: int) -> tuple[list[dict], str]:
    if not settings.rerank_base_url:
        return candidates[:top_n], "rerank 未启用，RRF 顺序兜底"

    pairs = [[query, c.get("text", "")] for c in candidates]
    try:
        resp = httpx.post(f"{settings.rerank_base_url.rstrip('/')}/rerank",
                          json={"query": query, "documents": pairs}, timeout=60,
                          trust_env=False)  # 本地 rerank 服务，不穿代理
        resp.raise_for_status()
        scores = resp.json().get("scores") or resp.json().get("results") or []
    except Exception as exc:
        return candidates[:top_n], f"rerank 服务失败已降级：{exc}"

    for c, s in zip(candidates, scores, strict=False):
        c["rerank_score"] = s.get("score", s.get("relevance_score", 0.0)) if isinstance(s, dict) else float(s)
    ordered = sorted(candidates, key=lambda x: -x.get("rerank_score", 0.0))
    return ordered[:top_n], "rerank ok"


# ---------------------------------------------------------------- SiliconFlow 云 API
def _rerank_siliconflow(settings: "Settings", query: str, candidates: list[dict],
                        top_n: int) -> tuple[list[dict], str]:
    base = (getattr(settings, "rerank_base_url", None) or "").rstrip("/")
    if not base or not getattr(settings, "rerank_api_key", None):
        return candidates[:top_n], "rerank 未启用（OWNRAG_RERANK_URL / OWNRAG_RERANK_API_KEY 未配置）"

    docs = [c.get("text", "") for c in candidates]
    try:
        resp = httpx.post(f"{base}/rerank",
                          json={"model": getattr(settings, "rerank_model", None) or "BAAI/bge-reranker-v2-m3",
                                "query": query, "documents": docs,
                                "top_n": len(docs), "return_documents": False},
                          headers={"Authorization": f"Bearer {settings.rerank_api_key}"},
                          timeout=60, trust_env=False)
        resp.raise_for_status()
        results = resp.json().get("results") or []
    except Exception as exc:
        # rerank 服务挂了不应拖垮问答——降级可见
        return candidates[:top_n], f"rerank 服务失败已降级：{exc}"

    if len(results) != len(docs):
        return candidates[:top_n], f"rerank 返回条数不符（{len(results)}/{len(docs)}），已降级"

    # 规范回映：results[].index 对应输入 documents 下标；缺失/异常时退回位置对齐
    if all(isinstance(r.get("index"), int) and 0 <= r["index"] < len(candidates) for r in results):
        for r in results:
            candidates[r["index"]]["rerank_score"] = float(r.get("relevance_score", 0.0))
    else:
        for c, r in zip(candidates, results, strict=False):
            c["rerank_score"] = float(r.get("relevance_score", 0.0)) if isinstance(r, dict) else float(r)
    ordered = sorted(candidates, key=lambda x: -x.get("rerank_score", 0.0))
    return ordered[:top_n], "rerank ok"


# ---------------------------------------------------------------- Ollama 本地（/api/embed 标量分数）
def _rerank_ollama(settings: "Settings", query: str, candidates: list[dict],
                   top_n: int) -> tuple[list[dict], str]:
    """Ollama 本地重排：/api/embed 对 reranker GGUF 输出 1 维标量分数，按输入顺序对齐。"""
    base = (getattr(settings, "ollama_base_url", None) or "").rstrip("/")
    if not base:
        return candidates[:top_n], "rerank 未启用（OLLAMA_BASE_URL 未配置）"

    docs = [c.get("text", "") for c in candidates]
    model = getattr(settings, "rerank_model", None) or _OLLAMA_RERANK_MODEL_DEFAULT
    try:
        resp = httpx.post(f"{base}/api/embed",
                          json={"model": model, "input": [f"{query}{_BGE_PAIR_SEP}{d}" for d in docs]},
                          timeout=120, trust_env=False)  # 本地服务，不穿代理
        resp.raise_for_status()
        embs = resp.json().get("embeddings") or []
    except Exception as exc:
        # rerank 挂了不拖垮问答——降级可见
        return candidates[:top_n], f"rerank 服务失败已降级：{exc}"

    if len(embs) != len(docs):
        return candidates[:top_n], f"rerank 返回条数不符（{len(embs)}/{len(docs)}），已降级"
    bad = next((len(e) for e in embs if len(e) != 1), None)
    if bad is not None:
        return candidates[:top_n], (
            f"rerank 模型输出 {bad} 维（期望 1 维标量分数）——该 GGUF 未按 rank pooling 封装，"
            f"已降级；换 {model} 这类 rerank 封装或改用 service/siliconflow 分派")
    for c, e in zip(candidates, embs, strict=False):
        c["rerank_score"] = float(e[0])
    ordered = sorted(candidates, key=lambda x: -x.get("rerank_score", 0.0))
    return ordered[:top_n], "rerank ok"
