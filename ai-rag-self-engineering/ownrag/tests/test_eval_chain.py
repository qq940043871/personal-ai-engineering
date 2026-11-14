"""评测链路离线回归：qa.example.jsonl 格式契约 + 判中口径 + 评测脚本端到端（BM25 单路）。

对应评测三问（吴师兄《视频 RAG 怎么做》——找对 / 找全 / 该拒答的拒答）：
- expect（任一关键词）= 找对；
- expect_all（全部要件）= 找全（证据够不够）；
- expect_empty（无答案题）= 该拒答的拒答（检索层一无所获才算过）。
指标数值一律【待实测】——本测试只锁口径与资产可用性，不锁命中率数字。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import ownrag.steps  # noqa: F401  注册内置步骤
from ownrag.config import get_settings, reset_settings_cache
from ownrag.core.db import connect, init_schema
from ownrag.core.pipeline import StepContext
from ownrag.generate.gates import sufficiency_check
from ownrag.index.chunker import chunk_markdown
from ownrag.index.embedder import EmbedError
from ownrag.index.store import IndexUpsert

ROOT = Path(__file__).resolve().parents[1]
QA_PATH = ROOT / "data" / "eval" / "qa.example.jsonl"
CORPUS_PATH = ROOT / "data" / "eval" / "corpus_policy_example.md"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """离线确定性环境：Ollama 打桩为不可用（EmbedError）→ 混合检索走 BM25 单路。
    本机即便跑着 Ollama 也不影响判中口径验证。"""
    monkeypatch.setenv("OWNRAG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("ownrag.index.embedder.embed_query",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            EmbedError("测试桩：Ollama 不可用（BM25 单路）")))
    reset_settings_cache()
    settings = get_settings()
    init_schema(settings.db_path)
    conn = connect(settings.db_path)
    md = CORPUS_PATH.read_text(encoding="utf-8")
    chunks = chunk_markdown(md, doc_id="eval-corpus", kb="policy_v1", source_type="pdf",
                            base_meta={"source_file": "员工制度手册（示例语料）.md"},
                            max_tokens=120)   # 小语料用小块径：让各小节独立成块，找全口径才有意义
    ctx = StepContext(doc_id="eval-corpus", trace_id="t", kb="policy_v1",
                      conn=conn, settings=settings)
    ctx.data["chunks"] = [c.__dict__ | {"anchors": c.anchors, "meta": c.meta} for c in chunks]
    result = IndexUpsert().run(ctx, {"replace_by_doc": True})
    assert result.status == "ok", result.error
    yield conn, settings
    conn.close()
    reset_settings_cache()


def _cases() -> list[dict]:
    cases = [json.loads(line) for line in
             QA_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert cases, "评测集不能为空"
    return cases


def test_qa_dataset_format_contract():
    """每题判中口径三选一且唯一——口径含糊的评测题不许进集。"""
    for case in _cases():
        assert case.get("question", "").strip(), f"问题为空：{case}"
        kinds = sum(bool(case.get(k)) for k in ("expect", "expect_all", "expect_empty"))
        assert kinds == 1, f"判中口径必须三选一：{case['question']}"
        for key in ("expect", "expect_all"):
            for kw in case.get(key) or []:
                assert kw.strip(), f"空关键词：{case['question']}"


def _search(env, question):
    conn, settings = env
    from ownrag.retrieve import hybrid
    return hybrid.search(conn, settings, "policy_v1", question, top_n=10)


def _candidate_texts(env, result) -> dict[str, str]:
    conn, _ = env
    from ownrag.index.store import read_chunks
    mapped = read_chunks(conn, [c["chunk_id"] for c in result["candidates"]])
    return {cid: c["text"] for cid, c in mapped.items()}


def test_answerable_questions_hit(env):
    """找对/找全：有答案的题必须召回，且召回池过闸门一（有依据才进模型）。"""
    from scripts.eval_recall import judge
    checked = 0
    for case in _cases():
        if case.get("expect_empty"):
            continue
        result = _search(env, case["question"])
        texts = _candidate_texts(env, result)
        assert judge(case, result["candidates"], texts), \
            f"未召回：{case['question']}\n got={[c['chunk_id'] for c in result['candidates']]}"
        assert sufficiency_check(result["candidates"]).passed
        checked += 1
    assert checked >= 5, f"有答案题太少（{checked}），评测集覆盖不足"


def test_unanswerable_questions_refused(env):
    """该拒答的拒答：语料里没有的内容必须被闸门一拦下——
    捞到了就会进模型，被包装成看似合理的答案。
    口径与生产同路径（检索 → 重排 → sufficiency_check）：BM25 单路下靠零召回/低融合分，
    向量通道开启后靠重排分下限（gates._MIN_RERANK_SCORE，随评测集校准）。"""
    for case in _cases():
        if not case.get("expect_empty"):
            continue
        result = _search(env, case["question"])
        assert not sufficiency_check(result["candidates"]).passed, \
            f"无答案题未被闸门拒答（拒答门槛失效）：{case['question']}"


def test_eval_script_end_to_end(env, monkeypatch, capsys):
    """评测脚本端到端：语料已灌 → 全部判中 → 退出码 0；报告含拒答口径。"""
    from scripts import eval_recall
    monkeypatch.setattr(sys, "argv",
                        ["eval_recall.py", "--qa", str(QA_PATH), "--kb", "policy_v1"])
    assert eval_recall.main() == 0
    report = json.loads(capsys.readouterr().out.split("\n\n")[0])
    assert report["hits"] == report["total"] and report["total"] >= 8
    assert report["refusal"]["cases"] == 2 and report["refusal"]["refused"] == 2


def test_eval_script_fails_on_missing_qa_file(monkeypatch):
    """评测资产缺失必须显式失败（退出码 2）——不能静默按空集通过。"""
    from scripts import eval_recall
    monkeypatch.setattr(sys, "argv", ["eval_recall.py", "--qa", "no_such_file.jsonl"])
    assert eval_recall.main() == 2
