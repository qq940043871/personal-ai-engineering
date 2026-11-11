#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摸清 /responses 与 /messages 的流式 SSE 事件名（尤其工具调用相关）。"""
import json
import os
import uuid
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

BASE = os.environ.get("OPENCODE_BASE", "https://opencode.ai/zen/go/v1").rstrip("/")
KEY = os.environ.get("OPENCODE_API_KEY", "").strip()
UA = "workbuddy-oc-proxy/1.3"


def stream(path, body, extra=None, label="", limit=120):
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer %s" % KEY,
        "x-opencode-session": "probe-" + uuid.uuid4().hex[:12],
        "User-Agent": UA,
        "Accept": "text/event-stream",
        "Accept-Encoding": "identity",
    }
    if extra:
        headers.update(extra)
    req = urlrequest.Request(BASE + path,
                             data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                             headers=headers, method="POST")
    print("=" * 78)
    print("[%s] STREAM %s" % (label, path))
    try:
        with urlrequest.urlopen(req, timeout=180) as r:
            print("   >>> HTTP %s" % r.status)
            n = 0
            for line in r:
                line = line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("event:"):
                    print("   event:", line[6:].strip())
                    continue
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    try:
                        ev = json.loads(raw)
                        t = ev.get("type", "?")
                        # 只打印事件类型 + 关键字段，避免刷屏
                        key = {}
                        for k in ("delta", "index", "item_id", "output_index"):
                            if k in ev:
                                key[k] = ev[k]
                        if "item" in ev:
                            it = ev["item"]
                            key["item.type"] = it.get("type")
                            key["item.name"] = it.get("name")
                        if "content_block" in ev:
                            cb = ev["content_block"]
                            key["cb.type"] = cb.get("type")
                            key["cb.name"] = cb.get("name")
                        if t == "message_delta":
                            key["stop_reason"] = (ev.get("delta") or {}).get("stop_reason")
                        print("   data:", t, json.dumps(key, ensure_ascii=False)[:160])
                    except Exception:
                        print("   data:", raw[:160])
                    n += 1
                    if n >= limit:
                        print("   ... (截断)")
                        return
    except HTTPError as e:
        print("   >>> HTTP %s  <<< %s" % (e.code, e.read().decode("utf-8", "replace")[:400]))
    except URLError as e:
        print("   >>> URLError", e)


print("### 1. Responses 流式 + 工具（Luna）")
stream("/responses", {
    "model": "gpt-6-luna",
    "input": [{"type": "message", "role": "user",
               "content": [{"type": "input_text",
                            "text": "查一下上海今天天气，必须调用 get_weather。"}]}],
    "tools": [{"type": "function", "name": "get_weather", "description": "查询城市天气",
               "parameters": {"type": "object",
                              "properties": {"city": {"type": "string"}},
                              "required": ["city"]}}],
    "tool_choice": "auto",
    "stream": True,
}, label="responses stream tools")

print("\n### 2. Anthropic 流式（MiniMax）")
stream("/messages", {
    "model": "minimax-m3",
    "max_tokens": 64,
    "messages": [{"role": "user", "content": "数到三"}],
    "stream": True,
}, extra={"x-api-key": KEY, "anthropic-version": "2023-06-01"},
    label="messages stream")

print("\n### 3. Anthropic 流式 + 工具（MiniMax）")
stream("/messages", {
    "model": "minimax-m3",
    "max_tokens": 128,
    "messages": [{"role": "user", "content": "查一下北京天气，必须调用 get_weather。"}],
    "tools": [{"name": "get_weather", "description": "查询城市天气",
               "input_schema": {"type": "object",
                                "properties": {"city": {"type": "string"}},
                                "required": ["city"]}}],
    "stream": True,
}, extra={"x-api-key": KEY, "anthropic-version": "2023-06-01"},
    label="messages stream tools")
