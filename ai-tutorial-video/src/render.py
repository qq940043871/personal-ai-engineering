# -*- coding: utf-8 -*-
"""Playwright 渲染：注入剧本 → 逐帧驱动 __render(t) → 截图帧序列。"""
import shutil
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "scene.html"


def open_browser(playwright, prefer_channel=None):
    """优先 Playwright 自带 chromium，失败则回退系统 Edge / Chrome。"""
    launch_args = ["--hide-scrollbars", "--force-color-profile=srgb"]
    attempts = []
    if prefer_channel:
        attempts.append({"channel": prefer_channel})
    attempts.append({})
    attempts.append({"channel": "msedge"})
    attempts.append({"channel": "chrome"})
    last_err = None
    for kw in attempts:
        try:
            browser = playwright.chromium.launch(headless=True, args=launch_args, **kw)
            label = kw.get("channel") or "chromium"
            return browser, label
        except Exception as exc:  # 浏览器内核缺失等
            last_err = exc
    raise RuntimeError(f"无法启动无头浏览器: {last_err}")


def new_page(browser, width, height):
    page = browser.new_page(viewport={"width": width, "height": height},
                            device_scale_factor=1)
    page.goto(TEMPLATE.as_uri())
    page.evaluate("() => document.fonts.ready")
    return page


def render_scene(page, scene, fps, frames_dir):
    """渲染单幕：确定性时间轴逐帧截图，返回帧数。"""
    frames_dir = Path(frames_dir)
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)
    page.evaluate("s => { window.SCENE = s; }", scene)
    n_frames = int(round(scene["duration"] * fps))
    for i in range(n_frames):
        page.evaluate("t => window.__render(t)", i / fps)
        page.screenshot(path=str(frames_dir / f"f_{i:06d}.jpg"),
                        type="jpeg", quality=90)
    return n_frames
