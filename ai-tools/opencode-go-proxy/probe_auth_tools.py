#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精确定位：/messages 要哪种鉴权；/responses 的 function_call 完整形状。"""
import json
import os
import sys
import uuid
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

BASE = os.environ.get("OPENCODE_BASE", "https://opencode.ai/zen/go/v1").rstrip("/")
KEY = os.environ.get("OPENCODE_API_KEY", "").strip()
UA = "workbuddy-oc-proxy/1.3"


def post(path, body, extra=None, label=""):
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer %s" % KEY,
        "x-opencode-session": "probe-" + uuid.uuid4().hex[:12],
        "User-Agent": UA,
        "Accept-Encoding": "identity",
    }
    if extra:
        headers.update(extra)
    req = urlrequest.Request(BASE + path,
                             data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                             headers=headers, method="POST")
    print("=" * 78)
    print("[%s] POST %s" % (label, path))
    print("       headers:", {k: (v[:14] + "..." if k in ("Authorization", "x-api-key") else v)
                              for k, v in extra_headers_preview(extra).items()})
    try:
        with urlrequest.urlopen(req, timeout=180) as r:
            raw = r.read().decode("utf-8", errors="replace")
            print("   >>> HTTP %s" % r.status)
            print(json.dumps(json.loads(raw), ensure_ascii=False, indent=2)[:3500])
            return r.status, raw
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        print("   >>> HTTP %s" % e.code)
        print("   <<<", raw[:900])
        return e.code, raw
    except URLError as e:
        print("   >>> URLError", e)
        return None, ""


def extra_headers_preview(extra):
    d = {"Authorization": "Bearer " + KEY}
    d.update(extra or {})
    return d


msgs = {"model": "minimax-m3", "max_tokens": 32,
        "messages": [{"role": "user", "content": "只回复：OK"}]}

print("核心问题：/messages 用哪种鉴权头？\n")
post("/messages", msgs, {"x-api-key": KEY}, label="x-api-key only")
post("/messages", msgs, {"x-api-key": KEY, "anthropic-version": "2023-06-01"},
     label="x-api-key + anthropic-version")
post("/messages", dict(msgs, model="qwen3.8-flash"),
     {"x-api-key": KEY, "anthropic-version": "2023-06-01"}, label="qwen3.8-flash")

print("\n\n########## /responses 工具调用完整形状 ##########\n")
status, raw = post("/responses", {
    "model": "gpt-6-luna",
    "input": [{"type": "message", "role": "user",
               "content": [{"type": "input_text",
                            "text": "查一下北京今天天气，必须调用 get_weather 工具。"}]}],
    "tools": [{"type": "function", "name": "get_weather", "description": "查询城市天气",
               "parameters": {"type": "object",
                              "properties": {"city": {"type": "string"}},
                              "required": ["city"]}}],
    "tool_choice": "auto",
}, label="luna tools")

fc = None
try:
    rj = json.loads(raw)
    for item in rj.get("output", []) or []:
        print("   output item type=%s" % item.get("type"))
        if item.get("type") == "function_call":
            fc = item
    if fc:
        print("\n   完整 function_call 项:")
        print(json.dumps(fc, ensure_ascii=False, indent=2))
        print("\n   回灌 function_call_output 续一轮:")
        post("/responses", {
            "model": "gpt-6-luna",
            "input": [
                {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "查一下北京今天天气。"}]},
                {"type": "function_call", "call_id": fc.get("call_id"),
                 "name": fc.get("name"), "arguments": fc.get("arguments")},
                {"type": "function_call_output", "call_id": fc.get("call_id"),
                 "output": "{\"temp\":25,\"weather\":\"晴\"}"},
            ],
            "tools": [{"type": "function", "name": "get_weather", "description": "查询城市天气",
                       "parameters": {"type": "object",
                                      "properties": {"city": {"type": "string"}},
                                      "required": ["city"]}}],
        }, label="function_call_output 多轮")
except Exception as e:
    print("解析失败:", e, raw[:300])
