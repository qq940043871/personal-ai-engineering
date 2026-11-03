# -*- coding: utf-8 -*-
"""ffmpeg 封装：查找可执行文件、时长探测、逐幕编码、系列拼接。"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:  # 兜底：imageio-ffmpeg 自带的 ffmpeg 二进制
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise RuntimeError("未找到 ffmpeg，请安装（winget install Gyan.FFmpeg）或 pip install imageio-ffmpeg")


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        tail = "\n".join((r.stderr or "").strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg 失败: {' '.join(map(str, cmd[:6]))}...\n{tail}")
    return r


def probe_duration(path):
    """ffprobe 读取媒体时长（秒）。"""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "json", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {r.stderr}")
    return float(json.loads(r.stdout)["format"]["duration"])


def encode_scene(frames_dir, fps, duration, out_path, audio_path=None, ffmpeg=None):
    """帧序列 (+ 旁白) → 单幕 MP4。

    音轨恒定存在（真实旁白或静音），保证后续 concat -c copy 流参数一致。
    """
    ffmpeg = ffmpeg or find_ffmpeg()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-framerate", str(int(fps)),
           "-i", str(Path(frames_dir) / "f_%06d.jpg")]
    if audio_path:
        cmd += ["-i", str(audio_path), "-af", f"apad=whole_dur={duration:.3f}"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-r", str(int(fps)), "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
            "-video_track_timescale", "90000", "-t", f"{duration:.3f}",
            "-movflags", "+faststart", str(out_path)]
    _run(cmd)
    return out_path


def concat(parts, out_path, ffmpeg=None):
    """同参数 MP4 无重编码拼接。"""
    ffmpeg = ffmpeg or find_ffmpeg()
    parts = [Path(p) for p in parts]
    missing = [p for p in parts if not p.exists()]
    if missing:
        raise FileNotFoundError(f"缺少待拼接片段: {missing}")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in parts:
            f.write("file '" + str(p.resolve()).replace("\\", "/") + "'\n")
        list_path = f.name
    try:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
              "-c", "copy", "-movflags", "+faststart", str(out_path)])
    finally:
        Path(list_path).unlink(missing_ok=True)
    return out_path
