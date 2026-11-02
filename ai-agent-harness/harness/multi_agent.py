"""
Multi-Agent 协同系统 - 主智能体 + 子智能体协同工作

核心设计:
1. 主智能体(Orchestrator): 用廉价模型做任务规划和调度，不下场干活
2. 子智能体(Worker): 按职责分工，只加载必要工具，结果压缩回传
3. Token 节省策略:
   - 模型分层: 规划用便宜模型，编码/审查用强模型
   - 上下文隔离: 子智能体只看到任务相关的上下文
   - 结果压缩: 子智能体结果摘要后回传，不全量传回
   - 工具裁剪: 每个子智能体只加载职责范围内的工具
"""

from __future__ import annotations

import asyncio
import copy
import json
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Optional
from uuid import uuid4

from .provider.base import BaseProvider, LLMResponse, Usage
from .provider.factory import create_provider
from .tools.registry import ToolRegistry
from .tools.plugins import register_all_tools
from .tools.edit import EditTool
from .main_loop import MainLoop, LoopResult, LoopStatus
from .cost_tracker import CostTracker

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════


class AgentRole(Enum):
    ORCHESTRATOR = "orchestrator"
    CODER = "coder"
    READER = "reader"
    REVIEWER = "reviewer"
    SEARCHER = "searcher"
    DEBUGGER = "debugger"


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkerSpec:
    name: str
    role: AgentRole
    model: str
    provider_type: str = ""
    system_prompt: str = ""
    allowed_tools: list[str] | None = None
    max_turns: int = 20
    readonly: bool = False

    @property
    def is_cheap(self) -> bool:
        cheap_models = {
            "doubao-pro-32k", "doubao-lite-32k",
            "deepseek-chat", "gpt-4o-mini",
            "qwen-turbo", "claude-3-haiku-20240307",
            "claude-3-5-haiku-20241022",
        }
        return self.model in cheap_models


@dataclass
class SubTask:
    id: str
    description: str
    assigned_to: str
    role: AgentRole
    context: dict = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    compressed_result: str = ""
    tokens_used: int = 0
    cost: float = 0.0
    duration_ms: float = 0.0
    files_modified: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class OrchestratorPlan:
    tasks: list[SubTask]
    strategy: str = "sequential"
    estimated_tokens: int = 0
    estimated_cost: float = 0.0


@dataclass
class MultiAgentResult:
    status: LoopStatus
    content: str
    total_tokens: int = 0
    total_cost: float = 0.0
    total_duration_ms: float = 0.0
    tasks_completed: int = 0
    tasks_failed: int = 0
    files_modified: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    task_details: list[dict] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# 预置 Worker 规格 - 针对 AI 编程场景优化
# ═══════════════════════════════════════════════════════════


WORKER_PRESETS: dict[str, WorkerSpec] = {
    "coder": WorkerSpec(
        name="coder",
        role=AgentRole.CODER,
        model="",
        system_prompt=(
            "你是一个专业的编码智能体。你的职责是根据任务描述编写或修改代码。\n"
            "规则:\n"
            "- 只修改与任务直接相关的文件\n"
            "- 遵循项目现有代码风格\n"
            "- 修改完成后简要说明改了什么、为什么\n"
            "- 不要做超出任务范围的修改"
        ),
        allowed_tools=["read_file", "write_file", "edit_file", "list_dir", "run_command"],
        max_turns=15,
        readonly=False,
    ),
    "reader": WorkerSpec(
        name="reader",
        role=AgentRole.READER,
        model="",
        system_prompt=(
            "你是一个只读分析智能体。你的职责是阅读和分析代码，回答问题。\n"
            "规则:\n"
            "- 只读取文件，不修改任何文件\n"
            "- 输出简洁的分析结果摘要\n"
            "- 不要输出完整的文件内容，只输出关键发现"
        ),
        allowed_tools=["read_file", "list_dir", "grep", "glob"],
        max_turns=10,
        readonly=True,
    ),
    "reviewer": WorkerSpec(
        name="reviewer",
        role=AgentRole.REVIEWER,
        model="",
        system_prompt=(
            "你是一个代码审查智能体。你的职责是审查代码变更的质量。\n"
            "审查要点:\n"
            "- 代码逻辑正确性\n"
            "- 潜在的 Bug 或安全漏洞\n"
            "- 性能问题\n"
            "- 代码风格一致性\n"
            "- 输出简洁的审查意见，列出需要修改的具体问题"
        ),
        allowed_tools=["read_file", "list_dir", "grep", "glob"],
        max_turns=10,
        readonly=True,
    ),
    "searcher": WorkerSpec(
        name="searcher",
        role=AgentRole.SEARCHER,
        model="",
        system_prompt=(
            "你是一个搜索智能体。你的职责是在项目中搜索特定的代码模式、文件或内容。\n"
            "规则:\n"
            "- 使用搜索工具高效定位目标\n"
            "- 只输出搜索结果摘要，不输出完整文件\n"
            "- 标注文件路径和行号"
        ),
        allowed_tools=["grep", "glob", "list_dir", "read_file"],
        max_turns=8,
        readonly=True,
    ),
    "debugger": WorkerSpec(
        name="debugger",
        role=AgentRole.DEBUGGER,
        model="",
        system_prompt=(
            "你是一个调试智能体。你的职责是定位和修复 Bug。\n"
            "流程:\n"
            "1. 阅读错误信息，理解问题\n"
            "2. 定位相关代码\n"
            "3. 分析根因\n"
            "4. 提出修复方案并实施\n"
            "5. 简要说明修复逻辑"
        ),
        allowed_tools=["read_file", "write_file", "edit_file", "grep", "glob", "list_dir", "run_command"],
        max_turns=15,
        readonly=False,
    ),
}


