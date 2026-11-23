"""解析复核（入库前第三道闸）：质量检查口径 / 工件落盘 / 状态机闸门 / 审批接口。

要锁住的三件事：
① 自动检查只做"事实陈述"——阻断项是硬事实（空正文、几乎无字），提示项是复核重点；
② 闸门是管道里的真步骤：pending / rejected 时索引步骤根本跑不到（不是页面藏按钮）；
③ 审批接口只改状态机并续跑管道，不"代跑"入库逻辑（避免两套口径）。
"""
from __future__ import annotations

import json
import types

import pytest
from fastapi.testclient import TestClient

import ownrag.steps  # noqa: F401  注册内置步骤
from ownrag import review as review_mod
from ownrag.config import get_settings, reset_settings_cache
from ownrag.core import tasks as taskstore
from ownrag.core.db import connect, init_schema
from ownrag.core.pipeline import run_pipeline
from ownrag.core.registry import Step, StepResult, register
from ownrag.index.embedder import EmbedError
from ownrag.review import PrepareReview, ReviewGate, quality_checks

MD_OK = ("# 年假规定\n\n"
         "<!--page:1-->\n第一章 年假额度。员工入职满一年享有 5 天年假，需提前 3 天申请。\n\n"
         "<!--page:2-->\n第二章 报销。单笔超过 2000 元需邮件批准。")


def _parsed(markdown: str, *, pages: int = 2, backend: str = "pipeline",
            degraded: str | None = None) -> dict:
    metadata = {"source_file": "手册.pdf"}
    if degraded:
        metadata["degraded"] = degraded
    return {"doc_id": "d1", "source_type": "pdf", "markdown": markdown, "metadata": metadata,
            "structures": [{"kind": "table", "location": "page:2"}],
            "assets": {}, "stats": {"pages": pages, "backend": backend}}


def _chunks(markdown: str, n: int = 2) -> list[dict]:
    return [{"chunk_id": f"d1#{i:04d}", "doc_id": "d1", "kb": "policy_v1", "source_type": "pdf",
             "ordinal": i, "text": markdown[:80], "anchors": {"heading_path": ["年假规定"]},
             "meta": {"has_table": i == 2}} for i in range(1, n + 1)]


# ---------------------------------------------------------------- 质量检查口径
def test_正常解析判定通过且页级明细可算():
    checks = quality_checks(_parsed(MD_OK), _chunks(MD_OK))
    assert checks["verdict"] == "pass", checks
    assert checks["stats"]["page_markers"] == 2 and checks["stats"]["pages"] == 2
    assert checks["stats"]["headings"] == 1
    assert [p["page"] for p in checks["pages"]] == [1, 2]
    assert checks["pages"][0]["chars"] > 0
    assert checks["pages"][1]["tables"] == 1        # 结构锚点落到了第 2 页


def test_空产物是阻断项():
    checks = quality_checks(_parsed("", pages=3), [])
    assert checks["verdict"] == "fail"
    assert checks["blocking"][0]["code"] == "empty_markdown"


def test_字符密度过低是阻断项():
    """扫描件没走 OCR 的典型形态：有页数、几乎没字——必须在入库前拦住。"""
    checks = quality_checks(_parsed("<!--page:1-->\n封面", pages=40), _chunks("x"))
    assert checks["verdict"] == "fail"
    assert checks["blocking"][0]["code"] == "too_few_chars"


def test_空页与页数不一致进提示项():
    md = MD_OK + "\n<!--page:3-->\n"
    checks = quality_checks(_parsed(md, pages=2), _chunks(md))
    codes = {w["code"] for w in checks["warn"]}
    assert {"empty_pages", "page_marker_mismatch"} <= codes
    assert 3 in [p["page"] for p in checks["pages"] if p["empty"]]


def test_乱码率高与无标题进提示项():
    md = "这是一段没有标题的正文，" * 20 + "\ufffd" * 10
    checks = quality_checks(_parsed(md, pages=1), _chunks(md))
    codes = {w["code"] for w in checks["warn"]}
    assert "mojibake" in codes and "no_headings" in codes


def test_表格被拍平进提示项():
    md = "# 表\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    parsed = _parsed(md, pages=1)
    parsed["structures"] = []                        # 解析没认出表，只留 pipe 文本
    checks = quality_checks(parsed, _chunks(md))
    assert "table_flattened" in {w["code"] for w in checks["warn"]}


def test_降级链留痕进提示项():
    checks = quality_checks(_parsed(MD_OK, degraded="pymupdf 纯文本兜底，结构信息缺失"),
                            _chunks(MD_OK))
    assert "degraded_path" in {w["code"] for w in checks["warn"]}


