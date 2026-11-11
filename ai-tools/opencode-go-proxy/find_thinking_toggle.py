#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出 ACP 配置项里的 thinking 开关，以及 forcesReasoning 的使用点。"""
import os

ROOT = r"C:\Program Files\WorkBuddy\resources\app.asar.unpacked\cli\dist"
FILES = ["codebuddy-lite-wb.mjs", "codebuddy-headless.js"]

for fn in FILES:
    path = os.path.join(ROOT, fn)
    txt = open(path, encoding="utf-8", errors="replace").read()

    # 1) getConfigOptions 完整实现
    i = txt.find("async getConfigOptions(")
    if i > 0:
        print("=" * 78)
        print("%s :: getConfigOptions 完整实现" % fn)
        print("=" * 78)
        print(txt[i:i + 3000])
        print()

    # 2) forcesReasoning 使用点
    print("=" * 78)
    print("%s :: forcesReasoning 使用点" % fn)
    print("=" * 78)
    idx = 0
    n = 0
    while n < 5:
        idx = txt.find("forcesReasoning", idx)
        if idx < 0:
            break
        print("@%-9d ...%s..." % (idx, txt[max(0, idx - 250): idx + 250].replace("\n", " ")))
        print()
        idx += 1
        n += 1
    print()
