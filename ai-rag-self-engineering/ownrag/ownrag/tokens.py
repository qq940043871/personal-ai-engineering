"""Token 粗估（预算口径）：CJK 一字≈1 token，其余 4 字符≈1 token。

不追求精确分词——预算只需同口径可比。切分与上下文裁剪共用同一函数，
避免"切分按一套口径、预算按另一套"的两本账。
"""
from __future__ import annotations


def est_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk + (len(text) - cjk) // 4
