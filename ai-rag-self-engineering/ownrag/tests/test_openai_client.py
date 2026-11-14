"""OpenAI 兼容 chat 客户端 + 供应商分派器：httpx.Client 整类打桩，零出网。

覆盖：SSE 帧解析（content 增量 / reasoning_content 跳过 / [DONE] 终止 / DONE 后不产）/
error JSON 与坏帧 → ChatError / 缺配置不发起请求 / 分派器按 provider 路由 / OllamaError 别名兼容。
"""
import json
import types

import httpx
import pytest

import ownrag.generate.client as disp
import ownrag.generate.openai_client as oc
from ownrag.generate.ollama_client import ChatError, OllamaError

SETTINGS = types.SimpleNamespace(
    chat_provider="openai", chat_base_url="http://api.test/v1", chat_api_key="tok",
    chat_model="agnes-3.0-flash", ollama_base_url="http://127.0.0.1:9")


def _frame(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False)


HAPPY_LINES = [
    "",                                                    # SSE 帧间隔空行
    _frame({"choices": [{"delta": {"role": "assistant", "content": ""}}]}),
    _frame({"choices": [{"delta": {"reasoning_content": "思考中…"}}]}),   # 思维链必须被跳过
    _frame({"choices": [{"delta": {"content": "RAG（检索"}}]}),
    ": keep-alive",                                        # SSE 注释行
    _frame({"choices": [{"delta": {"content": "增强生成"}}]}),
    "data: [DONE]",
    _frame({"choices": [{"delta": {"content": "！不该出现"}}]}),           # DONE 即终止
]


class _FakeStreamResp:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        return None

    def iter_lines(self):
        return iter(self._lines)


class _FakeStreamCtx:
    def __init__(self, lines, exc=None):
        self._lines, self._exc = lines, exc

    def __enter__(self):
        if self._exc:
            raise self._exc
        return _FakeStreamResp(self._lines)

    def __exit__(self, *exc):
        return False


def _install_client(monkeypatch, captured, lines=None, exc=None):
    """替换 httpx.Client 整类（test_embedder 同款打桩位），并收集请求参数。"""
    class _FakeClient:
        def __init__(self, timeout=None, trust_env=None):
            pass

        def stream(self, method, url, json=None, headers=None):
            captured.update(method=method, url=url, json=json, headers=headers)
            return _FakeStreamCtx(lines or [], exc)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(httpx, "Client", _FakeClient)


def test_stream_parses_sse_and_skips_reasoning(monkeypatch):
    """content 增量拼接；reasoning_content / 注释行 / [DONE] 全部不进正文。"""
    captured = {}
    _install_client(monkeypatch, captured, HAPPY_LINES)
    out = "".join(oc.chat_stream(SETTINGS, [{"role": "user", "content": "q"}], num_predict=32))
    assert out == "RAG（检索增强生成"
    assert captured["url"] == "http://api.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert captured["json"]["model"] == "agnes-3.0-flash"
    assert captured["json"]["max_tokens"] == 32          # num_predict → max_tokens
    assert "options" not in captured["json"]             # Ollama 专有参数不上送


def test_chat_aggregates_stream(monkeypatch):
    captured = {}
    _install_client(monkeypatch, captured, HAPPY_LINES)
    assert oc.chat(SETTINGS, [{"role": "user", "content": "q"}]) == "RAG（检索增强生成"


def test_error_payload_raises_chat_error(monkeypatch):
    captured = {}
    _install_client(monkeypatch, captured, [_frame({"error": {"message": "余额不足"}})])
    with pytest.raises(ChatError, match="余额不足"):
        "".join(oc.chat_stream(SETTINGS, [{"role": "user", "content": "q"}]))


def test_malformed_frame_raises_chat_error(monkeypatch):
    """坏 JSON 帧不裸抛解析异常：包成 ChatError 带现场预览，SSE error 事件才接得住。"""
    captured = {}
    _install_client(monkeypatch, captured, ["data: {oops"])
    with pytest.raises(ChatError, match="响应无法解析"):
        "".join(oc.chat_stream(SETTINGS, [{"role": "user", "content": "q"}]))


def test_transport_error_wrapped(monkeypatch):
    """连接失败 → ChatError（带端点与模型名），routes_chat 的 except 才能捕获转 error 事件。"""
    captured = {}
    _install_client(monkeypatch, captured, exc=httpx.ConnectError("connection refused"))
    with pytest.raises(ChatError, match="不可达"):
        "".join(oc.chat_stream(SETTINGS, [{"role": "user", "content": "q"}]))


def test_missing_config_fails_before_request(monkeypatch):
    """缺 base_url / key 在发请求前就炸——配置错误不该伪装成网络故障。"""
    captured = {}
    _install_client(monkeypatch, captured)                 # 若发请求会空响应；根本不该走到
    bare = types.SimpleNamespace(chat_base_url=None, chat_api_key=None, chat_model="m")
    with pytest.raises(ChatError, match="OWNRAG_CHAT_BASE_URL"):
        "".join(oc.chat_stream(bare, [{"role": "user", "content": "q"}]))
    assert "url" not in captured


def test_dispatch_routes_by_provider(monkeypatch):
    """ollama | openai 按配置分派：调用点只认 generate.client，换供应商零改动。"""
    monkeypatch.setattr(disp, "_openai_stream", lambda s, m, **kw: iter(["openai"]))
    monkeypatch.setattr(disp, "_ollama_stream", lambda s, m, **kw: iter(["ollama"]))
    openai_settings = types.SimpleNamespace(chat_provider="openai")
    ollama_settings = types.SimpleNamespace(chat_provider="ollama")
    assert "".join(disp.chat_stream(openai_settings, [])) == "openai"
    assert "".join(disp.chat_stream(ollama_settings, [])) == "ollama"


def test_ollama_error_alias_compat():
    """OllamaError 是 ChatError 的旧名别名：既有引用/文档语义不破坏。"""
    assert OllamaError is ChatError
