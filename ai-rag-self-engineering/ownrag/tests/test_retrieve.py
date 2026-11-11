"""检索融合与重排：RRF 名次融合 / 通道贡献 / rerank 三态（未启用兜底、成功重排、失败降级）。

rerank 服务挂了不应拖垮问答——降级必须可见；三态全部离线可测（httpx 打桩）。
"""
from __future__ import annotations

import types

from ownrag.retrieve.hybrid import rrf_fuse
from ownrag.retrieve.rerank import rerank


def _vec(*ids) -> list[dict]:
    return [{"chunk_id": i, "score": 0.9, "channel": "vector", "doc_id": "d"} for i in ids]


def _bm25(*ids) -> list[dict]:
    return [{"chunk_id": i, "score": 5.0, "channel": "bm25", "doc_id": "d"} for i in ids]


def test_rrf_two_channel_hit_ranks_first():
    """双路同时命中的块融合分最高——RRF 只看名次，不比原始分数量纲。"""
    fused = rrf_fuse(_vec("c1", "c2"), _bm25("c2", "c3"), top_n=10)
    assert [f["chunk_id"] for f in fused][:2] == ["c2", "c1"]
    top = fused[0]
    assert len(top["channels"]) == 2                       # 通道贡献可追溯
    assert {c["channel"] for c in top["channels"]} == {"vector", "bm25"}
    assert top["rrf"] > fused[1]["rrf"]


def test_rrf_single_channel_and_topn():
    fused = rrf_fuse(_bm25("a", "b", "c"), top_n=2)
    assert [f["chunk_id"] for f in fused] == ["a", "b"]    # top_n 截断保序
    assert all(len(f["channels"]) == 1 for f in fused)


def _candidates():
    return [{"ordinal": 1, "text": "甲"}, {"ordinal": 2, "text": "乙"}]


def test_rerank_fallback_without_service():
    """未配置 rerank → 原序返回（RRF 顺序兜底），说明随返回值可见。"""
    settings = types.SimpleNamespace(rerank_base_url=None)
    out, note = rerank(settings, "q", _candidates(), top_n=2)
    assert [c["ordinal"] for c in out] == [1, 2]
    assert "兜底" in note


def test_rerank_reorders_by_service_score(monkeypatch):
    """配置了服务：按服务分数重排，rerank_score 写回候选。"""
    import ownrag.retrieve.rerank as mod

    class _FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"score": 0.1}, {"score": 0.9}]}

    captured = {}

    def fake_post(url, json=None, **kw):
        captured["url"], captured["payload"] = url, json
        return _FakeResp()

    monkeypatch.setattr(mod.httpx, "post", fake_post)
    settings = types.SimpleNamespace(rerank_base_url="http://rerank.local")
    out, note = rerank(settings, "q", _candidates(), top_n=2)
    assert captured["payload"]["query"] == "q"
    assert [c["ordinal"] for c in out] == [2, 1]           # 0.9 > 0.1，重排生效
    assert out[0]["rerank_score"] == 0.9
    assert note == "rerank ok"


def test_rerank_degrades_visibly_on_failure(monkeypatch):
    """服务挂了 → 原序兜底 + 降级说明可见，不抛异常、不静默。"""
    import ownrag.retrieve.rerank as mod

    def fake_post(*a, **kw):
        raise ConnectionError("rerank 服务不可达")

    monkeypatch.setattr(mod.httpx, "post", fake_post)
    settings = types.SimpleNamespace(rerank_base_url="http://rerank.local")
    out, note = rerank(settings, "q", _candidates(), top_n=2)
    assert [c["ordinal"] for c in out] == [1, 2]
    assert "降级" in note and "不可达" in note
