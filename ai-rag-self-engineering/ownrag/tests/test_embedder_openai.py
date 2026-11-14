"""openai 兼容嵌入分派（魔搭 API-Inference / DashScope 等同一通道）：httpx.Client 整类打桩，零出网。

覆盖：data[i] 按 index 对齐 / 数量校验 / 鉴权头与 model 参数 / 指令前缀（query 加、文档不加、
空串关闭）/ 传输错误熔断 + 4xx 不熔断 / 缺配置不发请求 / 分派路由 / 旧 stub 兼容。
"""
import types

import httpx
import pytest

import ownrag.index.embedder as emb
from ownrag.index.embedder import DEFAULT_QUERY_INSTRUCT, EmbedError


@pytest.fixture(autouse=True)
def _clean_breaker():
    emb.reset_breaker()
    yield
    emb.reset_breaker()


def _openai_settings(**kw):
    base = dict(embed_provider="openai", embed_base_url="http://api.test/v1",
                embed_api_key="ms-tok", embed_model="Qwen/Qwen3-Embedding-0.6B",
                embed_query_instruct=None, ollama_base_url="http://127.0.0.1:9",
                embed_version="qwen3-emb-0.6b@modelscope-api")
    base.update(kw)
    return types.SimpleNamespace(**base)


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "http://api.test/v1/embeddings"),
                response=httpx.Response(self.status_code, json=self._payload))

    def json(self):
        return self._payload


class _FakeClient:
    """httpx.Client 替身：post 按 scripts 顺序回包，全量捕获请求参数。"""
    calls = []
    scripts = []

    def __init__(self, timeout=None, trust_env=None):
        pass

    def post(self, url, json=None, headers=None):
        type(self).calls.append({"url": url, "json": json, "headers": headers})
        script = type(self).scripts[len(type(self).calls) - 1]
        if isinstance(script, Exception):
            raise script
        return script if isinstance(script, _Resp) else _Resp(script)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install(monkeypatch, scripts):
    _FakeClient.calls, _FakeClient.scripts = [], list(scripts)
    monkeypatch.setattr(httpx, "Client", _FakeClient)


def test_openai_embeddings_index_aligned(monkeypatch):
    """响应乱序（data 顺序与输入不一致）也要按 index 对齐；头与参数正确。"""
    _install(monkeypatch, [{"data": [
        {"index": 1, "embedding": [0.0, 0.0, 1.0]},
        {"index": 0, "embedding": [1.0, 0.0, 0.0]},
    ]}])
    out = emb.embed_texts(_openai_settings(), ["甲", "乙"], model=None)
    assert out == [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
    call = _FakeClient.calls[0]
    assert call["url"] == "http://api.test/v1/embeddings"
    assert call["headers"]["Authorization"] == "Bearer ms-tok"
    assert call["json"]["model"] == "Qwen/Qwen3-Embedding-0.6B"
    assert call["json"]["input"] == ["甲", "乙"]


def test_openai_batches_and_count_mismatch(monkeypatch):
    """分批按 batch 切；返回数量不符直接 EmbedError（不落半截结果）。"""
    _install(monkeypatch, [
        {"data": [{"index": 0, "embedding": [1.0]}]},
        {"data": [{"index": 0, "embedding": [2.0]}]},
        {"data": [{"index": 0, "embedding": [3.0]}]},
    ])
    out = emb.embed_texts(_openai_settings(), ["a", "b", "c"], batch=1)
    assert out == [[1.0], [2.0], [3.0]] and len(_FakeClient.calls) == 3

    _install(monkeypatch, [{"data": [{"index": 0, "embedding": [1.0]}]}])
    with pytest.raises(EmbedError, match="数量不符"):
        emb.embed_texts(_openai_settings(), ["a", "b"])


def test_openai_missing_config_fails_before_request(monkeypatch):
    """缺 base_url / key 在发请求前就炸——配置错误不该伪装成网络故障。"""
    _install(monkeypatch, [])
    with pytest.raises(EmbedError, match="OWNRAG_EMBED"):
        emb.embed_texts(_openai_settings(embed_base_url=None), ["x"])
    with pytest.raises(EmbedError, match="OWNRAG_EMBED"):
        emb.embed_texts(_openai_settings(embed_api_key=None), ["x"])
    assert _FakeClient.calls == []


def test_openai_transport_trips_breaker(monkeypatch):
    """连接级失败熔断 20s：窗口内不再撞端点（省 DNS/TLS/超时代价）。"""
    _install(monkeypatch, [httpx.ConnectError("connection refused")])
    with pytest.raises(EmbedError, match="不可达"):
        emb.embed_texts(_openai_settings(), ["x"])
    assert emb.breaker_open()
    calls_after = len(_FakeClient.calls)
    with pytest.raises(EmbedError, match="熔断中"):
        emb.embed_texts(_openai_settings(), ["x"])
    assert len(_FakeClient.calls) == calls_after


def test_openai_429_quota_message(monkeypatch):
    """真实 429 状态：限速不熔断（恢复即好），错误消息带提示。"""
    _install(monkeypatch, [_Resp({"error": "quota"}, status=429)])
    with pytest.raises(EmbedError, match="429.*速率"):
        emb.embed_texts(_openai_settings(), ["x"])
    assert not emb.breaker_open()


def test_query_instruct_off_by_default_and_opt_in(monkeypatch):
    """bge-m3 等模型无需指令前缀（默认关闭）；Qwen3-Embedding 系设值开启，只加 query 侧。"""
    _install(monkeypatch, [
        {"data": [{"index": 0, "embedding": [1.0]}]},   # 默认 embed_query
        {"data": [{"index": 0, "embedding": [1.0]}]},   # 开 instruct 的 embed_query
        {"data": [{"index": 0, "embedding": [1.0]}]},   # 开 instruct 的 embed_texts
    ])
    emb.embed_query(_openai_settings(), "年假怎么申请")
    assert _FakeClient.calls[0]["json"]["input"][0] == "年假怎么申请"   # 默认不加前缀
    emb.embed_query(_openai_settings(embed_query_instruct=DEFAULT_QUERY_INSTRUCT), "年假怎么申请")
    assert _FakeClient.calls[1]["json"]["input"][0].startswith(f"Instruct: {DEFAULT_QUERY_INSTRUCT}\nQuery: ")
    emb.embed_texts(_openai_settings(embed_query_instruct=DEFAULT_QUERY_INSTRUCT), ["年假申请流程"])
    assert _FakeClient.calls[2]["json"]["input"][0] == "年假申请流程"   # 文档侧永不加


def test_instruct_disable_via_empty(monkeypatch):
    """空串 = 显式关闭（不加前缀）。"""
    _install(monkeypatch, [{"data": [{"index": 0, "embedding": [1.0]}]}])
    emb.embed_query(_openai_settings(embed_query_instruct=""), "q")
    assert _FakeClient.calls[0]["json"]["input"][0] == "q"


def test_ollama_dispatch_unchanged_and_legacy_stub(monkeypatch):
    """ollama 路径不加指令前缀、URL 不变；无 embed_provider 字段的旧 settings stub 仍走 ollama。"""
    _install(monkeypatch, [{"embeddings": [[1.0, 2.0]]}])
    legacy = types.SimpleNamespace(ollama_base_url="http://127.0.0.1:9", embed_model="bge-m3")
    assert emb.embed_query(legacy, "原始查询") == [1.0, 2.0]
    call = _FakeClient.calls[0]
    assert call["url"] == "http://127.0.0.1:9/api/embed"
    assert call["json"]["input"] == ["原始查询"]    # 无 Instruct 前缀