# ═══════════════════════════════════════════════════════════
# Worker Agent - 子智能体
# ═══════════════════════════════════════════════════════════


class WorkerAgent:
    def __init__(
        self,
        spec: WorkerSpec,
        provider: BaseProvider,
        workspace: str = ".",
        cost_tracker: CostTracker | None = None,
    ):
        self.spec = spec
        self.provider = provider
        self.workspace = workspace
        self.cost_tracker = cost_tracker
        self._running = False

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def role(self) -> AgentRole:
        return self.spec.role

    def stop(self):
        self._running = False

    def _build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        register_all_tools(registry, self.workspace)

        if not self.spec.readonly and "edit_file" not in (
            self.spec.allowed_tools or []
        ):
            edit_tool = EditTool()

            @registry.tool(
                description="精确编辑文件中的特定内容",
                category="filesystem",
            )
            async def edit_file(path: str, old_str: str, new_str: str) -> str:
                return await edit_tool.edit(path, old_str, new_str)

        if self.spec.allowed_tools is not None:
            to_remove = [
                name for name in registry._tools if name not in self.spec.allowed_tools
            ]
            for name in to_remove:
                registry.unregister(name)

        return registry

    async def execute(self, task: SubTask) -> SubTask:
        task.status = TaskStatus.RUNNING
        self._running = True
        start = time.time()

        try:
            registry = self._build_registry()
            system_prompt = self.spec.system_prompt
            if task.context:
                ctx_lines = [f"- {k}: {v}" for k, v in task.context.items() if v]
                if ctx_lines:
                    system_prompt += "\n\n## 任务上下文\n" + "\n".join(ctx_lines)

            loop = MainLoop(
                provider=self.provider,
                tool_registry=registry,
                system_prompt=system_prompt,
                max_turns=self.spec.max_turns,
                cost_tracker=self.cost_tracker,
            )

            result = await loop.run(task.description)

            task.result = result.content or ""
            task.compressed_result = self._compress_result(task.result)
            task.tokens_used = result.stats.total_tokens
            task.status = TaskStatus.COMPLETED if result.is_success() else TaskStatus.FAILED

            if self.cost_tracker:
                task.cost = self.cost_tracker.get_total_cost()

            task.duration_ms = (time.time() - start) * 1000

            self._extract_file_changes(task, result)

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            raise
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error(f"Worker [{self.name}] 执行失败: {e}", exc_info=True)
        finally:
            task.duration_ms = (time.time() - start) * 1000

        return task

    def _compress_result(self, result: str, max_len: int = 2000) -> str:
        if len(result) <= max_len:
            return result

        lines = result.split("\n")
        if len(lines) <= 30:
            return result

        head = lines[:10]
        tail = lines[-5:]
        skipped = len(lines) - 15
        return "\n".join(head) + f"\n\n... [省略 {skipped} 行] ...\n\n" + "\n".join(tail)

    def _extract_file_changes(self, task: SubTask, result: LoopResult) -> None:
        content = task.result.lower()
        for keyword in ("写入", "写入文件", "已写入", "written to"):
            pass

        import re
        write_patterns = [
            r"已写入.*?到\s+`?([^\s`]+\.\w+)`?",
            r"written.*?to\s+`?([^\s`]+\.\w+)`?",
            r"创建文件[:：]\s*`?([^\s`]+\.\w+)`?",
            r"修改文件[:：]\s*`?([^\s`]+\.\w+)`?",
        ]
        for pattern in write_patterns:
            matches = re.findall(pattern, task.result)
            task.files_modified.extend(matches)


