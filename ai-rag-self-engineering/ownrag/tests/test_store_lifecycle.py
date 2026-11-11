"""存储生命周期：幂等重灌（旧块必须退出检索）/ 删除退出可检索 / 版本链留痕。

对应视频 RAG 两问（吴师兄《视频 RAG 怎么做》）：
- 视频重新处理时，旧字幕不得继续被搜到（幂等替换，不是追加）；
- 删除后，字幕/向量/映射全部退出可检索状态——不是只在页面上藏按钮。
全程 BM25 通道（chromadb 缺失时向量降级可见），不依赖外部服务。
"""
from __future__ import annotations

import pytest

import ownrag.steps  # noqa: F401  注册内置步骤
from ownrag.config import get_settings, reset_settings_cache
from ownrag.core.db import connect, init_schema
from ownrag.core.pipeline import StepContext
from ownrag.index.chunker import ChunkMarkdown
from ownrag.index.store import IndexUpsert, keyword_search, read_chunks

MD_V1 = ("# 年假规定（v1）\n\n年假额度每年 5 天，需提前 3 天申请。\n\n"
         "年假未休完不跨年结转，离职时按比例折算。")
# 注意措辞：v2 全文不得含"年/假/额/度"任一单字——BM25 兜底阶梯按单字 OR 召回，
# 一个"度"字（如"制度"）都会让旧内容"看起来还能搜到"
MD_V2 = "# 报销流程（v2）\n\n报销需在费用发生后 30 天内提交发票原件。\n\n超过 2000 元需邮件批准。"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OWNRAG_DATA_DIR", str(tmp_path / "data"))
    reset_settings_cache()
    settings = get_settings()
    init_schema(settings.db_path)
    conn = connect(settings.db_path)
    yield conn, settings
    conn.close()
    reset_settings_cache()


def _upsert(conn, settings, doc_id: str, md: str, source_type="pdf") -> dict:
    """真实步骤链：ChunkMarkdown（含版本链留痕）→ IndexUpsert（先删后插）。"""
    ctx = StepContext(doc_id=doc_id, trace_id="t", kb="policy_v1", conn=conn, settings=settings)
    ctx.data["_pipeline"] = "pdf_v1"
    ctx.data["parsed"] = {"markdown": md, "source_type": source_type,
                          "metadata": {"source_file": f"{doc_id}.md"}}
    r1 = ChunkMarkdown().run(ctx, {"max_tokens": 200, "overlap": 0})
    assert r1.status == "ok", r1.error
    r2 = IndexUpsert().run(ctx, {"replace_by_doc": True})
    assert r2.status == "ok", r2.error
    return {"chunks": ctx.data["chunks"], "metrics": r2.metrics}


def _doc_rows(conn, doc_id: str) -> list[dict]:
    return [dict(r) for r in
            conn.execute("SELECT chunk_id, text FROM chunks WHERE doc_id=?", (doc_id,)).fetchall()]


def test_reingest_replaces_old_chunks(env):
    """重灌 v2 后：旧内容从 chunks 表与 FTS 同时退出，检索不再命中——
    用户不能同时搜到新旧两份证据（chunk_id 前缀复用是替换语义的正常现象，
    断言落在内容上而非 id 上）。"""
    conn, settings = env
    _upsert(conn, settings, "doc1", MD_V1)
    assert keyword_search(conn, "policy_v1", "年假额度", top_k=10)   # v1 可检索

    _upsert(conn, settings, "doc1", MD_V2)
    rows = _doc_rows(conn, "doc1")
    assert rows and all("年假" not in r["text"] for r in rows)        # 旧行消失（不是追加）
    fts_ids = {r["chunk_id"] for r in
               conn.execute("SELECT chunk_id FROM chunks_fts WHERE doc_id='doc1'").fetchall()}
    assert fts_ids == {r["chunk_id"] for r in rows}                  # 两通道行集一致
    assert not keyword_search(conn, "policy_v1", "年假额度", top_k=10)   # 旧内容搜不到
    hits = keyword_search(conn, "policy_v1", "报销 发票", top_k=10)
    assert hits and all(h["chunk_id"] in {r["chunk_id"] for r in rows} for h in hits)


def test_delete_doc_exits_searchable_state(env):
    """删除 = chunks/FTS 同步退出可检索；向量通道降级可见（chromadb 缺失时 skipped）。"""
    conn, settings = env
    info = _upsert(conn, settings, "doc1", MD_V1)
    from ownrag.index.store import keyword_delete_doc, vector_delete_doc
    vector_ok = vector_delete_doc(settings, "policy_v1", "doc1")
    keyword_delete_doc(conn, "doc1")
    conn.execute("DELETE FROM chunks WHERE doc_id=?", ("doc1",))
    conn.commit()
    assert not keyword_search(conn, "policy_v1", "年假额度", top_k=10)
    assert not read_chunks(conn, [c["chunk_id"] for c in info["chunks"]])
    assert isinstance(vector_ok, bool)                   # 通道结果显式回传（True/False，不抛异常）


def test_chunk_rows_carry_version_chain(env):
    """块上留痕版本链：embed_version + pipeline + chunker 参数——
    同块新旧口径可比较，引用偏移时能归因到具体一层。"""
    conn, settings = env
    _upsert(conn, settings, "doc1", MD_V1)
    rows = read_chunks(conn, [r["chunk_id"] for r in _doc_rows(conn, "doc1")])
    assert rows, "有块落库"
    for row in rows.values():
        assert row["meta"].get("pipeline") == "pdf_v1"
        assert row["meta"].get("chunker", {}).get("max_tokens") == 200
    versions = {r["embed_version"] for r in conn.execute(
        "SELECT embed_version FROM chunks").fetchall()}
    assert versions == {settings.embed_version}


def test_delete_endpoint_removes_all_channels(env):
    """DELETE /docs/{doc_id}：一次调用清空 chunks/FTS/向量三通道，
    查询不再命中；不存在的 doc 显式 404。"""
    from fastapi import HTTPException

    from ownrag.api.routes_docs import delete_doc
    conn, settings = env
    _upsert(conn, settings, "doc1", MD_V1)
    assert keyword_search(conn, "policy_v1", "年假额度", top_k=10)

    before = len(_doc_rows(conn, "doc1"))
    body = delete_doc("doc1")
    assert body["chunks_removed"] == before >= 1
    assert not keyword_search(conn, "policy_v1", "年假额度", top_k=10)
    assert not _doc_rows(conn, "doc1")

    with pytest.raises(HTTPException) as exc_info:
        delete_doc("doc1")
    assert exc_info.value.status_code == 404
