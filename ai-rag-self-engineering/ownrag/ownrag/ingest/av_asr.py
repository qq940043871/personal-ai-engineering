"""链路 B：ffmpeg 抽流 + 本地 ASR 转写（03 文档 §三）。

时间戳是音视频唯一可靠结构：块边界优先语义边界（自然停顿、句尾标点），其次时长上限，
每块带 [mm:ss] 锚点可回跳源视频——锚点错一秒，引用就指错位置，切分参数随块存档（版本链）。
画面文字与口播字幕分字段保存：OCR 文本进 structures，不拼进正文（冲突不隐藏归属）。
ASR 错误是链路噪声不是静默失败——低置信度段在正文上显式标记 [?mm:ss]。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from ownrag.core.pipeline import StepContext
from ownrag.core.registry import Step, StepResult, register
from ownrag.ingest.base import ParsedDoc, Structure


def _need(bin_name: str) -> str:
    path = shutil.which(bin_name)
    if not path:
        raise RuntimeError(f"依赖 {bin_name} 不在 PATH（安装 ffmpeg：winget install ffmpeg）")
    return path


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


# ---------------------------------------------------------------- 步骤：抽音轨
@register("ff_extract_audio")
class FfExtractAudio(Step):
    """-vn -ac 1 -ar 16000：ASR 标准输入；视频按固定间隔抽关键帧（画面信息不靠语音）。"""

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        src = Path(ctx.data["source_path"])
        ffmpeg, ffprobe = _need("ffmpeg"), _need("ffprobe")

        probe = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(src)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if probe.returncode != 0:
            return StepResult.fail(f"ffprobe 失败：{probe.stderr[-200:]}")
        info = json.loads(probe.stdout or "{}")
        duration = float((info.get("format") or {}).get("duration") or 0)

        out_dir = ctx.settings.parsed_dir / ctx.doc_id
        out_dir.mkdir(parents=True, exist_ok=True)
        wav = out_dir / "audio_16k_mono.wav"
        subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-i", str(src),
             "-vn", "-ac", str(params.get("ac", 1)), "-ar", str(params.get("ar", 16000)), str(wav)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
        if not wav.exists() or wav.stat().st_size == 0:
            return StepResult.fail("ffmpeg 未产出有效音轨")

        assets: dict[str, str] = {}
        keyframe_fps = str(params.get("keyframe_fps", "1/60"))  # 默认每 60s 一帧
        if src.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi"}:
            kf_dir = out_dir / "keyframes"
            kf_dir.mkdir(exist_ok=True)
            subprocess.run(
                [ffmpeg, "-y", "-v", "error", "-i", str(src), "-vf", f"fps={keyframe_fps}",
                 str(kf_dir / "kf_%04d.jpg")], capture_output=True, timeout=3600)
            assets = {p.stem: str(p) for p in sorted(kf_dir.glob("*.jpg"))}

        # keyframe_fps 随黑板下传：下游按 帧序号/fps 推每帧时间锚（画面证据要能对齐时间轴）
        ctx.data.update({"audio_wav": str(wav), "duration_sec": duration, "assets": assets,
                         "keyframe_fps": keyframe_fps})
        return StepResult.ok(keyframes=len(assets), duration_sec=round(duration, 1))


# ---------------------------------------------------------------- 步骤：ASR 转写
@register("asr_transcribe")
class AsrTranscribe(Step):
    """本地 ASR → 段级(词级)时间戳转写。引擎由配置/参数决定，失败走 fallback 换引擎。"""

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        engine = params.get("engine", ctx.settings.asr_engine)
        model_name = params.get("model", ctx.settings.asr_model)
        wav = ctx.data["audio_wav"]
        if engine == "faster-whisper":
            segments = self._faster_whisper(wav, model_name, bool(params.get("vad", True)))
        elif engine == "funasr":
            segments = self._funasr(wav, model_name)
        else:
            return StepResult.fail(f"未知 ASR 引擎：{engine}")
        if not segments:
            return StepResult.fail("转写结果为空（静音或引擎异常）", engine=engine)
        ctx.data["segments"] = segments
        return StepResult.ok(engine=engine, model=model_name, segments=len(segments))

    @staticmethod
    def _faster_whisper(wav: str, model_name: str, vad: bool) -> list[dict]:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError("faster-whisper 未安装（pip install 'ownrag[asr]'）") from None
        # CPU 档 int8 可跑；长音频按 VAD 段喂，不整段进显存
        model = WhisperModel(model_name, device="auto", compute_type="int8")
        raw_iter, info = model.transcribe(wav, vad_filter=vad, word_timestamps=False)
        return [{"start": round(s.start, 2), "end": round(s.end, 2),
                 "text": s.text.strip(), "conf": round(s.avg_logprob, 2)}
                for s in raw_iter if s.text.strip()]

    @staticmethod
    def _funasr(wav: str, model_name: str) -> list[dict]:
        try:
            from funasr import AutoModel
        except ImportError:
            raise RuntimeError("funasr 未安装（pip install 'ownrag[funasr]'）") from None
        model = AutoModel(model=model_name, vad_model="fsmn-vad", punc_model="ct-punc")
        res = model.generate(input=wav, batch_size_s=300)
        sentences = (res[0] or {}).get("sentence_info", [])
        return [{"start": s["start"] / 1000, "end": s["end"] / 1000,
                 "text": s["text"].strip(), "conf": round(float(s.get("sp", 1.0)), 2)}
                for s in sentences if s.get("text", "").strip()]


# ---------------------------------------------------------------- 步骤：按时间切分
_SENT_END = tuple("。！？；!?;…")


@register("segment_by_time")
class SegmentByTime(Step):
    """聚段成块：优先语义边界，其次时长上限——字幕不能按时长硬切。

    每段要能独立说清一件事（"然后在系统里提交申请"单独成块谁也看不懂）：
    - 段间停顿 > gap_sec → 自然停顿即话题边界，先切；
    - 块长超过 max_sec → 必切，但回退到最后一个句尾段之后，不把一句话拦腰截断。
    切分参数写入 metadata.split_params（处理版本链：重灌后能比较新旧口径）。
    关键帧登记为 structures（画面证据带时间锚，供画面文字对齐与引用展示）。
    """

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        segments: list[dict] = ctx.data.get("segments") or []
        if not segments:
            return StepResult.fail("无转写段（上游 asr_transcribe 缺失？）")
        max_sec = float(params.get("max_sec", 60))
        gap_sec = float(params.get("gap_sec", 1.5))
        blocks: list[str] = []
        buf: list[dict] = []
        buf_start = 0.0
        prev_end: float | None = None

        def flush() -> None:
            nonlocal buf, buf_start
            if not buf:
                return
            lines = []
            for seg in buf:
                stamp = _fmt_ts(seg["start"])
                text = seg["text"]
                if seg.get("conf", 0) < -0.8:  # 低置信度：检索照常，人工核验有标记
                    text = f"[?{stamp}] {text}"
                lines.append(f"[{stamp}] {text}")
            blocks.append(f"#### [{_fmt_ts(buf_start)}]（源视频锚点）\n\n" + "\n".join(lines))
            buf, buf_start = [], 0.0

        for seg in segments:
            paused = prev_end is not None and (seg["start"] - prev_end) > gap_sec
            overflow = bool(buf) and (seg["end"] - buf_start) > max_sec
            if paused or overflow:
                cut = len(buf)
                if overflow and cut > 1 and not buf[-1]["text"].endswith(_SENT_END):
                    for i in range(cut - 1, 0, -1):   # 超限但末段没说完：回退到最近句尾再切
                        if buf[i]["text"].endswith(_SENT_END):
                            cut = i + 1
                            break
                keep = buf[cut:]
                buf = buf[:cut]
                flush()
                if keep:                              # 被回退的段留给下一块，锚点跟块走
                    buf, buf_start = keep, keep[0]["start"]
            if not buf:
                buf_start = seg["start"]
            buf.append(seg)
            prev_end = seg["end"]
        flush()

        if not blocks:
            return StepResult.fail("切分零块")
        src_path = Path(ctx.data["source_path"])
        doc = ParsedDoc(
            doc_id=ctx.doc_id, source_type="av", markdown="\n\n".join(blocks),
            metadata={"source_file": src_path.name,
                      "duration_sec": ctx.data.get("duration_sec", 0),
                      "split_params": {"max_sec": max_sec, "gap_sec": gap_sec},
                      **ctx.data.get("source_meta", {})},
            structures=_keyframe_structures(ctx.data),
            assets={k: v for k, v in (ctx.data.get("assets") or {}).items()},
            stats={"blocks": len(blocks), "duration_sec": ctx.data.get("duration_sec", 0)},
        )
        ctx.data["parsed"] = doc.to_dict()
        return StepResult.ok(blocks=len(blocks), keyframes=len(doc.structures))


def _fps_of(raw: str) -> float:
    """'1/60' -> 1/60；解析失败回退默认值（抽帧率与帧序号共同决定时间锚）。"""
    try:
        num, _, den = str(raw).partition("/")
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 1.0 / 60


def _keyframe_structures(data: dict) -> list[Structure]:
    """关键帧 → 结构化画面证据：location=t:时间锚（帧序号/fps 的窗口起点近似）。"""
    assets: dict[str, str] = data.get("assets") or {}
    if not assets:
        return []
    fps = _fps_of(data.get("keyframe_fps") or "1/60")
    return [Structure(kind="keyframe", location=f"t:{_fmt_ts(i / fps)}", pointer=key)
            for i, key in enumerate(sorted(assets))]


# ---------------------------------------------------------------- 步骤：关键帧 OCR（可选）
# 测试注入点：Callable[[str], str]（图片路径 -> 画面文字）。生产未注入时走 _default_ocr。
_OCR_FN: Callable[[str], str] | None = None
_PADDLE_OCR = None  # 惰性单例：OCR 模型加载重，进程内只做一次


def _default_ocr(image_path: str) -> str:
    """生产默认实现：PaddleOCR 可用则识别；未安装/任何失败返回空串（上层显式降级，不静默）。"""
    try:
        from paddleocr import PaddleOCR
    except Exception:
        return ""
    global _PADDLE_OCR
    try:
        if _PADDLE_OCR is None:
            _PADDLE_OCR = PaddleOCR(use_angle_cls=True, lang="ch")
        result = _PADDLE_OCR.ocr(image_path)
        lines: list[str] = []
        for page in result or []:
            for item in page or []:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    txt = item[1]
                    lines.append(txt[0] if isinstance(txt, (list, tuple)) and txt else str(txt))
        return "\n".join(lines)
    except Exception:
        return ""


@register("ocr_keyframes")
class OcrKeyframes(Step):
    """关键帧画面文字 OCR（可选步骤）：文字进 structures.ocr_text 字段。

    画面文字**不拼进正文**——口播字幕与画面文字分字段保存，冲突不隐藏归属
    （某句话来自口播、某个数值来自哪一帧的画面，都能分别回到对应时间）。
    OCR 不可用/零文字 → 显式 skipped（降级可见），不静默。
    """

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        assets: dict = ctx.data.get("assets") or {}
        parsed: dict = ctx.data.get("parsed") or {}
        if not assets:
            return StepResult.ok(ocr=0, ocr_note="无关键帧（纯音频或未抽帧）")
        fn = _OCR_FN or _default_ocr
        fps = _fps_of(ctx.data.get("keyframe_fps") or "1/60")
        structures: list[dict] = list(parsed.get("structures") or [])
        done = 0
        for i, key in enumerate(sorted(assets)):
            text = (fn(assets[key]) or "").strip()
            if not text:
                continue
            structures.append({"kind": "ocr_text", "location": f"t:{_fmt_ts(i / fps)}",
                               "pointer": key, "text": text})
            done += 1
        if parsed:
            parsed["structures"] = structures
        if not done:
            return StepResult.ok(ocr=0, ocr_note="OCR 不可用或零文字（显式降级）")
        return StepResult.ok(ocr=done)