# ═══════════════════════════════════════════════════════════
# Worker 池 - 管理子智能体实例
# ═══════════════════════════════════════════════════════════


class WorkerPool:
    def __init__(
        self,
        default_provider_config: dict,
        workspace: str = ".",
        max_concurrent: int = 3,
        model_overrides: dict[str, str] | None = None,
    ):
        self.default_provider_config = default_provider_config
        self.workspace = workspace
        self.max_concurrent = max_concurrent
        self.model_overrides = model_overrides or {}

        self._workers: dict[str, WorkerAgent] = {}
        self._cost_tracker = CostTracker()
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def _resolve_model(self, spec: WorkerSpec) -> str:
        if self.model_overrides.get(spec.name):
            return self.model_overrides[spec.name]
        if spec.model:
            return spec.model

        default_model = self.default_provider_config.get("model", "doubao-pro-32k")
        if spec.role in (AgentRole.CODER, AgentRole.DEBUGGER):
            return default_model
        return default_model

    def _create_provider(self, model: str) -> BaseProvider:
        config = copy.deepcopy(self.default_provider_config)
        config["model"] = model
        config.pop("type", None)
        
        # 自动检测火山引擎 Coding Plan API Key
        # 火山引擎 API Key 格式为 ark-xxx，需要使用 volcengine_plan 或 volcengine-plan provider
        api_key = config.get("api_key", "")
        if api_key.startswith("ark-"):
            # 使用配置中指定的 type，如果未指定则使用默认值
            provider_type = self.default_provider_config.get("type", "volcengine_plan")
        else:
            provider_type = self.default_provider_config.get("type", "doubao")
        
        return create_provider(provider_type, **config)

    def get_worker(self, role: str | AgentRole) -> WorkerAgent:
        if isinstance(role, AgentRole):
            role_name = role.value
        else:
            role_name = role

        spec = WORKER_PRESETS.get(role_name)
        if not spec:
            spec = WorkerSpec(name=role_name, role=AgentRole(role_name), model="")

        key = f"{spec.name}_{uuid4().hex[:6]}"
        model = self._resolve_model(spec)
        provider = self._create_provider(model)

        worker = WorkerAgent(
            spec=spec,
            provider=provider,
            workspace=self.workspace,
            cost_tracker=self._cost_tracker,
        )
        self._workers[key] = worker
        return worker

    async def execute_task(self, task: SubTask) -> SubTask:
        async with self._semaphore:
            worker = self.get_worker(task.role)
            task.assigned_to = worker.name
            logger.info(f"[WorkerPool] 分配任务 {task.id[:8]} -> {worker.name} ({worker.spec.model})")
            return await worker.execute(task)

    async def execute_parallel(self, tasks: list[SubTask]) -> list[SubTask]:
        coros = [self.execute_task(t) for t in tasks]
        return await asyncio.gather(*coros, return_exceptions=False)

    def cancel_all(self):
        for worker in self._workers.values():
            worker.stop()

    def get_stats(self) -> dict:
        return {
            "total_workers": len(self._workers),
            "total_cost": self._cost_tracker.get_total_cost(),
        }


# ═══════════════════════════════════════════════════════════
# Orchestrator - 主智能体（规划 + 调度）
# ═══════════════════════════════════════════════════════════


