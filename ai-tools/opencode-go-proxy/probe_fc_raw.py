#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打印 function_call 相关 SSE 事件的完整 JSON，确认 call_id 在哪个事件里。"""
import json
import os
import uuid
from urllib import request as urlrequest
from urllib.error import HTTPError

BASE = os.environ.get("OPENCODE_BASE", "https://opencode.ai/zen/go/v1").rstrip("/")
KEY = os.environ.get("OPENCODE_API_KEY", "").strip()

req = urlrequest.Request(
    BASE + "/responses",
    data=json.dumps({
        "model": "gpt-6-luna",
        "input": [{"type": "message", "role": "user",
                   "content": [{"type": "input_text",
                                "text": "查一下广州天气，必须调用 get_weather。"}]}],
        "tools": [{"type": "function", "name": "get_weather", "description": "查询城市天气",
                   "parameters": {"type": "object",
                                  "properties": {"city": {"type": "string"}},
                                  "required": ["city"]}}],
        "tool_choice": "auto",
        "stream": True,
    }, ensure_ascii=False).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer %s" % KEY,
        "x-opencode-session": "probe-" + uuid.uuid4().hex[:12],
        "User-Agent": "workbuddy-oc-proxy/1.3",
        "Accept": "text/event-stream",
        "Accept-Encoding": "identity",
    },
    method="POST",
)
INTEREST = ("output_item.added", "arguments.delta", "arguments.done", "output_item.done")
try:
    with urlrequest.urlopen(req, timeout=180) as r:
        for line in r:
            line = line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                continue
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            t = ev.get("type", "")
            if any(k in t for k in INTEREST):
                print("-" * 70)
                print("TYPE:", t)
                print(json.dumps(ev, ensure_ascii=False, indent=2)[:1200])
except HTTPError as e:
    print("HTTP", e.code, e.read().decode("utf-8", "replace")[:400])
