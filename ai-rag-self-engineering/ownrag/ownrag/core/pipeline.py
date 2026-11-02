"""管道执行器：按 DSL 串行执行步骤，带 fallback 降级链、检查点续跑、失败入待办。

承接 Harness 六机制（02 文档 §五）：
  ① 终止闸门  —— 接入管道是线性有限步骤，天然有界
  ② 状态外置  —— 每步 checkpoint 到任务表，中断可续跑
  ④ 失败补偿  —— 步骤级 fallback 降级链 + 任务级失败入待办
  ⑥ 评测观测  —— 每步 trace 落表
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ownrag.core import tasks as taskstore
from ownrag.core import trace
from ownrag.core.registry import STEP_REGISTRY, Step, StepResult


@dataclass
class StepContext:
    doc_id: str
    trace_id: str
    kb: str
    conn: sqlite3.Connection
    settings: Any                                  # ownrag.config.Settings
    data: dict = field(default_factory=dict)       # 步骤间黑板（state 外置的内存态）


def run_pipeline(conn: sqlite3.Connection, settings: Any, task_id: str,
                 resume: bool = False) -> str:
    """执行一条任务。返回最终状态：done | failed。

    resume=True 时从任务表检查点续跑（重试 = 同一入口，幂等键 doc_id+step）。
    """
    task = taskstore.get_task(conn, task_id)
    if task is None:
        raise KeyError(f"任务不存在：{task_id}")

    pipeline_name = task["pipeline"]
    spec = settings.pipelines.get(pipeline_name)
    if spec is None:
        return _fail(conn, task_id, f"管道未定义：{pipeline_name}")

    steps: list[dict] = spec.get("steps", [])
    ctx = StepContext(doc_id=task["doc_id"], trace_id=task["trace_id"] or trace.new_trace_id(),
                      kb=task["kb"] or spec.get("kb", "default"), conn=conn, settings=settings)

    start = 0
    if task["state_json"]:  # 初始 state（如 source_path）与检查点统一从任务表恢复（状态外置）
        try:
            ctx.data = json.loads(task["state_json"])
        except Exception:
            ctx.data = {}
    if resume and task["current_step"]:
        start = next((i for i, s in enumerate(steps) if s.get("type") == task["current_step"]), 0)
        # 检查点坏了就从头来：源文件还在，重跑安全（按 doc_id 原子替换索引）

    taskstore.update_task(conn, task_id, status="running")

    for i, step_spec in enumerate(steps):
        if i < start:
            continue
        step_name = step_spec.get("type", f"step{i}")
        taskstore.checkpoint(conn, task_id, step_name, ctx.data)

        result = _run_with_fallbacks(step_spec, ctx)
        if result.status != "ok":
            reason = f"[{pipeline_name}/{step_name}] {result.error}"
            taskstore.add_todo(conn, task_id, ctx.doc_id, reason,
                               {"metrics": result.metrics, "trace_id": ctx.trace_id})
            return _fail(conn, task_id, reason)
        ctx.data.update(result.data)

    taskstore.update_task(conn, task_id, status="done", current_step=None, error=None)
    trace.log(conn, ctx.trace_id, "pipeline", "ok", doc_id=ctx.doc_id,
              counters={"pipeline": pipeline_name, "steps": len(steps)})
    return "done"


def _run_with_fallbacks(step_spec: dict, ctx: StepContext) -> StepResult:
    """主步骤失败后按序尝试 fallback 链（02 文档 §1.3：能表达串行/降级，不表达复杂图）。"""
    attempts = [step_spec] + list(step_spec.get("fallback") or [])
    last: StepResult | None = None
    for idx, attempt in enumerate(attempts):
        result = _invoke(attempt, ctx, attempt_tag="main" if idx == 0 else f"fallback{idx}")
        if result.status == "ok":
            return result
        last = result
    return last or StepResult.fail("空步骤定义")


def _invoke(step_spec: dict, ctx: StepContext, attempt_tag: str) -> StepResult:
    step_type = step_spec.get("type")
    cls = STEP_REGISTRY.get(step_type)
    if cls is None:
        return StepResult.fail(f"步骤类型未注册：{step_type}")

    step: Step = cls()
    params = dict(step_spec.get("params") or {})
    with trace.Timer() as t:
        try:
            result = step.run(ctx, params)
        except Exception as exc:  # 步骤内未捕获异常 = 一次失败，不是执行器崩溃
            result = StepResult.fail(f"{type(exc).__name__}: {exc}")

    trace.log(ctx.conn, ctx.trace_id, f"{attempt_tag}:{step_type}", result.status,
              ms=t.ms, doc_id=ctx.doc_id, counters=result.metrics, error=result.error)
    return result


def _fail(conn: sqlite3.Connection, task_id: str, error: str) -> str:
    taskstore.update_task(conn, task_id, status="failed", error=error[:500])
    return "failed"