ORCHESTRATOR_SYSTEM_PROMPT = """\
你是一个 AI 编程任务的规划调度智能体。你不直接编写代码，而是将用户任务分解为子任务并分配给专业子智能体。

## 可用的子智能体

| 子智能体 | 职责 | 何时使用 |
|---------|------|---------|
| reader  | 只读分析代码 | 需要理解现有代码结构、查找定义 |
| searcher | 搜索代码模式 | 需要查找特定模式、TODO、引用 |
| coder   | 编写/修改代码 | 需要实现功能、修改文件 |
| reviewer | 代码审查 | 代码修改后需要质量检查 |
| debugger | 调试修复 | 需要定位和修复 Bug |

## 分解原则

1. **最小化子任务**: 每个子智能体只做一件事
2. **先读后写**: 修改代码前先让 reader/searcher 了解现状
3. **写后审查**: 代码修改后让 reviewer 检查
4. **节省 Token**: 不要让子智能体做超出职责范围的事

## 输出格式

输出一个 JSON 任务计划，格式如下：

```json
{
  "strategy": "sequential|parallel|mixed",
  "tasks": [
    {
      "id": "t1",
      "role": "reader",
      "description": "阅读 main.py 理解项目入口逻辑",
      "context": {"target": "main.py"},
      "depends_on": []
    },
    {
      "id": "t2",
      "role": "coder",
      "description": "在 main.py 中添加 --multi-agent 参数支持",
      "context": {"target": "main.py", "requirement": "添加命令行参数"},
      "depends_on": ["t1"]
    }
  ]
}
```

只输出 JSON，不要输出其他内容。"""

RESULT_SUMMARY_PROMPT = """\
你是任务结果汇总智能体。根据以下子任务的执行结果，生成一份简洁的最终报告。

## 子任务结果

{results}

## 输出要求

1. 简要说明完成了什么
2. 列出修改/创建的文件
3. 如有失败任务，说明原因和影响
4. 不要重复子任务的完整输出，只提炼关键信息"""


