"""embedding 熔断：Ollama 挂掉时第二次请求必须秒失败（否则一次问答要撞两次墙）。"""
from __future__ import annotations

import time
import types

import httpx
import pytest

from ownrag.index import embedder

SETTINGS = types.SimpleNamespace(ollama_base_url="http://127.0.0.1:9", embed_model="bge-m3")


@pytest.fixture(autouse=True)
def _clean_breaker():
    embedder.reset_breaker()
    yield
    embedder.reset_breaker()


class _DownClient:
    """模拟连接级失败（Ollama 没起）。"""

    calls = 0

    def __init__(self, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, *a, **kw):
        _DownClient.calls += 1
        raise httpx.ConnectError("connection refused")


class _OkClient:
    def __init__(self, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, **kw):
        class R:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"embeddings": [[0.1, 0.2] for _ in json["input"]]}

        return R()


def test_breaker_short_circuits(monkeypatch):
    _DownClient.calls = 0
    monkeypatch.setattr(httpx, "Client", _DownClient)

    with pytest.raises(embedder.EmbedError):
        embedder.embed_texts(SETTINGS, ["第一段"])
    assert embedder.breaker_open()
    assert _DownClient.calls == 1

    t0 = time.perf_counter()
    with pytest.raises(embedder.EmbedError) as exc:
        embedder.embed_texts(SETTINGS, ["第二段"])
    assert time.perf_counter() - t0 < 0.05      # 立刻失败，不再等连接超时
    assert "熔断" in str(exc.value)
    assert _DownClient.calls == 1               # 没有再撞一次后端


def test_success_keeps_breaker_closed(monkeypatch):
    monkeypatch.setattr(httpx, "Client", _OkClient)
    out = embedder.embed_texts(SETTINGS, ["a", "b", "c"], batch=2)
    assert len(out) == 3 and not embedder.breaker_open()
