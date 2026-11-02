"""SQLite 连接与建表（单文件零部署；字段设计按可平迁 PostgreSQL 写）。

表清单（对应 05 文档 §二 观测三记录 + 02 文档 §四中台机制）：
  tasks          任务表：状态机 pending→running→done/failed（步骤检查点在 state_json）
  todos          待办表：一切 fail 的终点是人工队列，绝不静默丢
  traces         步骤 trace：trace_id 串全链路
  chunks         块表（canonical）：正文 + 锚点 + 元数据 + embed 版本
  chunks_fts     FTS5 关键词通道（BM25）
  direct_hits    直击库（L0/L1/L2）
  qa_log         问答日志：评测集扩充 + 直击库 L2 回流原料
  staging_registry  Excel 临时表登记
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    pipeline TEXT NOT NULL,
    kb TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL DEFAULT 'pending',   -- pending|running|done|failed
    current_step TEXT,
    error TEXT,
    state_json TEXT,                          -- 执行器检查点（状态外置，可续跑）
    trace_id TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    doc_id TEXT,
    reason TEXT NOT NULL,
    payload_json TEXT,
    status TEXT NOT NULL DEFAULT 'open',      -- open|done
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    doc_id TEXT,
    step TEXT NOT NULL,
    status TEXT NOT NULL,                     -- ok|fail
    ms REAL,
    counters_json TEXT,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_traces_tid ON traces(trace_id);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    kb TEXT NOT NULL,
    source_type TEXT,
    ordinal INTEGER,
    text TEXT NOT NULL,
    anchors_json TEXT,                        -- 页码 / mm:ss / 行区间（引用粒度在切分层固化）
    meta_json TEXT,
    embed_version TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_kb ON chunks(kb);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, chunk_id UNINDEXED, doc_id UNINDEXED, kb UNINDEXED
);
CREATE TABLE IF NOT EXISTS direct_hits (
    id TEXT PRIMARY KEY,
    kb TEXT NOT NULL,
    level TEXT NOT NULL,                      -- L0|L1|L2
    question TEXT NOT NULL,
    aliases_json TEXT DEFAULT '[]',
    answer TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS qa_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT DEFAULT (datetime('now', 'localtime')),
    app TEXT, question TEXT NOT NULL,
    hit_chunks_json TEXT, answer TEXT,
    feedback TEXT,                            -- 赞/踩+纠错文本（直击库 L2 回流原料）
    trace_id TEXT
);
CREATE TABLE IF NOT EXISTS staging_registry (
    doc_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    sheet TEXT,
    schema_json TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (doc_id, table_name)
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_schema(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(DDL)
        conn.commit()
    finally:
        conn.close()
