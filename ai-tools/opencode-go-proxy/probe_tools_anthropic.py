#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性诊断：直连 OpenCode Go，摸清两件事的真实协议形状。

  1) Anthropic /messages 端点：Qwen / MiniMax 到底能不能用、要哪些头、返回什么结构
  2) Responses /responses 端点：function_call（工具调用）在网络上的真实字段形状

只用来"取证"，不参与正式代理逻辑。跑完可以直接删。
"""
import json
import os
import sys
import uuid
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

BASE = os.environ.get("OPENCODE_BASE", "https://opencode.ai/zen/go/v1").rstrip("/")
KEY = os.environ.get("OPENCODE_API_KEY", "").strip()
if not KEY:
    print("需要先设 OPENCODE_API_KEY")
    sys.exit(1)


def post(path, body, extra_headers=None, label=""):
    url = BASE + path
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer %s" % KEY,
        "x-opencode-session": "probe-" + uuid.uuid4().hex[:12],
        "Accept-Encoding": "identity",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urlrequest.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers, method="POST",
    )
    print("=" * 78)
    print("[PROBE] %s  POST %s" % (label, url))
    print("        body =", json.dumps(body, ensure_ascii=False)[:300])
    try:
        with urlrequest.urlopen(req, timeout=120) as r:
            raw = r.read().decode("utf-8", errors="replace")
            print("        >>> HTTP %s" % r.status)
            print("        <<<", raw[:2000])
            return r.status, raw
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        print("        >>> HTTP %s" % e.code)
        print("        <<<", raw[:2000])
        return e.code, raw
    except URLError as e:
        print("        >>> URLError", e)
        return None, ""


# ---------------- 1) Anthropic /messages ----------------

print("\n########## 1. Anthropic /messages 端点 ##########\n")

anth_body = {
    "model": "minimax-m3",
    "max_tokens": 64,
    "messages": [{"role": "user", "content": "只回复两个字：收到"}],
}

# 1a 带 anthropic-version，Bearer 认证
post("/messages", anth_body,
     extra_headers={"anthropic-version": "2023-06-01", "x-api-key": KEY},
     label="anthropic-version + x-api-key + Bearer")

# 1b 只带 Bearer，不带 anthropic-version
post("/messages", anth_body, label="只 Bearer，无 anthropic-version")

# 1c 试 qwen
post("/messages", dict(anth_body, model="qwen3.8-max"), label="qwen3.8-max")

# 1d 无鉴权头以外的路径猜测：/v1/messages vs 已在 BASE 内
post("/messages", dict(anth_body, model="minimax-m2.7"), label="minimax-m2.7")


# ---------------- 2) Responses tool_calls ----------------

print("\n########## 2. Responses 工具调用真实形状 ##########\n")

tools = [{
    "type": "function",
    "name": "get_weather",
    "description": "查询指定城市的天气",
    "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "城市名"}},
        "required": ["city"],
    },
}]

resp_body = {
    "model": "gpt-6-luna",
    "input": [{
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text",
                     "text": "帮我查一下北京现在的天气，必须调用工具。"}],
    }],
    "tools": tools,
    "tool_choice": "auto",
}

status, raw = post("/responses", resp_body, label="luna + tools")

# 2b 回归：带 function_call_output 的多轮形状（如果上面成功，取 call_id 续一轮）
try:
    rj = json.loads(raw)
    out = rj.get("output", []) or []
    fc = None
    for item in out:
        if item.get("type") == "function_call":
            fc = item
            break
    if fc:
        print("\n[PROBE] 拿到 function_call，回灌 function_call_output 试多轮")
        follow = {
            "model": "gpt-6-luna",
            "input": [
                {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "帮我查一下北京现在的天气。"}]},
                {"type": "function_call", "call_id": fc.get("call_id"),
                 "name": fc.get("name"), "arguments": fc.get("arguments")},
                {"type": "function_call_output", "call_id": fc.get("call_id"),
                 "output": "{\"temp\":25,\"weather\":\"晴\"}"},
            ],
            "tools": tools,
        }
        post("/responses", follow, label="回灌 function_call_output")
    else:
        print("\n[PROBE] 上游没有返回 function_call，output 类型列表：",
              [i.get("type") for i in out])
except Exception as e:
    print("解析失败:", e)

print("\n探测结束。")
