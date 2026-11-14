"""SiliconFlow rerank 适配（/v1/rerank，index 回映）：httpx.post 打桩，零出网。

覆盖：index 回映重排 / 位置对齐回退 / 条数不符降级 / 服务失败降级可见 / 缺 key 不发请求 /
legacy service 协议兼容（provider 未声明时 base_url 有值即 service）。
"""
import types

import httpx

import ownrag.retrieve.rerank as rr


def _sf_settings(**kw):
    base = dict(rerank_provider="siliconflow", rerank_base_url="http://api.test/v1",
                rerank_api_key="sk-tok", rerank_model="BAAI/bge-reranker-v2-m3")
    base.update(kw)
    return types.SimpleNamespace(**base)


def _cands(*texts):
    return [{"ordinal": i + 1, "chunk_id": f"c{i}", "text": t} for i, t in enumerate(texts)]


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        assert self.status_code < 400, f"测试桩未预期 HTTP {self.status_code}"

    def json(self):
        return self._payload


def test_siliconflow_reorders_by_index(monkeypatch):
    """results[].index 回映到原候选（乱序返回也要对上），按 relevance_score 降序。"""
    captured = {}

    def fake_post(url, json=None, headers=None, **kw):
        captured.update(url=url, json=json, headers=headers)
        return _Resp({"results": [
            {"index": 2, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.5},
            {"index": 3, "relevance_score": 0.8},
            {"index": 1, "relevance_score": 0.1},
        ]})

    monkeypatch.setattr(rr.httpx, "post", fake_post)
    cands = _cands("甲", "乙", "丙", "丁")
    out, note = rr.rerank(_sf_settings(), "q", cands, top_n=4)
    assert note == "rerank ok"
    assert [c["text"] for c in out] == ["丙", "丁", "甲", "乙"]
    assert out[0]["rerank_score"] == 0.9
    assert captured["url"] == "http://api.test/v1/rerank"
    assert captured["headers"]["Authorization"] == "Bearer sk-tok"
    assert captured["json"]["model"] == "BAAI/bge-reranker-v2-m3"
    assert captured["json"]["documents"] == ["甲", "乙", "丙", "丁"]   # 平铺文本，非 pairs
    assert captured["json"]["return_documents"] is False


def test_siliconflow_positional_fallback(monkeypatch):
    """缺 index 的非规范响应退回位置对齐，不炸问答。"""
    monkeypatch.setattr(rr.httpx, "post", lambda url, **kw: _Resp(
        {"results": [{"relevance_score": 0.2}, {"relevance_score": 0.9}]}))
    out, note = rr.rerank(_sf_settings(), "q", _cands("甲", "乙"), top_n=2)
    assert [c["text"] for c in out] == ["乙", "甲"] and note == "rerank ok"


def test_siliconflow_count_mismatch_degrades(monkeypatch):
    """条数不符：降级原序返回，错误可见。"""
    monkeypatch.setattr(rr.httpx, "post", lambda url, **kw: _Resp(
        {"results": [{"index": 0, "relevance_score": 0.9}]}))
    out, note = rr.rerank(_sf_settings(), "q", _cands("甲", "乙"), top_n=2)
    assert [c["text"] for c in out] == ["甲", "乙"] and "条数不符" in note


def test_siliconflow_failure_degrades_visibly(monkeypatch):
    """服务挂了不拖垮问答：原序兜底 + 降级说明。"""
    def fake_post(*a, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(rr.httpx, "post", fake_post)
    out, note = rr.rerank(_sf_settings(), "q", _cands("甲", "乙"), top_n=2)
    assert [c["text"] for c in out] == ["甲", "乙"] and "降级" in note


def test_siliconflow_missing_key_fails_before_request(monkeypatch):
    """缺 key：未启用说明，不发请求（RRF 顺序兜底）。"""
    captured = []

    def fake_post(*a, **kw):
        captured.append(1)
        return _Resp({"results": []})

    monkeypatch.setattr(rr.httpx, "post", fake_post)
    out, note = rr.rerank(_sf_settings(rerank_api_key=None), "q", _cands("甲", "乙"), top_n=2)
    assert [c["text"] for c in out] == ["甲", "乙"] and "未启用" in note
    assert captured == []


def test_legacy_service_protocol_when_provider_unset(monkeypatch):
    """兼容旧语义：provider 未声明 + base_url 有值 → 自建 service 协议（pairs + 无鉴权头）。"""
    captured = {}

    def fake_post(url, json=None, headers=None, **kw):
        captured.update(url=url, json=json, headers=headers)
        return _Resp({"scores": [{"score": 0.3}, {"score": 0.8}]})

    monkeypatch.setattr(rr.httpx, "post", fake_post)
    legacy = types.SimpleNamespace(rerank_base_url="http://rerank.local")
    out, note = rr.rerank(legacy, "q", _cands("甲", "乙"), top_n=2)
    assert note == "rerank ok"
    assert [c["text"] for c in out] == ["乙", "甲"]
    assert captured["url"] == "http://rerank.local/rerank"
    assert captured["json"]["documents"] == [["q", "甲"], ["q", "乙"]]  # pairs 协议


# ---------------------------------------------------------------- Ollama 本地分派（/api/embed 标量分数）
def test_ollama_rerank_scalar_scores(monkeypatch):
    """reranker GGUF 经 /api/embed 输出 1 维标量：按输入顺序对齐并降序重排。"""
    captured = {}

    def fake_post(url, json=None, headers=None, **kw):
        captured.update(url=url, json=json)
        return _Resp({"embeddings": [[0.1], [0.95], [0.3]]})

    monkeypatch.setattr(rr.httpx, "post", fake_post)
    settings = types.SimpleNamespace(rerank_provider="ollama",
                                     ollama_base_url="http://127.0.0.1:11434",
                                     rerank_model="qllama/bge-reranker-v2-m3")
    out, note = rr.rerank(settings, "q", _cands("甲", "乙", "丙"), top_n=3)
    assert note == "rerank ok" and [c["text"] for c in out] == ["乙", "丙", "甲"]
    # bge pair 拼接约定：query</s></s>doc
    assert captured["json"]["input"][0] == "q</s></s>甲"
    assert captured["url"] == "http://127.0.0.1:11434/api/embed"


def test_ollama_rerank_multi_dim_degrades_with_hint(monkeypatch):
    """非 1 维输出 = GGUF 未按 rank pooling 封装：显式报错降级，不猜分数。"""
    monkeypatch.setattr(rr.httpx, "post", lambda url, **kw: _Resp(
        {"embeddings": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]}))
    settings = types.SimpleNamespace(rerank_provider="ollama",
                                     ollama_base_url="http://127.0.0.1:11434",
                                     rerank_model="bad/gguf")
    out, note = rr.rerank(settings, "q", _cands("甲", "乙", "丙"), top_n=3)
    assert [c["text"] for c in out] == ["甲", "乙", "丙"] and "rank pooling" in note


def test_ollama_rerank_failure_degrades(monkeypatch):
    """Ollama 没起：降级原序 + 说明可见。"""
    monkeypatch.setattr(rr.httpx, "post",
                        lambda url, **kw: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    settings = types.SimpleNamespace(rerank_provider="ollama",
                                     ollama_base_url="http://127.0.0.1:11434",
                                     rerank_model=None)
    out, note = rr.rerank(settings, "q", _cands("甲", "乙"), top_n=2)
    assert [c["text"] for c in out] == ["甲", "乙"] and "降级" in note
    # rerank_model 未设时用默认 GGUF 名
    assert rr._OLLAMA_RERANK_MODEL_DEFAULT == "qllama/bge-reranker-v2-m3"
