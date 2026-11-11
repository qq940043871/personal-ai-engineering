#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断：为什么 OpenCode Go 的模型在 WorkBuddy 里不显示思考。

对比两个上游返回的字段名，找出 WorkBuddy 认的是哪个字段。
"""
import json
import os
import urllib.request
import urllib.error

OC_KEY = os.environ.get("OPENCODE_API_KEY", "")
BC_KEY = os.environ.get("BC_API_KEY", "")


def post(url, headers, body, timeout=120):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return -1, "EXC: %s" % e


def dump_message(tag, raw):
    print("---- %s ----" % tag)
    try:
        d = json.loads(raw)
    except Exception:
        print("  非 JSON:", raw[:300])
        return
    if "error" in d:
        print("  ERROR:", json.dumps(d["error"], ensure_ascii=False)[:300])
        return
    msg = d.get("choices", [{}])[0].get("message", {})
    print("  message 字段名 :", sorted(msg.keys()))
    for k in ("content", "reasoning_content", "reasoning", "thinking", "analysis"):
        if k in msg:
            v = msg[k]
            v = (v[:90] + "...") if isinstance(v, str) and len(v) > 90 else v
            print("     %-18s = %r" % (k, v))
    print("  usage 字段名   :", sorted((d.get("usage") or {}).keys()))
    print("  choices[0] 键  :", sorted(d.get("choices", [{}])[0].keys()))


print("=" * 72)
print("  A. 你的 BC 网关（据说能显示思考）")
print("=" * 72)
st, raw = post(
    "https://shanghai.017.pub/ds41f/v1/chat/completions",
    {"Content-Type": "application/json", "Authorization": "Bearer %s" % BC_KEY},
    {"model": "BC-DeepSeek-V4.1-Flash",
     "messages": [{"role": "user", "content": "1+1=? 只回答数字"}],
     "max_tokens": 400},
)
print("  HTTP", st)
dump_message("BC 非流式", raw)

print()
print("=" * 72)
print("  B. OpenCode Go 直连")
print("=" * 72)
st, raw = post(
    "https://opencode.ai/zen/go/v1/chat/completions",
    {"Content-Type": "application/json",
     "Authorization": "Bearer %s" % OC_KEY,
     "x-opencode-session": "probe-reasoning"},
    {"model": "deepseek-v4.1-flash",
     "messages": [{"role": "user", "content": "1+1=? 只回答数字"}],
     "max_tokens": 400},
)
print("  HTTP", st)
dump_message("OC 非流式", raw)

print()
print("=" * 72)
print("  C. OpenCode Go 流式（看 delta 里带什么）")
print("=" * 72)
data = json.dumps({
    "model": "deepseek-v4.1-flash",
    "messages": [{"role": "user", "content": "1+1=?"}],
    "stream": True,
    "max_tokens": 400,
}).encode("utf-8")
req = urllib.request.Request(
    "https://opencode.ai/zen/go/v1/chat/completions",
    data=data,
    headers={"Content-Type": "application/json",
             "Authorization": "Bearer %s" % OC_KEY,
             "x-opencode-session": "probe-stream"},
    method="POST",
)
delta_keys = []
with urllib.request.urlopen(req, timeout=120) as r:
    for line in r:
        line = line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        for ch in obj.get("choices", []):
            d = ch.get("delta", {})
            for k in d.keys():
                if k not in delta_keys:
                    delta_keys.append(k)
print("  delta 里出现过的键 :", delta_keys)

print()
print("=" * 72)
print("  D. Luna/Muse 走 /responses —— output 里有什么")
print("=" * 72)
st, raw = post(
    "https://opencode.ai/zen/go/v1/responses",
    {"Content-Type": "application/json",
     "Authorization": "Bearer %s" % OC_KEY,
     "x-opencode-session": "probe-responses"},
    {"model": "gpt-6-luna",
     "input": "1+1=? 只回答数字",
     "reasoning": {"summary": "auto", "effort": "medium"}},
)
print("  HTTP", st)
try:
    d = json.loads(raw)
    if "error" in d:
        print("  ERROR:", json.dumps(d["error"], ensure_ascii=False)[:400])
    else:
        print("  顶层键:", sorted(d.keys()))
        for item in d.get("output", []) or []:
            print("   - item.type =", item.get("type"),
                  "| 子类型 =", [c.get("type") for c in (item.get("content") or [])])
except Exception as e:
    print("  解析失败:", e, raw[:300])
