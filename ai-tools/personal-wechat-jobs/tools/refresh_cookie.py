# -*- coding: utf-8 -*-
r"""用仓库自带的 CDP 独立 profile（v10 cookie）启动 Edge，让页面续期登录态后读出 cookie。

用法（本地宝郑州招聘 cookie 过期时跑这个）：
    C:/Users/qq940/anaconda3/python.exe -X utf8 tools/refresh_cookie.py
    然后把 out/cookie_fresh.txt 的内容写回 config.yaml 的 source.weread.cookie
    （写前先 cp 备份 config.yaml）。

为什么必须走独立 profile（实测结论，别再用别的路子）：
    · Edge/Chrome 127+ 对「默认 user-data-dir」的 cookie 用 v20 App-Bound 加密，
      密文绑定 Windows 账户 + 浏览器安装路径 —— 复制到任何别的 profile 目录都会
      被浏览器当成损坏数据直接清掉（实测 10 条 weread cookie 全部解不出来）。
    · Chrome/Edge 136+ 起，在「默认 user-data-dir」下直接拒绝 --remote-debugging-port。
    · 而独立的非默认 profile（%TEMP%\cdp_edge_profile）用的是普通 v10 加密，
      既允许调试、又能通过 CDP 读出明文。
    · 卷影副本(VSS)能把锁住的 Cookies 文件抠出来，但对 v20 一样没用 —— 已在 2026-10-07 验证。

为什么不用主 profile：
    Edge/Chrome 127+ 对「默认 user-data-dir」的 cookie 用 v20 App-Bound 加密，
    复制出来必然解不开；且 136+ 起在默认目录下直接禁用 --remote-debugging-port。
    而独立的非默认 profile 用的是普通 v10 加密，既允许调试又能读出明文，
    这正是 tools/cookie_via_cdp.py 当初建 %TEMP%\cdp_edge_profile 的原因。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

import websocket

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from tools.cookie_via_cdp import (cdp_ready, launch_with_debug,  # noqa: E402
                                  get_cookies_via_cdp)

PORT = 9222
BOOK = "MP_WXS_3925849039"
OUT = os.path.join(HERE, "out", "cookie_fresh.txt")


def list_targets():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=3) as r:
        return json.load(r)


def ask(ws, mid, method, params=None):
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid:
            return msg


def main() -> int:
    if cdp_ready(PORT):
        print(f"[ok] 端口 {PORT} 已有调试实例，直接连接")
    else:
        print("[info] 用独立 profile 启动带调试端口的 Edge ...")
        if not launch_with_debug("edge", PORT, "https://weread.qq.com/web/shelf"):
            print("[error] 启动失败")
            return 1

    ws = None
    for _ in range(30):
        time.sleep(1)
        try:
            pages = [t for t in list_targets() if t.get("type") == "page"]
        except Exception:
            continue
        page = None
        for t in pages:
            if "weread" in (t.get("url") or ""):
                page = t
                break
        if page is None and pages:
            page = pages[0]
        if page is None:
            continue
        try:
            ws = websocket.create_connection(page["webSocketDebuggerUrl"],
                                             timeout=20, suppress_origin=True)
            break
        except Exception as exc:
            print("  ws 连接失败:", exc)
    if ws is None:
        print("[error] 连不上页面 target")
        return 1

    try:
        print("  打开微信读书，等页面续期登录态 ...")
        ask(ws, 1, "Page.enable")
        ask(ws, 2, "Page.navigate", {"url": "https://weread.qq.com/web/shelf"})
        time.sleep(15)

        # 页内直接验接口（用浏览器自己的会话）
        js = ("(async()=>{try{const r=await fetch('/web/mp/articles?bookId=%s&offset=0&count=1',"
              "{credentials:'include'});const t=await r.text();return t.slice(0,220);}"
              "catch(e){return 'FETCH_ERR '+e;}})()" % BOOK)
        r = ask(ws, 3, "Runtime.evaluate",
                {"expression": js, "awaitPromise": True, "returnByValue": True})
        val = (r.get("result", {}).get("result", {}) or {}).get("value")
        print("  页内接口返回:", str(val)[:220])

        r2 = ask(ws, 4, "Storage.getCookies", {})
        allc = r2.get("result", {}).get("cookies", [])
        weread = {c["name"]: c["value"] for c in allc if "weread" in c.get("domain", "")}
        print("  Storage.getCookies(weread):", len(weread), sorted(weread)[:12])
        nav = get_cookies_via_cdp(PORT)
        print("  Network.getCookies(weread):", len(nav), sorted(nav)[:12])
    finally:
        ws.close()

    merged = dict(nav or {})
    merged.update(weread)
    if "wr_skey" not in merged:
        print("[fail] 没拿到 wr_skey")
        return 1
    line = "; ".join(f"{k}={v}" for k, v in merged.items())
    print("\n>>> COOKIE LINE:\n" + line + "\n")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(line)
    print("saved ->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
