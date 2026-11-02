"""双通道存储（04 文档 §二）：向量 Chroma + 关键词 SQLite FTS5，按 doc_id 原子替换。

降级语义（骨架期）：chromadb 未安装时向量通道显式跳过并记 metric（vector=skipped），
检索退 BM25 单路——**降级可见，不是静默**。embed_version 记录在 chunks 行上。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ownrag.core.pipeline import StepContext
from ownrag.core.registry import Step, StepResult, register

if TYPE_CHECKING:
    from ownrag.config import Settings

_CHROMA = None  # 惰性单例：collection 缓存 {name: collection}


# ---------------------------------------------------------------- 关键词通道（FTS5）
def _fts_cjk(text: str) -> str:
    """FTS5 unicode61 不切 CJK（整段中文=一个 token，中文查询必零召回）。
    骨架期字符化兜底：CJK 逐字成 token、拉丁数字按词、其余当分隔——索引与查询两侧必须同函数。
    jieba 预分词为 M2 增强（04 文档 §二）。"""
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        elif ch.isalnum() and ch.isascii():
            buf += ch
        else:
            if buf:
                tokens.append(buf)
                buf = ""
    if buf:
        tokens.append(buf)
    return " ".join(tokens)


def keyword_upsert(conn: Any, chunks: list[dict]) -> None:
    for c in chunks:
        conn.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (c["chunk_id"],))
        conn.execute("INSERT INTO chunks_fts(text, chunk_id, doc_id, kb) VALUES (?,?,?,?)",
                     (_fts_cjk(c["text"]), c["chunk_id"], c["doc_id"], c["kb"]))


def keyword_delete_doc(conn: Any, doc_id: str) -> None:
    conn.execute("DELETE FROM chunks_fts WHERE doc_id=?", (doc_id,))


def keyword_search(conn: Any, kb: str, query: str, top_k: int) -> list[dict]:
    """MATCH 语法与召回兜底阶梯：原文短语 → 字符化短语 → 字符化 OR（CJK 主路径）。
    OR 命中按 bm25 排名，重叠字符越多越靠前——骨架期够用，语义分词属 M2。"""
    cjk = _fts_cjk(query)
    ladder = [f'"{query}"']
    if cjk and cjk != query:
        ladder += [f'"{cjk}"', " OR ".join(cjk.split())]
    rows: list[Any] = []
    for q in ladder:
        try:
            rows = conn.execute(
                "SELECT chunk_id, doc_id, bm25(chunks_fts) AS score FROM chunks_fts "
                "WHERE chunks_fts MATCH ? AND kb=? ORDER BY score LIMIT ?",
                (q, kb, top_k)).fetchall()
            if rows:
                break
        except Exception:
            continue
    return [{"chunk_id": r["chunk_id"], "doc_id": r["doc_id"],
             "score": -float(r["score"]), "channel": "bm25"} for r in rows]


# ---------------------------------------------------------------- 向量通道（Chroma，可选）
def _get_collection(settings: "Settings", kb: str):
    try:
        import chromadb
    except ImportError:
        return None
    global _CHROMA
    if _CHROMA is None:
        _CHROMA = chromadb.PersistentClient(path=str(settings.chroma_dir))
    return _CHROMA.get_or_create_collection(f"kb_{kb}", metadata={"hnsw:space": "cosine"})


def vector_upsert(settings: "Settings", kb: str, chunks: list[dict], embeddings: list[list[float]]) -> bool:
    col = _get_collection(settings, kb)
    if col is None:
        return False
    col.upsert(
        ids=[c["chunk_id"] for c in chunks],
        embeddings=embeddings,
        documents=[c["text"] for c in chunks],
        metadatas=[{"doc_id": c["doc_id"], "ordinal": c["ordinal"],
                    **{k: str(v) for k, v in c["meta"].items() if v is not None}} for c in chunks],
    )
    return True


def vector_delete_doc(settings: "Settings", kb: str, doc_id: str) -> bool:
    col = _get_collection(settings, kb)
    if col is None:
        return False
    col.delete(where={"doc_id": doc_id})
    return True


def vector_search(settings: "Settings", kb: str, query_embedding: list[float], top_k: int) -> list[dict]:
    col = _get_collection(settings, kb)
    if col is None:
        return []
    res = col.query(query_embeddings=[query_embedding], n_results=top_k,
                    include=["distances"])
    ids = (res.get("ids") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    return [{"chunk_id": i, "score": 1.0 - float(d), "channel": "vector"}
            for i, d in zip(ids, dists)]


def read_chunks(conn: Any, chunk_ids: list[str]) -> dict[str, dict]:
    """按 id 批量取块正文与锚点（检索结果回填用）。"""
    out: dict[str, dict] = {}
    for cid in chunk_ids:
        row = conn.execute("SELECT * FROM chunks WHERE chunk_id=?", (cid,)).fetchone()
        if row:
            out[cid] = {"chunk_id": row["chunk_id"], "doc_id": row["doc_id"], "kb": row["kb"],
                        "ordinal": row["ordinal"], "text": row["text"],
                        "anchors": json.loads(row["anchors_json"] or "{}"),
                        "meta": json.loads(row["meta_json"] or "{}")}
    return out


# ---------------------------------------------------------------- 步骤：index_upsert
@register("index_upsert")
class IndexUpsert(Step):
    """双通道写入；replace_by_doc=true 时先删后插（重跑/增量同一条路，天然幂等）。"""

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        chunks: list[dict] = ctx.data.get("chunks") or []
        if not chunks:
            return StepResult.fail("无待索引块")
        replace = bool(params.get("replace_by_doc", True))

        if replace:
            keyword_delete_doc(ctx.conn, ctx.doc_id)
            vector_delete_doc(ctx.settings, ctx.kb, ctx.doc_id)
            ctx.conn.execute("DELETE FROM chunks WHERE doc_id=?", (ctx.doc_id,))

        embed_version = ctx.settings.embed_version
        for c in chunks:
            ctx.conn.execute(
                "INSERT OR REPLACE INTO chunks(chunk_id, doc_id, kb, source_type, ordinal, text, "
                "anchors_json, meta_json, embed_version) VALUES (?,?,?,?,?,?,?,?,?)",
                (c["chunk_id"], c["doc_id"], c["kb"], c["source_type"], c["ordinal"],
                 c["text"], json.dumps(c["anchors"], ensure_ascii=False),
                 json.dumps(c["meta"], ensure_ascii=False), embed_version))
        keyword_upsert(ctx.conn, chunks)

        vectors_ok = False
        embeddings: list[list[float]] = ctx.data.get("embeddings") or []
        if embeddings:
            if len(embeddings) != len(chunks):
                return StepResult.fail(f"向量数与块数不符：{len(embeddings)} vs {len(chunks)}")
            vectors_ok = vector_upsert(ctx.settings, ctx.kb, chunks, embeddings)

        ctx.conn.commit()
        metrics = {"chunks": len(chunks), "vector": "ok" if vectors_ok else "skipped"}
        if params.get("require_vector") and not vectors_ok:
            return StepResult.fail("向量通道不可用（chromadb 未安装）且 require_vector=true", **metrics)
        return StepResult.ok(**metrics)


# ---------------------------------------------------------------- 步骤：embed
@register("embed")
class Embed(Step):
    """embedding 批量。Ollama 不可用时：allow_skip=true → 显式降级（embedded=0，BM25 单路，
    降级写入 trace 与 metric，检索侧会播报）；false → 任务失败进待办（默认严格）。"""

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        from ownrag.index.embedder import EmbedError, embed_texts

        chunks: list[dict] = ctx.data.get("chunks") or []
        if not chunks:
            return StepResult.fail("无待向量化块（上游 chunk 步骤缺失？）")
        try:
            embeddings = embed_texts(ctx.settings, [c["text"] for c in chunks],
                                     batch=int(params.get("batch", 32)),
                                     model=params.get("model"))
        except EmbedError as exc:
            if params.get("allow_skip"):
                return StepResult.ok(embedded=0, vector="skipped（关键词单路）", note=str(exc)[:200])
            return StepResult.fail(str(exc))
        ctx.data["embeddings"] = embeddings
        return StepResult.ok(embedded=len(embeddings), model=ctx.settings.embed_model)
