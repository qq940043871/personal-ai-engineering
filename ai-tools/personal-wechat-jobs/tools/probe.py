# -*- coding: utf-8 -*-
"""探活脚本：确认免 Docker 路线的外部依赖与接口可达性。"""
import importlib

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
     "Referer": "https://weread.qq.com/"}

for m in ("browser_cookie3", "requests", "feedparser"):
    try:
        importlib.import_module(m)
        print(f"[dep] {m}: OK")
    except Exception as e:
        print(f"[dep] {m}: MISSING ({e.__class__.__name__})")

print("\n--- weread 接口探活（无 cookie，看返回码/是否 404）---")
try:
    r = requests.get("https://weread.qq.com/web/mp/articles",
                     params={"bookId": "MP_WXS_3073282833", "offset": 0},
                     headers=H, timeout=12)
    print("articles:", r.status_code, r.text[:220].replace("\n", " "))
except Exception as e:
    print("articles: EXC", e.__class__.__name__, e)

print("\n--- 郑州人社局官网探活（绕开微信的替代源）---")
for url in ("https://rsj.zhengzhou.gov.cn/", "https://www.zzrsks.com.cn/"):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=12)
        print(f"{url} -> {r.status_code}, {len(r.content)} bytes, "
              f"enc={r.apparent_encoding}")
    except Exception as e:
        print(f"{url} -> EXC {e.__class__.__name__}: {e}")
