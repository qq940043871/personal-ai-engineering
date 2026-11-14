"""AV 链路离线测试：时间锚正确性 / 语义切分 / 版本参数 / 关键帧结构 / OCR 分字段。

对应视频 RAG 三条铁律（吴师兄《视频 RAG 怎么做》）：
- 锚点错一秒，引用就指错位置（buf_start 修复回归）；
- 字幕不能按时长硬切——停顿与句尾才是语义边界；
- 画面文字与口播字幕分字段保存，冲突不隐藏归属。
全程不依赖 ffmpeg/ASR/Ollama——只测确定性切分与结构登记。
"""
from __future__ import annotations

import pytest

import ownrag.steps  # noqa: F401  注册内置步骤
from ownrag.config import get_settings, reset_settings_cache
from ownrag.core.db import connect, init_schema
from ownrag.core.pipeline import StepContext
from ownrag.index.chunker import chunk_markdown
from ownrag.ingest import av_asr


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


def _ctx(conn, settings, assets=None, fps="1/60") -> StepContext:
    ctx = StepContext(doc_id="av1", trace_id="tt", kb="policy_v1", conn=conn, settings=settings)
    ctx.data = {"source_path": "/x/培训.mp4", "duration_sec": 600.0,
                "assets": assets or {}, "keyframe_fps": fps, "source_meta": {}}
    return ctx


def _segs(*items) -> list[dict]:
    """(text, start, end) -> ASR 段列表（conf 全部可信）。"""
    return [{"text": t, "start": s, "end": e, "conf": 0.0} for t, s, e in items]


def _run_segment(conn, settings, segments, **params) -> str:
    ctx = _ctx(conn, settings)
    ctx.data["segments"] = segments
    result = av_asr.SegmentByTime().run(ctx, params)
    assert result.status == "ok", result.error
    return ctx.data["parsed"]["markdown"]


def test_block_anchor_matches_first_segment_start(env):
    """溢出切分后，后续块的锚点必须跟自己的首段走——曾经 buf_start 不重置，
    第二块起全部错标 00:00（引用跳转会指到视频开头）。"""
    conn, settings = env
    md = _run_segment(conn, settings,
                      _segs(("第一段。", 0, 30), ("第二段。", 30, 60),
                            ("第三段。", 60, 90), ("第四段。", 90, 120)),
                      max_sec=60)
    assert "#### [00:00]" in md
    assert "#### [01:00]" in md          # 第三段起点 60s——不是 00:00
    assert md.count("#### [00:00]") == 1  # 00:00 只出现一次（块头，不算段内 [mm:ss] 行）


def test_gap_splits_at_natural_pause(env):
    """段间停顿 > gap_sec → 语义边界先切，即使块长远小于 max_sec。"""
    conn, settings = env
    md = _run_segment(conn, settings,
                      _segs(("第一句。", 10, 20), ("第二句。", 25, 35)),
                      max_sec=60, gap_sec=1.5)
    assert "#### [00:10]" in md and "#### [00:25]" in md
    assert "第一句。" in md.split("#### [00:25]")[0]     # 第一句留在前块
    assert "第二句。" in md.split("#### [00:25]")[1]     # 第二句进入后块


def test_overflow_falls_back_to_sentence_end(env):
    """超限必切，但回退到最近句尾——不把一句话拦腰截断。"""
    conn, settings = env
    md = _run_segment(conn, settings,
                      _segs(("完整句一。", 0, 10), ("完整句二。", 10, 20),
                            ("未完句", 20, 30), ("未完句续", 30, 40)),
                      max_sec=35, gap_sec=99)   # 关掉 gap，纯测句尾回退
    first_block = md.split("#### [00:20]")[0]
    assert "未完句" not in first_block            # 半截话没被切进上一块
    assert "完整句二。" in first_block            # 在句尾边界切
    assert "#### [00:20]" in md                   # 回退段进入下一块，锚点正确