# ---------------------------------------------------------------- 步骤：落盘 + 状态
@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OWNRAG_DATA_DIR", str(tmp_path / "data"))
    reset_settings_cache()
    settings = get_settings()
    init_schema(settings.db_path)
    conn = connect(settings.db_path)
    yield conn, settings
    conn.close()
    reset_settings_cache()


def _ctx(conn, settings, doc_id="d1"):
    from ownrag.core.pipeline import StepContext
    ctx = StepContext(doc_id=doc_id, trace_id="t-1", kb="policy_v1", conn=conn, settings=settings)
    ctx.data["_pipeline"] = "pdf_v1"
    ctx.data["_task_id"] = "task-1"
    ctx.data["page_route"] = "pipeline"
    return ctx


def test_prepare_review_落盘三份工件并置pending(env):
    conn, settings = env
    ctx = _ctx(conn, settings)
    ctx.data["parsed"] = _parsed(MD_OK)
    ctx.data["chunks"] = _chunks(MD_OK)

    result = PrepareReview().run(ctx, {"auto_approve": False})
    assert result.status == "ok", result.error
    assert result.metrics["status"] == "pending" and result.metrics["verdict"] == "pass"

    base = settings.review_dir / "d1"
    assert (base / "parsed.md").read_text(encoding="utf-8") == MD_OK
    report = json.loads((base / "report.json").read_text(encoding="utf-8"))
    assert report["parse_route"] == "pipeline" and report["stats"]["backend"] == "pipeline"
    assert len(json.loads((base / "chunks.json").read_text(encoding="utf-8"))) == 2

    row = review_mod.get_review(conn, "d1")
    assert row["status"] == "pending" and row["task_id"] == "task-1"
    assert row["trace_id"] == "t-1" and row["chars"] > 0


def test_prepare_review_阻断项即失败但工件仍留档(env):
    conn, settings = env
    ctx = _ctx(conn, settings)
    ctx.data["parsed"] = _parsed("<!--page:1-->\n封面", pages=40)
    ctx.data["chunks"] = _chunks("x")

    result = PrepareReview().run(ctx, {})
    assert result.status == "fail" and "too_few_chars" in result.error
    # 失败也要能看到产物——否则人工无法判断是"解析坏了"还是"参数配错了"
    assert (settings.review_dir / "d1" / "report.json").is_file()
    assert review_mod.get_review(conn, "d1")["verdict"] == "fail"


def test_缺少上游产物直接失败(env):
    conn, settings = env
    ctx = _ctx(conn, settings)
    assert PrepareReview().run(ctx, {}).status == "fail"          # 无 parsed
    ctx.data["parsed"] = _parsed(MD_OK)
    assert PrepareReview().run(ctx, {}).status == "fail"          # 无 chunks（顺序放错）


def test_auto_approve_仅对无阻断项生效(env):
    conn, settings = env
    ctx = _ctx(conn, settings)
    ctx.data["parsed"] = _parsed(MD_OK)
    ctx.data["chunks"] = _chunks(MD_OK)
    assert PrepareReview().run(ctx, {"auto_approve": True}).metrics["status"] == "approved"

    ctx2 = _ctx(conn, settings, doc_id="d2")
    ctx2.data["parsed"] = _parsed("<!--page:1-->\n封面", pages=40)
    ctx2.data["chunks"] = _chunks("x")
    assert PrepareReview().run(ctx2, {"auto_approve": True}).status == "fail"
    assert review_mod.get_review(conn, "d2")["status"] == "pending"


def test_已审批的复核不因重跑回落(env):
    conn, settings = env
    ctx = _ctx(conn, settings)
    ctx.data["parsed"] = _parsed(MD_OK)
    ctx.data["chunks"] = _chunks(MD_OK)
    PrepareReview().run(ctx, {})
    review_mod.set_status(conn, "d1", "approved", "人工通过")
    # 重跑同一 doc（例如改了切分参数重试）不该抹掉审批事实
    assert PrepareReview().run(ctx, {}).metrics["status"] == "approved"


# ---------------------------------------------------------------- 闸门语义
def test_gate_无记录拒绝入库(env):
    conn, settings = env
    result = ReviewGate().run(_ctx(conn, settings), {})
    assert result.status == "fail" and "复核记录缺失" in result.error


def test_gate_pending与rejected都拒绝入库(env):
    conn, settings = env
    ctx = _ctx(conn, settings)
    ctx.data["parsed"] = _parsed(MD_OK)
    ctx.data["chunks"] = _chunks(MD_OK)
    PrepareReview().run(ctx, {})

    pending = ReviewGate().run(ctx, {})
    assert pending.status == "fail" and "待人工复核" in pending.error

    review_mod.set_status(conn, "d1", "rejected", "第 2 页表格串行，重传")
    rejected = ReviewGate().run(ctx, {})
    assert rejected.status == "fail" and "已驳回" in rejected.error
    assert "第 2 页表格串行" in rejected.error


