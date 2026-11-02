"""Ollama chat 客户端：流式（/api/chat stream）+ 聚合；模型中立——换远程只改端点配置。"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from ownrag.config import Settings


class OllamaError(RuntimeError):
    pass


def chat_stream(settings: "Settings", messages: list[dict], model: str | None = None,
                num_ctx: int | None = None, temperature: float = 0.2,
                num_predict: int | None = None) -> Iterator[str]:
    """逐 token 产出文本；连接/模型异常抛 OllamaError（调用方转 SSE error 事件，快速失败不吊死）。"""
    import httpx

    options: dict = {"temperature": temperature}
    if num_ctx or num_ctx == 0:
        options["num_ctx"] = num_ctx
    if num_predict:
        options["num_predict"] = num_predict
    payload = {"model": model or settings.chat_model, "messages": messages,
               "stream": True, "options": options}

    try:
        with httpx.Client(timeout=httpx.Timeout(connect=10, read=300, write=30, pool=10),
                          trust_env=False) as client:  # 本地模型服务，不穿代理
            with client.stream("POST", f"{settings.ollama_base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise OllamaError(f"Ollama 返回错误：{chunk['error']}")
                    piece = ((chunk.get("message") or {}).get("content")) or ""
                    if piece:
                        yield piece
                    if chunk.get("done"):
                        return
    except httpx.HTTPError as exc:
        raise OllamaError(
            f"Ollama 不可达（{settings.ollama_base_url}，模型 {payload['model']}）：{exc}") from exc


def chat(settings: "Settings", messages: list[dict], **kw) -> str:
    """聚合版：闸门重答、列映射建议等非流式场景用。"""
    return "".join(chat_stream(settings, messages, **kw))