class Orchestrator:
    def __init__(
        self,
        planner_provider: BaseProvider,
        worker_pool: WorkerPool,
        workspace: str = ".",
        cost_tracker: CostTracker | None = None,
    ):
        self.planner_provider = planner_provider
        self.worker_pool = worker_pool
        self.workspace = workspace
        self.cost_tracker = cost_tracker or CostTracker()
        self._running = False

    def stop(self):
        self._running = False
        self.worker_pool.cancel_all()

    async def run(self, user_task: str) -> MultiAgentResult:
        start = time.time()
        self._running = True

        try:
            plan = await self._plan(user_task)
            if not plan or not plan.tasks:
                return MultiAgentResult(
                    status=LoopStatus.ERROR,
                    content="规划失败：无法分解任务",
                )

            logger.info(
                f"[Orchestrator] 规划完成: {len(plan.tasks)} 个子任务, "
                f"策略={plan.strategy}"
            )

            task_map = {t.id: t for t in plan.tasks}
            completed: dict[str, SubTask] = {}

            if plan.strategy == "parallel":
                results = await self.worker_pool.execute_parallel(plan.tasks)
                for r in results:
                    completed[r.id] = r
            else:
                completed = await self._execute_sequential(plan.tasks, task_map)

            result = self._aggregate(user_task, completed)

            if self._running and result.tasks_completed > 0:
                summary = await self._summarize(user_task, completed)
                result.content = summary

            result.total_duration_ms = (time.time() - start) * 1000
            return result

        except asyncio.CancelledError:
            return MultiAgentResult(
                status=LoopStatus.STOPPED,
                content="任务已取消",
                total_duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            logger.error(f"[Orchestrator] 执行失败: {e}", exc_info=True)
            return MultiAgentResult(
                status=LoopStatus.ERROR,
                content=f"执行失败: {e}",
                total_duration_ms=(time.time() - start) * 1000,
            )

    async def _plan(self, user_task: str) -> OrchestratorPlan | None:
        planner_loop = MainLoop(
            provider=self.planner_provider,
            tool_registry=ToolRegistry(),
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
            max_turns=1,
            max_tokens_per_turn=4096,
            cost_tracker=self.cost_tracker,
        )

        result = await planner_loop.run(user_task)

        if not result.is_success():
            logger.error(f"[Orchestrator] 规划失败: {result.content}")
            return None

        plan = self._parse_plan(result.content)
        if not plan:
            plan = self._fallback_plan(user_task)
        return plan

    def _parse_plan(self, content: str) -> OrchestratorPlan | None:
        json_str = content.strip()
        if json_str.startswith("```"):
            lines = json_str.split("\n")
            json_str = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            )

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            try:
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(content[start:end])
                else:
                    return None
            except json.JSONDecodeError:
                logger.warning(f"[Orchestrator] JSON 解析失败: {content[:200]}")
                return None

        tasks = []
        for t in data.get("tasks", []):
            role_str = t.get("role", "reader")
            try:
                role = AgentRole(role_str)
            except ValueError:
                role = AgentRole.READER

            tasks.append(SubTask(
                id=t.get("id", f"t_{uuid4().hex[:6]}"),
                description=t.get("description", ""),
                assigned_to="",
                role=role,
                context=t.get("context", {}),
                dependencies=t.get("depends_on", []),
            ))

        return OrchestratorPlan(
            tasks=tasks,
            strategy=data.get("strategy", "sequential"),
        )

    def _fallback_plan(self, user_task: str) -> OrchestratorPlan:
        if any(kw in user_task for kw in ["修复", "Bug", "错误", "调试", "bug", "fix"]):
            tasks = [
                SubTask(
                    id="t1",
                    description=f"搜索和阅读与错误相关的代码: {user_task}",
                    assigned_to="",
                    role=AgentRole.SEARCHER,
                    context={"goal": user_task},
                ),
                SubTask(
                    id="t2",
                    description=f"定位并修复问题: {user_task}",
                    assigned_to="",
                    role=AgentRole.DEBUGGER,
                    context={"goal": user_task},
                    dependencies=["t1"],
                ),
                SubTask(
                    id="t3",
                    description="审查修复的代码，确保无副作用",
                    assigned_to="",
                    role=AgentRole.REVIEWER,
                    dependencies=["t2"],
                ),
            ]
        elif any(kw in user_task for kw in ["实现", "添加", "开发", "创建", "写", "编写"]):
            tasks = [
                SubTask(
                    id="t1",
                    description=f"阅读相关代码，了解现有结构: {user_task}",
                    assigned_to="",
                    role=AgentRole.READER,
                    context={"goal": user_task},
                ),
                SubTask(
                    id="t2",
                    description=f"实现功能: {user_task}",
                    assigned_to="",
                    role=AgentRole.CODER,
                    context={"goal": user_task},
                    dependencies=["t1"],
                ),
                SubTask(
                    id="t3",
                    description="审查新编写的代码",
                    assigned_to="",
                    role=AgentRole.REVIEWER,
                    dependencies=["t2"],
                ),
            ]
        else:
            tasks = [
                SubTask(
                    id="t1",
                    description=f"分析和理解: {user_task}",
                    assigned_to="",
                    role=AgentRole.READER,
                    context={"goal": user_task},
                ),
                SubTask(
                    id="t2",
                    description=f"执行任务: {user_task}",
                    assigned_to="",
                    role=AgentRole.CODER,
                    context={"goal": user_task},
                    dependencies=["t1"],
                ),
            ]

        return OrchestratorPlan(tasks=tasks, strategy="sequential")

    async def _execute_sequential(
        self,
        tasks: list[SubTask],
        task_map: dict[str, SubTask],
    ) -> dict[str, SubTask]:
        completed: dict[str, SubTask] = {}
        remaining = list(tasks)

        max_iterations = len(tasks) * 2
        iteration = 0

        while remaining and iteration < max_iterations:
            iteration += 1
            if not self._running:
                break

            ready = [
                t for t in remaining
                if all(dep in completed for dep in t.dependencies)
            ]

            if not ready:
                logger.warning("[Orchestrator] 无可执行任务，可能存在循环依赖")
                break

            parallel_ready = [t for t in ready if not t.dependencies]
            serial_ready = [t for t in ready if t.dependencies]

            if parallel_ready and len(parallel_ready) > 1:
                results = await self.worker_pool.execute_parallel(parallel_ready)
                for r in results:
                    completed[r.id] = r
                for t in parallel_ready:
                    remaining.remove(t)
            else:
                batch = parallel_ready if parallel_ready else serial_ready[:1]
                for task in batch:
                    if not self._running:
                        break
                    result = await self.worker_pool.execute_task(task)
                    completed[result.id] = result
                    remaining.remove(task)

                    if result.status == TaskStatus.COMPLETED:
                        self._inject_context(task_map, result, completed)

        for t in remaining:
            t.status = TaskStatus.CANCELLED
            completed[t.id] = t

        return completed

    def _inject_context(
        self,
        task_map: dict[str, SubTask],
        completed_task: SubTask,
        all_completed: dict[str, SubTask],
    ):
        summary = completed_task.compressed_result or completed_task.result
        if not summary:
            return

        for tid, task in task_map.items():
            if completed_task.id in task.dependencies and task.status == TaskStatus.PENDING:
                key = f"前置任务[{completed_task.assigned_to}]结果"
                task.context[key] = summary[:800]

    def _aggregate(
        self,
        user_task: str,
        completed: dict[str, SubTask],
    ) -> MultiAgentResult:
        total_tokens = 0
        total_cost = 0.0
        tasks_completed = 0
        tasks_failed = 0
        files_modified = set()
        files_created = set()
        task_details = []

        for task in completed.values():
            total_tokens += task.tokens_used
            total_cost += task.cost
            if task.status == TaskStatus.COMPLETED:
                tasks_completed += 1
            else:
                tasks_failed += 1
            files_modified.update(task.files_modified)
            files_created.update(task.files_created)
            task_details.append({
                "id": task.id,
                "role": task.role.value,
                "assigned_to": task.assigned_to,
                "status": task.status.value,
                "tokens": task.tokens_used,
                "cost": task.cost,
                "duration_ms": task.duration_ms,
                "error": task.error,
            })

        has_failure = tasks_failed > 0 and tasks_completed == 0
        status = LoopStatus.ERROR if has_failure else LoopStatus.COMPLETED

        return MultiAgentResult(
            status=status,
            content="",
            total_tokens=total_tokens,
            total_cost=total_cost,
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
            files_modified=list(files_modified),
            files_created=list(files_created),
            task_details=task_details,
        )

    async def _summarize(
        self,
        user_task: str,
        completed: dict[str, SubTask],
    ) -> str:
        results_text = ""
        for task in completed.values():
            status_icon = "✅" if task.status == TaskStatus.COMPLETED else "❌"
            output = task.compressed_result or task.result or task.error or "(无输出)"
            results_text += f"\n### {status_icon} [{task.role.value}] {task.description}\n"
            results_text += f"Token: {task.tokens_used} | 耗时: {task.duration_ms/1000:.1f}s\n"
            results_text += f"结果:\n{output}\n"

        try:
            summary_loop = MainLoop(
                provider=self.planner_provider,
                tool_registry=ToolRegistry(),
                system_prompt=RESULT_SUMMARY_PROMPT.format(results=results_text),
                max_turns=1,
                max_tokens_per_turn=2048,
                cost_tracker=self.cost_tracker,
            )

            result = await summary_loop.run(
                f"请汇总以下任务的执行结果: {user_task}"
            )
            return result.content if result.is_success() else results_text
        except Exception as e:
            logger.warning(f"[Orchestrator] 汇总阶段失败: {e}")
            return results_text


