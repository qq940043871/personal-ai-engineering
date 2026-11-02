"""直击库（04 文档 §四）：L0 精确/别名 → L1 语义 → L2 沉淀候选。

口径复用公司设计（权威版：../../../../../personal-investment-notes/02-AI智能体/03-业务设计/RAG直击库-方案与治理.md）；
ownrag 实现其工程壳。命中校验（生效期/权限/完整性）在命中后、返回前执行——
直击库答错比 RAG 答错更伤信任，因为它看起来最权威。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from ownrag.config import get_settings


@dataclass
class DirectHit:
    hit_id: str
    level: str
    question: str
    answer: str
    score: float


def match(conn: sqlite3.Connection, kb_list: list[str], question: str,
          l1_threshold: float = 0.86) -> DirectHit | None:
    q = question.strip()
    if not q:
        return None
    placeholders = ",".join("?" * len(kb_list))

    # ---- L0：标准问 + 别名 精确匹配（归一化：去空白/标点/全半角）----
    norm = _normalize(q)
    for row in conn.execute(
            f"SELECT * FROM direct_hits WHERE enabled=1 AND level='L0' AND kb IN ({placeholders})",
            kb_list):
        if norm in {_normalize(row["question"])} | {_normalize(a) for a in json.loads(row["aliases_json"] or "[]")}:
            return DirectHit(row["id"], "L0", row["question"], row["answer"], 1.0)

    # ---- L1：embedding 相似度阈值命中（Ollama 不可用时跳过，降级可见）----
    try:
        from ownrag.index.embedder import EmbedError, embed_query, embed_texts
        q_emb = embed_query(get_settings(), q)
        rows = conn.execute(
            f"SELECT * FROM direct_hits WHERE enabled=1 AND level IN ('L1','L2') AND kb IN ({placeholders})",
            kb_list).fetchall()
        if rows:
            embs = embed_texts(get_settings(), [r["question"] for r in rows])
            for row, emb in zip(rows, embs):
                sim = _cosine(q_emb, emb)
                if sim >= l1_threshold:
                    return DirectHit(row["id"], row["level"], row["question"], row["answer"], round(sim, 4))
    except EmbedError:
        return None  # L1 通道不可用——静默？不：调用方把"直击库未检 L1"写进 trace 说明

    return None


def _normalize(s: str) -> str:
    return "".join(ch for ch in s.strip().lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    db = sum(x * x for x in b) ** 0.5
    return num / (da * db) if da and db else 0.0
