"""Prompt 版本化（04 文档 §五）：配置即代码，文件进 Git——历史与回滚免费送。

对应 Dify"Prompt 与代码解耦"能力的自研落点；AB = 两份模板 + 固定评测集对比。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from ownrag.config import get_settings


@lru_cache(maxsize=32)
def load_prompt(name: str) -> dict:
    path = Path(get_settings().prompts_dir) / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt 模板不存在：{path}")
    with open(path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f) or {}
    for key in ("system", "template"):
        if not spec.get(key):
            raise ValueError(f"Prompt {name} 缺少 {key} 字段")
    return spec


def render(name: str, question: str, context_blocks: str, **extra: str) -> list[dict]:
    """渲染成 messages；模板占位符缺失在渲染期爆（配置错误不进运行期）。"""
    spec = load_prompt(name)
    user = spec["template"]
    for key, value in {"question": question, "context_blocks": context_blocks, **extra}.items():
        user = user.replace("{" + key + "}", value)
    leftover = [tok for tok in _placeholders(user) if tok not in {"question", "context_blocks", *extra}]
    if leftover:
        raise ValueError(f"Prompt {name} 渲染后仍有未填占位符：{leftover}")
    return [{"role": "system", "content": spec["system"]}, {"role": "user", "content": user}]


def _placeholders(text: str) -> set[str]:
    import re
    return set(re.findall(r"\{(\w+)\}", text))
