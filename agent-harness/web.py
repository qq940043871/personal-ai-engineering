#!/usr/bin/env python3
"""
Agent Harness - Web 用户界面 (WEB UI)
基于 FastAPI + Vue.js 实现，支持实时流式输出

@author: OpenClaw Team
@date: 2026-04-22
"""

import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from harness import MainLoop, ToolRegistry, create_provider
from harness.cost_tracker import CostTracker
from harness.memory_manager import create_memory_manager
from harness.tracer import Tracer
from harness.multi_agent import (
    create_multi_agent,
    Orchestrator,
    WorkerPool,
    MultiAgentResult,
    AgentRole,
    TaskStatus,
    SubTask,
)
import yaml


# ============================================================================
# FastAPI 应用
# ============================================================================

app = FastAPI(title="Agent Harness", version="1.0.0", description="OpenClaw Web UI")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件目录
BASE_DIR = Path(__file__).parent
web_dir = BASE_DIR / "web"
web_dir.mkdir(exist_ok=True)
static_dir = web_dir / "static"
static_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ============================================================================
# 配置加载
# ============================================================================


def load_config() -> dict:
    """加载配置文件（优先从 web.py 所在目录）"""
    config_file = BASE_DIR / "config.yaml"
    if config_file.exists():
        try:
            import yaml
            with open(config_file, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[WARN] 加载配置文件失败: {e}")
    return {}


def load_experts() -> list:
    """加载专家配置"""
    experts_file = BASE_DIR / "experts.yaml"
    if experts_file.exists():
        try:
            with open(experts_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data.get("experts", [])
        except Exception as e:
            print(f"[WARN] 加载专家配置失败: {e}")
    return []


# 全局专家列表
EXPERTS = load_experts()


# ============================================================================
# 会话管理
# ============================================================================


class SessionManager:
    """Web 会话管理器"""

    def __init__(self):
        self.sessions: dict[str, dict] = {}

    def create_session(self, config: dict, workspace_id: str = "default", workspace_path: str = "") -> str:
        """创建新会话"""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "id": session_id,
            "config": config,
            "workspace_id": workspace_id,
            "workspace_path": workspace_path,
            "conversation": [],
            "created_at": datetime.now().isoformat(),
            "last_activity": datetime.now().isoformat(),
            "cost": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "turns": 0,
        }
        return session_id

    def get_session(self, session_id: str) -> Optional[dict]:
        """获取会话"""
        session = self.sessions.get(session_id)
        if session:
            session["last_activity"] = datetime.now().isoformat()
        return session

    def update_session(self, session_id: str, **kwargs):
        """更新会话"""
        if session_id in self.sessions:
            self.sessions[session_id].update(kwargs)

    def delete_session(self, session_id: str):
        """删除会话"""
        self.sessions.pop(session_id, None)

    def list_sessions(self) -> list[dict]:
        """列出所有会话"""
        return [
            {
                "id": s["id"],
                "workspace_id": s.get("workspace_id", "default"),
                "workspace_name": self._get_workspace_name(s.get("workspace_id", "default")),
                "created_at": s["created_at"],
                "last_activity": s["last_activity"],
                "message_count": len(s["conversation"]),
                "cost": s["cost"],
            }
            for s in self.sessions.values()
        ]
    
    def _get_workspace_name(self, workspace_id: str) -> str:
        """获取工作空间名称"""
        workspaces = load_workspaces()
        for ws in workspaces:
            if ws["id"] == workspace_id:
                return ws["name"]
        return "未知工作空间"


session_manager = SessionManager()


# ============================================================================
# WebSocket 连接管理器
# ============================================================================


class ConnectionManager:
    """WebSocket 连接管理器 - 支持取消正在运行的任务"""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.running_tasks: dict[str, asyncio.Task] = {}  # 保存正在运行的任务

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: str):
        self.active_connections.pop(session_id, None)
        # 断开连接时取消任务
        self.cancel_task(session_id)

    def cancel_task(self, session_id: str):
        """取消正在运行的任务"""
        if session_id in self.running_tasks:
            task = self.running_tasks.pop(session_id)
            if not task.done():
                task.cancel()
                print(f"[WebSocket] 已取消任务: {session_id}")

    def register_task(self, session_id: str, task: asyncio.Task):
        """注册正在运行的任务"""
        self.running_tasks[session_id] = task

    async def send_message(self, session_id: str, message: dict):
        if session_id in self.active_connections:
            try:
                await self.active_connections[session_id].send_json(message)
            except Exception as e:
                print(f"[WebSocket] 发送消息失败: {e}")

    async def broadcast(self, message: dict):
        for connection in self.active_connections.values():
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"[WebSocket] 广播消息失败: {e}")


