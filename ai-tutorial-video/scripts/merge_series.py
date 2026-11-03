# -*- coding: utf-8 -*-
"""把系列短视频合并为完整教程长片（ffmpeg concat，无重编码）。

用法:
  python scripts/merge_series.py --inputs output/a.mp4 output/b.mp4 --out output/series.mp4
  python scripts/merge_series.py --list series.txt --out output/series.mp4
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import encode as enc  # noqa: E402


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="合并多个 MP4 为教程长片")
    ap.add_argument("--inputs", nargs="*", default=[], help="待合并 MP4（按顺序）")
    ap.add_argument("--list", default=None, help="文本文件，每行一个 MP4 路径，# 开头为注释")
    ap.add_argument("--out", required=True, help="输出路径")
    args = ap.parse_args()

    parts = [Path(p) for p in args.inputs]
    if args.list:
        for line in Path(args.list).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                parts.append(Path(line))
    if len(parts) < 2:
        sys.exit("至少需要两个输入片段")
    for p in parts:
        if not p.exists():
            sys.exit(f"输入不存在: {p}")

    out = enc.concat(parts, args.out)
    dur = enc.probe_duration(out)
    size = out.stat().st_size / 1048576
    print(f"✔ 合并完成: {out}\n  {len(parts)} 段 ｜ {dur / 60:.1f} 分钟 ｜ {size:.1f} MB")


if __name__ == "__main__":
    main()
