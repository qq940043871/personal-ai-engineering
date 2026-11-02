"""契约测试：中间态可用性 / 表格永不跨块 / 引用闸门抓假引用与无引用数字。"""
from __future__ import annotations

from ownrag.generate.gates import citation_check, sufficiency_check
from ownrag.index.chunker import chunk_markdown
from ownrag.ingest.base import ParsedDoc


def test_parsed_doc_usable():
    assert ParsedDoc("d1", "pdf", "").is_usable() == (False, "空 Markdown")
    ok, _ = ParsedDoc("d1", "pdf", "x" * 100).is_usable()
    assert ok


def _md_with_table() -> str:
    rows = "\n".join(f"| 项目{i} | 金额{i} | 日期2024-01-0{i} |" for i in range(1, 6))
    return ("# 第一章 总则\n\n这是正文段落，讲一些背景内容。" * 3
            + "\n\n| 列A | 列B | 列C |\n|---|---|---|\n" + rows
            + "\n\n## 第二节 附则\n\n表格之后的正文。")


def test_table_never_split():
    chunks = chunk_markdown(_md_with_table(), doc_id="d1", kb="kb1",
                            source_type="pdf", base_meta={"source_file": "样例.pdf"},
                            max_tokens=120, overlap=0)
    table_chunks = [c for c in chunks if c.meta.get("has_table")]
    assert len(table_chunks) == 1                      # 表格整体在一个块里
    assert table_chunks[0].text.count("项目1") == 1    # 首行在
    assert "项目5" in table_chunks[0].text             # 尾行也在——没被切走
    assert chunks[0].text.startswith("【样例.pdf")      # 块头增强：文档标题 > 章节路径


def _cands():
    return [{"ordinal": 1, "rrf": 0.03, "text": "报销金额为 1,234 元，截止日期 2024-12-31。",
             "chunk_id": "d1#0001"}]


def test_citation_check_catches_fake_ref():
    bad = citation_check("金额是 5,678 元 [来源: 块1]", _cands())
    assert not bad.passed and any("不在块" in v for v in bad.violations)  # 数字不在原文

    fake = citation_check("结论见 [来源: 块9]", _cands())
    assert not fake.passed and any("引用不存在" in v for v in fake.violations)  # 假引用

    good = citation_check("报销金额为 1,234 元，截止日期 2024-12-31 [来源: 块1]", _cands())
    assert good.passed


def test_citation_check_requires_refs_for_numbers():
    bare = citation_check("报销金额为 9,999 元。", _cands())
    assert not bare.passed and any("无引用" in v for v in bare.violations)


def test_sufficiency_empty_pool():
    assert not sufficiency_check([]).passed
    assert sufficiency_check([{"rrf": 0.03}]).passed