manager = ConnectionManager()


# ============================================================================
# API 路由
# ============================================================================


@app.get("/", response_class=HTMLResponse)
async def root():
    """主页"""
    return FileResponse(str(web_dir / "index.html"))


@app.get("/api/health")
async def health():
    """健康检查"""
    return {"status": "ok", "version": "1.0.0"}


# ============================================================================
# 工作空间管理
# ============================================================================

WORKSPACES_FILE = BASE_DIR / "workspaces.json"


def load_workspaces() -> list[dict]:
    """加载工作空间列表"""
    if WORKSPACES_FILE.exists():
        try:
            with open(WORKSPACES_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # 返回默认工作空间
    default_ws = {
        "id": "default",
        "name": "默认工作空间",
        "path": str(Path.cwd()),
        "description": "项目根目录",
        "created_at": datetime.now().isoformat(),
    }
    return [default_ws]


def save_workspaces(workspaces: list[dict]):
    """保存工作空间列表"""
    with open(WORKSPACES_FILE, "w", encoding="utf-8") as f:
        json.dump(workspaces, f, ensure_ascii=False, indent=2)


@app.get("/api/workspaces")
async def list_workspaces():
    """列出所有工作空间"""
    return load_workspaces()


@app.post("/api/workspaces")
async def create_workspace(request: Request):
    """创建新工作空间"""
    body = await request.json()
    name = body.get("name", "新工作空间")
    path = body.get("path", "")
    description = body.get("description", "")
    
    # 验证路径是否存在
    if path and Path(path).exists():
        workspaces = load_workspaces()
        new_ws = {
            "id": str(uuid.uuid4()),
            "name": name,
            "path": str(Path(path).resolve()),
            "description": description,
            "created_at": datetime.now().isoformat(),
        }
        workspaces.append(new_ws)
        save_workspaces(workspaces)
        return new_ws
    else:
        raise HTTPException(status_code=400, detail="路径不存在或无效")


@app.delete("/api/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str):
    """删除工作空间"""
    if workspace_id == "default":
        raise HTTPException(status_code=400, detail="不能删除默认工作空间")
    
    workspaces = load_workspaces()
    workspaces = [ws for ws in workspaces if ws["id"] != workspace_id]
    save_workspaces(workspaces)
    return {"status": "ok"}


@app.put("/api/workspaces/{workspace_id}")
async def update_workspace(workspace_id: str, request: Request):
    """更新工作空间"""
    body = await request.json()
    workspaces = load_workspaces()
    
    for ws in workspaces:
        if ws["id"] == workspace_id:
            ws["name"] = body.get("name", ws["name"])
            ws["description"] = body.get("description", ws["description"])
            save_workspaces(workspaces)
            return ws
    
    raise HTTPException(status_code=404, detail="工作空间不存在")


# ============================================================================
# 专家管理
# ============================================================================


@app.get("/api/experts")
async def list_experts():
    """列出所有专家（不含系统提示词）"""
    return [
        {
            "id": e["id"],
            "name": e["name"],
            "icon": e["icon"],
            "description": e["description"],
        }
        for e in EXPERTS
    ]


@app.get("/api/experts/{expert_id}/system-prompt")
async def get_expert_system_prompt(expert_id: str):
    """获取专家的系统提示词"""
    for e in EXPERTS:
        if e["id"] == expert_id:
            return {"system_prompt": e["system_prompt"]}
    raise HTTPException(status_code=404, detail="专家不存在")


# ============================================================================
# 会话管理
# ============================================================================


@app.post("/api/sessions")
async def create_session(request: Request):
    """创建新会话"""
    body = await request.json()
    config = body.get("config", {})
    workspace_id = body.get("workspace_id", "default")
    workspace_path = body.get("workspace_path", "")
    
    session_id = session_manager.create_session(config, workspace_id, workspace_path)
    return {"session_id": session_id}


@app.get("/api/sessions")
async def list_sessions():
    """列出所有会话"""
    return session_manager.list_sessions()


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话详情"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    session_manager.delete_session(session_id)
    return {"status": "ok"}


@app.get("/api/sessions/{session_id}/conversation")
async def get_conversation(session_id: str):
    """获取会话历史"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session["conversation"]


@app.post("/api/sessions/{session_id}/run")
async def run_agent(session_id: str, request: Request):
    """运行 Agent（非流式）"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    body = await request.json()
    prompt = body.get("prompt", "")
    workspace = body.get("workspace", str(Path.cwd()))
    system_prompt = body.get("system_prompt")

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    try:
        result = await _run_agent_async(session, prompt, workspace, system_prompt)
        return {"result": result, "session": session}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/multi-agent", response_class=HTMLResponse)
async def multi_agent_page():
    return FileResponse(str(web_dir / "multi_agent.html"))


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket 端点 - 支持流式输出和取消任务"""
    await manager.connect(session_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "run":
                prompt = data.get("prompt", "")
                workspace = data.get("workspace", str(Path.cwd()))
                system_prompt = data.get("system_prompt")

                await manager.send_message(session_id, {
                    "type": "status",
                    "status": "running",
                    "message": "Agent 运行中..."
                })

                try:
                    # 创建任务并注册
                    task = asyncio.create_task(
                        _run_agent_stream(session_id, prompt, workspace, system_prompt)
                    )
                    manager.register_task(session_id, task)
                    await task
                except asyncio.CancelledError:
                    await manager.send_message(session_id, {
                        "type": "status",
                        "status": "stopped",
                        "message": "Agent 已停止"
                    })
                except Exception as e:
                    await manager.send_message(session_id, {
                        "type": "error",
                        "message": str(e)
                    })
                finally:
                    # 清理任务
                    if session_id in manager.running_tasks:
                        manager.running_tasks.pop(session_id, None)

            elif action == "run_multi_agent":
                prompt = data.get("prompt", "")
                workspace = data.get("workspace", str(Path.cwd()))
                planner_model = data.get("planner_model")
                coder_model = data.get("coder_model")
                max_workers = data.get("max_workers", 3)

                await manager.send_message(session_id, {
                    "type": "status",
                    "status": "running",
                    "message": "多智能体模式启动中..."
                })

                try:
                    task = asyncio.create_task(
                        _run_multi_agent_stream(session_id, prompt, workspace, planner_model, coder_model, max_workers)
                    )
                    manager.register_task(session_id, task)
                    await task
                except asyncio.CancelledError:
                    await manager.send_message(session_id, {
                        "type": "status",
                        "status": "stopped",
                        "message": "多智能体已停止"
                    })
                except Exception as e:
                    await manager.send_message(session_id, {
                        "type": "error",
                        "message": str(e)
                    })
                finally:
                    if session_id in manager.running_tasks:
                        manager.running_tasks.pop(session_id, None)

            elif action == "stop":
                # 真正取消任务
                manager.cancel_task(session_id)
                await manager.send_message(session_id, {
                    "type": "status",
                    "status": "stopped",
                    "message": "Agent 正在停止..."
                })

    except WebSocketDisconnect:
        manager.disconnect(session_id)


# ============================================================================
# Agent 运行逻辑
# ============================================================================


async def _run_agent_async(session: dict, prompt: str, workspace: str, system_prompt: str = None) -> str:
    """异步运行 Agent"""
    from harness.tools.plugins import register_all_tools

    config = session["config"]
    yaml_config = load_config()

    # 创建组件
    provider_type = config.get("provider_type", "claude")
    
    # API Key 优先级：前端传入 > config.yaml > 环境变量
    api_key = config.get("api_key", "")
    if not api_key:
        # 尝试从 config.yaml 获取
        provider_key = provider_type.replace("-", "_")
        provider_key_dash = provider_type.replace("_", "-")
        provider_config = yaml_config.get("providers", {}).get(provider_key, {}) or \
                         yaml_config.get("providers", {}).get(provider_key_dash, {})
        api_key = provider_config.get("api_key", "")
        if not api_key:
            # 尝试环境变量
            env_vars = {
                "volcengine_plan": "VOLCANO_ENGINE_API_KEY",
                "volcengine-plan": "VOLCANO_ENGINE_API_KEY",
                "doubao": "DOUBAO_API_KEY",
                "claude": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
                "qwen": "DASHSCOPE_API_KEY",
            }
            env_var = env_vars.get(provider_type)
            if env_var:
                api_key = os.environ.get(env_var, "")
    
    # 从 config.yaml 获取 model
    model = config.get("model", "")
    if not model:
        provider_key = provider_type.replace("-", "_")
        provider_key_dash = provider_type.replace("_", "-")
        provider_config = yaml_config.get("providers", {}).get(provider_key, {}) or \
                         yaml_config.get("providers", {}).get(provider_key_dash, {})
        model = provider_config.get("model", "")
    
    provider_kwargs = {
        "provider_type": provider_type,
        "api_key": api_key,
        "model": model,
    }
    
    # 只有 deepseek 和 openai 支持 base_url
    if provider_type in ("deepseek", "openai", "openai_compat"):
        base_url = config.get("base_url") or yaml_config.get("providers", {}).get(provider_type, {}).get("base_url", "")
        if base_url:
            provider_kwargs["base_url"] = base_url
    
    # 只有 claude 支持 model_kwargs
    if provider_type == "claude" and config.get("model_kwargs"):
        provider_kwargs["model_kwargs"] = config["model_kwargs"]
    
    provider = create_provider(**provider_kwargs)

    registry = ToolRegistry()
    register_all_tools(registry, workspace)

    # 可选组件
    cost_tracker = CostTracker()
    tracer = Tracer()
    memory = create_memory_manager(workspace)

    # 创建 MainLoop
    main_loop = MainLoop(
        provider=provider,
        tool_registry=registry,
        cost_tracker=cost_tracker,
        tracer=tracer,
        max_turns=config.get("max_turns", 50),
        system_prompt=system_prompt,
    )

    # 运行
    result = await main_loop.run(prompt)

    # 更新会话
    stats = cost_tracker.get_stats()
    session_manager.update_session(
        session["id"],
        conversation=session["conversation"] + [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": result.content},
        ],
        cost=stats["total_cost"],
        prompt_tokens=stats["total_prompt_tokens"],
        completion_tokens=stats["total_completion_tokens"],
    )

    # 返回可 JSON 序列化的结果
    return {
        "content": result.content,
        "status": result.status.value if hasattr(result.status, 'value') else str(result.status),
        "stats": result.stats.to_dict() if hasattr(result.stats, 'to_dict') else {},
    }


async def _run_agent_stream(session_id: str, prompt: str, workspace: str, system_prompt: str = None):
    """流式运行 Agent - 增强版：支持取消、更丰富的实时反馈"""
    from harness.tools.plugins import register_all_tools

    session = session_manager.get_session(session_id)
    if not session:
        raise ValueError("Session not found")

    config = session["config"]
    yaml_config = load_config()

    # 创建组件
    provider_type = config.get("provider_type", "claude")
    
    # API Key 优先级：前端传入 > config.yaml > 环境变量
    api_key = config.get("api_key", "")
    if not api_key:
        provider_key = provider_type.replace("-", "_")
        provider_key_dash = provider_type.replace("_", "-")
        provider_config = yaml_config.get("providers", {}).get(provider_key, {}) or \
                         yaml_config.get("providers", {}).get(provider_key_dash, {})
        api_key = provider_config.get("api_key", "")
        if not api_key:
            env_vars = {
                "volcengine_plan": "VOLCANO_ENGINE_API_KEY",
                "volcengine-plan": "VOLCANO_ENGINE_API_KEY",
                "doubao": "DOUBAO_API_KEY",
                "claude": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
                "qwen": "DASHSCOPE_API_KEY",
            }
            env_var = env_vars.get(provider_type)
            if env_var:
                api_key = os.environ.get(env_var, "")
    
    # 从 config.yaml 获取 model
    model = config.get("model", "")
    if not model:
        provider_key = provider_type.replace("-", "_")
        provider_key_dash = provider_type.replace("_", "-")
        provider_config = yaml_config.get("providers", {}).get(provider_key, {}) or \
                         yaml_config.get("providers", {}).get(provider_key_dash, {})
        model = provider_config.get("model", "")
    
    provider_kwargs = {
        "provider_type": provider_type,
        "api_key": api_key,
        "model": model,
    }
    
    if provider_type in ("deepseek", "openai", "openai_compat"):
        base_url = config.get("base_url") or yaml_config.get("providers", {}).get(provider_type, {}).get("base_url", "")
        if base_url:
            provider_kwargs["base_url"] = base_url
    
    if provider_type == "claude" and config.get("model_kwargs"):
        provider_kwargs["model_kwargs"] = config["model_kwargs"]
    
    provider = create_provider(**provider_kwargs)

    registry = ToolRegistry()
    register_all_tools(registry, workspace)

    cost_tracker = CostTracker()
    tracer = Tracer()

    main_loop = MainLoop(
        provider=provider,
        tool_registry=registry,
        cost_tracker=cost_tracker,
        tracer=tracer,
        max_turns=config.get("max_turns", 50),
        system_prompt=system_prompt,
    )

    async def safe_send(msg: dict):
        """安全发送消息 - 避免 create_task 时序问题"""
        try:
            await manager.send_message(session_id, msg)
        except Exception as e:
            print(f"[Stream] 发送消息失败: {e}")

    def on_thinking(content: str):
        asyncio.create_task(safe_send({
            "type": "thinking",
            "content": content,
        }))

    def on_tool_call(tool_name: str, arguments: str):
        asyncio.create_task(safe_send({
            "type": "tool_call",
            "tool": tool_name,
            "arguments": arguments,
        }))

    def on_tool_result(tool_name: str, result: str):
        asyncio.create_task(safe_send({
            "type": "tool_result",
            "tool": tool_name,
            "result": result[:800] if len(result) > 800 else result,
        }))

    def on_token_update(prompt_tokens: int, completion_tokens: int, cost: float, total_tokens: int = 0):
        asyncio.create_task(safe_send({
            "type": "token_update",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost": cost,
            "total_tokens": total_tokens,
        }))

    def on_turn_start(turn: int, max_turns: int):
        asyncio.create_task(safe_send({
            "type": "turn_start",
            "turn": turn,
            "max_turns": max_turns,
            "message": f"第 {turn}/{max_turns} 轮推理中..."
        }))

    main_loop.on("thinking", on_thinking)
    main_loop.on("tool_call", on_tool_call)
    main_loop.on("tool_result", on_tool_result)
    main_loop.on("token_update", on_token_update)
    main_loop.on("turn_start", on_turn_start)

    # 发送开始状态
    await safe_send({
        "type": "status",
        "status": "running",
        "message": "Agent 已启动，正在思考..."
    })

    # 运行 - 支持取消
    try:
        result = await main_loop.run(prompt)
    except asyncio.CancelledError:
        await safe_send({
            "type": "status",
            "status": "stopped",
            "message": "Agent 已停止"
        })
        raise

    # 发送最终结果
    stats = cost_tracker.get_stats()
    await safe_send({
        "type": "finished",
        "result": result.content,
        "status": result.status.value if hasattr(result.status, 'value') else str(result.status),
        "stats": stats,
    })

    # 更新会话
    session_manager.update_session(
        session_id,
        conversation=session["conversation"] + [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": result.content},
        ],
        cost=stats["total_cost"],
        prompt_tokens=stats["total_prompt_tokens"],
        completion_tokens=stats["total_completion_tokens"],
    )


async def _run_multi_agent_stream(
    session_id: str,
    prompt: str,
    workspace: str,
    planner_model: str = None,
    coder_model: str = None,
    max_workers: int = 3,
):
    from harness.tools.plugins import register_all_tools

    def roleLabel(role: str) -> str:
        return {
            "orchestrator": "主智能体", "reader": "读取器",
            "searcher": "搜索器", "coder": "编码器",
            "reviewer": "审查器", "debugger": "调试器",
        }.get(role, role)

    session = session_manager.get_session(session_id)
    if not session:
        raise ValueError("Session not found")

    config = session["config"]
    yaml_config = load_config()

    provider_type = config.get("provider_type", "claude")

    api_key = config.get("api_key", "")
    if not api_key:
        provider_key = provider_type.replace("-", "_")
        provider_key_dash = provider_type.replace("_", "-")
        provider_yaml_cfg = yaml_config.get("providers", {}).get(provider_key, {}) or \
                           yaml_config.get("providers", {}).get(provider_key_dash, {})
        api_key = provider_yaml_cfg.get("api_key", "")
        if not api_key:
            env_vars = {
                "volcengine_plan": "VOLCANO_ENGINE_API_KEY",
                "volcengine-plan": "VOLCANO_ENGINE_API_KEY",
                "doubao": "DOUBAO_API_KEY",
                "claude": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
                "qwen": "DASHSCOPE_API_KEY",
            }
            env_var = env_vars.get(provider_type)
            if env_var:
                api_key = os.environ.get(env_var, "")

    model = config.get("model", "")
    if not model:
        provider_key = provider_type.replace("-", "_")
        provider_key_dash = provider_type.replace("_", "-")
        provider_yaml_cfg = yaml_config.get("providers", {}).get(provider_key, {}) or \
                           yaml_config.get("providers", {}).get(provider_key_dash, {})
        model = provider_yaml_cfg.get("model", "")

    # 从 config.yaml 获取正确的 type（区分 provider 名称和 provider 类型）
    provider_key = provider_type.replace("-", "_")
    provider_key_dash = provider_type.replace("_", "-")
    provider_yaml_cfg = yaml_config.get("providers", {}).get(provider_key, {}) or \
                       yaml_config.get("providers", {}).get(provider_key_dash, {})
    provider_type_from_config = provider_yaml_cfg.get("type", provider_type)

    provider_config_dict = {
        "type": provider_type_from_config,
        "api_key": api_key,
        "model": model,
    }

    if provider_type in ("deepseek", "openai", "openai_compat"):
        base_url = config.get("base_url") or yaml_config.get("providers", {}).get(provider_type, {}).get("base_url", "")
        if base_url:
            provider_config_dict["base_url"] = base_url

    async def safe_send(msg: dict):
        try:
            await manager.send_message(session_id, msg)
        except Exception as e:
            print(f"[MultiAgent Stream] 发送消息失败: {e}")

    orchestrator = create_multi_agent(
        provider_config=provider_config_dict,
        workspace=workspace,
        planner_model=planner_model,
        coder_model=coder_model,
        max_concurrent_workers=max_workers,
    )

    original_plan = orchestrator._plan
    original_execute_sequential = orchestrator._execute_sequential
    original_execute_task = orchestrator.worker_pool.execute_task

    async def traced_plan(user_task: str):
        print(f"\n{'='*60}")
        print(f"[Orchestrator] 开始规划任务")
        print(f"[Orchestrator] 用户任务: {user_task[:100]}...")
        await safe_send({"type": "multi_agent", "event": "planning", "message": "主智能体正在规划任务..."})
        
        plan = await original_plan(user_task)
        
        if plan:
            print(f"[Orchestrator] 规划完成")
            print(f"[Orchestrator] 策略: {plan.strategy}")
            print(f"[Orchestrator] 子任务数量: {len(plan.tasks)}")
            print(f"[Orchestrator] {'-'*40}")
            for idx, t in enumerate(plan.tasks, 1):
                print(f"[Orchestrator] 任务 {idx}: [{t.role.value}] {t.description}")
                if t.dependencies:
                    print(f"[Orchestrator]            依赖: {', '.join(t.dependencies)}")
            print(f"[Orchestrator] {'-'*40}")
            
            tasks_info = []
            for t in plan.tasks:
                tasks_info.append({
                    "id": t.id,
                    "role": t.role.value,
                    "description": t.description,
                    "dependencies": t.dependencies,
                })
            await safe_send({
                "type": "multi_agent",
                "event": "plan_ready",
                "strategy": plan.strategy,
                "tasks": tasks_info,
                "message": f"规划完成：{len(plan.tasks)} 个子任务，策略={plan.strategy}",
            })
        return plan

    async def traced_execute_task(task: SubTask) -> SubTask:
        print(f"\n[Worker] 开始执行任务")
        print(f"[Worker] 任务ID: {task.id}")
        print(f"[Worker] 角色: {task.role.value}")
        print(f"[Worker] 描述: {task.description}")
        print(f"[Worker] 分配给: {task.assigned_to}")

        await safe_send({
            "type": "multi_agent",
            "event": "dispatch",
            "task_id": task.id,
            "role": task.role.value,
            "description": task.description,
            "assigned_to": task.assigned_to,
            "message": f"🧠→{roleLabel(task.role.value)} 派发任务: {task.description[:50]}",
        })

        await safe_send({
            "type": "multi_agent",
            "event": "task_start",
            "task_id": task.id,
            "role": task.role.value,
            "description": task.description,
            "assigned_to": task.assigned_to,
            "message": f"子智能体 [{task.role.value}] 开始执行: {task.description[:60]}",
        })

        print(f"[Worker] 正在执行...")
        result_task = await original_execute_task(task)

        event = "task_completed" if result_task.status == TaskStatus.COMPLETED else "task_failed"
        icon = "✅" if result_task.status == TaskStatus.COMPLETED else "❌"

        print(f"[Worker] {'-'*30}")
        print(f"[Worker] 执行结果: {result_task.status.name}")
        print(f"[Worker] Token使用: {result_task.tokens_used}")
        print(f"[Worker] 成本: ${result_task.cost:.4f}")
        print(f"[Worker] 耗时: {result_task.duration_ms/1000:.2f}s")

        if result_task.error:
            print(f"[Worker] 错误: {result_task.error}")
        elif result_task.compressed_result:
            print(f"[Worker] 结果预览: {result_task.compressed_result[:100]}...")
        elif result_task.result:
            print(f"[Worker] 结果预览: {result_task.result[:100]}...")

        await safe_send({
            "type": "multi_agent",
            "event": event,
            "task_id": result_task.id,
            "role": result_task.role.value,
            "assigned_to": result_task.assigned_to,
            "tokens": result_task.tokens_used,
            "cost": result_task.cost,
            "duration_ms": result_task.duration_ms,
            "result_preview": (result_task.compressed_result or result_task.result or "")[:500],
            "error": result_task.error,
            "message": f"{icon} [{result_task.role.value}] 完成: tokens={result_task.tokens_used}",
        })

        return_label = roleLabel(result_task.role.value)
        await safe_send({
            "type": "multi_agent",
            "event": "return",
            "task_id": result_task.id,
            "role": result_task.role.value,
            "success": result_task.status == TaskStatus.COMPLETED,
            "message": f"{return_label}→🧠 返回结果: {'成功' if result_task.status == TaskStatus.COMPLETED else '失败'}",
        })

        return result_task

    orchestrator._plan = traced_plan
    orchestrator.worker_pool.execute_task = traced_execute_task

    await safe_send({
        "type": "multi_agent",
        "event": "started",
        "message": "多智能体协同模式已启动",
        "config": {
            "planner_model": planner_model or model,
            "coder_model": coder_model or model,
            "max_workers": max_workers,
        },
    })

    try:
        print(f"\n[Orchestrator] 开始执行任务...")
        result = await orchestrator.run(prompt)

        print(f"\n{'='*60}")
        print(f"[Orchestrator] 汇总结果")
        print(f"[Orchestrator] 任务状态: {result.status.name}")
        print(f"[Orchestrator] 总Token: {result.total_tokens}")
        print(f"[Orchestrator] 总成本: ${result.total_cost:.4f}")
        print(f"[Orchestrator] 总耗时: {result.total_duration_ms/1000:.2f}s")
        print(f"[Orchestrator] 成功任务: {result.tasks_completed}")
        print(f"[Orchestrator] 失败任务: {result.tasks_failed}")
        print(f"[Orchestrator] 修改文件: {result.files_modified}")
        print(f"[Orchestrator] 创建文件: {result.files_created}")
        print(f"[Orchestrator] {'-'*40}")
        print(f"[Orchestrator] 结果摘要: {result.content[:200]}...")
        print(f"[Orchestrator] {'='*60}")

        # 发送 summarizing 事件
        await safe_send({
            "type": "multi_agent",
            "event": "summarizing",
            "message": "主智能体正在汇总结果...",
        })

        # 确保 result.content 不为空
        if not result.content:
            print("[Orchestrator] 汇总内容为空，使用默认内容")
            result.content = f"任务执行完成: {result.tasks_completed} 成功, {result.tasks_failed} 失败"

        # 发送 completed 事件
        await safe_send({
            "type": "multi_agent",
            "event": "completed",
            "result": {
                "status": result.status.value if hasattr(result.status, 'value') else str(result.status),
                "content": result.content[:3000] if result.content else "",
                "total_tokens": result.total_tokens,
                "total_cost": result.total_cost,
                "total_duration_ms": result.total_duration_ms,
                "tasks_completed": result.tasks_completed,
                "tasks_failed": result.tasks_failed,
                "files_modified": result.files_modified,
                "files_created": result.files_created,
                "task_details": result.task_details,
            },
            "message": f"任务完成: {result.tasks_completed} 成功, {result.tasks_failed} 失败",
        })

        await safe_send({
            "type": "finished",
            "result": result.content or "(无输出)",
            "status": result.status.value if hasattr(result.status, 'value') else str(result.status),
            "stats": {
                "total_cost": result.total_cost,
                "total_prompt_tokens": 0,
                "total_completion_tokens": result.total_tokens,
            },
        })

    except asyncio.CancelledError:
        await safe_send({
            "type": "multi_agent",
            "event": "stopped",
            "message": "多智能体已停止",
        })
        raise
    except Exception as e:
        await safe_send({
            "type": "multi_agent",
            "event": "error",
            "message": f"执行失败: {str(e)}",
        })
        raise


# ============================================================================
# 入口
# ============================================================================


def run_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    """启动服务器"""
    uvicorn.run(
        "web:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run_server(port=port)
