"""任务表 + 待办表：状态外置（Harness 机制②）、失败入待办（机制④⑤的管道版）。"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

STATUSES = ("pending", "running", "done", "failed")


def create_task(conn: sqlite3.Connection, doc_id: str, pipeline: str, trace_id: str,
                kb: str = "default", state: dict | None = None) -> str:
    task_id = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO tasks(id, doc_id, pipeline, kb, status, trace_id, state_json) "
        "VALUES (?,?,?,?,?,?,?)",
        (task_id, doc_id, pipeline, kb, "pending", trace_id,
         json.dumps(state or {}, ensure_ascii=False)),
    )
    conn.commit()
    return task_id


def get_task(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()


def update_task(conn: sqlite3.Connection, task_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE tasks SET {cols}, updated_at=datetime('now','localtime') WHERE id=?",
                 (*fields.values(), task_id))
    conn.commit()


def checkpoint(conn: sqlite3.Connection, task_id: str, step_name: str, state: dict) -> None:
    """执行器检查点：每步开始前落盘，中断可从这里续跑（状态外置）。"""
    update_task(conn, task_id, current_step=step_name, status="running",
                state_json=json.dumps(state, ensure_ascii=False))


def add_todo(conn: sqlite3.Connection, task_id: str | None, doc_id: str | None,
             reason: str, payload: dict | None = None) -> int:
    """待办表 = 人工队列。解析失败、校验不过、映射待确认，全部进这里，没有静默出口。"""
    cur = conn.execute(
        "INSERT INTO todos(task_id, doc_id, reason, payload_json) VALUES (?,?,?,?)",
        (task_id, doc_id, reason[:300], json.dumps(payload or {}, ensure_ascii=False)),
    )
    conn.commit()
    return cur.lastrowid


def list_tasks(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()


def list_todos(conn: sqlite3.Connection, only_open: bool = True) -> list[sqlite3.Row]:
    q = "SELECT * FROM todos"
    if only_open:
        q += " WHERE status='open'"
    return conn.execute(q + " ORDER BY created_at DESC").fetchall()


def resolve_todo(conn: sqlite3.Connection, todo_id: int) -> bool:
    cur = conn.execute(
        "UPDATE todos SET status='done', resolved_at=datetime('now','localtime') WHERE id=? AND status='open'",
        (todo_id,),
    )
    conn.commit()
    return cur.rowcount > 0