def test_split_params_recorded_for_version_chain(env):
    """切分参数写入 metadata.split_params——重灌后能比较新旧口径（处理版本链）。"""
    conn, settings = env
    ctx = _ctx(conn, settings)
    ctx.data["segments"] = _segs(("第一句。", 0, 10), ("第二句。", 10, 20))
    assert av_asr.SegmentByTime().run(ctx, {"max_sec": 45, "gap_sec": 2.0}).status == "ok"
    parsed = ctx.data["parsed"]
    assert parsed["metadata"]["split_params"] == {"max_sec": 45, "gap_sec": 2.0}


def test_keyframe_structures_with_time_anchor(env):
    """关键帧登记为结构化画面证据：kind=keyframe，location=t:时间锚（帧序号/抽帧率）。"""
    conn, settings = env
    ctx = _ctx(conn, settings,
               assets={"kf_0001": "/x/kf_0001.jpg", "kf_0002": "/x/kf_0002.jpg"},
               fps="1/60")
    ctx.data["segments"] = _segs(("第一句。", 0, 10), ("第二句。", 10, 20))
    result = av_asr.SegmentByTime().run(ctx, {"max_sec": 60})
    assert result.status == "ok" and result.metrics["keyframes"] == 2
    structures = ctx.data["parsed"]["structures"]
    assert [s["location"] for s in structures] == ["t:00:00", "t:01:00"]
    assert all(s["kind"] == "keyframe" and s["pointer"].startswith("kf_") for s in structures)


def test_ocr_text_goes_to_structures_not_markdown(env, monkeypatch):
    """画面文字进 structures 分字段保存，不拼进正文——口播与画面的归属不隐藏。"""
    conn, settings = env
    monkeypatch.setattr(av_asr, "_OCR_FN", lambda path: "画面表格：合格率 97%")
    ctx = _ctx(conn, settings,
               assets={"kf_0001": "/x/kf_0001.jpg", "kf_0002": "/x/kf_0002.jpg"},
               fps="1/60")
    ctx.data["segments"] = _segs(("第一句。", 0, 10), ("第二句。", 10, 20))
    assert av_asr.SegmentByTime().run(ctx, {"max_sec": 60}).status == "ok"
    result = av_asr.OcrKeyframes().run(ctx, {})
    assert result.status == "ok" and result.metrics["ocr"] == 2
    structures = ctx.data["parsed"]["structures"]
    ocr = [s for s in structures if s["kind"] == "ocr_text"]
    assert len(ocr) == 2
    assert ocr[0]["text"] == "画面表格：合格率 97%"
    assert ocr[0]["location"] == "t:00:00" and ocr[0]["pointer"] == "kf_0001"
    assert "合格率" not in ctx.data["parsed"]["markdown"]  # 正文没有画面文字——分字段


def test_ocr_step_skips_without_keyframes(env):
    """纯音频（无关键帧）→ 显式 skipped，不静默、不失败。"""
    conn, settings = env
    ctx = _ctx(conn, settings)
    ctx.data["parsed"] = {"markdown": "x", "structures": []}
    result = av_asr.OcrKeyframes().run(ctx, {})
    assert result.status == "ok" and result.metrics["ocr"] == 0
    assert "无关键帧" in result.metrics["ocr_note"]


def test_av_chunk_carries_structured_time_anchor():
    """切分产出的 [mm:ss] 锚点必须结构化进 chunk.anchors['t']——
    正文参与搜索，anchors 供引用回跳（内容+来源两类信息缺一不可）。"""
    md = ("#### [08:12]（源视频锚点）\n\n[08:12] 申请年假前先确认剩余额度\n"
          "[08:19] 然后在系统里提交申请\n\n"
          "#### [08:27]（源视频锚点）\n\n[08:27] 审批通过后申请才正式生效")
    chunks = chunk_markdown(md, doc_id="v1", kb="kb1", source_type="av",
                            base_meta={"source_file": "培训.mp4"}, max_tokens=512)
    assert chunks, "至少产出一块"
    for c in chunks:
        assert c.anchors.get("t"), f"块 {c.chunk_id} 缺时间锚"
    assert chunks[0].anchors["t"].startswith("08:12")
    assert chunks[-1].anchors["t"].endswith("08:27")
