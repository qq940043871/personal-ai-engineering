# -*- coding: utf-8 -*-
"""探测 /web/mp/content 接口的真实入参与返回结构。

背景：pipeline 跑真实数据时，每条文章的正文拉取都失败：
    [warn] 正文拉取失败，保留摘要：/web/mp/content 返回非 JSON（HTTP 200）：
返回体是空字符串，说明参数名或路径不对。本脚本用同一套 cookie，
把几种候选参数名/路径组合都试一遍，打印每种组合的真实返回，定位正确写法。
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from src.weread import WeReadClient, UA, BASE

COOKIE = ("wr_fp=1944574376; wr_skey=lD0bq_q1; wr_vid=10715363; wr_ql=0; "
          "wr_rt=web%40Xb6U3l5TUvFDPz9UNzD_AL")
BOOK_ID = "MP_WXS_3222425727"


def raw_get(path, params, cookie=COOKIE):
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{BASE}/web/mp/reader/{BOOK_ID}",
        "Cookie": cookie,
    })
    r = s.get(f"{BASE}{path}", params=params, timeout=15)
    return r


def main() -> int:
    c = WeReadClient(COOKIE)

    print("=== 1. 先拿一条真实条目，看清字段名 ===")
    items = c.list_articles(BOOK_ID, offset=0, count=3)
    if not items:
        print("[error] 列表为空，cookie 可能已失效")
        return 1
    first = items[0]
    print(json.dumps(first, ensure_ascii=False, indent=2)[:1200])

    rid = first.get("reviewId") or ""
    print(f"\nreviewId = {rid!r}")
    print(f"token 段  = {rid.rsplit('_', 1)[-1] if rid else ''!r}")

    token = rid.rsplit("_", 1)[-1] if "_" in rid else rid

    print("\n=== 2. 遍历候选参数组合，看哪个真出正文 ===")
    combos = [
        ("/web/mp/content", {"reviewId": rid}),
        ("/web/mp/content", {"reviewId": token}),
        ("/web/mp/content", {"id": rid}),
        ("/web/mp/content", {"bookId": BOOK_ID, "reviewId": rid}),
        ("/web/mp/content", {"readerId": rid}),
        ("/web/mp/article", {"reviewId": rid}),
        ("/web/mp/detail", {"reviewId": rid}),
        ("/web/review/content", {"reviewId": rid}),
        ("/web/mp/content", {"reviewId": rid, "type": "1"}),
    ]
    for path, params in combos:
        try:
            r = raw_get(path, params)
            body = r.text or ""
            ct = r.headers.get("content-type", "")
            tag = ""
            if "json" in ct:
                try:
                    j = r.json()
                    tag = " <-- JSON ok, errCode=" + str(j.get("errCode")) + \
                          " keys=" + str(list(j.keys())[:8])
                except Exception:
                    tag = " (声称 json 但解析失败)"
            print(f"\n[{path}] params={params}  HTTP {r.status_code} len={len(body)} ct={ct}{tag}")
            print("   前 200 字：", body[:200].replace("\n", " "))
        except Exception as exc:
            print(f"\n[{path}] params={params}  EXC {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
