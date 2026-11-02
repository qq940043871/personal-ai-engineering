"""链路 B：ffmpeg 抽流 + 本地 ASR 转写（03 文档 §三）。

时间戳是音视频唯一可靠结构：块边界对齐 VAD/自然停顿，每块带 [mm:ss] 锚点可回跳源视频。
ASR 错误是链路噪声不是静默失败——低置信度段在正文上显式标记 [?mm:ss]。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ownrag.core.pipeline import StepContext
from ownrag.core.registry import Step, StepResult, register
from ownrag.ingest.base import ParsedDoc


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
            capture_output=True, text=True, timeout=120)
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
            capture_output=True, text=True, timeout=3600)
        if not wav.exists() or wav.stat().st_size == 0:
            return StepResult.fail("ffmpeg 未产出有效音轨")

        assets: dict[str, str] = {}
        if src.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi"}:
            kf_dir = out_dir / "keyframes"
            kf_dir.mkdir(exist_ok=True)
            fps = params.get("keyframe_fps", "1/60")  # 默认每 60s 一帧
            subprocess.run(
                [ffmpeg, "-y", "-v", "error", "-i", str(src), "-vf", f"fps={fps}",
                 str(kf_dir / "kf_%04d.jpg")], capture_output=True, timeout=3600)
            assets = {p.stem: str(p) for p in sorted(kf_dir.glob("*.jpg"))}

        ctx.data.update({"audio_wav": str(wav), "duration_sec": duration, "assets": assets})
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
            raise RuntimeError("faster-whisper 未安装（pip install 'ownrag[asr]'）")
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
            raise RuntimeError("funasr 未安装（pip install 'ownrag[funasr]'）")
        model = AutoModel(model=model_name, vad_model="fsmn-vad", punc_model="ct-punc")
        res = model.generate(input=wav, batch_size_s=300)
        sentences = (res[0] or {}).get("sentence_info", [])
        return [{"start": s["start"] / 1000, "end": s["end"] / 1000,
                 "text": s["text"].strip(), "conf": round(float(s.get("sp", 1.0)), 2)}
                for s in sentences if s.get("text", "").strip()]


# ---------------------------------------------------------------- 步骤：按时间切分
@register("segment_by_time")
class SegmentByTime(Step):
    """按时长上限聚段成块：锚点 [mm:ss] 内嵌正文，低置信度段显式标记。"""

    def run(self, ctx: StepContext, params: dict) -> StepResult:
        segments: list[dict] = ctx.data.get("segments") or []
        max_sec = float(params.get("max_sec", 60))
        blocks: list[str] = []
        buf: list[dict] = []
        buf_start = 0.0

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
            if not buf:
                buf_start = seg["start"]
            elif seg["end"] - buf_start > max_sec:
                flush()
            buf.append(seg)
        flush()

        if not blocks:
            return StepResult.fail("切分零块")
        src_path = Path(ctx.data["source_path"])
        doc = ParsedDoc(
            doc_id=ctx.doc_id, source_type="av", markdown="\n\n".join(blocks),
            metadata={"source_file": src_path.name,
                      "duration_sec": ctx.data.get("duration_sec", 0),
                      **ctx.data.get("source_meta", {})},
            assets={k: v for k, v in (ctx.data.get("assets") or {}).items()},
            stats={"blocks": len(blocks), "duration_sec": ctx.data.get("duration_sec", 0)},
        )
        ctx.data["parsed"] = doc.to_dict()
        return StepResult.ok(blocks=len(blocks))
