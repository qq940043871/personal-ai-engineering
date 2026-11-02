"""上下文预算（04 文档 §五 生成层）：先算容量再拼装，不把截断权交给模型侧。

背景：`num_ctx` 是输入+输出的总窗口，超窗时 Ollama 静默截断——若把 top_n 个候选原样拼进去，
最坏情况先被截掉的是问题本身。这里把预算显式化：

    上下文容量 = num_ctx - prompt 固定开销（system+模板+问题） - 输出预留(max_new_tokens) - 安全余量

超出部分按候选顺序丢弃（保留高分在前），丢弃与截断都通过 SSE 事件上报，属"降级可见"的一部分。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from ownrag.tokens import est_tokens

SAFETY_TOKENS = 64      # 模板渲染的格式差异余量
MIN_CONTEXT_TOKENS = 128  # 再紧也要留一块的位置，否则等于拒答


@dataclass
class BudgetResult:
    blocks: list[dict]
    text: str
    tokens: int
    dropped: list[str] = field(default_factory=list)
    truncated: bool = False


def block_prompt(c: dict) -> str:
    """单块的 prompt 形态（与路由里拼装口径必须一致）。"""
    return f"[块{c.get('ordinal')}]（来源 doc={c.get('doc_id')}）\n{c.get('text', '')}"


def context_budget(num_ctx: int, prompt_overhead: int, max_new_tokens: int) -> int:
    """可用上下文预算（token）。永远至少 MIN_CONTEXT_TOKENS，避免配置写错就变成永远拒答。"""
    return max(MIN_CONTEXT_TOKENS, int(num_ctx) - int(prompt_overhead) - int(max_new_tokens)
               - SAFETY_TOKENS)


def fit_candidates(candidates: list[dict], budget_tokens: int) -> BudgetResult:
    """按序装块直到预算用尽；首个块就超预算时按字符比例截断并标记 truncated。"""
    if not candidates:
        return BudgetResult([], "", 0)

    budget = max(MIN_CONTEXT_TOKENS, int(budget_tokens))
    kept: list[dict] = []
    parts: list[str] = []
    used = 0

    for idx, c in enumerate(candidates):
        text = block_prompt(c)
        cost = max(1, est_tokens(text))
        if used + cost <= budget:
            kept.append(c)
            parts.append(text)
            used += cost
            continue
        if not kept:  # 第一块就超：截正文保住块头与引用编号
            head = f"[块{c.get('ordinal')}]（来源 doc={c.get('doc_id')}）\n"
            body = c.get("text", "")
            # 按预算比例先裁一次，再按实际估算收敛（CJK/ASCII 混排时比例不精确）
            cut = max(1, int(len(body) * budget / max(1, cost)))
            while cut > 1 and est_tokens(head + body[:cut]) > budget:
                cut = int(cut * 0.9)
            trimmed = {**c, "text": body[:cut]}
            kept.append(trimmed)
            parts.append(block_prompt(trimmed))
            used = est_tokens(parts[-1])
            return BudgetResult(kept, "\n\n".join(parts), used,
                                [x.get("chunk_id") for x in candidates[idx + 1:]] +
                                [c.get("chunk_id")], True)
        return BudgetResult(kept, "\n\n".join(parts), used,
                            [x.get("chunk_id") for x in candidates[idx:]], False)

    return BudgetResult(kept, "\n\n".join(parts), used)


# ---------------------------------------------------------------- 预算计划（问答与调试页共用）
@dataclass
class ContextPlan:
    fitted: BudgetResult
    prompt_name: str
    num_ctx: int
    max_new_tokens: int
    prompt_overhead: int
    available: int


def resolve_limits(settings, gen_cfg: dict) -> tuple[int, int]:
    """窗口与输出预留的优先级：环境变量（运维 kill-switch）> apps.yaml > models.yaml。"""
    num_ctx = int(os.environ.get("OWNRAG_NUM_CTX")
                  or gen_cfg.get("max_ctx_tokens") or settings.num_ctx)
    max_new = int(os.environ.get("OWNRAG_MAX_NEW_TOKENS")
                  or gen_cfg.get("max_new_tokens") or settings.max_new_tokens)
    return num_ctx, max_new


def plan_context(candidates: list[dict], *, question: str, prompt_name: str,
                 num_ctx: int, max_new_tokens: int) -> ContextPlan:
    """问答链路与检索调试端点共用同一份预算计算，避免"页面看到的 ≠ 线上跑的"。"""
    from ownrag.generate.prompts import render  # 延迟导入：避免配置加载期依赖

    probe = render(prompt_name, question=question, context_blocks="")
    overhead = sum(est_tokens(m["content"]) for m in probe)
    available = context_budget(num_ctx, overhead, max_new_tokens)
    return ContextPlan(fit_candidates(candidates, available), prompt_name,
                       num_ctx, max_new_tokens, overhead, available)