def test_gate_approved放行(env):
    conn, settings = env
    ctx = _ctx(conn, settings)
    ctx.data["parsed"] = _parsed(MD_OK)
    ctx.data["chunks"] = _chunks(MD_OK)
    PrepareReview().run(ctx, {})
    review_mod.set_status(conn, "d1", "approved", "ok")
    result = ReviewGate().run(ctx, {})
    assert result.status == "ok" and result.metrics["gate"] == "approved"


# ---------------------------------------------------------------- 端到端：索引步骤真的跑不到
@register("t_seed_parsed")
class SeedParsed(Step):
    def run(self, ctx, params) -> StepResult:
        ctx.data["parsed"] = _parsed(MD_OK)
        ctx.data["chunks"] = _chunks(MD_OK)
        return StepResult.ok(seeded=1)


@register("t_fake_index")
class FakeIndex(Step):
    def run(self, ctx, params) -> StepResult:
        ctx.data["indexed"] = ctx.data.get("indexed", 0) + 1
        return StepResult.ok(indexed=ctx.data["indexed"])


def test_端到端_未审批则索引不执行_审批后resume完成(env):
    """这是本需求的核心断言：pending 时 t_fake_index 一次都不能跑。"""
    conn, settings = env
    pipelines = {"pdf_like": {"steps": [
        {"type": "t_seed_parsed"},
        {"type": "prepare_review", "params": {"auto_approve": False}},
        {"type": "review_gate", "params": {}},
        {"type": "t_fake_index"},
    ]}}
    fake_settings = types.SimpleNamespace(pipelines=pipelines, review_dir=settings.review_dir)
    task_id = taskstore.create_task(conn, "d1", "pdf_like", "t-e2e", kb="policy_v1")
    taskstore.update_task(conn, task_id, state_json=json.dumps({"source_path": "x.pdf"}))

    assert run_pipeline(conn, fake_settings, task_id) == "failed"
    task = taskstore.get_task(conn, task_id)
    assert "待人工复核" in task["error"]
    assert taskstore.list_todos(conn, only_open=True)          # 失败进待办，不静默

    review_mod.set_status(conn, "d1", "approved", "人工通过")
    assert run_pipeline(conn, fake_settings, task_id, resume=True) == "done"
    assert taskstore.get_task(conn, task_id)["status"] == "done"


def test_端到端_真实PDF停在复核_审批后才入库(env, monkeypatch, tmp_path):
    """真链路：真 PDF（pymupdf 造）→ detect_pages → MinerU 不可用降级 pymupdf →
    validate → chunk → prepare_review → review_gate 拦住 → 审批后 resume 才写库。

    这条测试锁的是需求本身：**复核没过，chunks 表必须是空的**。
    """
    fitz = pytest.importorskip("pymupdf")
    pdf_path = tmp_path / "leave.pdf"
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page()
        page.insert_text((72, 100), f"Page {i + 1}: annual leave is 5 days,"
                                    " apply 3 days in advance for approval.")
    doc.save(str(pdf_path))
    doc.close()

    conn, settings = env
    # embedding 与向量通道打桩为不可用：走 allow_skip 显式降级（BM25 单路），测试不出网、不写 chroma
    monkeypatch.setattr("ownrag.index.embedder.embed_texts",
                        lambda *a, **kw: (_ for _ in ()).throw(EmbedError("测试桩：嵌入不可用")))
    monkeypatch.setattr("ownrag.index.store.vector_upsert", lambda *a, **kw: False)

    task_id = taskstore.create_task(conn, "pdf-real", "pdf_v1", "t-pdf", kb="policy_v1",
                                    state={"source_path": str(pdf_path),
                                           "source_meta": {"source_file": "leave.pdf"}})

    assert run_pipeline(conn, settings, task_id) == "failed"
    task = taskstore.get_task(conn, task_id)
    assert "待人工复核" in task["error"]

    assert conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"] == 0   # 关键断言

    row = review_mod.get_review(conn, "pdf-real")
    assert row["status"] == "pending" and row["verdict"] in ("pass", "warn")
    assert row["pages"] == 2
    base = settings.review_dir / "pdf-real"
    assert (base / "parsed.md").is_file() and row["chars"] > 0
    report = json.loads((base / "report.json").read_text(encoding="utf-8"))
    assert report["parse_route"] == "pipeline"
    assert report["checks"]["stats"]["page_markers"] == 2      # pymupdf 路径带页标记

    review_mod.set_status(conn, "pdf-real", "approved", "看过，没问题")
    assert run_pipeline(conn, settings, task_id, resume=True) == "done"
    assert conn.execute("SELECT COUNT(*) AS n FROM chunks WHERE doc_id='pdf-real'"
                        ).fetchone()["n"] > 0


