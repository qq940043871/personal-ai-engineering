"""召回测试（05 文档 §一）：固定问答集 → 检索链路 → 命中率报告。

用法（项目根 ownrag/ 下）：
  python scripts/eval_recall.py --qa data/eval/qa.example.jsonl --kb policy_v1

判中口径（每题三选一，题型互补对应"找对 / 找全 / 该拒答的拒答"）：
  expect       任一关键词出现在召回块正文（或 chunk_id 直接命中）——找对
  expect_all   全部关键词出现在召回正文合集——找全（证据够不够）
  expect_empty 资料里没有答案的题：与生产拒答同路径判定（检索 → 重排 → 闸门一）——
               向量通道开启后检索层永远捞得回语义邻近块，拒答语义从「零召回」迁移到「重排分不足」
门禁：全部判中退出码 0，否则 1（切分 / embedding / 解析器任何变更先跑本脚本再合入）。
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
from ownrag.generate import gates
from ownrag.retrieve import hybrid
from ownrag.retrieve import rerank as rerank_mod


def judge(case: dict, candidates: list[dict], texts: dict[str, str]) -> bool:
    """单题判中（answerable 题）。texts: chunk_id -> 块正文（候选池内的）。
    口径二选一（格式契约保证）：expect 任一命中 / expect_all 全部要件；
    expect_empty 由闸门一判（与生产拒答同一路径，见 main 循环）。"""
    if case.get("expect_all"):
        joined = "\n".join(texts.values()).lower()
        return all(k.lower() in joined for k in case["expect_all"])
    expect = case.get("expect") or []
    return any(c["chunk_id"] in expect
               or any(kw.lower() in texts.get(c["chunk_id"], "").lower() for kw in expect)
               for c in candidates)


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
    refusal = {"cases": 0, "refused": 0}
    t0 = time.perf_counter()

    for case in cases:
        question = case["question"]
        result = hybrid.search(conn, settings, case.get("kb", args.kb),
                               question, top_n=args.top_n)
        # 与生产同一路径：检索 → 重排 → 闸门一（向量通道永远捞得回语义邻近块，拒答以重排分判）
        candidates, _note = rerank_mod.rerank(settings, question,
                                              result["candidates"], top_n=args.top_n)
        gate = gates.sufficiency_check(candidates)
        chunks = {c["chunk_id"]: c for c in
                  [dict(row) for row in _rows(conn, [c["chunk_id"] for c in candidates])]}
        texts = {cid: c.get("text", "") for cid, c in chunks.items()}
        if case.get("expect_empty"):
            refusal["cases"] += 1
            refusal["refused"] += int(not gate.passed)
        judged_ok = (not gate.passed) if case.get("expect_empty") else judge(case, candidates, texts)
        if judged_ok:
            hits += 1
        else:
            misses.append({"question": question, "expect": case.get("expect"),
                           "expect_all": case.get("expect_all"),
                           "expect_empty": case.get("expect_empty", False),
                           "got": [(c["chunk_id"], (chunks.get(c["chunk_id"], {}).get("text", ""))[:60])
                                   for c in candidates[:3]]})

    elapsed = time.perf_counter() - t0
    report = {"total": total, "hits": hits,
              "hit_rate": round(hits / total, 4) if total else 0.0,
              "refusal": refusal,
              "vector": "on" if not misses else _probe_vector(settings),
              "rerank": f"on（{settings.rerank_provider}）" if settings.rerank_provider else "off",
              "elapsed_sec": round(elapsed, 2)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if misses:
        print("\n失配题（人工归因：切分 / embedding 适配 / 缺关键词 / top-k / 拒答门槛）：")
        for m in misses:
            print(f"  Q: {m['question']}  expect={m['expect']} expect_all={m['expect_all']} "
                  f"expect_empty={m['expect_empty']}")
            for cid, preview in m["got"]:
                print(f"    got {cid}: {preview}")
    return 0 if total and hits == total else 1


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
