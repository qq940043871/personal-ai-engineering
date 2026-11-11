#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出 WorkBuddy 中与思考（reasoning）相关的关键代码窗口。"""
import os

ROOT = r"C:\Program Files\WorkBuddy\resources\app.asar.unpacked"
FILE = os.path.join(ROOT, r"cli\dist\codebuddy-lite-wb.mjs")

txt = open(FILE, encoding="utf-8", errors="replace").read()


def dump(label, start, length):
    print("=" * 78)
    print(label)
    print("=" * 78)
    print(txt[start:start + length])
    print()


# 1. configureThinkingSettings 完整实现
i = txt.find("async configureThinkingSettings")
if i > 0:
    dump("configureThinkingSettings 完整实现", i, 2200)

# 2. alwaysThinkingEnabled 的所有出现
print("=" * 78)
print("alwaysThinkingEnabled 所有出现")
print("=" * 78)
idx = 0
n = 0
while n < 6:
    idx = txt.find("alwaysThinkingEnabled", idx)
    if idx < 0:
        break
    print("@%d  ...%s..." % (idx, txt[max(0, idx - 180): idx + 220].replace("\n", " ")))
    print()
    idx += 1
    n += 1
