#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 CodeBuddy 打包产物里搜「思考」相关字段，确认自定义模型怎么配才能开思考。

压缩 JS 行极长，不能按行 grep，按字符窗口截取。
"""
import io
import os

TARGETS = [
    r"C:\Program Files\nodejs\node_modules\@tencent-ai\codebuddy-code\dist\codebuddy-lite-wb.mjs",
]
KEYS = ["onlyReasoning", "canDisableThinking", "supportsReasoning"]


def scan(path, keys, win=380, maxhits=5):
    if not os.path.exists(path):
        print("[MISS] %s" % path)
        return
    txt = io.open(path, encoding="utf-8", errors="replace").read()
    print("=== %s  (%d chars) ===" % (os.path.basename(path), len(txt)))
    for k in keys:
        hits = []
        idx = 0
        while True:
            i = txt.find(k, idx)
            if i == -1:
                break
            hits.append(i)
            idx = i + 1
            if len(hits) > 40:
                break
        if not hits:
            print("\n[%s] 无命中" % k)
            continue
        print("\n[%s] 共 %d 处命中，展示前 %d 处：" % (k, len(hits), min(maxhits, len(hits))))
        for n, i in enumerate(hits[:maxhits], 1):
            s = max(0, i - win)
            e = min(len(txt), i + win)
            print("  --- #%d @%d ---" % (n, i))
            print("  " + txt[s:e].replace("\n", " "))
    print()


if __name__ == "__main__":
    for t in TARGETS:
        scan(t, KEYS)
