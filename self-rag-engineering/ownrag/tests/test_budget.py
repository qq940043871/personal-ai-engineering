"""上下文预算契约：先算容量再拼装，超出预算丢尾块并上报（不交给模型侧静默截断）。"""
from __future__ import annotations

from ownrag.generate.budget import (
    MIN_CONTEXT_TOKENS,
    block_prompt,
    context_budget,
    fit_candidates,
)
from ownrag.tokens import est_tokens


def _cands(n: int, text: str = "这是一段用来占预算的正文。" * 10) -> list[dict]:
    return [{"chunk_id": f"d1#{i:04d}", "doc_id": "d1", "ordinal": i,
             "rrf": 0.5 / i, "text": text} for i in range(1, n + 1)]


def test_est_tokens_口径():
    assert est_tokens("") == 0
    assert est_tokens("报销口径") == 4          # CJK 一字一 token
    assert est_tokens("abcdefgh") == 2          # 其余 4 字符 1 token


def test_context_budget_为输出留位():
    budget = context_budget(num_ctx=6144, prompt_overhead=300, max_new_tokens=512)
    assert budget == 6144 - 300 - 512 - 64      # SAFETY_TOKENS
    # 配置写错也必须留一块的位置，不能退化成永远拒答
    assert context_budget(num_ctx=100, prompt_overhead=999, max_new_tokens=999) == MIN_CONTEXT_TOKENS


def test_装得下时全保留():
    cands = _cands(3)
    fit = fit_candidates(cands, budget_tokens=100_000)
    assert [c["chunk_id"] for c in fit.blocks] == [c["chunk_id"] for c in cands]
    assert fit.dropped == [] and not fit.truncated
    assert fit.text == "\n\n".join(block_prompt(c) for c in cands)


def test_超预算按序丢尾块并上报():
    cands = _cands(10)
    one = est_tokens(block_prompt(cands[0]))
    fit = fit_candidates(cands, budget_tokens=one * 3 + 4)
    assert 1 <= len(fit.blocks) <= 3
    assert fit.blocks[0]["chunk_id"] == "d1#0001"        # 高分在前，先保
    assert len(fit.dropped) == 10 - len(fit.blocks)      # 丢掉的全部可追溯
    assert fit.tokens <= one * 3 + 4


def test_首块超预算时截断保块头():
    long_text = "政" * 5000
    fit = fit_candidates([{"chunk_id": "d1#0001", "doc_id": "d1", "ordinal": 1,
                          "text": long_text}], budget_tokens=MIN_CONTEXT_TOKENS)
    assert fit.truncated and len(fit.blocks) == 1
    assert fit.tokens <= MIN_CONTEXT_TOKENS
    assert fit.blocks[0]["text"].startswith("政") and len(fit.blocks[0]["text"]) < 5000
    assert fit.blocks[0]["chunk_id"] == "d1#0001"        # 引用编号仍在


def test_空候选():
    fit = fit_candidates([], budget_tokens=1000)
    assert (fit.blocks, fit.text, fit.tokens) == ([], "", 0)
