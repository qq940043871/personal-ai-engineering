"""闸门一 sufficiency_check：重排分感知（向量通道开启后的拒答语义迁移）+ RRF 口径兼容；
闸门二 citation_check：列表序号不参与数字核验的边界。"""
from ownrag.generate.gates import citation_check, sufficiency_check


def test_empty_pool_refuses():
    g = sufficiency_check([])
    assert not g.passed and "候选池为空" in g.reason


def test_rerank_score_floor_refuses_semantic_neighbors():
    """向量通道捞回的语义邻近块：重排分低于下限 → 拒答（不进模型，防"看似合理的包装答案"）。"""
    cands = [{"ordinal": 1, "rrf": 0.03, "rerank_score": 0.01},
             {"ordinal": 2, "rrf": 0.02, "rerank_score": 0.0}]
    g = sufficiency_check(cands)
    assert not g.passed and "重排分过低" in g.reason


def test_rerank_score_pass():
    cands = [{"ordinal": 1, "rrf": 0.03, "rerank_score": 0.98}]
    g = sufficiency_check(cands)
    assert g.passed and "top-rerank" in g.reason


def test_rrf_fallback_when_no_rerank():
    """未启用 rerank：维持 RRF 口径（旧语义不破坏，旧调用方零迁移）。"""
    cands = [{"ordinal": 1, "rrf": 0.03}]
    g = sufficiency_check(cands)
    assert g.passed and "top-rrf" in g.reason


# ---------------------------------------------------------------- 闸门二：列表序号边界
def test_citation_ignores_list_ordinals():
    """编号列表的行首序号是格式不是事实数字，不参与数字核验（此前误报导致闸门二误杀）。"""
    cands = [{"ordinal": 1, "text": "申请年假前，需要先确认剩余额度，额度以人事系统当年度显示为准。"}]
    answer = ("1. 申请年假前，需要先确认剩余额度 [来源: 块1]\n"
              "2. 之后在 OA 系统提交审批 [来源: 块1]")
    g = citation_check(answer, cands)
    assert g.passed, g.violations


def test_citation_still_catches_real_numbers():
    """真实数字仍被核验：不在引用块原文 → 违规（防数字幻觉的初衷不破坏）。"""
    cands = [{"ordinal": 1, "text": "申请年假前，需要先确认剩余额度。"}]
    answer = "年假最长 15 天 [来源: 块1]"
    g = citation_check(answer, cands)
    assert not g.passed and any("15" in v for v in g.violations)


def test_citation_decimal_not_treated_as_ordinal():
    """小数开头的事实数字（2.5）不被序号剔除规则吞掉。"""
    cands = [{"ordinal": 1, "text": "罚款金额为 50 元。"}]
    answer = "2.5 倍罚款没有依据 [来源: 块1]"
    g = citation_check(answer, cands)
    assert not g.passed
