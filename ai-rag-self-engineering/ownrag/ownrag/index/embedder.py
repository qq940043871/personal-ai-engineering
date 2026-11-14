"""embedding 适配（供应商可换）：ollama 原生 /api/embed | OpenAI 兼容 /embeddings。

openai 分派覆盖：SiliconFlow、DashScope text-embedding-v4、llama.cpp server 等
OpenAI 兼容端点——换后端只改 base_url/model/key，不动代码。
显式版本：embed_version 与向量兼容性绑定——跨版本向量禁止混用（换供应商/模型 = 换值 = 全量重建索引）。
熔断（breaker）：连接级失败在本机可能耗 2 秒以上（SYN 被丢/重传；远程端点还有 DNS/TLS）。
不熔断的话，一次问答要付两份代价（直击库 L1 + 混合检索各 embed 一次），页面就像卡死。
只对**连接级失败**熔断，4xx/5xx 不熔断——那是配额/配置问题，重试也没用。
指令前缀：Qwen3-Embedding 系 query 侧需 `Instruct: ...\nQuery: ...`（官方口径，不加掉 1-5 个点），
只加在 query 侧、文档侧不加；仅 openai 分派生效（bge-m3@ollama 无此语义）。
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ownrag.config import Settings

# Qwen3-Embedding 系官方推荐的任务指令（英文书写）：开启前缀时可直接引用的参考值
DEFAULT_QUERY_INSTRUCT = "Given a search query, retrieve relevant passages that answer the query"


class EmbedError(RuntimeError):
    pass


BREAKER_SECONDS = 20.0        # 熔断窗口：期间直接快速失败，不反复撞墙
_BREAKER_UNTIL = 0.0          # monotonic 时间点；0 = 闭合


def breaker_open() -> bool:
    return time.monotonic() < _BREAKER_UNTIL


def breaker_remaining() -> float:
    return max(0.0, round(_BREAKER_UNTIL - time.monotonic(), 1))


def reset_breaker() -> None:
    """测试/运维用：清掉熔断状态（例如刚把后端起起来）。"""
    global _BREAKER_UNTIL
    _BREAKER_UNTIL = 0.0


def _trip_breaker() -> None:
    global _BREAKER_UNTIL
    _BREAKER_UNTIL = time.monotonic() + BREAKER_SECONDS


def embed_texts(settings: "Settings", texts: list[str], batch: int = 32,
                model: str | None = None) -> list[list[float]]:
    """文档侧批量向量化：不加指令前缀。按 settings.embed_provider 分派，失败抛 EmbedError。"""
    if getattr(settings, "embed_provider", "ollama") == "openai":
        return _embed_texts_openai(settings, texts, batch, model)
    return _embed_texts_ollama(settings, texts, batch, model)


def embed_query(settings: "Settings", query: str) -> list[float]:
    """查询侧单条向量化：指令前缀默认关闭（bge-m3 无此语义）；Qwen3-Embedding 系用户
    设 OWNRAG_EMBED_QUERY_INSTRUCT 开启（官方口径不加会掉 1-5 个点），只加 query 侧。"""
    if getattr(settings, "embed_provider", "ollama") == "openai":
        instruct = getattr(settings, "embed_query_instruct", None)
        if instruct:
            query = f"Instruct: {instruct}\nQuery: {query}"
    return embed_texts(settings, [query])[0]


# ---------------------------------------------------------------- ollama 分派
def _embed_texts_ollama(settings: "Settings", texts: list[str], batch: int,
                        model: str | None) -> list[list[float]]:
    """POST {base}/api/embed —— Ollama 原生批量接口。"""
    import httpx

    if breaker_open():
        raise EmbedError(f"embedding 后端不可用（熔断中，{breaker_remaining()}s 后重试）："
                         f"{settings.ollama_base_url}")

    model = model or settings.embed_model
    out: list[list[float]] = []
    # trust_env=False：本地服务不该走 HTTP(S)_PROXY；读超时留给大批量，连接超时要短
    timeout = httpx.Timeout(connect=5, read=300, write=30, pool=5)
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        for i in range(0, len(texts), batch):
            part = texts[i:i + batch]
            try:
                resp = client.post(f"{settings.ollama_base_url}/api/embed",
                                   json={"model": model, "input": part})
                resp.raise_for_status()
                payload = resp.json()
            except httpx.TransportError as exc:   # 连接级：Ollama 没起/网络不通
                _trip_breaker()
                raise EmbedError(
                    f"Ollama embedding 不可达（{settings.ollama_base_url}，模型 {model}）：{exc}") from exc
            except httpx.HTTPError as exc:        # 协议/状态码级：不改熔断，属于配置或模型问题
                raise EmbedError(
                    f"Ollama embedding 失败（{settings.ollama_base_url}，模型 {model}）：{exc}") from exc
            embs = payload.get("embeddings") or []
            if len(embs) != len(part):
                raise EmbedError(f"embedding 数量不符：请求 {len(part)} 返回 {len(embs)}")
            out.extend(embs)
    return out


# ---------------------------------------------------------------- openai 兼容分派
def _embed_texts_openai(settings: "Settings", texts: list[str], batch: int,
                        model: str | None) -> list[list[float]]:
    """POST {base}/embeddings（OpenAI 兼容）：响应 data[i].embedding 按 index 对齐。"""
    import httpx

    base = (getattr(settings, "embed_base_url", None) or "").rstrip("/")
    if not base or not getattr(settings, "embed_api_key", None):
        raise EmbedError("OPENAI 嵌入供应商未配置：OWNRAG_EMBED_BASE_URL / OWNRAG_EMBED_API_KEY 未设置")
    if breaker_open():
        raise EmbedError(f"embedding 后端不可用（熔断中，{breaker_remaining()}s 后重试）：{base}")

    model = model or settings.embed_model
    out: list[list[float]] = []
    timeout = httpx.Timeout(connect=10, read=300, write=30, pool=10)
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        for i in range(0, len(texts), batch):
            part = texts[i:i + batch]
            try:
                resp = client.post(f"{base}/embeddings",
                                   json={"model": model, "input": part},
                                   headers={"Authorization": f"Bearer {settings.embed_api_key}"})
                resp.raise_for_status()
                payload = resp.json()
            except httpx.TransportError as exc:   # 连接级：网络不通/DNS 失败
                _trip_breaker()
                raise EmbedError(f"嵌入端点不可达（{base}，模型 {model}）：{exc}") from exc
            except httpx.HTTPStatusError as exc:  # 状态码级：配额/余额/模型名/鉴权问题，重试无用
                code = exc.response.status_code
                hint = {429: "（速率/额度限制，稍后重试）",
                        402: "（账户余额不足：免费模型也需实名认证后的赠金或充值）"}.get(code, "")
                raise EmbedError(
                    f"嵌入端点返回 HTTP {code}{hint}（{base}，模型 {model}）") from exc
            except httpx.HTTPError as exc:
                raise EmbedError(f"嵌入端点失败（{base}，模型 {model}）：{exc}") from exc
            data = payload.get("data") or []
            if len(data) != len(part):
                raise EmbedError(f"embedding 数量不符：请求 {len(part)} 返回 {len(data)}")
            ordered = sorted(data, key=lambda d: d.get("index", 0))
            out.extend(d["embedding"] for d in ordered)
    return out
