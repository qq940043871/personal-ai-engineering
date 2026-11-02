"""执行器行为测试：正常流 / fallback 降级链 / 失败入待办 / 检查点。全程不依赖外部服务。"""
from __future__ import annotations

import types

import pytest

import ownrag.steps  # noqa: F401  内置步骤注册（不触发外部服务）
from ownrag.core import tasks as taskstore
from ownrag.core import trace
from ownrag.core.db import connect, init_schema
from ownrag.core.pipeline import run_pipeline
from ownrag.core.registry import Step, StepResult, register


@register("t_ok")
class OkStep(Step):
    def run(self, ctx, params) -> StepResult:
        n = ctx.data.get("n", 0) + 1
        return StepResult.ok({"n": n}, calls=n)


@register("t_bad")
class BadStep(Step):
    def run(self, ctx, params) -> StepResult:
        return StepResult.fail("boom", tried=1)


PIPES = {
    "p_ok": {"steps": [{"type": "t_ok"}, {"type": "t_ok"}]},
    "p_fb": {"steps": [{"type": "t_bad", "fallback": [{"type": "t_ok"}]}, {"type": "t_ok"}]},
    "p_fail": {"steps": [{"type": "t_bad"}]},
}
SETTINGS = types.SimpleNamespace(pipelines=PIPES)


@pytest.fixture()
def conn(tmp_path):
    db = tmp_path / "t.db"
    init_schema(db)
    c = connect(db)
    yield c
    c.close()


def _new_task(conn, pipeline):
    trace_id = trace.new_trace_id()
    task_id = taskstore.create_task(conn, "doc1", pipeline, trace_id, kb="kb1")
    return task_id, trace_id


def test_ok_flow(conn):
    task_id, trace_id = _new_task(conn, "p_ok")
    assert run_pipeline(conn, SETTINGS, task_id) == "done"
    task = taskstore.get_task(conn, task_id)
    assert task["status"] == "done"
    steps = trace.by_trace(conn, trace_id)
    assert [s["step"] for s in steps].count("main:t_ok") == 2


def test_fallback_chain(conn):
    task_id, trace_id = _new_task(conn, "p_fb")
    assert run_pipeline(conn, SETTINGS, task_id) == "done"
    tags = [(s["step"], s["status"]) for s in trace.by_trace(conn, trace_id)]
    assert ("main:t_bad", "fail") in tags          # 主步骤失败可见
    assert ("fallback1:t_ok", "ok") in tags        # 降级链接管


def test_fail_goes_to_todo(conn):
    task_id, _ = _new_task(conn, "p_fail")
    assert run_pipeline(conn, SETTINGS, task_id) == "failed"
    task = taskstore.get_task(conn, task_id)
    assert task["status"] == "failed" and "boom" in task["error"]
    todos = taskstore.list_todos(conn, only_open=True)
    assert len(todos) == 1 and "boom" in todos[0]["reason"]   # 绝不静默


def test_resume_after_fail(conn):
    task_id, _ = _new_task(conn, "p_fail")
    assert run_pipeline(conn, SETTINGS, task_id) == "failed"
    # 重试 = 同一入口：仍是失败，但任务与待办状态机正常推进
    assert run_pipeline(conn, SETTINGS, task_id, resume=True) == "failed"
    assert taskstore.get_task(conn, task_id)["status"] == "failed"
