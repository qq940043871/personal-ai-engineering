"""控制台页面：单文件 HTML（零构建、零 CDN），随包分发。

页面只是壳——所有数据都从 /admin/* 与 /chat 拿，口径与线上链路一致。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse

router = APIRouter(tags=["ui"])
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui")


@router.get("/ui", include_in_schema=False)
def index():
    path = WEB_DIR / "index.html"
    if not path.is_file():
        return PlainTextResponse(f"缺少页面文件：{path}", status_code=500)
    # no-store：改完页面刷新即生效，不用清缓存
    return FileResponse(path, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store"})
