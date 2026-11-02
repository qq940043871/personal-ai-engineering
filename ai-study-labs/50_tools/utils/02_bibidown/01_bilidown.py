# -*- coding: utf-8 -*-
"""
B站视频下载工具 - 基于 yt-dlp
支持：单个视频、分P视频、合集/系列、番剧
"""

import os
import sys
import subprocess
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent.absolute()
VIDEO_DIR = SCRIPT_DIR / "video"
COOKIES_FILE = SCRIPT_DIR / "cookies.txt"

VIDEO_DIR.mkdir(parents=True, exist_ok=True)


def get_video_quality_option(quality="best"):
    """
    获取视频质量配置
    
    quality:
        - "best": 最好质量（默认）
        - "4k": 4K画质
        - "1080p": 1080P画质
        - "720p": 720P画质
        - "480p": 480P画质
        - "audio": 仅音频（mp3）
    """
    if quality == "audio":
        return {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        }
    
    if quality == "best":
        format_str = "bv*+ba/b"
    elif quality == "4k":
        format_str = "bv*[height<=2160]+ba/b[height<=2160]"
    elif quality == "1080p":
        format_str = "bv*[height<=1080]+ba/b[height<=1080]"
    elif quality == "720p":
        format_str = "bv*[height<=720]+ba/b[height<=720]"
    elif quality == "480p":
        format_str = "bv*[height<=480]+ba/b[height<=480]"
    else:
        format_str = "bv*+ba/b"
    
    return {"format": format_str}


def build_ydl_opts(output_template=None, quality="best", cookies_path=None):
    """构建 yt-dlp 配置"""
    
    if output_template is None:
        output_template = str(
            VIDEO_DIR / "%(playlist_title|)s" / "%(title)s [%(id)s].%(ext)s"
        )
    
    if cookies_path is None:
        cookies_path = str(COOKIES_FILE) if COOKIES_FILE.exists() else None
    
    opts = {
        "outtmpl": output_template,
        "ignoreerrors": True,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "noprogress": False,
        "writethumbnail": False,
        "writesubtitles": False,
        "no_warnings": False,
        "merge_output_format": "mp4",
        "postprocessor_args": {
            "ffmpeg_i": ["-hwaccel", "auto"],
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
        },
    }
    
    if cookies_path and os.path.exists(cookies_path):
        opts["cookies"] = cookies_path
        print(f"  [i] 使用 cookies: {cookies_path}")
    else:
        print("  [!] 未找到 cookies 文件，可能无法下载高清视频或会员视频")
    
    quality_opts = get_video_quality_option(quality)
    opts.update(quality_opts)
    
    return opts


def download_with_python_lib(urls, opts):
    """使用 yt-dlp Python API 下载"""
    try:
        import yt_dlp
    except ImportError:
        print("[x] 未安装 yt-dlp，正在尝试安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp"])
        import yt_dlp
    
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.download(urls)


def download_with_cli(urls, opts):
    """使用 yt-dlp 命令行下载（更稳定的输出显示）"""
    cmd = ["yt-dlp"]
    
    if opts.get("cookies"):
        cmd.extend(["--cookies", opts["cookies"]])
    
    cmd.extend(["-f", opts.get("format", "bv*+ba/b")])
    cmd.extend(["-o", opts.get("outtmpl", "%(title)s.%(ext)s")])
    cmd.extend(["--merge-output-format", "mp4"])
    
    if opts.get("retries"):
        cmd.extend(["--retries", str(opts["retries"])])
    
    if opts.get("fragment_retries"):
        cmd.extend(["--fragment-retries", str(opts["fragment_retries"])])
    
    if opts.get("concurrent_fragment_downloads"):
        cmd.extend(["--concurrent-fragments", str(opts["concurrent_fragment_downloads"])])
    
    if opts.get("http_headers"):
        for key, value in opts["http_headers"].items():
            cmd.extend(["--add-header", f"{key}:{value}"])
    
    if opts.get("ignoreerrors"):
        cmd.append("--ignore-errors")
    
    if "postprocessors" in opts:
        for pp in opts["postprocessors"]:
            if pp.get("key") == "FFmpegExtractAudio":
                cmd.extend(["-x", "--audio-format", pp.get("preferredcodec", "mp3"),
                            "--audio-quality", pp.get("preferredquality", "192")])
    
    cmd.extend(["--no-warnings"])
    cmd.extend(urls)
    
    print(f"\n[i] 执行命令: {' '.join(cmd[:5])} ...")
    
    result = subprocess.run(cmd)
    return result.returncode


def download(urls, quality="best", use_cli=True, cookies_path=None):
    """主下载函数"""
    if isinstance(urls, str):
        urls = [urls]
    
    print(f"[i] 共 {len(urls)} 个下载链接")
    print(f"[i] 视频质量: {quality}")
    print(f"[i] 输出目录: {VIDEO_DIR}")
    print(f"[i] 下载方式: {'命令行' if use_cli else 'Python API'}")
    print("=" * 60)
    
    opts = build_ydl_opts(quality=quality, cookies_path=cookies_path)
    
    try:
        if use_cli:
            return download_with_cli(urls, opts)
        else:
            return download_with_python_lib(urls, opts)
    except KeyboardInterrupt:
        print("\n[!] 用户中断下载")
        return 1
    except Exception as e:
        print(f"\n[x] 下载出错: {e}")
        import traceback
        traceback.print_exc()
        return 2


def interactive_mode():
    """交互式下载模式"""
    print("=" * 60)
    print("           B站视频下载工具 - yt-dlp")
    print("=" * 60)
    print()
    
    url = input("请输入视频/合集/番剧URL: ").strip()
    if not url:
        print("[!] 未输入URL，退出")
        return
    
    print("\n可选画质:")
    print("  1) 最好质量 (best)")
    print("  2) 4K 画质")
    print("  3) 1080P 画质")
    print("  4) 720P 画质")
    print("  5) 480P 画质")
    print("  6) 仅音频 (MP3)")
    
    choice = input("请选择画质 [默认 1]: ").strip() or "1"
    
    quality_map = {
        "1": "best",
        "2": "4k",
        "3": "1080p",
        "4": "720p",
        "5": "480p",
        "6": "audio",
    }
    quality = quality_map.get(choice, "best")
    
    mode = input("使用命令行模式? [y/n, 默认 y]: ").strip().lower()
    use_cli = mode != "n"
    
    print()
    download(url, quality=quality, use_cli=use_cli)


if __name__ == "__main__":
    
    # 方式1: 命令行参数: python 01_bilidown.py URL [quality]
    #         例如: python 01_bilidown.py https://www.bilibili.com/video/BVxxx 1080p
    if len(sys.argv) >= 2:
        url = sys.argv[1]
        quality = sys.argv[2] if len(sys.argv) >= 3 else "best"
        download(url, quality=quality)
        sys.exit(0)
    
    # 方式2: 直接运行脚本，使用硬编码的示例URL
    # 合集URL示例（确保URL包含合集ID）
    urls = [
        "https://www.bilibili.com/video/BV1LG4weoEBv/?spm_id_from=333.1245.0.0",
    ]
    
    # 如需交互式输入，取消下一行注释:
    # interactive_mode()
    # sys.exit(0)
    
    # 方式3: 直接下载上面配置的URL
    download(urls, quality="best")
