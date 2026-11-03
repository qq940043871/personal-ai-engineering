# -*- coding: utf-8 -*-
"""剧本（storyboard）加载、规范化与时长估算。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

META_DEFAULTS = {
    "fps": 30,
    "width": 1920,
    "height": 1080,
    "voice": "zh-CN-XiaoxiaoNeural",
    "narration": True,
    "accent": "#22d3ee",
    "seriesTag": "AI 学习教程",
}


def load(path):
    """读取剧本 JSON 并规范化；返回 {meta, scenes, path}。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"剧本不存在: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    meta = dict(META_DEFAULTS)
    meta.update(data.get("meta") or {})
    if not meta.get("id"):
        raise ValueError("meta.id 缺失")
    if not meta.get("title"):
        meta["title"] = meta["id"]

    scenes = data.get("scenes") or []
    if not scenes:
        raise ValueError("scenes 为空，至少需要一幕")
    scenes = [_normalize(s, i, len(scenes)) for i, s in enumerate(scenes)]
    return {"meta": meta, "scenes": scenes, "path": str(p)}


def _normalize(s, i, total):
    s = dict(s)
    s.setdefault("id", f"s{i + 1:02d}")
    s["sceneIndex"] = i + 1
    s["sceneTotal"] = total
    bullets = s.get("bullets")
    if bullets:
        s["bullets"] = [b if isinstance(b, dict) else {"text": str(b)} for b in bullets]
    if s.get("type") == "code" and isinstance(s.get("code"), str):
        s["lines"] = s["code"].splitlines()
        s.pop("code", None)
    return s


def min_duration(scene):
    """无旁白/旁白缺失时各幕类型的最短可读时长（秒）。"""
    if scene.get("minDuration"):
        return float(scene["minDuration"])
    t = scene.get("type", "bullets")
    if t == "title" or t == "end":
        return 5.0
    if t == "section":
        return 4.0
    if t == "quote":
        return 5.0
    if t == "bullets":
        return 3.5 + 1.7 * len(scene.get("bullets") or [])
    if t == "code":
        chars = sum(len(x) for x in (scene.get("lines") or []))
        return 4.5 + chars / 30.0
    if t == "compare":
        n = max(len((scene.get("left") or {}).get("items") or []),
                len((scene.get("right") or {}).get("items") or []))
        return 4.0 + 1.3 * n
    if t == "diagram":
        return 3.5 + 0.9 * len(scene.get("steps") or [])
    if t == "summary":
        return 3.0 + 0.8 * len(scene.get("bullets") or [])
    return 5.0
