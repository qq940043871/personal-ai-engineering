# -*- coding: utf-8 -*-
"""通过 CDP（Chrome DevTools Protocol）从运行中的 Edge/Chrome 读取 cookie。

为什么走这条路：
    Edge/Chrome 现在给 cookie 数据库加了独占锁 + App-Bound Encryption，
    第三方进程直接读文件基本无望（实测 GetLastError=32 共享冲突）。
    但浏览器自己的调试端口是官方支持的接口 —— 让它自己把 cookie 吐出来，
    既不用管理员权限，也不用关浏览器。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from typing import Dict, Optional

DEFAULT_PORT = 9222


def _browser_paths() -> Dict[str, str]:
    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    return {
        "edge": [
            os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
        ],
        "chrome": [
            os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
        ],
    }


def find_exe(browser: str) -> str:
    for p in _browser_paths().get(browser, []):
        if os.path.exists(p):
            return p
    return ""


def cdp_ready(port: int) -> Optional[dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version",
                                    timeout=2) as r:
            return json.load(r)
    except Exception:
        return None


def launch_with_debug(browser: str, port: int, start_url: str = "https://weread.qq.com") -> bool:
    exe = find_exe(browser)
    if not exe:
        print(f"[error] 找不到 {browser} 的可执行文件")
        return False
    # 用独立的 user-data-dir，避免和用户正在用的实例冲突（同 profile 无法重复启动）
    profile = os.path.join(os.environ.get("TEMP", "."), f"cdp_{browser}_profile")
    os.makedirs(profile, exist_ok=True)
    cmd = [exe, f"--remote-debugging-port={port}",
           f"--user-data-dir={profile}", "--no-first-run",
           "--no-default-browser-check", start_url]
    print(f"[info] 启动：{exe}")
    print(f"[info] 独立 profile：{profile}")
    subprocess.Popen(cmd, close_fds=True)
    for _ in range(20):
        time.sleep(0.5)
        if cdp_ready(port):
            return True
    return False


def get_cookies_via_cdp(port: int, domain_filter: str = "weread") -> Dict[str, str]:
    """通过 CDP 的 Network.getCookies 拿 cookie。"""
    try:
        import websocket  # websocket-client
    except ImportError:
        return {}

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as r:
            targets = json.load(r)
    except Exception as exc:
        print(f"[error] 读 targets 失败: {exc}")
        return {}

    pages = [t for t in targets if t.get("type") == "page"]
    if not pages:
        print("[error] 没有可用的页面 target")
        return {}
    ws_url = pages[0]["webSocketDebuggerUrl"]

    # 新版 Chromium 会拒绝带 http:// 开头的 Origin 的 WebSocket 握手（403）。
    # 用 CDP 自带的字段抑制 Origin（等价于 --remote-allow-origins 的绕法），
    # 这样用户不用为了迁就我们而重启浏览器。
    try:
        ws = websocket.create_connection(
            ws_url, timeout=10, suppress_origin=True)
    except Exception:
        # 老版本 websocket-client 没有 suppress_origin 参数，退回手动去头
        ws = websocket.create_connection(
            ws_url, timeout=10, origin=None,
            header=["Origin: devtools://devtools"])
    try:
        ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        ws.recv()
        ws.send(json.dumps({"id": 2, "method": "Network.getCookies",
                            "params": {"urls": ["https://weread.qq.com",
                                                "https://weread.qq.com/web/mp/articles"]}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 2:
                cookies = msg.get("result", {}).get("cookies", [])
                return {c["name"]: c["value"] for c in cookies
                        if domain_filter in c.get("domain", "")}
    finally:
        ws.close()
    return {}


def _emit(cookies: Dict[str, str]) -> int:
    if not cookies or "wr_skey" not in cookies:
        print(f"[warn] 没拿到 wr_skey（拿到 {len(cookies)} 条）")
        print("       请在弹出的浏览器窗口里登录 weread.qq.com，然后重跑本脚本。")
        return 1
    line = "; ".join(f"{k}={v}" for k, v in cookies.items())
    print("\n成功！复制下面这行到 config.yaml：")
    print()
    print(line)
    print()
    print("记得把 source.weread.cookie_from 改成 manual")
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "out", "cookie.txt"), "w", encoding="utf-8") as fh:
        fh.write(line)
    print("（同时已存到 out/cookie.txt）")
    return 0


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="通过 CDP 从浏览器读取 weread cookie")
    p.add_argument("--browser", default="edge", choices=["edge", "chrome"])
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--attach", action="store_true",
                   help="只连接已开调试端口的浏览器，不自己启动")
    a = p.parse_args()

    if cdp_ready(a.port):
        print(f"[ok] 端口 {a.port} 已有调试实例，直接连接")
    elif a.attach:
        print(f"[error] 端口 {a.port} 没有调试实例。请先这样启动浏览器：\n"
              f'  "{find_exe(a.browser)}" --remote-debugging-port={a.port}')
        return 1
    else:
        if not launch_with_debug(a.browser, a.port):
            print("[error] 启动带调试端口的浏览器失败")
            return 1

    cookies = get_cookies_via_cdp(a.port)
    if cookies:
        return _emit(cookies)

    # 页面可能还没登录，等用户登完再读一次
    print("\n[info] 请在打开的浏览器里完成 weread.qq.com 扫码登录，")
    print("       登录完成后回到这里按回车，我会再读一次。")
    try:
        input()
    except EOFError:
        return 1
    return _emit(get_cookies_via_cdp(a.port))


if __name__ == "__main__":
    raise SystemExit(main())