# ═══════════════════════════════════════════════════════════
# 便捷创建函数
# ═══════════════════════════════════════════════════════════


def create_multi_agent(
    provider_config: dict,
    workspace: str = ".",
    planner_model: str | None = None,
    coder_model: str | None = None,
    max_concurrent_workers: int = 3,
    model_overrides: dict[str, str] | None = None,
) -> Orchestrator:
    config = copy.deepcopy(provider_config)
    overrides = dict(model_overrides or {})

    if planner_model:
        overrides["orchestrator"] = planner_model
    if coder_model:
        overrides["coder"] = coder_model

    # 自动检测火山引擎 Coding Plan API Key
    # 火山引擎 API Key 格式为 ark-xxx，需要使用 volcengine_plan 或 volcengine-plan provider
    api_key = config.get("api_key", "")
    if api_key.startswith("ark-"):
        # 使用配置中指定的 type，如果未指定则使用默认值
        planner_type = config.get("type", "volcengine_plan")
    else:
        planner_type = config.get("type", "doubao")
    planner_cfg = copy.deepcopy(config)
    planner_model_resolved = overrides.get(
        "orchestrator",
        config.get("model", "doubao-pro-32k"),
    )
    planner_cfg["model"] = planner_model_resolved
    planner_cfg.pop("type", None)
    planner_provider = create_provider(planner_type, **planner_cfg)

    worker_pool = WorkerPool(
        default_provider_config=config,
        workspace=workspace,
        max_concurrent=max_concurrent_workers,
        model_overrides=overrides,
    )

    cost_tracker = CostTracker()

    return Orchestrator(
        planner_provider=planner_provider,
        worker_pool=worker_pool,
        workspace=workspace,
        cost_tracker=cost_tracker,
    )
