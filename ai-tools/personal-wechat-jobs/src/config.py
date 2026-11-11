# -*- coding: utf-8 -*-
"""配置加载。"""
from __future__ import annotations

import os
from typing import Any, Dict

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(ROOT, "config.yaml")

DEFAULTS: Dict[str, Any] = {
    "source": {"rss_url": "mock", "account_name": "未命名公众号",
               "max_items": 60, "fetch_workers": 4, "timeout": 15},
    "filter": {"title_include": [], "body_include": [], "exclude": [],
               "require_title_hit": True},
    "extract": {"mode": "rule", "llm": {"base_url": "", "api_key": "",
                                        "model": "", "temperature": 0}},
    "output": {"data_dir": "data", "out_dir": "out", "formats": ["md", "html"]},
}


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | None = None) -> Dict[str, Any]:
    path = path or DEFAULT_CONFIG
    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    cfg = _merge(DEFAULTS, raw)

    # 相对路径一律锚定到项目根，避免 cwd 不同导致目录漂移
    for key in ("data_dir", "out_dir"):
        cfg["output"][key] = os.path.join(ROOT, cfg["output"][key])
    return cfg
