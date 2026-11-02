"""链路 A：MinerU 识别 PDF（03 文档 §二）。

步骤：detect_pages（页级路由）→ parse_mineru（主）→ parse_pymupdf（纯文本降级）。
主解析形态 http / cli 双模同接口；重活失败走 DSL fallback 链，绝不静默丢文档。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

from ownrag.core.pipeline import StepContext
from ownrag.core.registry import Step, StepResult, register
from ownrag.ingest.base import ParsedDoc, Structure


# ---------------------------------------------------------------- 步骤：页级路由
@register("detect_pages")
class DetectPages(Step):
    """抽样判版式：电子版走 pipeline（快），扫描/复杂版式建议 VLM（准）。
    判定允许人工在待办里改判重跑——判定错了两头不讨好。"""

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        src = Path(ctx.data["source_path"])
        if src.suffix.lower() != ".pdf":
            return StepResult.ok({"page_route": "skip"}, sample_pages=0)

        sample_n = int(params.get("sample_pages", 3))
        text_chars = self._sample_text_chars(src, sample_n)
        # 极简口径：抽样页几乎无文本层 → 扫描件倾向 VLM；有文本层 → pipeline。
        # 复杂版式（多栏/嵌套表）的精细判定留给 MinerU 自身后端能力（M3 增强，TODO）。
        route = "pipeline" if text_chars > 50 else "vlm"
        return StepResult.ok({"page_route": route}, sampled=sample_n, text_chars=text_chars)

    @staticmethod
    def _sample_text_chars(src: Path, n: int) -> int:
        try:
            import fitz  # pymupdf（可选依赖）
        except ImportError:
            return 999  # 无法探测时不拦路，交由 parse_mineru 自身路由
        total = 0
        with fitz.open(str(src)) as doc:
            for page in doc[:n]:
                total += len(page.get_text("text").strip())
        return total


# ---------------------------------------------------------------- 步骤：MinerU 解析
@register("parse_mineru")
class ParseMinerU(Step):
    """MinerU 解析 → ParsedDoc（统一中间态）。mode: http | cli 同接口。"""

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        src = Path(ctx.data["source_path"])
        backend = params.get("backend", "auto")
        if backend == "auto":
            backend = {"pipeline": "pipeline", "vlm": "vlm"}.get(
                ctx.data.get("page_route", "pipeline"), "pipeline")
        # VLM 后端与 chat 模型抢显存——由全局队列排程兜底（01 文档 §四并发现实）。
        if ctx.settings.mineru_mode == "http":
            md, assets, stats = self._via_http(src, ctx, params)
        else:
            md, assets, stats = self._via_cli(src, ctx, params)
        if not md or not md.strip():
            return StepResult.fail("MinerU 产出空 Markdown", backend=backend)

        doc = ParsedDoc(
            doc_id=ctx.doc_id, source_type="pdf", markdown=md,
            metadata={"source_file": src.name, **ctx.data.get("source_meta", {})},
            assets=assets, stats={"backend": backend, **stats},
        )
        ok, why = doc.is_usable()
        if not ok:
            return StepResult.fail(f"产出不可用：{why}", backend=backend)
        ctx.data["parsed"] = doc.to_dict()
        return StepResult.ok(**{"pages": stats.get("pages", 0)}, backend=backend)

    # ---- http 模式：POST 文件，约定返回 JSON {"markdown": "...", "pages": N} ----
    # （对接 MinerU 服务化部署时的真实契约在 M1 对齐；此处先立接口与失败语义）
    def _via_http(self, src: Path, ctx: StepContext, params: dict):
        import httpx
        base = ctx.settings.mineru_base_url
        if not base:
            raise RuntimeError("MINERU_MODE=http 但 MINERU_BASE_URL 未配置")
        resp = httpx.post(f"{base}/file_parse",
                          files={"file": (src.name, src.read_bytes())},
                          data={"backend": params.get("backend", "auto"),
                                "lang": params.get("lang", "ch")},
                          timeout=600, trust_env=False)  # 本地 MinerU 服务，不穿代理
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("markdown", ""), payload.get("assets", {}), {"pages": payload.get("pages", 0)}

    # ---- cli 模式：子进程拉起，读输出目录的 .md ----
    def _via_cli(self, src: Path, ctx: StepContext, params: dict):
        cmd = list(ctx.settings.mineru_cmd)
        if not shutil.which(cmd[0]):
            raise RuntimeError(f"MinerU CLI 不可用：{cmd[0]} 未安装（可用 pdf 降级链或改 http 模式）")
        out_dir = ctx.settings.parsed_dir / ctx.doc_id
        out_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(cmd + ["-p", str(src), "-o", str(out_dir)],
                              capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0:
            raise RuntimeError(f"MinerU CLI 失败：{proc.stderr[-300:]}")
        mds = sorted(out_dir.rglob("*.md"))
        if not mds:
            raise RuntimeError("MinerU CLI 未产出 Markdown")
        md = mds[0].read_text(encoding="utf-8")
        assets = {p.stem: str(p) for p in out_dir.rglob("*") if p.suffix.lower() in {".png", ".jpg"}}
        return md, assets, {"pages": len(list(out_dir.rglob("*.md")))}


# ---------------------------------------------------------------- 降级：纯文本
@register("parse_pymupdf")
class ParsePyMuPDF(Step):
    """纯文本兜底：结构丢了内容也要在。产出带页码锚点的 Markdown（降级质量可见）。"""

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        src = Path(ctx.data["source_path"])
        try:
            import fitz
        except ImportError:
            return StepResult.fail("pymupdf 未安装（pip install 'ownrag[pdf]'），降级链穷尽")

        pages: list[str] = []
        structures: list[Structure] = []
        with fitz.open(str(src)) as doc:
            for i, page in enumerate(doc, start=1):
                text = page.get_text("text").strip()
                pages.append(f"<!--page:{i}-->\n{text}" if text else f"<!--page:{i}-->（本页无可提取文本）")
        md = "\n\n".join(pages)
        doc = ParsedDoc(
            doc_id=ctx.doc_id, source_type="pdf", markdown=md,
            metadata={"source_file": src.name,
                      "degraded": "pymupdf 纯文本兜底，结构信息缺失",
                      **ctx.data.get("source_meta", {})},
            structures=structures,
            stats={"pages": len(pages), "backend": "pymupdf-fallback"},
        )
        ok, why = doc.is_usable()
        if not ok:
            return StepResult.fail(f"兜底产出仍不可用：{why}")
        ctx.data["parsed"] = doc.to_dict()
        return StepResult.ok(pages=len(pages), degraded=1)
