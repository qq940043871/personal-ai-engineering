"""ownrag · FastAPI 入口。

启动期三件套（配置错误不进运行期）：
  1. 建表（幂等 DDL）
  2. import steps 触发步骤注册
  3. 管道 DSL 全量校验：YAML 里的 type 必须在注册表里
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

import ownrag.steps  # noqa: F401  —— import 即注册全部步骤类型
from ownrag.config import get_settings
from ownrag.core.db import init_schema
from ownrag.core.registry import STEP_REGISTRY, validate_pipeline_steps
from ownrag.api import routes_admin, routes_chat, routes_docs, routes_inspect, routes_ui


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_schema(settings.db_path)
    missing = validate_pipeline_steps(settings.pipelines)
    if missing:
        raise RuntimeError(f"管道 DSL 校验失败（启动期拦截）：{missing}")
    print(f"[ownrag] steps registered: {sorted(STEP_REGISTRY)}")
    print(f"[ownrag] pipelines: {sorted(settings.pipelines)} apps: {sorted(settings.apps)}")
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="ownrag · 自研 RAG 工程（个人实战骨架）", version="0.1.0",
                  lifespan=lifespan)
    app.include_router(routes_ui.router)
    app.include_router(routes_docs.router)
    app.include_router(routes_chat.router)
    app.include_router(routes_admin.router)
    app.include_router(routes_inspect.router)

    @app.get("/health")
    def health() -> dict:
        return {"service": "ownrag", "ok": True}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ownrag.main:app", host="127.0.0.1", port=8420, reload=False)