# ---------------------------------------------------------------- 接口
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OWNRAG_DATA_DIR", str(tmp_path / "data"))
    reset_settings_cache()
    from ownrag.main import app

    with TestClient(app) as c:
        yield c
    reset_settings_cache()


def _seed(client, verdict_md: str = MD_OK) -> dict:
    """走真实落盘路径造一条待复核记录（与线上同一函数）。"""
    settings = get_settings()
    conn = connect(settings.db_path)
    try:
        checks = quality_checks(_parsed(verdict_md), _chunks(verdict_md))
        paths = review_mod.write_artifacts(settings.review_dir / "d1",
                                          markdown=verdict_md, chunks=_chunks(verdict_md),
                                          report={"checks": checks})
        review_mod.save_review(conn, doc_id="d1", kb="policy_v1", task_id=None,
                               trace_id="t-1", pipeline="pdf_v1", source_file="手册.pdf",
                               checks=checks, report_path=paths["report"])
        return {"status": review_mod.get_review(conn, "d1")["status"]}
    finally:
        conn.close()


def test_api_列表与详情(client):
    assert client.get("/admin/reviews").json()["items"] == []
    _seed(client)
    body = client.get("/admin/reviews").json()
    assert body["counts"] == {"pending": 1} and body["pending_total"] == 1

    detail = client.get("/admin/reviews/d1").json()
    assert detail["source_file"] == "手册.pdf" and detail["status"] == "pending"
    assert detail["markdown"].startswith("# 年假规定")
    assert len(detail["chunks"]) == 2 and detail["pages_detail"][0]["page"] == 1


def test_api_详情可按offset续读产物(client):
    _seed(client)
    head = client.get("/admin/reviews/d1", params={"md": True, "max_chars": 10}).json()
    assert head["markdown_total_chars"] == len(MD_OK) and len(head["markdown"]) == 10
    tail = client.get("/admin/reviews/d1", params={"offset": 10, "max_chars": 10}).json()
    assert tail["markdown"] == MD_OK[10:20]


def test_api_通过则置approved并续跑管道(client, monkeypatch):
    _seed(client)
    import ownrag.api.routes_review as rr

    called = {}

    def fake_run(conn, settings, task_id, resume=False):
        called["resume"] = resume
        return "done"

    monkeypatch.setattr(rr, "run_pipeline", fake_run)
    conn = connect(get_settings().db_path)
    try:  # 补一个真实任务，验证"通过即续跑"
        tid = taskstore.create_task(conn, "d1", "pdf_v1", "t-1", kb="policy_v1")
        conn.execute("UPDATE parse_reviews SET task_id=? WHERE doc_id='d1'", (tid,))
        conn.commit()
    finally:
        conn.close()

    body = client.post("/admin/reviews/d1/approve", json={"note": "看过，没问题"}).json()
    assert body["status"] == "approved" and body["task_status"] == "done"
    assert called["resume"] is True

    detail = client.get("/admin/reviews/d1").json()
    assert detail["status"] == "approved" and detail["note"] == "看过，没问题"


def test_api_阻断项不允许放行(client):
    _seed(client, verdict_md="<!--page:1-->\n封面")
    r = client.post("/admin/reviews/d1/approve", json={})
    assert r.status_code == 409 and "阻断项" in r.json()["detail"]


def test_api_驳回必须写原因并关闭待办(client):
    _seed(client)
    assert client.post("/admin/reviews/d1/reject", json={"note": "  "}).status_code == 422

    conn = connect(get_settings().db_path)
    try:
        tid = taskstore.create_task(conn, "d1", "pdf_v1", "t-1", kb="policy_v1")
        taskstore.add_todo(conn, tid, "d1", "解析产物待人工复核")
        conn.execute("UPDATE parse_reviews SET task_id=? WHERE doc_id='d1'", (tid,))
        conn.commit()
    finally:
        conn.close()

    body = client.post("/admin/reviews/d1/reject", json={"note": "第 2 页表格串行"}).json()
    assert body["status"] == "rejected" and body["todos_closed"] == 1
    assert client.get("/admin/reviews/d1").json()["note"] == "第 2 页表格串行"


def test_api_未知doc返回404(client):
    assert client.get("/admin/reviews/nope").status_code == 404
    assert client.post("/admin/reviews/nope/approve", json={}).status_code == 404
