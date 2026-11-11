#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 WorkBuddy 的打包产物里搜索推理字段的处理逻辑。

这些是压缩 JS，行可能极长，所以按字符窗口截取，不做行式打印。
"""
import os

ROOT = r"C:\Program Files\WorkBuddy\resources\app.asar.unpacked"
TARGETS = [
    r"cli\dist\codebuddy-lite-wb.mjs",
    r"cli\dist\codebuddy-headless.js",
    r"cli\product.json",
    r"cli\product.internal.json",
    r"cli\product.ioa.json",
]
# 也扫 lazy-* 目录
for d in ("cli\\dist\\lazy-lite-wb", "cli\\dist\\lazy-headless"):
    p = os.path.join(ROOT, d)
    if os.path.isdir(p):
        for f in os.listdir(p):
            if f.endswith((".mjs", ".js")):
                TARGETS.append(os.path.join(d, f))

NEEDLES = ["supportsReasoning", "reasoning_content", "reasoning_effort", "reasoningContent"]

for rel in TARGETS:
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        continue
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except Exception as e:
        print("[skip]", rel, e)
        continue
    for needle in NEEDLES:
        idx = 0
        hits = 0
        while hits < 3:
            idx = txt.find(needle, idx)
            if idx < 0:
                break
            snippet = txt[max(0, idx - 200): idx + 260].replace("\n", " ")
            print("=" * 70)
            print("FILE   : %s" % rel)
            print("NEEDLE : %s   @%d" % (needle, idx))
            print("CTX    : ...%s..." % snippet)
            idx += len(needle)
            hits += 1
        if hits:
            print()
