# -*- coding: utf-8 -*-
"""校验邮件正文里的「查看原文」链接是否真的打得开。

为什么需要它：微信短链 token 用 Base64 URL-safe 编码（字符集 A-Za-z0-9-_），
而微信读书 reviewId 里把 `_` 转义成了 `~`。忘了还原就会生成
`/s/<含~的token>`，微信返回一个 31KB 的「参数错误」页 ——
**HTTP 状态码仍然是 200**，只检查状态码完全发现不了。

所以本工具的判断依据是「页面体量 + 特征串」，不是状态码。

用法：
    python tools/check_mail_links.py                       # 查最新的 mail_body_*.html
    python tools/check_mail_links.py out/xxx.html          # 查指定文件
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")}


def is_real_article(text: str) -> bool:
    """判断响应是不是真文章页。

    失败页两个特征：体量约 31KB、正文含「参数错误」且没有文章结构。
    """
    if "参数错误" in text:
        return False
    return "js_content" in text or "msg_title" in text


def main() -> int:
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        cands = sorted(glob.glob(os.path.join(ROOT, "out", "mail_body_*.html")))
        if not cands:
            print("out/ 下没有 mail_body_*.html，先跑一次流水线。")
            return 1
        path = cands[-1]

    html = open(path, encoding="utf-8").read()
    urls = list(dict.fromkeys(
        re.findall(r'href="(https?://mp\.weixin\.qq\.com/s/[^"]+)"', html)))
    if not urls:
        print(f"{os.path.basename(path)}：没找到 mp.weixin.qq.com 链接。")
        return 0

    print(f"校验 {os.path.basename(path)} 里的 {len(urls)} 个链接\n")
    bad = 0
    for u in urls:
        try:
            r = requests.get(u, headers=HEADERS, timeout=25)
            real = is_real_article(r.text)
        except Exception as exc:
            real, r = False, None
            print(f"  请求异常：{type(exc).__name__}: {exc}")
        if not real:
            bad += 1
        size = f"{len(r.text):>9}" if r is not None else "        -"
        print(f"{'OK ' if real else 'BAD'} {size}  {u}")

    if bad:
        print(f"\n❌ {bad}/{len(urls)} 个链接打不开。"
              f"\n   若链接里含 `~`，说明 reviewId 的转义没还原（应为 `_`），"
              f"检查 src/weread.py 的 review_to_url()。")
    else:
        print(f"\n✅ {len(urls)}/{len(urls)} 个链接全部可正常打开。")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
