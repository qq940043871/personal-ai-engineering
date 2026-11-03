# -*- coding: utf-8 -*-
"""编排入口：剧本 JSON → TTS 旁白 → 逐幕渲染编码 → 拼接成片。

用法:
  python src/build_video.py --storyboard storyboards/llm_base10.json
  python src/build_video.py --storyboard ... --dry-run      # 只看分幕计划
  python src/build_video.py --storyboard ... --only s05,s06 # 重做指定幕
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from src import encode as enc  # noqa: E402
from src import render as rnd  # noqa: E402
from src import storyboard as sb  # noqa: E402
from src import tts as tts  # noqa: E402


def parse_args():
    ap = argparse.ArgumentParser(description="把剧本 JSON 渲染成教程视频 MP4")
    ap.add_argument("--storyboard", required=True, help="剧本 JSON 路径")
    ap.add_argument("--out", default=None, help="成片路径（默认 output/<id>.mp4）")
    ap.add_argument("--fps", type=int, default=None, help="覆盖剧本 fps")
    ap.add_argument("--no-tts", action="store_true", help="跳过旁白合成（纯字幕）")
    ap.add_argument("--only", default=None, help="只重做指定幕，逗号分隔，如 s05,s06")
    ap.add_argument("--force", action="store_true", help="忽略已有幕片段缓存，全部重渲染")
    ap.add_argument("--keep-frames", action="store_true", help="保留中间帧（调试用）")
    ap.add_argument("--dry-run", action="store_true", help="只打印分幕与时长计划")
    return ap.parse_args()


def plan_durations(meta, scenes, work_dir, no_tts):
    """旁白合成 + 幕时长对齐；返回 (有声幕数, 静音幕数)。"""
    tts_cache = work_dir / "tts_cache"
    voiced = silent = 0
    for sc in scenes:
        # 注入系列级展示字段（模板顶栏/水印用）
        sc.setdefault("seriesTag", meta.get("seriesTag", "AI 学习教程"))
        sc.setdefault("seriesTitle", meta["title"])
        sc.setdefault("watermark", meta.get("watermark", meta["seriesTag"] + "系列"))
        audio = None
        text = (sc.get("narration") or "").strip()
        if meta["narration"] and not no_tts and text:
            audio, fresh = tts.synth(text, meta["voice"], tts_cache)
            if audio:
                sc["narrationAudio"] = str(audio)
        if audio:
            dur = enc.probe_duration(audio) + 0.7
            voiced += 1
        else:
            dur = sb.min_duration(sc)
            if text:
                silent += 1
        sc["duration"] = round(max(dur, sb.min_duration(sc)), 3)
    return voiced, silent


def print_plan(meta, scenes):
    print(f"\n剧本: {meta['title']}  （{meta['id']}，{len(scenes)} 幕，{meta['fps']} fps，"
          f"{meta['width']}x{meta['height']}）")
    print("-" * 88)
    total = 0.0
    for sc in scenes:
        d = sc["duration"]
        total += d
        nar = sc.get("narration", "")
        flag = "🔊" if sc.get("narrationAudio") else ("  " if not nar else "🔇")
        print(f"  {sc['id']}  {sc['type']:<8} {d:6.1f}s  {flag} "
              f"{sc.get('chapter', ''):　<8} {sc.get('title', nar[:26])}")
    print("-" * 88)
    print(f"  预计成片时长 {total / 60:.1f} 分钟，渲染帧数约 {int(total * meta['fps'])} 帧\n")
    return total


def main():
    args = parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    sbdata = sb.load(args.storyboard)
    meta, scenes = sbdata["meta"], sbdata["scenes"]
    if args.fps:
        meta["fps"] = args.fps
    if args.only:
        keep = {x.strip() for x in args.only.split(",") if x.strip()}
        scenes = [s for s in scenes if s["id"] in keep]
        if not scenes:
            sys.exit(f"--only 没有匹配到任何幕: {keep}")

    work_dir = ROOT / "output" / meta["id"]
    out_path = Path(args.out) if args.out else ROOT / "output" / f"{meta['id']}.mp4"

    print("== 阶段 1/3：旁白合成与时长规划 ==")
    voiced, silent = plan_durations(meta, scenes, work_dir, args.no_tts)
    total = print_plan(meta, scenes)
    if args.dry_run:
        print("(dry-run 结束，未渲染)")
        return
    if silent:
        print(f"[warn] {silent} 幕有旁白文本但未合成成功（无网络或 --no-tts），将以无声字幕呈现")

    ffmpeg = enc.find_ffmpeg()
    print("== 阶段 2/3：逐幕渲染 + 编码 ==")
    from playwright.sync_api import sync_playwright

    t0 = time.time()
    # 拼接清单始终按完整剧本顺序取全部幕（--only 只影响重渲染范围）
    parts = [ROOT / "output" / meta["id"] / "scenes" / f"{s['id']}.mp4"
             for s in sbdata["scenes"]]
    with sync_playwright() as p:
        browser, engine = rnd.open_browser(p)
        print(f"  渲染内核: {engine}")
        page = rnd.new_page(browser, meta["width"], meta["height"])
        try:
            for idx, sc in enumerate(scenes, 1):
                scene_mp4 = work_dir / "scenes" / f"{sc['id']}.mp4"
                if scene_mp4.exists() and not args.force:
                    print(f"  ({idx}/{len(scenes)}) {sc['id']} 已有缓存片段，跳过 "
                          f"(--force 可重渲染)")
                    continue
                frames = work_dir / "frames" / sc["id"]
                t1 = time.time()
                n = rnd.render_scene(page, sc, meta["fps"], frames)
                enc.encode_scene(frames, meta["fps"], sc["duration"], scene_mp4,
                                 audio_path=sc.get("narrationAudio"), ffmpeg=ffmpeg)
                if not args.keep_frames:
                    import shutil
                    shutil.rmtree(frames, ignore_errors=True)
                print(f"  ({idx}/{len(scenes)}) {sc['id']} {sc['type']:<8} "
                      f"{n} 帧 {time.time() - t1:5.1f}s → {scene_mp4.name}")
        finally:
            browser.close()

    print("== 阶段 3/3：拼接成片 ==")
    enc.concat(parts, out_path, ffmpeg=ffmpeg)
    size_mb = out_path.stat().st_size / 1048576
    real = enc.probe_duration(out_path)
    print(f"\n✔ 完成: {out_path}")
    print(f"  时长 {real / 60:.1f} 分钟 ｜ {size_mb:.1f} MB ｜ "
          f"渲染耗时 {(time.time() - t0) / 60:.1f} 分钟 ｜ 旁白 {voiced}/{len(scenes)} 幕")


if __name__ == "__main__":
    main()
