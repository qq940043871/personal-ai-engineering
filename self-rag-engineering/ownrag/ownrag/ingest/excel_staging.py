"""链路 C：Excel 转临时表 staging（03 文档 §四）。

四步：落地（全 TEXT 保真）→ schema 推断 → 列语义映射（LLM 建议 + 人工确认，HITL 卡点）
→ 文本化（row_card 行级卡片 / aggregate 聚合摘要，数字正确性来自 SQL 不来自向量）。
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from ownrag.core.pipeline import StepContext
from ownrag.core.registry import Step, StepResult, register
from ownrag.ingest.base import ParsedDoc


def _sanitize(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\u4e00-\u9fa5]", "_", name)[:40] or "sheet"


# ---------------------------------------------------------------- 步骤：落地临时表
@register("excel_stage")
class ExcelStage(Step):
    """pandas 逐 sheet 读 → SQLite staging 表。全 TEXT 保真：类型是推断出的结论，不是前提。"""

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        src = Path(ctx.data["source_path"])
        try:
            import pandas as pd
        except ImportError:
            return StepResult.fail("pandas/openpyxl 未安装（pip install 'ownrag[excel]'）")

        frames: dict[str, "pd.DataFrame"] = {}
        if src.suffix.lower() == ".csv":
            frames["csv"] = pd.read_csv(src, dtype=str, keep_default_na=False)
        else:
            frames = pd.read_excel(src, sheet_name=None, dtype=str)  # 全 sheet、全 TEXT

        registered = []
        for sheet, df in frames.items():
            if df.empty:
                continue
            table = f"staging_{ctx.doc_id[:8]}_{_sanitize(sheet)}"
            cols = list(df.columns)
            col_defs = ", ".join(f'"{_sanitize(c)}" TEXT' for c in cols)
            ctx.conn.execute(f'DROP TABLE IF EXISTS "{table}"')
            ctx.conn.execute(
                f'CREATE TABLE "{table}" ({col_defs}, '
                f'"_src_file" TEXT, "_sheet" TEXT, "_rownum" INTEGER)')
            rows = df.fillna("").values.tolist()
            placeholders = ", ".join("?" * (len(cols) + 3))
            ctx.conn.executemany(
                f'INSERT INTO "{table}" VALUES ({placeholders})',
                [(*[str(v) for v in r], src.name, sheet, i + 1) for i, r in enumerate(rows)],
            )
            ctx.conn.execute(
                "INSERT OR REPLACE INTO staging_registry(doc_id, table_name, sheet, schema_json) "
                "VALUES (?,?,?,?)",
                (ctx.doc_id, table, sheet, json.dumps({"columns": cols}, ensure_ascii=False)))
            registered.append({"table": table, "sheet": sheet, "rows": len(rows), "columns": cols})
        ctx.conn.commit()

        if not registered:
            return StepResult.fail("无有效 sheet（全部为空）")
        ctx.data["staged"] = registered
        return StepResult.ok(tables=len(registered),
                             rows=sum(r["rows"] for r in registered))


# ---------------------------------------------------------------- 步骤：schema 推断
@register("schema_infer")
class SchemaInfer(Step):
    """列名 / 非空率 / 样本值 / 类型推断——映射与文本化的依据。"""

    TYPE_RULES = [  # 顺序即优先级：日期 > 数值 > 枚举 > 自由文本
        ("date", re.compile(r"^\d{4}[-/年]\d{1,2}([-/月]\d{1,2})?日?$")),
        ("number", re.compile(r"^-?\d+([.,]\d+)?%?$")),
    ]

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        staged: list[dict] = ctx.data.get("staged") or []
        sample_n = int(params.get("sample_n", 5))
        schemas = []
        for item in staged:
            table = item["table"]
            cols = [r["name"] for r in ctx.conn.execute(f'PRAGMA table_info("{table}")')
                    if not r["name"].startswith("_")]
            col_info = []
            for c in cols:
                vals = [r[0] for r in ctx.conn.execute(
                    f'SELECT "{c}" FROM "{table}" WHERE TRIM(COALESCE("{c}",\'\'))<>\'\' LIMIT 200')]
                nonnull_rate = round(len(vals) / max(item["rows"], 1), 2)
                ctype = "text"
                if vals:
                    match_rate = lambda rx: sum(1 for v in vals if rx.match(str(v).strip())) / len(vals)
                    if match_rate(self.TYPE_RULES[0][1]) > 0.8:
                        ctype = self.TYPE_RULES[0][0]
                    elif match_rate(self.TYPE_RULES[1][1]) > 0.8:
                        ctype = self.TYPE_RULES[1][0]
                    elif len(set(vals)) <= max(3, len(vals) // 20):
                        ctype = "enum"
                col_info.append({"column": c, "type": ctype, "nonnull_rate": nonnull_rate,
                                 "samples": vals[:sample_n]})
            schemas.append({"table": table, "sheet": item["sheet"], "rows": item["rows"],
                            "columns": col_info})
        ctx.data["schemas"] = schemas
        return StepResult.ok(tables=len(schemas),
                             columns=sum(len(s["columns"]) for s in schemas))


# ---------------------------------------------------------------- 步骤：列语义映射
@register("column_mapping")
class ColumnMapping(Step):
    """LLM 给建议映射，人工确认后生效（写待办 = HITL 卡点，见 05 文档 §六 风险表）。

    M1 口径：默认恒等映射 + 待办提示；LLM 建议为 params.suggest_by_llm=true 时的增强（M2）。
    """

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        schemas: list[dict] = ctx.data.get("schemas") or []
        mapping = {s["table"]: {c["column"]: c["column"] for c in s["columns"]} for s in schemas}
        ctx.data["column_mapping"] = mapping
        if params.get("suggest_by_llm"):
            ctx.conn.execute(
                "INSERT INTO todos(task_id, doc_id, reason, payload_json) VALUES (?,?,?,?)",
                (None, ctx.doc_id, "Excel 列语义映射待人工确认（当前为恒等映射）",
                 json.dumps(schemas, ensure_ascii=False)[:4000]))
            ctx.conn.commit()
        return StepResult.ok(tables=len(mapping))


# ---------------------------------------------------------------- 步骤：文本化
@register("textualize")
class Textualize(Step):
    """row_card：每行一张"字段: 值"卡片文本（明细查询类）。
    aggregate：分组聚合摘要，数字必须来自 SQL 结果（M2 实现 SQL 路径，先立接口）。"""

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        strategy = params.get("strategy", "row_card")
        staged: list[dict] = ctx.data.get("staged") or []
        schemas = {s["table"]: s for s in (ctx.data.get("schemas") or [])}
        max_rows = int(params.get("max_rows", 5000))
        blocks: list[str] = []
        skipped_rows = 0

        if strategy == "aggregate":
            return StepResult.fail("aggregate 策略属 M2（问题→SQL→结果直入答案），M1 先用 row_card")

        for item in staged:
            table, sheet = item["table"], item["sheet"]
            cols = [r["name"] for r in ctx.conn.execute(f'PRAGMA table_info("{table}")')
                    if not r["name"].startswith("_")]
            for rownum, row in enumerate(ctx.conn.execute(
                    f'SELECT * FROM "{table}" LIMIT {max_rows + 1}'), start=1):
                if rownum > max_rows:
                    skipped_rows += item["rows"] - max_rows
                    break
                pairs = [f"{c}: {row[c]}" for c in cols if str(row[c] or "").strip()]
                if not pairs:
                    continue
                header = f"#### {item.get('sheet', table)} 第 {rownum} 行\n\n"
                blocks.append(header + "\n".join(f"- {p}" for p in pairs))
                _ = sheet, schemas  # sheet 已并入 header；schemas 留给 M2 aggregate

        if not blocks:
            return StepResult.fail("文本化零块（全空表？）")
        doc = ParsedDoc(
            doc_id=ctx.doc_id, source_type="excel",
            markdown="\n\n".join(blocks),
            metadata={"source_file": Path(ctx.data["source_path"]).name,
                      "strategy": strategy, "tables": [s["table"] for s in staged],
                      **ctx.data.get("source_meta", {})},
            stats={"blocks": len(blocks), "skipped_rows": skipped_rows},
        )
        ctx.data["parsed"] = doc.to_dict()
        return StepResult.ok(blocks=len(blocks), skipped_rows=skipped_rows)
