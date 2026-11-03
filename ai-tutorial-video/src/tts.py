# -*- coding: utf-8 -*-
"""edge-tts 旁白合成：文本 → MP3，带内容哈希缓存。"""
import asyncio
import hashlib
from pathlib import Path


def _cache_path(cache_dir, text, voice):
    h = hashlib.md5((voice + "|" + text).encode("utf-8")).hexdigest()[:16]
    return Path(cache_dir) / f"{h}.mp3"


def synth(text, voice, cache_dir):
    """合成旁白，返回 (mp3路径或None, 是否新合成)。失败返回 (None, False)。"""
    import edge_tts  # 延迟导入，便于 --no-tts 时跳过依赖

    text = (text or "").strip()
    if not text:
        return None, False
    out = _cache_path(cache_dir, text, voice)
    if out.exists() and out.stat().st_size > 1024:
        return out, False

    async def _run():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(out))

    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(_run())
    except Exception as exc:  # 网络不通 / 服务波动 → 降级无声
        print(f"  [tts] 旁白合成失败（{exc.__class__.__name__}），本视频该幕将无声")
        return None, False
    if not out.exists() or out.stat().st_size < 1024:
        return None, False
    return out, True
