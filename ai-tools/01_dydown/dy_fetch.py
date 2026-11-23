"""抖音单视频下载器（绕开 cookie / a_bogus 签名）

原理：用 Playwright 真实加载抖音视频页，拦截播放器发出的 DASH 流请求，
拿到带签名的 media-video / media-audio 地址后直接下载，再用 ffmpeg 合并。

为什么不用 f2 / yt-dlp：
  - f2 需要登录 cookie，本地 dy-one.yaml 里的 cookie 早已过期（403 Forbidden）；
  - f2 `--auto-cookie edge` 要求关闭全部浏览器进程（Edge 常驻 30+ 进程，不可行）；
  - yt-dlp `--cookies-from-browser chrome` 撞 Chrome 127+ App-Bound Encryption（DPAPI 失败），
    edge 则因数据库被独占锁而无法复制。
本脚本完全不需要 cookie —— 页面公开可播即可。

用法：
  python dy_fetch.py "https://www.douyin.com/video/7679040345799150900"
  python dy_fetch.py "https://www.douyin.com/jingxuan?modal_id=7679040345799150900"
  python dy_fetch.py <url> --outdir "D:/some/dir" --dry-run

依赖：playwright（含 chromium）、requests、ffmpeg（PATH 中或 --ffmpeg 指定）
"""

import argparse
import asyncio
import os
import re
import subprocess
import sys

FFMPEG_DEFAULT = r"C:\DevTools\ffmpeg-6.1.1-essentials_build\bin\ffmpeg.exe"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
)
HEADERS = {"User-Agent": UA, "Referer": "https://www.douyin.com/", "Accept": "*/*"}


def parse_aweme_id(url: str) -> str:
    """从 /video/<id> 或 ?modal_id=<id> 里取作品 id。"""
    for pat in (r"/video/(\d+)", r"modal_id=(\d+)", r"/note/(\d+)"):
        m = re.search(pat, url)
        if m:
            return m.group(1)
    raise SystemExit("[!] 无法从链接解析作品 id，请传 /video/<id> 或 ?modal_id=<id> 形式的链接")


async def grab_streams(page_url: str, aweme_id: str, wait_rounds: int):
    from playwright.async_api import async_playwright

    found = {"video": None, "audio": None, "title": ""}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--use-gl=angle",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--mute-audio",
            ],
        )
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900}, user_agent=UA, locale="zh-CN"
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = await ctx.new_page()

        def on_response(resp):
            u = resp.url
            # 只认目标作品自己的流（URL 里带 o<xxx> 段无法直判，用视频/音频轨类型区分）
            if found["video"] is None and "media-video-avc1" in u and "douyinvod" in u:
                found["video"] = u
            elif found["audio"] is None and "media-audio-und-mp4a" in u and "douyinvod" in u:
                found["audio"] = u

        page.on("response", on_response)

        print(f"[*] 打开页面：{page_url}", flush=True)
        try:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"[!] 页面加载告警（继续等待流）：{type(e).__name__}", flush=True)

        for _ in range(wait_rounds):
            if found["video"] and found["audio"]:
                break
            await page.wait_for_timeout(2500)

        try:
            found["title"] = (await page.title()).replace(" - 抖音", "").strip()
        except Exception:
            pass

        await browser.close()

    return found


def download(url: str, path: str) -> int:
    import requests

    with requests.get(url, headers=HEADERS, stream=True, timeout=180) as r:
        r.raise_for_status()
        total = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(262144):
                f.write(chunk)
                total += len(chunk)
    print(f"[*] 已保存 {os.path.basename(path)}  {total / 1024 / 1024:.1f} MB", flush=True)
    return total


def safe_name(s: str, limit: int = 60) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", s).strip(" .")
    return s[:limit] or "douyin"


def main():
    ap = argparse.ArgumentParser(description="抖音单视频下载（Playwright 截流法）")
    ap.add_argument("url", help="抖音视频链接，支持 /video/<id> 与 ?modal_id=<id>")
    ap.add_argument("--outdir", default=None, help="输出目录，默认 ./video/douyin")
    ap.add_argument("--ffmpeg", default=FFMPEG_DEFAULT, help="ffmpeg 可执行文件路径")
    ap.add_argument("--dry-run", action="store_true", help="只打印截到的流地址，不下载")
    ap.add_argument("--wait", type=int, default=12, help="等待流的轮数（每轮 2.5 秒）")
    args = ap.parse_args()

    aweme_id = parse_aweme_id(args.url)
    page_url = f"https://www.douyin.com/video/{aweme_id}"
    print(f"[*] 作品 id：{aweme_id}")

    found = asyncio.run(grab_streams(page_url, aweme_id, args.wait))
    if not found["video"]:
        print("[!] 没截到视频流。可能原因：作品已删除/私密、页面弹了验证码、或者需要登录。")
        print("    排查：把 --wait 调大，或临时改成 headless=False 看页面长什么样。")
        return 2

    print(f"[*] 标题：{found['title'] or '(空)'}")
    print(f"[*] 视频轨：{found['video'][:120]}...")
    print(f"[*] 音频轨：{(found['audio'] or '(无音频)')[:120]}...")

    if args.dry_run:
        print("\n--dry-run 结束，未下载。")
        return 0

    outdir = args.outdir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "video", "douyin")
    os.makedirs(outdir, exist_ok=True)

    vpath = os.path.join(outdir, f"{aweme_id}_v.mp4")
    apath = os.path.join(outdir, f"{aweme_id}_a.mp4")
    final = os.path.join(outdir, f"{safe_name(found['title'])}_{aweme_id}.mp4")

    download(found["video"], vpath)
    has_audio = bool(found["audio"])
    if has_audio:
        download(found["audio"], apath)

    ffmpeg = args.ffmpeg if os.path.exists(args.ffmpeg) else "ffmpeg"
    if has_audio:
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", vpath, "-i", apath,
               "-c", "copy", "-movflags", "+faststart", final]
    else:
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", vpath,
               "-c", "copy", "-movflags", "+faststart", final]

    print("[*] 合并中…", flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print("[!] ffmpeg 失败：", p.stderr[-400:])
        return 3

    for f in (vpath, apath):
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass

    print(f"[OK] {final}  {os.path.getsize(final) / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
