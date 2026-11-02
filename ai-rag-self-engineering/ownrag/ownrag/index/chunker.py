"""结构感知切分（04 文档 §一）：标题树优先、表格永不跨块、锚点保留、块头增强。

索引侧决定天花板——切分参数变更必须过评测集回归，没有例外。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ownrag.tokens import est_tokens as _est_tokens  # 与生成侧预算同一套口径


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    kb: str
    source_type: str
    ordinal: int
    text: str
    anchors: dict = field(default_factory=dict)   # page / t / row_range / heading_path
    meta: dict = field(default_factory=dict)


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_LINE = re.compile(r"^\s*(\|.*|<table\b.*|</table>\s*)$", re.IGNORECASE)


def split_segments(markdown: str) -> list[dict]:
    """把 Markdown 拆成带语义类型的段：heading | table | paragraph | code。
    表格整段收集（永不跨块的前提）；标题记录层级供章节路径使用。"""
    segments: list[dict] = []
    heading_path: list[str] = []
    buf: list[str] = []
    kind = "paragraph"

    def flush() -> None:
        nonlocal buf
        text = "\n".join(buf).strip()
        if text:
            segments.append({"kind": kind, "text": text,
                             "heading_path": list(heading_path)})
        buf = []

    for line in markdown.splitlines():
        m = _HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            heading_path = heading_path[:level - 1] + [m.group(2).strip()]
            kind = "heading"
            buf = [line]
            flush()
            kind = "paragraph"
            continue
        if _TABLE_LINE.match(line):
            if kind != "table":
                flush()
                kind = "table"
            buf.append(line)
            continue
        if kind == "table":  # 表格结束
            flush()
            kind = "paragraph"
        if line.strip().startswith("```"):
            if kind == "code":
                buf.append(line)
                flush()
                kind = "paragraph"
            else:
                flush()
                kind = "code"
                buf.append(line)
            continue
        buf.append(line)
    flush()
    return segments


def chunk_markdown(markdown: str, *, doc_id: str, kb: str, source_type: str,
                   base_meta: dict, max_tokens: int = 512, overlap: int = 64) -> list[Chunk]:
    """段打包成块：≤max_tokens；块首注入"文档标题 > 章节路径"短头（裸块缺主语会召回漂移）。"""
    segments = split_segments(markdown)
    chunks: list[Chunk] = []
    cur: list[dict] = []
    cur_tokens = 0
    ordinal = 0
    doc_title = base_meta.get("source_file", doc_id)

    def pack(segs: list[dict]) -> None:
        nonlocal ordinal, cur, cur_tokens
        if not segs:
            return
        ordinal += 1
        heading_path = segs[0].get("heading_path") or []
        header = " > ".join([doc_title] + heading_path)
        body = "\n\n".join(s["text"] for s in segs)
        text = f"【{header}】\n\n{body}" if header else body
        anchors: dict = {}
        for key in ("page", "t", "row_range"):
            if key in base_meta:
                anchors[key] = base_meta[key]
        anchors["heading_path"] = heading_path
        has_table = any(s["kind"] == "table" for s in segs)
        chunks.append(Chunk(
            chunk_id=f"{doc_id}#{ordinal:04d}", doc_id=doc_id, kb=kb,
            source_type=source_type, ordinal=ordinal, text=text,
            anchors=anchors, meta={**base_meta, "has_table": has_table},
        ))

    for seg in segments:
        t = _est_tokens(seg["text"])
        # 表格/超长段独立成块（表格不切；单段超限也保留——完整性优先于块径均匀）
        if seg["kind"] in ("table", "code") or t > max_tokens:
            pack(cur)
            cur, cur_tokens = [], 0
            pack([seg])
            continue
        if cur_tokens + t > max_tokens:
            pack(cur)
            # 简化重叠：重叠仅在段落型内容间生效，且不跨表格
            tail = cur[-1:] if overlap and cur and cur[-1]["kind"] == "paragraph" else []
            cur, cur_tokens = list(tail), sum(_est_tokens(s["text"]) for s in tail)
        cur.append(seg)
        cur_tokens += t
    pack(cur)
    return chunks


# ---------------------------------------------------------------- 步骤
from ownrag.core.pipeline import StepContext          # noqa: E402  (置于函数定义后注册)
from ownrag.core.registry import Step, StepResult, register  # noqa: E402
from ownrag.ingest.base import ParsedDoc              # noqa: E402


@register("chunk_markdown")
class ChunkMarkdown(Step):
    def run(self, ctx: StepContext, params: dict) -> StepResult:
        parsed: dict = ctx.data.get("parsed") or {}
        if not parsed.get("markdown"):
            return StepResult.fail("无 parsed.markdown——上游解析步骤缺失或未产出")
        chunks = chunk_markdown(
            parsed["markdown"], doc_id=ctx.doc_id, kb=ctx.kb,
            source_type=parsed.get("source_type", "unknown"),
            base_meta=parsed.get("metadata", {}),
            max_tokens=int(params.get("max_tokens", 512)),
            overlap=int(params.get("overlap", 64)),
        )
        if not chunks:
            return StepResult.fail("切分零块")
        ctx.data["chunks"] = [c.__dict__ | {"anchors": c.anchors, "meta": c.meta} for c in chunks]
        return StepResult.ok(chunks=len(chunks),
                             tables=sum(1 for c in chunks if c.meta.get("has_table")))


@register("validate_parsed")
class ValidateParsed(Step):
    """独立于 parse 的校验闸：'解析成功但产出不可用'与'解析失败'同等待遇。"""

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        parsed: dict = ctx.data.get("parsed") or {}
        min_chars = int(params.get("min_chars_per_page", 20))
        ok, why = ParsedDoc(**{**parsed, "structures": []}).is_usable(min_chars) \
            if parsed else (False, "上游无 parsed 产物")
        if not ok:
            return StepResult.fail(f"校验不过：{why}")
        return StepResult.ok(chars=len(parsed["markdown"]))
