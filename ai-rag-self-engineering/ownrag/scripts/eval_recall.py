"""召回测试（05 文档 §一）：固定问答集 → 检索链路 → 命中率报告。

用法（项目根 ownrag/ 下）：
  python scripts/eval_recall.py --qa data/eval/qa.example.jsonl --kb policy_v1
判中口径：expect 关键词任一出现在召回块正文，或 expect 以 chunk_id 形式直接命中。
纪律：切分参数 / embedding 模型 / 解析器版本——任何变更先跑本脚本再合入。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ownrag.steps  # noqa: F401
from ownrag.config import get_settings
from ownrag.core.db import connect
from ownrag.retrieve import hybrid


def main() -> int:
    parser = argparse.ArgumentParser(description="ownrag 召回测试")
    parser.add_argument("--qa", default="data/eval/qa.example.jsonl")
    parser.add_argument("--kb", default="policy_v1")
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()

    qa_path = Path(args.qa)
    if not qa_path.exists():
        print(f"✗ 问答集不存在：{qa_path}")
        return 2
    cases = [json.loads(line) for line in
             qa_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    settings = get_settings()
    conn = connect(settings.db_path)
    total, hits, misses = len(cases), 0, []
    t0 = time.perf_counter()

    for case in cases:
        question = case["question"]
        expect = case.get("expect", [])
        result = hybrid.search(conn, settings, case.get("kb", args.kb),
                               question, top_n=args.top_n)
        chunks = {c["chunk_id"]: c for c in
                  [dict(row) for row in _rows(conn, [c["chunk_id"] for c in result["candidates"]])]}
        hit = False
        for cand in result["candidates"]:
            chunk = chunks.get(cand["chunk_id"])
            if chunk is None:
                continue
            text = chunk["text"]
            if cand["chunk_id"] in expect or any(kw.lower() in text.lower() for kw in expect):
                hit = True
                break
        if hit:
            hits += 1
        else:
            misses.append({"question": question, "expect": expect,
                           "got": [(c["chunk_id"], (chunks.get(c["chunk_id"], {}).get("text", ""))[:60])
                                   for c in result["candidates"][:3]]})

    elapsed = time.perf_counter() - t0
    report = {"total": total, "hits": hits,
              "hit_rate": round(hits / total, 4) if total else 0.0,
              "vector": "on" if not misses else _probe_vector(settings),
              "elapsed_sec": round(elapsed, 2)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if misses:
        print("\n失配题（人工归因：切分 / embedding 适配 / 缺关键词 / top-k）：")
        for m in misses:
            print(f"  Q: {m['question']}  expect={m['expect']}")
            for cid, preview in m["got"]:
                print(f"    got {cid}: {preview}")
    return 0 if total == 0 or hits else 1


def _rows(conn, ids: list[str]):
    from ownrag.index.store import read_chunks
    mapped = read_chunks(conn, ids)
    return [{"chunk_id": k, **v} for k, v in mapped.items()]


def _probe_vector(settings) -> str:
    try:
        import chromadb  # noqa: F401
        return "on"
    except ImportError:
        return "off（chromadb 未安装，BM25 单路）"


if __name__ == "__main__":
    raise SystemExit(main())
