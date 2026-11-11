# -*- coding: utf-8 -*-
"""从当日日报 Markdown 生成邮件纯文本正文（最多 15 条，超出注明见附件）。"""
from __future__ import annotations

import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATE = "2026-10-07"
MD = os.path.join(HERE, "out", f"jobs_{DATE}.md")
OUT = os.path.join(HERE, "out", "mail_body.txt")

KEYS = ("招聘单位", "岗位类别", "人数", "学历", "报名截止", "报名起止",
        "薪酬待遇", "发布")

text = open(MD, encoding="utf-8").read()
blocks = re.split(r"^## ", text, flags=re.M)[1:]
jobs = []
for b in blocks:
    head, _, rest = b.partition("\n")
    job = {"title": re.sub(r"^\d+\.\s*", "", head).strip()}
    for line in rest.splitlines():
        m = re.match(r"- ([^：]+)：(.*)", line.strip())
        if m:
            job[m.group(1).strip()] = m.group(2).strip()
    jobs.append(job)

total = len(jobs)
new_count = 1

def clip(s, n=70):
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"

lines = [
    f"本地宝郑州招聘 · 招聘信息日报（{DATE}）",
    "",
    f"本次筛出 {total} 个岗位（本次新增 {new_count} 条，其余为历史重复）。",
    "",
]
for i, j in enumerate(jobs[:15], 1):
    unit = clip(j.get("招聘单位") or "(未识别单位)", 40)
    cat = clip(j.get("岗位类别") or "未注明", 30)
    hc = j.get("人数") or "人数未注明"
    lines.append(f"{i}. {unit}")
    lines.append(f"   岗位类别：{cat}｜人数：{hc}")
    bits = []
    bits.append(f"学历：{clip(j.get('学历'), 30) or '未注明'}")
    end = j.get("报名截止") or j.get("报名起止") or "未注明"
    bits.append(f"报名截止：{clip(end, 30)}")
    lines.append("   " + "；".join(bits))
    sal = clip(j.get("薪酬待遇"), 80)
    if sal:
        lines.append(f"   薪酬待遇：{sal}")
    lines.append("")

if total > 15:
    lines.append(f"（其余 {total - 15} 个岗位详见附件 HTML / Markdown）")
    lines.append("")
lines.append("完整岗位信息见附件 jobs_2026-10-07.html 与 jobs_2026-10-07.md。")
lines.append("本邮件由 wechat-jobs 流水线自动生成，信息以官方公告原文为准")

body = "\n".join(lines)
with open(OUT, "w", encoding="utf-8") as fh:
    fh.write(body)
print(f"岗位总数={total}  取前 {min(15, total)} 条写入正文")
print("----")
print(body)
