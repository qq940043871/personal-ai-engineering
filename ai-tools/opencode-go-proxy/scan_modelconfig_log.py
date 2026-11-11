#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按时间顺序抽取 [ModelConfig] 相关日志，看清"哪个模型 -> 什么思考结果"。"""
import glob
import os
import re

LOG_DIR = r"C:\Users\qq940\.workbuddy\logs\2026-10-01"
pat = re.compile(r"(\[ModelConfig\][^\r\n]{0,200})")

rows = []
for f in sorted(glob.glob(os.path.join(LOG_DIR, "*.log"))):
    try:
        fh = open(f, encoding="utf-8", errors="replace")
    except Exception:
        continue
    try:
        for line in fh:
            if "[ModelConfig]" not in line:
                continue
            m = pat.search(line)
            if not m:
                continue
            ts = ""
            i = line.find("[2026")
            if i >= 0:
                ts = line[i + 1:i + 19]
            rows.append((ts, m.group(1)))
    finally:
        fh.close()

print("共 %d 条 [ModelConfig] 记录" % len(rows))
print()
for ts, msg in rows:
    s = msg.replace("sessionId=", "sid=")
    s = re.sub(r"sid=[0-9a-f\-]{36}", "sid=<S>", s)
    s = re.sub(r"\(no maxOutputTokens[^)]*\)", "", s)
    s = re.sub(r"requestOptions\.model=[^,]+,?\s*", "", s)
    s = re.sub(r"options\.model=[^,]+,?\s*", "", s)
    print("%s  %s" % (ts, s[:190]))
