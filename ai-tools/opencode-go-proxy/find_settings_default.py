#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""1) 找 alwaysThinkingEnabled 的默认值；2) 找 models.json 的读取与字段 schema。"""
import os

ROOT = r"C:\Program Files\WorkBuddy\resources\app.asar.unpacked\cli\dist"

TASKS = [
    ("alwaysThinkingEnabled 的设置定义", ["alwaysThinkingEnabled"], 6, 500),
    ("models.json 读取", ["models.json"], 4, 700),
    ("custom model 字段解析", ["isCustomModelRequest"], 4, 600),
]

for label, needles, maxhits, win in TASKS:
    print("#" * 78)
    print("# " + label)
    print("#" * 78)
    for fn in os.listdir(ROOT):
        if not fn.endswith((".js", ".mjs")):
            continue
        path = os.path.join(ROOT, fn)
        try:
            txt = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for needle in needles:
            idx = 0
            n = 0
            while n < maxhits:
                idx = txt.find(needle, idx)
                if idx < 0:
                    break
                snip = txt[max(0, idx - win): idx + win].replace("\n", " ")
                print("--- %s @%d ---" % (fn, idx))
                print(snip)
                print()
                idx += len(needle)
                n += 1
    print()
