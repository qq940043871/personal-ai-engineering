"""端到端 demo：一份文件 → 管道入库 →（可选）提问看检索与生成。

用法（项目根 ownrag/ 下）：
  python scripts/run_demo.py --file 样例.pdf
  python scripts/run_demo.py --file 样例.xlsx --question "A公司的欠款余额"
前置：Ollama 已启动且模型可用（embedding 必须；question 演示还需 chat 模型）。
      MinerU/ASR/chromadb 缺任一组件时按降级链走，失败进待办表——这本身就是演示的一部分。
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ownrag.steps  # noqa: F401  —— import 即注册
from ownrag.api.routes_docs import EXT_PIPELINE
from ownrag.config import get_settings
from ownrag.core import tasks as taskstore
from ownrag.core import trace
from ownrag.core.db import connect, init_schema
from ownrag.core.pipeline import run_pipeline
from ownrag.index.store import read_chunks
from ownrag.retrieve import hybrid


def main() -> int:
    parser = argparse.ArgumentParser(description="ownrag 端到端 demo")
    parser.add_argument("--file", required=True, help="样例文件（pdf/xlsx/csv/mp3/mp4…）")
    parser.add_argument("--kb", default="policy_v1")
    parser.add_argument("--question", default=None, help="入库后提问（演示检索+生成）")
    args = parser.parse_args()

    src = Path(args.file)
    if not src.exists():
        print(f"✗ 文件不存在：{src}")
        return 2
    pipeline = EXT_PIPELINE.get(src.suffix.lower())
    if pipeline is None:
        print(f"✗ 不支持的后缀 {src.suffix}；可选：{sorted(EXT_PIPELINE)}")
        return 2

    settings = get_settings()
    init_schema(settings.db_path)
    conn = connect(settings.db_path)

    doc_id = uuid.uuid4().hex[:12]
    trace_id = trace.new_trace_id()
    dest = settings.files_dir / doc_id / f"source{src.suffix.lower()}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())

    task_id = taskstore.create_task(conn, doc_id, pipeline, trace_id, kb=args.kb,
                                    state={"source_path": str(dest),
                                           "source_meta": {"source_file": src.name}})
    print(f"▶ doc={doc_id} task={task_id} pipeline={pipeline}")

    status = run_pipeline(conn, settings, task_id)
    task = taskstore.get_task(conn, task_id)
    print(f"▶ 任务状态：{status}" + (f"（{task['error']}）" if task["error"] else ""))
    for row in trace.by_trace(conn, trace_id):
        counters = json.loads(row["counters_json"] or "{}")
        print(f"   {row['status']:>4} {row['ms']:>8}ms  {row['step']:<28} {counters or ''}")
    if status != "done":
        print("▶ 失败已入待办表：python -c \"...\" 或 GET /admin/todos 查看；修复后 /docs/tasks/{id}/retry")
        return 1

    if not args.question:
        print(f"▶ 入库完成：doc={doc_id} kb={args.kb}")
        return 0

    result = hybrid.search(conn, settings, args.kb, args.question, top_n=5)
    print(f"\n▶ 问题：{args.question}")
    if result["vector_skipped_reason"]:
        print(f"   [降级] {result['vector_skipped_reason']}")
    chunks = read_chunks(conn, [c["chunk_id"] for c in result["candidates"]])
    for i, c in enumerate(result["candidates"], start=1):
        text = chunks.get(c["chunk_id"], {}).get("text", "")
        print(f"   {i}. rrf={c['rrf']:.4f} channels={[x['channel'] for x in c['channels']]}")
        print(f"      {text[:100].replace(chr(10), ' ')}")

    try:
        from ownrag.generate.ollama_client import chat_stream
        from ownrag.generate.prompts import render
        blocks = "\n\n".join(f"[块{chunks[c['chunk_id']].get('ordinal', i)}] {chunks[c['chunk_id']]['text']}"
                             for i, c in enumerate(result["candidates"], start=1))
        messages = render("policy_strict_v1", question=args.question, context_blocks=blocks)
        print("\n▶ 生成（流式）：")
        for piece in chat_stream(settings, messages):
            print(piece, end="", flush=True)
        print()
    except Exception as exc:
        print(f"\n[生成跳过] {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
