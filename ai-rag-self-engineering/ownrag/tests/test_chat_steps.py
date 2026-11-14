"""问答编排单元：_search / _rerank / _fit_context / _repair_answer / _log_qa / _ctx_event。

拆 `_stream` 的意义就在这里：这些分支原先只能靠端到端 SSE 间接覆盖，
现在可逐段打桩，把"降级可见 / 预算砍块 / 修复采纳 / 修复失败按规则拒答"变成可回归的断言。
全程零出网（检索与生成全部打桩）。
"""
from __future__ import annotations

import pytest

import ownrag.steps  # noqa: F401  注册内置步骤
from ownrag.api import routes_chat as rc
from ownrag.config import get_settings, reset_settings_cache
from ownrag.core.db import connect, init_schema


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


# ---------------------------------------------------------------- 检索：降级必须可见
def test_search_向量通道不可用下发降级事件(env, monkeypatch):
    conn, settings = env
    seen: dict = {}

    def fake_search(c, s, kb, q, **kw):
        seen.update(kw)
        return {"candidates": [], "retrieval_path": {"vector": "skip", "bm25": 0},
                "vector_skipped_reason": "chromadb 未安装，向量通道跳过"}

    monkeypatch.setattr(rc.hybrid, "search", fake_search)
    result, events = rc._search(conn, settings, "问", "policy_v1", {})
    assert events == [("gate", {"stage": "retrieval_degraded",
                                "note": "chromadb 未安装，向量通道跳过"})]
    # apps.yaml 缺省值必须被透传（默认档不能被重构改掉）
    assert seen == {"vector_topk": 20, "bm25_topk": 20, "top_n": 12}
    assert result["retrieval_path"]["vector"] == "skip"


def test_search_正常路径不出降级事件(env, monkeypatch):
    conn, settings = env
    monkeypatch.setattr(rc.hybrid, "search", lambda *a, **kw: {
        "candidates": [{"chunk_id": "c1"}], "retrieval_path": {"vector": 1},
        "vector_skipped_reason": None})
    _, events = rc._search(conn, settings, "问", "policy_v1", {})
    assert events == []


# ---------------------------------------------------------------- 重排：计数口径不变
def test_rerank_计数合并检索路径(env, monkeypatch):
    conn, settings = env
    monkeypatch.setattr(rc.rerank_mod, "rerank", lambda s, q, c, top_n=None:
                        (c[:1], "rerank 未启用，RRF 顺序兜底"))
    result = {"candidates": [{"chunk_id": "a"}, {"chunk_id": "b"}],
              "retrieval_path": {"vector_hits": 2, "bm25_hits": 1}}
    candidates, counters = rc._rerank(settings, "问", result, {}, None)
    assert len(candidates) == 1
    assert counters["candidates"] == 1
    assert counters["bm25_hits"] == 1 and counters["vector_hits"] == 2
    assert "RRF" in counters["rerank"]


# ---------------------------------------------------------------- 预算：超窗砍块可见
def test_fit_context_超预算砍尾块并下发预算事件(env, monkeypatch):
    conn, settings = env
    monkeypatch.setenv("OWNRAG_NUM_CTX", "200")
    monkeypatch.setenv("OWNRAG_MAX_NEW_TOKENS", "64")
    long_text = "年假额度每年 5 天，需提前 3 天申请。" * 40
    candidates = [{"ordinal": i, "chunk_id": f"c{i}", "doc_id": "d",
                   "text": long_text} for i in (1, 2, 3)]

    ctx, events = rc._fit_context(settings, "年假怎么请", candidates, {})
    assert len(ctx.blocks) < len(candidates)          # 砍块，不是静默截断
    assert ctx.num_ctx == 200 and ctx.max_new == 64
    assert events and events[0][0] == "gate"
    payload = events[0][1]
    assert payload["stage"] == "context_budget"
    assert payload["dropped"] >= 1 and payload["num_ctx"] == 200
    # 渲染后模型看到的就是裁剪后的块（块头带引用编号）
    assert "[块1]" in ctx.messages[-1]["content"]


def test_fit_context_预算充足时不发事件(env):
    conn, settings = env
    candidates = [{"ordinal": 1, "chunk_id": "c1", "doc_id": "d", "text": "短块"}]
    ctx, events = rc._fit_context(settings, "问", candidates, {})
    assert events == [] and len(ctx.blocks) == 1


# ---------------------------------------------------------------- 闸门二：修复分支
def _ctx(candidates: list[dict]) -> rc.Context:
    return rc.Context(blocks=candidates, text="", tokens=0,
                      messages=[{"role": "user", "content": "问"}],
                      num_ctx=512, max_new=64, prompt_name="policy_strict_v1")


def test_repair_采纳违规更少的重答(env, monkeypatch):
    conn, settings = env
    candidates = [{"ordinal": 1, "text": "罚款金额为 50 元。"}]
    bad = "罚款 99 元 [来源: 块1]"
    good = "罚款金额为 50 元 [来源: 块1]"
    post = rc.gates.citation_check(bad, candidates)
    assert not post.passed                          # 前置：首答必须真的违规

    monkeypatch.setattr(rc, "chat", lambda *a, **kw: good)
    answer, post2, events = rc._repair_answer(settings, _ctx(candidates), bad, post, candidates, {})
    assert answer == good and post2.passed
    assert events == [("token", {"t": good, "repaired": True})]


def test_repair_失败按规则拒答原答案(env, monkeypatch):
    conn, settings = env
    candidates = [{"ordinal": 1, "text": "罚款金额为 50 元。"}]
    bad = "罚款 99 元 [来源: 块1]"
    post = rc.gates.citation_check(bad, candidates)

    def boom(*a, **kw):
        raise rc.ChatError("模型不可达")

    monkeypatch.setattr(rc, "chat", boom)
    answer, post2, events = rc._repair_answer(settings, _ctx(candidates), bad, post, candidates, {})
    assert "已按规则拒答原答案" in answer
    assert post2 is post                            # 失败不洗白违规结论
    assert events == [("gate", {"stage": "repair_failed", "note": "模型不可达"})]


# ---------------------------------------------------------------- 留痕与事件形状
def test_log_qa_落库可查(env):
    conn, _settings = env
    rc._log_qa(conn, "policy_qa", "年假几天", "5 天", [{"chunk_id": "c1"}, {"chunk_id": "c2"}], "t-1")
    row = conn.execute("SELECT app, question, hit_chunks_json, answer, trace_id "
                       "FROM qa_log").fetchone()
    assert row["app"] == "policy_qa" and row["trace_id"] == "t-1"
    assert row["hit_chunks_json"] == '["c1", "c2"]'


def test_ctx_event_只带前端需要的字段():
    name, payload = rc._ctx_event([{"ordinal": 1, "chunk_id": "c1", "doc_id": "d",
                                    "rrf": 0.5, "channels": [{"channel": "bm25"}],
                                    "text": "x" * 300, "anchors": {"t": [0, 3]}}])
    assert name == "ctx"
    one = payload["candidates"][0]
    assert one["chunk_id"] == "c1" and one["ordinal"] == 1
    assert len(one["preview"]) == 160               # preview 截断，不把全文推给前端
    assert "text" not in one
