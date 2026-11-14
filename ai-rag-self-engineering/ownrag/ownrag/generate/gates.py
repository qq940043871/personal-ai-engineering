"""两道纯代码闸门（04 文档 §六）：把"模型会错"从故障变成可测试的规则集。

闸门一 生成前 sufficiency_check：候选不足不进模型——"未找到有效依据"是合法答案。
闸门二 生成后 citation_check：引用的块必须在候选池内；数字/日期必须能在引用块原文找到。
规则表进 Git、随评测集回归——确定性的事不交给模型。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_REF = re.compile(r"\[来源[:：]\s*块?(\d+)\]|块(\d+)")
_NUM = re.compile(r"\d[\d,，.]*")
_DATE = re.compile(r"\d{4}[-/年]\d{1,2}([-/月]\d{1,2})?日?")
# 行首列表序号（1. / 1、 / 1）是格式不是事实数字；(?!\d) 防吞小数（"2.5 万元"的 2. 不是序号）
_LIST_ORD = re.compile(r"^\s*\d+\s*[.、)）](?!\d)\s*")
_MIN_SCORE = 0.0  # RRF 分数下限——骨架期只做非空与相对值校验，阈值随评测集校准（M2）
# 重排分下限：bge-reranker-v2-m3 校准（相关块 ~0.9+，语义邻近无关块 ~0.0）——向量通道开启后
# 检索层永远"捞得到"，拒答语义从「零召回」迁移到「重排分不足」，评测集随门禁回归校准
_MIN_RERANK_SCORE = 0.05


@dataclass
class GateResult:
    name: str
    passed: bool
    reason: str = ""
    violations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 闸门一：生成前
def sufficiency_check(candidates: list[dict]) -> GateResult:
    """候选不足不进模型。有重排分（rerank 已启用）时按重排分下限校验——
    向量通道永远能捞回"语义邻近"的块，RRF 名次分区分不了实质依据；无重排分退回 RRF 口径。"""
    if not candidates:
        return GateResult("sufficiency_check", False, "候选池为空：未找到有效依据，不进模型")
    rerank_scores: list[float] = [
        float(s) for c in candidates if (s := c.get("rerank_score")) is not None
    ]
    if rerank_scores:
        top = max(rerank_scores)
        if top < _MIN_RERANK_SCORE:
            return GateResult("sufficiency_check", False,
                              f"最高重排分过低（{top:.4f} < {_MIN_RERANK_SCORE}）：语义邻近但无实质依据，拒答")
        return GateResult("sufficiency_check", True,
                          f"候选 {len(candidates)} 条，top-rerank={top:.4f}")
    top = candidates[0].get("rrf", 0.0)
    if top <= _MIN_SCORE:
        return GateResult("sufficiency_check", False, f"最高融合分过低（{top}）")
    return GateResult("sufficiency_check", True, f"候选 {len(candidates)} 条，top-rrf={top:.4f}")


# ---------------------------------------------------------------- 闸门二：生成后
def citation_check(answer: str, candidates: list[dict]) -> GateResult:
    """引用真实性校验：
    ① 引用的块编号必须在候选池内；
    ② 答案中的数字/日期必须能在其引用的块原文中找到（防数字幻觉；无引用的数字句=违规）。
    """
    by_ordinal = {c["ordinal"]: c for c in candidates if c.get("ordinal") is not None}
    violations: list[str] = []
    cited: set[int] = set()

    lines = answer.splitlines()
    for line in lines:
        refs = [int(a or b) for a, b in _REF.findall(line)]
        bare = _REF.sub("", line)  # 剔除引用标注本身，防"块1"的 1 被当数字校验
        bare = _LIST_ORD.sub("", bare)  # 编号列表的行首序号同理是格式，不参与数字核验
        nums = _NUM.findall(bare) + _DATE.findall(bare)
        if not refs:
            if nums:  # 有数字但无引用——数字幻觉的温床
                violations.append(f"数字/日期无引用：{line.strip()[:60]}")
            continue
        for r in refs:
            if r not in by_ordinal:
                violations.append(f"引用不存在：块{r}（候选池 {sorted(by_ordinal)}）")
                continue
            cited.add(r)
            chunk_text = by_ordinal[r].get("text", "")
            for n in nums:
                if _norm_num(n) and _norm_num(n) not in _norm_text(chunk_text):
                    violations.append(f"数字 {_norm_num(n)} 不在块{r}原文中：{line.strip()[:60]}")

    # 关键硬约束：一条引用都没有但答案很长——疑似模型自由发挥
    if not cited and len(answer.strip()) > 100:
        violations.append("长答案无任何引用")

    return GateResult("citation_check", not violations,
                      f"引用块 {sorted(cited)}" if cited else "无有效引用",
                      violations)


def schema_check(answer: str, expect_json: bool = False) -> GateResult:
    """输出结构校验（JSON 模式时的骨架实现）。"""
    if not expect_json:
        return GateResult("schema_check", True, "非 JSON 模式，跳过")
    import json
    try:
        json.loads(answer)
        return GateResult("schema_check", True, "JSON 合法")
    except json.JSONDecodeError as exc:
        return GateResult("schema_check", False, f"JSON 不合法：{exc}")


def _norm_num(s: str) -> str:
    return re.sub(r"[,，\s]", "", s).rstrip(".")


def _norm_text(s: str) -> str:
    return re.sub(r"[\s,，]", "", s)
