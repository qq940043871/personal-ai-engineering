#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""区分 403/1010 是「Cloudflare 拦 UA」还是「key 失效」。"""
import json
import os
import sys
import uuid
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

BASE = os.environ.get("OPENCODE_BASE", "https://opencode.ai/zen/go/v1").rstrip("/")
KEY = os.environ.get("OPENCODE_API_KEY", "").strip()

CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def post(path, body, ua, extra=None, label=""):
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer %s" % KEY,
        "x-opencode-session": "probe-" + uuid.uuid4().hex[:12],
        "Accept-Encoding": "identity",
    }
    if ua:
        headers["User-Agent"] = ua
    if extra:
        headers.update(extra)
    req = urlrequest.Request(BASE + path,
                             data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                             headers=headers, method="POST")
    print("-" * 78)
    print("[%s] POST %s  UA=%r" % (label, path, (ua or "")[:40]))
    try:
        with urlrequest.urlopen(req, timeout=120) as r:
            raw = r.read().decode("utf-8", errors="replace")
            print("   >>> HTTP %s   <<< %s" % (r.status, raw[:400]))
            return r.status, raw
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        print("   >>> HTTP %s   <<< %s" % (e.code, raw[:400]))
        return e.code, raw
    except URLError as e:
        print("   >>> URLError", e)
        return None, ""


chat = {"model": "deepseek-v4.1-flash",
        "messages": [{"role": "user", "content": "只回复：OK"}],
        "max_tokens": 32}

print("### A. 用代理的 UA（默认 Python-urllib）")
post("/chat/completions", chat, None, label="urllib默认UA")

print("### B. 用代理自己的 UA 字符串")
post("/chat/completions", chat, "workbuddy-oc-proxy/1.3", label="代理UA")

print("### C. 伪装 Chrome UA")
post("/chat/completions", chat, CHROME, label="ChromeUA")

print("### D. Chrome UA + /messages (minimax-m3)")
post("/messages", {"model": "minimax-m3", "max_tokens": 32,
                   "messages": [{"role": "user", "content": "只回复：OK"}]},
     CHROME, extra={"anthropic-version": "2023-06-01"}, label="ChromeUA messages")

print("### E. Chrome UA + /responses 带工具")
post("/responses", {
    "model": "gpt-6-luna",
    "input": [{"type": "message", "role": "user",
               "content": [{"type": "input_text", "text": "查北京天气，要调工具"}]}],
    "tools": [{"type": "function", "name": "get_weather", "description": "查天气",
               "parameters": {"type": "object",
                              "properties": {"city": {"type": "string"}},
                              "required": ["city"]}}],
    "tool_choice": "auto",
}, CHROME, label="ChromeUA responses+tools")
