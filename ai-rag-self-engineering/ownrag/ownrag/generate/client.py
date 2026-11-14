"""生成侧供应商分派器：settings.chat_provider（ollama | openai）→ 具体客户端。

同接口同异常（ChatError）；routes_chat / scripts 只 import 这里，换供应商零调用点改动。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

from ownrag.generate.ollama_client import ChatError
from ownrag.generate.ollama_client import chat as _ollama_chat
from ownrag.generate.ollama_client import chat_stream as _ollama_stream
from ownrag.generate.openai_client import chat as _openai_chat
from ownrag.generate.openai_client import chat_stream as _openai_stream

if TYPE_CHECKING:
    from ownrag.config import Settings

# 门面约定：调用方只 import client，不直接依赖具体供应商模块（换供应商零调用点改动）。
# ChatError 在此显式再导出——它在下方代码里只作接口承诺，不在本模块被调用。
__all__ = ["ChatError", "chat", "chat_stream"]


def chat_stream(settings: "Settings", messages: list[dict], **kw) -> Iterator[str]:
    if settings.chat_provider == "openai":
        return _openai_stream(settings, messages, **kw)
    return _ollama_stream(settings, messages, **kw)


def chat(settings: "Settings", messages: list[dict], **kw) -> str:
    if settings.chat_provider == "openai":
        return _openai_chat(settings, messages, **kw)
    return _ollama_chat(settings, messages, **kw)
