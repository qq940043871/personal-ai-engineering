"""trace：每步一行，任何一次"答案不对"要能在 10 分钟内回答——召回给了什么、模型看到了什么、闸门放过了什么。"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


class Timer:
    """步骤计时：with Timer() as t: ... t.ms"""

    def __enter__(self) -> "Timer":
        self._t0 = time.perf_counter()
        self.ms = 0.0
        return self

    def __exit__(self, *exc) -> None:
        self.ms = round((time.perf_counter() - self._t0) * 1000, 1)


def log(
    conn: sqlite3.Connection,
    trace_id: str,
    step: str,
    status: str,
    ms: float = 0.0,
    doc_id: str | None = None,
    counters: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """落一条步骤 trace。失败也是一条正常记录（同 Harness 报文铁律：错误也回结果）。"""
    conn.execute(
        "INSERT INTO traces(trace_id, doc_id, step, status, ms, counters_json, error) "
        "VALUES (?,?,?,?,?,?,?)",
        (trace_id, doc_id, step, status, ms,
         json.dumps(counters or {}, ensure_ascii=False),
         (str(error)[:500] if error else None)),
    )
    conn.commit()


def by_trace(conn: sqlite3.Connection, trace_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM traces WHERE trace_id=? ORDER BY id", (trace_id,)
    ).fetchall()
