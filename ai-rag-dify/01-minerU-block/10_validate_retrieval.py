# -*- coding: utf-8 -*-
"""C 层：向量化 / 检索准确性校验（Recall@k / Precision@k / MRR / nDCG@k）。

为什么需要：
    09_quality_gate.py 的 A 层（解析保真）与 B 层（分片合法）只保证
    「喂给 embedding 的文本是对的、切的单元是对的」。但向量化本身是否把
    语义存对了、检索时能否命中正确片段，最终只能靠「问它问题、看它命没命中」
    来验证——这就是本脚本做的 C 层，是判断「向量化内容是否准确」的终局判据。

原理：
    构造黄金测试集 {query -> 期望命中的片段}，逐条调 Dify 检索接口，
    看 top-k 结果里命中哪些黄金片段，汇总成 Recall@k / Precision@k / MRR / nDCG@k。

    三个问题缺一不可：
        召回全不全   → Recall@k     正确片段有没有被召回来
        召回干不干净 → Precision@k  召回来的片段是不是都相关（需标多个相关片段才有意义）
        排对不对     → MRR / nDCG@k 最相关的有没有排最前

黄金集格式（JSONL，每行一条，UTF-8）：
    单相关（旧格式，向后兼容）：
        {"query": "制定本细则的依据是什么？", "expected_id": "segment-uuid", "expected_anchor": "制定目的"}
    多相关（推荐，用于算 Precision@k）：
        {"query": "结算周期与违约金分别怎么约定？",
         "relevant": [{"anchor": "结算周期"}, {"anchor": "违约金", "id": "seg-xxx"}]}

    字段说明：
    - expected_id / expected_anchor：单相关；id 精确匹配 records[].segment.id，
      anchor 包含匹配 records[].segment.content（子串）。
    - relevant：多相关片段数组；每项 {"id": ..., "anchor": ...} 或直接写子串 "xxx"。
      一条 query 可标多个相关片段，用于算 Precision@k；只标 1 个时 Precision 退化为 Recall 的缩放。

用法：
    python 10_validate_retrieval.py --golden golden.jsonl --dataset-id <id> --api-key <key>
    python 10_validate_retrieval.py --golden golden.jsonl --dataset-id <id> --api-key <key> \
        --base-url http://10.17.1.134:30001 --top-k 8 --report recall.md

指标阈值（默认，可覆盖）：
    Recall@top_k  >= 0.85   主指标
    Precision@k   >= 0.60   召回噪声（仅当黄金集标了多相关片段时才可信）
    MRR           >= 0.70   第一个正确片段平均排第几
    nDCG@5        >= 0.75   排序质量
退出码：0 = 全部达标；1 = 存在不达标项。
依赖：requests。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path


# ------------------------------------------------------------------ 检索
def retrieve(base_url: str, api_key: str, dataset_id: str, query: str, top_k: int) -> list[dict]:
    """调 Dify 检索接口，返回命中的片段列表 [{id, content, score, position}]。

    优先用 hit-testing（官方命中测试接口）；兼容 retrieve 接口的返回结构。
    """
    url = f"{base_url.rstrip('/')}/v1/datasets/{dataset_id}/hit-testing"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "query": query,
        "retrieval_model": {
            "search_method": "hybrid_search",
            "reranking_enable": True,
            "reranking_mode": "reranking_model",
            "reranking_model": {
                "reranking_provider_name": "langgenius/gpustack/gpustack",
                "reranking_model_name": "bge-reranker-v2-m3",
            },
            "top_k": top_k,
            "score_threshold_enabled": False,
        },
    }

    import requests

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    records = data.get("records") or data.get("result") or []
    out: list[dict] = []
    for r in records:
        seg = r.get("segment") or r.get("content") or {}
        if isinstance(seg, str):
            seg = {"content": seg}
        out.append(
            {
                "id": seg.get("id", ""),
                "content": seg.get("content", ""),
                "score": r.get("score"),
                "position": seg.get("position"),
            }
        )
    return out


# ------------------------------------------------------------------ 黄金集解析与匹配
def parse_expected(c: dict) -> list[tuple[str | None, str | None]]:
    """把一条黄金集条目解析成相关片段列表 [(id, anchor), ...]。"""
    rel = c.get("relevant")
    if isinstance(rel, list) and rel:
        out = []
        for r in rel:
            if isinstance(r, str):
                out.append((None, r))
            elif isinstance(r, dict):
                out.append((r.get("id"), r.get("anchor")))
        return [x for x in out if x and (x[0] or x[1])]
    eid = c.get("expected_id")
    anchor = c.get("expected_anchor")
    return [(eid, anchor)] if (eid or anchor) else []


def hit_indices(record: dict, expecteds: list[tuple[str | None, str | None]]) -> set[int]:
    """返回 record 命中的相关片段下标集合（同一条 record 可命中多个相关片段）。"""
    hits = set()
    for idx, (eid, anchor) in enumerate(expecteds):
        if eid and record["id"] == eid:
            hits.add(idx)
        elif anchor and anchor in record["content"]:
            hits.add(idx)
    return hits


def ndcg(hits: list[int], k: int) -> float:
    """hits: 0/1 相关度序列（已按检索顺序）。理想排序是 1 都在前，故 idcg = 前 k 个 1 的折损累加。"""
    k = min(k, len(hits))
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(hits[:k]))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, sum(hits))))
    return dcg / ideal if ideal > 0 else 0.0


# ------------------------------------------------------------------ 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="C 层：向量化/检索准确性校验（Recall/Precision/MRR/nDCG）")
    ap.add_argument("--golden", required=True, help="黄金测试集 JSONL 路径")
    ap.add_argument("--dataset-id", required=True, help="Dify 知识库 ID")
    ap.add_argument("--api-key", required=True, help="Dify API Key（dataset-...）")
    ap.add_argument("--base-url", default="http://10.17.1.134:30001", help="Dify 服务地址")
    ap.add_argument("--top-k", type=int, default=8, help="检索 top_k，与知识库配置一致")
    ap.add_argument("--report", default="quality_report_recall.md", help="报告输出路径")
    ap.add_argument("--recall-min", type=float, default=0.85, help="Recall@top_k 达标线")
    ap.add_argument("--precision-min", type=float, default=0.60, help="Precision@k 达标线")
    ap.add_argument("--mrr-min", type=float, default=0.70, help="MRR 达标线")
    ap.add_argument("--ndcg-min", type=float, default=0.75, help="nDCG@5 达标线")
    args = ap.parse_args()

    golden_path = Path(args.golden)
    if not golden_path.is_file():
        sys.exit(f"黄金集不存在：{golden_path}")

    # 读取黄金集
    cases = []
    with golden_path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                c = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[跳过] 第 {line_no} 行 JSON 解析失败：{e}")
                continue
            if not c.get("query"):
                print(f"[跳过] 第 {line_no} 行缺少 query")
                continue
            c["_expecteds"] = parse_expected(c)
            if not c["_expecteds"]:
                print(f"[跳过] 第 {line_no} 行缺少 expected_id/expected_anchor/relevant")
                continue
            cases.append(c)

    if not cases:
        sys.exit("黄金集为空，无法校验")

    print(f"黄金集共 {len(cases)} 条，开始逐条检索（top_k={args.top_k}）...\n")

    # 每条 query 只检索一次，复用结果算全部指标
    rows = []
    recall_vals, precision_vals, mrr_vals, ndcg_vals = [], [], [], []
    for i, c in enumerate(cases, 1):
        try:
            recs = retrieve(args.base_url, args.api_key, args.dataset_id, c["query"], args.top_k)
        except Exception as e:
            print(f"[{i}/{len(cases)}] 检索异常：{e}")
            recs = []

        expecteds = c["_expecteds"]
        hit_seq = []       # 每条返回是否命中任一相关片段（0/1，按检索顺序）
        matched = set()    # 命中的「唯一相关片段」下标集合
        for r in recs:
            h = hit_indices(r, expecteds)
            hit_seq.append(1 if h else 0)
            matched |= h

        hit_pos = hit_seq.index(1) + 1 if 1 in hit_seq else None  # 1-based 首个命中位置
        recall_hit = bool(matched)
        precision_k = len(matched) / args.top_k if recs else 0.0

        recall_vals.append(1 if recall_hit else 0)
        precision_vals.append(precision_k)
        if hit_pos:
            mrr_vals.append(1.0 / hit_pos)
        ndcg_vals.append(ndcg(hit_seq, 5))

        rows.append(
            {
                "query": c["query"],
                "expected": [e[1] or e[0] for e in expecteds],
                "top_scores": [round(r["score"], 4) for r in recs[:3] if r["score"] is not None],
                "hit": recall_hit,
                "rank": hit_pos,
                "precision": precision_k,
            }
        )
        mark = f"命中@#{hit_pos}" if hit_pos else "未命中"
        print(f"[{i}/{len(cases)}] {mark:<10} {c['query'][:40]}")

    n = len(rows)
    recall = sum(recall_vals) / n
    precision = sum(precision_vals) / n
    mrr = sum(mrr_vals) / n
    ndcg5 = sum(ndcg_vals) / n

    def grade(v, lo):
        return "PASS" if v >= lo else "FAIL"

    metrics = [
        ("Recall@k", recall, args.recall_min, f"top_k={args.top_k}，正确片段有没有召回来"),
        ("Precision@k", precision, args.precision_min, "召回来的是不是都相关（需标多相关片段）"),
        ("MRR", mrr, args.mrr_min, "第一个正确片段平均排位倒数"),
        ("nDCG@5", ndcg5, args.ndcg_min, "排序质量（理想排序为 1）"),
    ]

    print("\n=== C 层：向量化/检索准确性 ===")
    print(f"{'指标':<12}{'实测':<10}{'达标线':<10}判定")
    print("-" * 46)
    code = 0
    for name, val, lo, note in metrics:
        g = grade(val, lo)
        print(f"{name:<12}{val:<10.3f}{lo:<10.3f}{g}")
        if g == "FAIL":
            code = 1

    # 输出报告
    lines = [
        "# 质量门禁报告 — C 层 向量化/检索准确性",
        "",
        f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- dataset_id：`{args.dataset_id}`",
        f"- top_k：`{args.top_k}`",
        f"- 黄金集：`{golden_path}`（{n} 条）",
        "",
        "| 指标 | 实测 | 达标线 | 判定 |",
        "|------|------|--------|------|",
    ]
    for name, val, lo, note in metrics:
        lines.append(f"| {name} | {val:.3f} | {lo:.3f} | {grade(val, lo)} |")
    lines += ["", "## 逐条明细", "", "| # | 问题 | 命中 | 排位 | 精确率 | top3 score |",
              "|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        rank = f"#{r['rank']}" if r["rank"] else "—"
        lines.append(
            f"| {i} | {r['query'][:50]} | {'✓' if r['hit'] else '✗'} | {rank} | "
            f"{r['precision']:.2f} | {r['top_scores']} |"
        )
    Path(args.report).write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告：{Path(args.report).resolve()}")
    print(f"汇总：{'达标' if code == 0 else '不达标'}（Recall@k={recall:.3f} / Precision@k={precision:.3f}）")
    return code


if __name__ == "__main__":
    sys.exit(main())
