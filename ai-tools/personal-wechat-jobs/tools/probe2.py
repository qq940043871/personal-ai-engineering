# -*- coding: utf-8 -*-
"""看看郑州人事考试网首页有没有可直接消费的招聘公告列表。"""
import re

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")

r = requests.get("https://www.zzrsks.com.cn/", headers={"User-Agent": UA}, timeout=15)
r.encoding = r.apparent_encoding or "utf-8"
soup = BeautifulSoup(r.text, "lxml")

print("title:", (soup.title.get_text(strip=True) if soup.title else "")[:80])
print("\n--- 含「招聘/公告/考试」的链接 ---")
seen = set()
for a in soup.find_all("a", href=True):
    t = a.get_text(strip=True)
    if not t:
        continue
    if re.search(r"招聘|招录|公告|考试|报名|成绩|岗位", t):
        href = a["href"]
        if (t, href) in seen:
            continue
        seen.add((t, href))
        print(f"{t[:38]:40s} {href[:80]}")
    if len(seen) >= 25:
        break
