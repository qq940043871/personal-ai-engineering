"""统一中间态契约 ParsedDoc（03 文档 §一）：三条解析链路的汇合点。

换解析器不动向量库的前提：所有链路收敛到同一契约；
锚点即引用——页码 / mm:ss / 行区间在解析层决定，生成层只透传。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Structure:
    kind: str                 # table | image | formula | keyframe
    location: str             # 位置锚点：page:3 / t:12:34 / row:3-7
    pointer: str | None = None  # 产物指针（assets 的 key 或内联说明）


@dataclass
class ParsedDoc:
    doc_id: str
    source_type: str                       # pdf | av | excel
    markdown: str
    metadata: dict = field(default_factory=dict)     # 公共元数据（03 文档 §1.1）
    structures: list[Structure] = field(default_factory=list)
    assets: dict[str, str] = field(default_factory=dict)  # key -> 文件路径
    stats: dict = field(default_factory=dict)         # 页数/时长/行列数/耗时

    def to_dict(self) -> dict:
        d = asdict(self)
        d["structures"] = [asdict(s) for s in self.structures]
        return d

    def is_usable(self, min_chars_total: int = 20) -> tuple[bool, str]:
        """与 validate_parsed 步骤共用同一口径：产出可用 = 正文非空且达到最低信息量。"""
        if not self.markdown or not self.markdown.strip():
            return False, "空 Markdown"
        if len(self.markdown.strip()) < min_chars_total:
            return False, f"正文过短（{len(self.markdown.strip())} 字符 < {min_chars_total}）"
        return True, ""
