"""Ollama embedding 适配：批量、显式版本（embed_version 与向量兼容性绑定——跨版本向量禁止混用）。

熔断（breaker）：Ollama 不可达时，单次连接失败在本机可能耗 2 秒以上（SYN 被丢/重传）。
不熔断的话，一次问答要付两份代价（直击库 L1 + 混合检索各 embed 一次），页面就像卡死。
这里只对**连接级失败**熔断，模型不存在之类的内容错误不熔断——那是配置问题，重试也没用。
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ownrag.config import Settings


class EmbedError(RuntimeError):
    pass


BREAKER_SECONDS = 20.0        # 熔断窗口：期间直接快速失败，不反复撞墙
_BREAKER_UNTIL = 0.0          # monotonic 时间点；0 = 闭合


def breaker_open() -> bool:
    return time.monotonic() < _BREAKER_UNTIL


def breaker_remaining() -> float:
    return max(0.0, round(_BREAKER_UNTIL - time.monotonic(), 1))


def reset_breaker() -> None:
    """测试/运维用：清掉熔断状态（例如刚把 Ollama 起起来）。"""
    global _BREAKER_UNTIL
    _BREAKER_UNTIL = 0.0


def _trip_breaker() -> None:
    global _BREAKER_UNTIL
    _BREAKER_UNTIL = time.monotonic() + BREAKER_SECONDS


def embed_texts(settings: "Settings", texts: list[str], batch: int = 32,
                model: str | None = None) -> list[list[float]]:
    """POST {base}/api/embed —— Ollama 原生批量接口；失败抛 EmbedError（调用方决定降级）。"""
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


def embed_query(settings: "Settings", query: str) -> list[float]:
    return embed_texts(settings, [query])[0]
