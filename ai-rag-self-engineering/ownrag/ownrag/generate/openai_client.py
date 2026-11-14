"""OpenAI 兼容 chat 客户端（远程推理档）：标准 /chat/completions + SSE 流式。

与 ollama_client 同接口同异常（ChatError），由 generate/client.py 按 settings.chat_provider 分派。
参数映射：num_ctx 无对应项不上送——它只是预算侧的装箱口径（budget.py）；num_predict → max_tokens。
思维链不进正文：supportsReasoning 的模型会先在 delta.reasoning_content 吐思维链，直接跳过。
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Iterator

from ownrag.generate.ollama_client import ChatError

if TYPE_CHECKING:
    from ownrag.config import Settings


def chat_stream(settings: "Settings", messages: list[dict], model: str | None = None,
                num_ctx: int | None = None, temperature: float = 0.2,
                num_predict: int | None = None) -> Iterator[str]:
    """逐 token 产出文本；连接/模型异常抛 ChatError（调用方转 SSE error 事件，快速失败不吊死）。"""
    import httpx

    base_url = (settings.chat_base_url or "").rstrip("/")
    if not base_url or not settings.chat_api_key:
        raise ChatError("OPENAI 供应商未配置：OWNRAG_CHAT_BASE_URL / OWNRAG_CHAT_API_KEY 未设置")
    payload = {"model": model or settings.chat_model, "messages": messages,
               "stream": True, "temperature": temperature}
    if num_predict:
        payload["max_tokens"] = num_predict

    try:
        with httpx.Client(timeout=httpx.Timeout(connect=10, read=300, write=30, pool=10),
                          trust_env=False) as client:
            with client.stream("POST", f"{base_url}/chat/completions", json=payload,
                               headers={"Authorization": f"Bearer {settings.chat_api_key}"}) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue  # SSE 注释行 / 事件名行 / 空行一律跳过
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                        err = chunk.get("error")
                        if err:
                            msg = err if isinstance(err, str) else err.get("message") or err
                            raise ChatError(f"生成端点返回错误：{msg}")
                        piece = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                    except (json.JSONDecodeError, AttributeError, IndexError, TypeError) as exc:
                        raise ChatError(f"生成端点响应无法解析：{data[:120]}（{exc}）") from exc
                    if piece:
                        yield piece
    except httpx.HTTPError as exc:
        raise ChatError(
            f"生成端点不可达（{base_url}，模型 {payload['model']}）：{exc}") from exc


def chat(settings: "Settings", messages: list[dict], **kw) -> str:
    """聚合版：闸门重答、列映射建议等非流式场景用。"""
    return "".join(chat_stream(settings, messages, **kw))
