#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定位自定义模型（models.json）的字段 schema。"""
import os

ROOT = r"C:\Program Files\WorkBuddy\resources\app.asar.unpacked"
FILES = [
    r"cli\dist\codebuddy-lite-wb.mjs",
    r"cli\dist\codebuddy-headless.js",
]

NEEDLES = ["useCustomProtocol", "onlyReasoning", "defaultEffort"]

for rel in FILES:
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        continue
    txt = open(path, encoding="utf-8", errors="replace").read()
    for needle in NEEDLES:
        print("=" * 78)
        print("%s   ::   %s" % (os.path.basename(rel), needle))
        print("=" * 78)
        idx = 0
        n = 0
        while n < 4:
            idx = txt.find(needle, idx)
            if idx < 0:
                break
            print("@%-9d ...%s..." % (idx, txt[max(0, idx - 420): idx + 420].replace("\n", " ")))
            print()
            idx += len(needle)
            n += 1
        if n == 0:
            print("(未找到)\n")
