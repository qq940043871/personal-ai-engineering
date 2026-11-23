"""控制台页面：按功能拆分的多页面 HTML（零构建、零 CDN），随包分发。

页面只是壳——所有数据都从 /admin/* 与 /chat 拿，口径与线上链路一致。
每页共享 web/assets/app.css（样式）与 web/assets/app.js（工具 / API / 侧边栏进度 / 启动）。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse

router = APIRouter(tags=["ui"])
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
ASSETS_DIR = WEB_DIR / "assets"

# 功能页清单：路径段 -> 页面标题（页面文件名为 {seg}.html）
PAGES = {
    "overview": "概览",
    "ingest": "入库",
    "review": "解析复核",
    "chat": "问答",
    "retrieve": "检索调试",
    "kb": "知识库",
    "observe": "观测",
    "plan": "14 天路线",
}

_MEDIA = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".ico": "image/x-icon",
    ".png": "image/png",
}


def _file(path: Path) -> FileResponse | PlainTextResponse:
    if not path.is_file():
        return PlainTextResponse(f"缺少页面文件：{path}", status_code=500)
    media = _MEDIA.get(path.suffix, "application/octet-stream")
    # no-store：改完页面刷新即生效，不用清缓存
    return FileResponse(path, media_type=media, headers={"Cache-Control": "no-store"})


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui")


@router.get("/ui", include_in_schema=False)
def ui_home():
    # 老入口 /ui 直接落概览页，保持既有书签与 / 重定向可用
    return _file(WEB_DIR / "overview.html")


@router.get("/ui/assets/{name}", include_in_schema=False)
def ui_asset(name: str):
    return _file(ASSETS_DIR / name)


# 站点图标必须落在根路径：浏览器对 /favicon.ico 是隐式探测，iOS 也只认 /apple-touch-icon.png。
# 这里显式注册而不挂 StaticFiles，是为了与 /ui/** 的显式路由风格一致、且不吞掉其它根级路径。
@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return _file(WEB_DIR / "favicon.ico")


@router.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon():
    return _file(WEB_DIR / "apple-touch-icon.png")


@router.get("/ui/{page}", include_in_schema=False)
def ui_page(page: str):
    if page in PAGES:
        return _file(WEB_DIR / f"{page}.html")
    raise HTTPException(status_code=404, detail=f"未知页面：{page}")
