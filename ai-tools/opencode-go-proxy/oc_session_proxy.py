#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenCode Go  ->  WorkBuddy / CodeBuddy 统一适配代理
==================================================

【为什么需要这个】
WorkBuddy 的自定义模型（models.json）有两个先天限制，导致它连不上 OpenCode Go：

  1. 不会发私有请求头 x-opencode-session
     -> 上游返回 400 MissingSessionID

  2. 会把 models.json 条目的 `id` 字段**原样当作模型名**发给上游
     -> 上游返回 400 "Model is unavailable"
        （models.json 里没有独立的 model 字段，id 就是模型名）

本代理把这两件事都替 WorkBuddy 办了：

  - 注入 x-opencode-session 头
  - 把 WorkBuddy 发来的本地 id 翻译成 OpenCode 认识的真实模型名
  - 按模型协议分流：
        Chat Completions 模型（deepseek / glm / kimi / mimo ...）-> 原样透传
        Responses 模型（luna / grok / muse）-> 翻译成 Responses 协议再回译
        Anthropic 模型（qwen / minimax）-> 翻译成 Messages 协议再回译

【v1.4 新增】
  1. Responses 协议**工具调用（function calling）**全链路支持
     - 请求：tools / tool_choice / 历史里的 tool_calls、tool 结果 一并翻译
     - 响应：function_call -> chat 的 tool_calls（含流式增量）
  2. Anthropic Messages 协议支持（原来直接 501）
     - /messages 端点 + x-api-key 鉴权
     - tool_use / tool_result / thinking 与 chat 结构双向翻译
     - 流式 content_block_* 事件 -> chat chunk

【依赖】仅 Python 标准库。
"""

import os
import sys
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

# ---- 控制台编码加固：横幅全 ASCII，此处理是双保险 ----
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------- 配置 ----------------
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(os.environ.get("LUNA_PROXY_PORT", "8787"))

UPSTREAM_BASE = os.environ.get("OPENCODE_BASE", "https://opencode.ai/zen/go/v1").rstrip("/")

VERSION = "1.4"

API_KEY = os.environ.get("OPENCODE_API_KEY", "").strip()
TIMEOUT = int(os.environ.get("OPENCODE_TIMEOUT", "300"))

# ⚠️ 上游（Cloudflare 前置）会按浏览器指纹封禁 UA：
#    默认的 "Python-urllib/3.x" 直接吃 HTTP 403 error code: 1010。
#    这个 UA 是实测能过的，别随便改；要改用环境变量覆盖。
USER_AGENT = os.environ.get("PROXY_USER_AGENT", "workbuddy-oc-proxy/1.4")

# Anthropic /messages 需要的版本头（实测可选，但带上更稳）
ANTHROPIC_VERSION = os.environ.get("ANTHROPIC_VERSION", "2023-06-01")
# Anthropic 协议 max_tokens 是必填项，客户端没给时用这个兜底
ANTHROPIC_MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "4096"))

# 兜底模型：任何认不出来的模型名，都改写成它（走 Chat Completions）
DEFAULT_MODEL = os.environ.get("DEFAULT_UPSTREAM_MODEL", "deepseek-v4.1-flash")

# Luna 默认型号（名字里只写 "luna" 而没写具体版本时用它）
# 改这里或设环境变量 LUNA_DEFAULT 即可在 gpt-5.6-luna / gpt-6-luna 之间切换
DEFAULT_LUNA = os.environ.get("LUNA_DEFAULT", "gpt-6-luna")

# Muse 默认型号（名字里只写 "muse" 时用它；走 Responses 协议）
DEFAULT_MUSE = os.environ.get("MUSE_DEFAULT", "muse-spark-1.3-contributor")

# ---------------- 思考（reasoning）相关 ----------------
# 实测：OpenCode Go 的 /responses 只有 summary="concise" 会真的返回摘要文本；
#       "auto" / "detailed" 返回的是空 summary 数组（内容只在 encrypted_content 里）。
# 设为空字符串可关闭向 Responses 请求注入 reasoning 参数。
REASONING_SUMMARY = os.environ.get("REASONING_SUMMARY", "concise")
REASONING_EFFORT = os.environ.get("REASONING_EFFORT", "medium")

# WorkBuddy 可能会把 summary 传成 auto/detailed，这里统一收敛成能出文本的档位。
_EMPTY_SUMMARY_VALUES = {"auto", "detailed", "*"}

# ---------------- 模型名映射表 ----------------
# OpenCode Go 目录里走 Chat Completions 协议的模型
CHAT_IDS = {
    "deepseek-v4-flash", "deepseek-v4-flash-vision-exp", "deepseek-flash",
    "deepseek-v4.1-flash", "deepseek-v4-pro",
    "glm-5.2", "glm-5.3", "glm-5.3-flash",
    "kimi-k2.7-code", "kimi-k3",
    "mimo-v2.5", "mimo-v2.5-pro", "mimo-v2.6-flash", "mimo-v2.6-pro",
    "hy3", "hy4-preview",
    "longcat-2.0", "longcat-2.5-preview-free",
    "space-bunny-free",
}

# 走 OpenAI Responses API 的模型（协议不同，需要翻译）
#   - luna / grok 系列
#   - muse-spark-*-contributor（Meta 模型，官方文档确认走 /responses）
RESPONSES_IDS = {
    "gpt-5.6-luna", "gpt-6-luna",
    "grok-4.6", "grok-4.7",
    "muse-spark-1.2-contributor", "muse-spark-1.3-contributor",
}

# 走 Anthropic Messages API (/messages) 的模型
# v1.4 起代理做该协议的完整双向翻译（含工具调用）。
ANTHROPIC_IDS = {
    "minimax-m2.7", "minimax-m3",
    "qwen3.8-max", "qwen3.8-flash", "qwen3.7-plus",
}


def resolve_model(name):
    """把 WorkBuddy 发来的模型名翻译成 (上游真实模型ID, 协议类型)。

    协议类型: "chat" -> /chat/completions
              "responses" -> /responses
              "anthropic" -> /messages

    匹配策略（从精确到宽松）：
      1. 上游真名作为子串出现（按长度降序，避免 mio-v2.5 抢先命中 mimo-v2.5-pro）
         -> 直接用它，同时确定协议
      2. 只写了 "luna" / "grok" / "muse" 这类系列名 -> 用默认型号
      3. 都不认识 -> 兜底 DEFAULT_MODEL(chat)
    因为第 1 条用子串匹配，本地自定义 id（如 opencode-go-gpt-6-luna）
    也能被正确识别，不依赖 id 与真名完全一致。
    """
    n = (name or "").strip()
    low = n.lower()

    # 1) 上游真名作为子串出现（长的优先，避免前缀互相包含时误判）
    for mid in sorted(RESPONSES_IDS, key=len, reverse=True):
        if mid in low:
            return mid, "responses"
    for mid in sorted(ANTHROPIC_IDS, key=len, reverse=True):
        if mid in low:
            return mid, "anthropic"
    for mid in sorted(CHAT_IDS, key=len, reverse=True):
        if mid in low:
            return mid, "chat"

    # 2) 只给了系列名
    if "luna" in low:
        return DEFAULT_LUNA, "responses"
    if "grok" in low:
        return "grok-4.7", "responses"
    if "muse" in low:
        return DEFAULT_MUSE, "responses"
    if "qwen" in low:
        return "qwen3.8-flash", "anthropic"
    if "minimax" in low:
        return "minimax-m3", "anthropic"

    # 3) 兜底
    return DEFAULT_MODEL, "chat"


# ======================================================================
#  通用小工具
# ======================================================================
def _content_to_text(content):
    """把 chat 的 content（str 或分片数组）压成纯文本。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for part in content:
            if isinstance(part, dict):
                ptype = part.get("type")
                if ptype in ("text", "input_text", "output_text"):
                    texts.append(str(part.get("text", "")))
                elif ptype == "image_url":
                    iu = part.get("image_url")
                    url = iu.get("url", "") if isinstance(iu, dict) else (iu or "")
                    if url:
                        texts.append("[image: %s]" % url)
            else:
                texts.append(str(part))
        return "\n".join(texts)
    return str(content)


def _norm_chat_tool(t):
    """chat 的 tools 条目 -> (name, description, parameters)。

    兼容两种写法：{"type":"function","function":{...}} 和已拍平的 {...}。
    """
    if not isinstance(t, dict):
        return None
    fn = t.get("function") if isinstance(t.get("function"), dict) else t
    name = fn.get("name")
    if not name:
        return None
    params = fn.get("parameters")
    if not isinstance(params, dict):
        params = {"type": "object", "properties": {}}
    return name, (fn.get("description") or ""), params


def tools_to_responses(tools):
    """chat tools -> Responses tools（Responses 是**平铺**结构，不是嵌套 function）。

    实测上游返回体里 tools[].type == "function"，字段 name/description/parameters 直接平铺。
    """
    out = []
    for t in tools or []:
        norm = _norm_chat_tool(t)
        if not norm:
            continue
        name, desc, params = norm
        item = {"type": "function", "name": name,
                "description": desc, "parameters": params}
        if isinstance(t, dict) and isinstance(t.get("strict"), bool):
            item["strict"] = t["strict"]
        out.append(item)
    return out


def tools_to_anthropic(tools):
    """chat tools -> Anthropic tools（参数键名是 input_schema，不是 parameters）。"""
    out = []
    for t in tools or []:
        norm = _norm_chat_tool(t)
        if not norm:
            continue
        name, desc, params = norm
        out.append({"name": name, "description": desc, "input_schema": params})
    return out


def tool_choice_to_responses(tc):
    """chat tool_choice -> Responses tool_choice。"""
    if isinstance(tc, str):
        if tc in ("auto", "required", "none"):
            return tc
        return None
    if isinstance(tc, dict):
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
        name = fn.get("name")
        if name:
            return {"type": "function", "name": name}
    return None


def tool_choice_to_anthropic(tc):
    """chat tool_choice -> Anthropic tool_choice。

    Anthropic 没有 "none"，退化成语义最接近的 auto；"required" 对应 "any"。
    """
    if isinstance(tc, str):
        if tc == "required":
            return {"type": "any"}
        return {"type": "auto"}
    if isinstance(tc, dict):
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
        name = fn.get("name")
        if name:
            return {"type": "tool", "name": name}
    return None


# ======================================================================
#  Responses 协议转换（chat  <->  /responses）
# ======================================================================
def chat_to_responses(payload):
    """Chat Completions 请求体 -> Responses API 请求体。

    除文本外还翻译：
      - tools / tool_choice / parallel_tool_calls
      - assistant 历史里的 tool_calls     -> function_call 条目
      - role="tool" 的工具结果            -> function_call_output 条目
    """
    messages = payload.get("messages", []) or []
    instructions_parts = []
    input_items = []

    for msg in messages:
        role = (msg.get("role") or "user").lower()
        content = msg.get("content")

        if role in ("system", "developer"):
            instructions_parts.append(_content_to_text(content))
            continue

        # 工具执行结果 -> function_call_output
        if role == "tool":
            input_items.append({
                "type": "function_call_output",
                "call_id": str(msg.get("tool_call_id") or msg.get("id") or ""),
                "output": _content_to_text(content) or "",
            })
            continue

        if role == "assistant":
            text = _content_to_text(content)
            if text:
                input_items.append({
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                })
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                args = fn.get("arguments")
                if not isinstance(args, str):
                    args = json.dumps(args if args is not None else {},
                                      ensure_ascii=False)
                input_items.append({
                    "type": "function_call",
                    "call_id": str(tc.get("id") or ""),
                    "name": fn.get("name") or tc.get("name") or "",
                    "arguments": args,
                })
            continue

        input_items.append({
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": _content_to_text(content)}],
        })

    out = {
        "model": payload.get("model"),
        "input": input_items if input_items else "hi",
        "stream": False,
    }
    if instructions_parts:
        merged = "\n\n".join([p for p in instructions_parts if p])
        if merged:
            out["instructions"] = merged

    for key in ("temperature", "top_p", "max_output_tokens"):
        if key in payload:
            out[key] = payload[key]
    if "max_tokens" in payload and "max_output_tokens" not in out:
        out["max_output_tokens"] = payload["max_tokens"]

    # ---- 工具定义 ----
    tools = tools_to_responses(payload.get("tools"))
    if tools:
        out["tools"] = tools
        tc = tool_choice_to_responses(payload.get("tool_choice"))
        if tc is not None:
            out["tool_choice"] = tc
        if "parallel_tool_calls" in payload:
            out["parallel_tool_calls"] = bool(payload["parallel_tool_calls"])

    # ---- 思考参数：Chat 风格 -> Responses 风格 ----
    # WorkBuddy 会按模型配置发 reasoning:{effort,summary} 或 reasoning_effort，
    # 还可能额外塞一个顶层的 reasoning_summary。这里统一翻译成 Responses 需要的形状。
    effort = None
    summary = None
    reasoning_obj = payload.get("reasoning")
    if isinstance(reasoning_obj, dict):
        effort = reasoning_obj.get("effort")
        summary = reasoning_obj.get("summary")
    if isinstance(payload.get("reasoning_effort"), str):
        effort = payload["reasoning_effort"]
    if isinstance(payload.get("reasoning_summary"), str):
        summary = payload["reasoning_summary"]

    if REASONING_SUMMARY:
        # 上游只认 concise 会真的吐文本，其余档位收敛过来
        if not summary or str(summary).lower() in _EMPTY_SUMMARY_VALUES:
            summary = REASONING_SUMMARY
        out["reasoning"] = {
            "effort": effort or REASONING_EFFORT,
            "summary": summary,
        }

    return out


def extract_text(resp_json):
    """从 Responses API 返回体里抽取纯文本（忽略 reasoning / function_call）。"""
    chunks = []
    for item in resp_json.get("output", []) or []:
        if item.get("type") == "message":
            for c in item.get("content", []) or []:
                if c.get("type") in ("output_text", "text"):
                    chunks.append(c.get("text", ""))
        elif item.get("type") == "output_text":
            chunks.append(item.get("text", ""))
    if chunks:
        return "".join(chunks)
    if isinstance(resp_json.get("output_text"), str):
        return resp_json["output_text"]
    return ""


def extract_tool_calls(resp_json):
    """从 Responses API 返回体里抽取 function_call -> chat 的 tool_calls 结构。

    实测上游形状：
      {"type":"function_call","id":"fc_...","call_id":"call_...",
       "name":"get_weather","arguments":"{\\"city\\":\\"北京\\"}"}
    """
    calls = []
    for item in resp_json.get("output", []) or []:
        if item.get("type") != "function_call":
            continue
        calls.append({
            "id": item.get("call_id") or item.get("id") or ("call_" + uuid.uuid4().hex[:16]),
            "type": "function",
            "function": {
                "name": item.get("name") or "",
                "arguments": item.get("arguments") or "{}",
            },
        })
    return calls


def extract_reasoning(resp_json):
    """从 Responses API 返回体里抽取推理摘要（reasoning summary）。

    只有 summary="concise" 时上游才会真的填 content；
    auto/detailed 会得到空数组（真正内容躺在 encrypted_content 里，无法解密）。
    """
    parts = []
    for item in resp_json.get("output", []) or []:
        if item.get("type") != "reasoning":
            continue
        for s in item.get("summary", []) or []:
            if isinstance(s, dict):
                t = s.get("text")
                if isinstance(t, str) and t:
                    parts.append(t)
        for c in item.get("content", []) or []:
            if isinstance(c, dict):
                t = c.get("text")
                if isinstance(t, str) and t:
                    parts.append(t)
    return "\n".join(parts)


def build_chat_response(text, model, resp_json, reasoning="", tool_calls=None):
    """Responses 结果 -> Chat Completions 响应结构。"""
    usage = resp_json.get("usage", {}) or {}
    pt = usage.get("input_tokens", 0)
    ct = usage.get("output_tokens", 0)

    if tool_calls is None:
        tool_calls = extract_tool_calls(resp_json)

    message = {"role": "assistant", "content": text}
    if reasoning:
        # WorkBuddy 的流式解析器读的正是 reasoning_content（实测其产物代码）
        message["reasoning_content"] = reasoning
    if tool_calls:
        message["tool_calls"] = tool_calls
    # 有 tool_calls 时必须返回 tool_calls，否则客户端会当成最终答案
    finish_reason = "tool_calls" if tool_calls else "stop"

    return {
        "id": resp_json.get("id", "chatcmpl-" + uuid.uuid4().hex[:24]),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason,
        }],
        "usage": {
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
        },
    }


# ======================================================================
#  Anthropic Messages 协议转换（chat  <->  /messages）
# ======================================================================
def chat_to_messages(payload):
    """Chat Completions 请求体 -> Anthropic Messages 请求体。

    要点：
      - system 提到顶层，不进 messages
      - assistant.tool_calls -> tool_use 内容块
      - role="tool"          -> user 消息里的 tool_result 内容块
      - tools 的 parameters 键改名为 input_schema
      - max_tokens 必填，缺省用 ANTHROPIC_MAX_TOKENS
      - user/assistant 必须交替，连续同角色会被合并
    """
    src = payload.get("messages", []) or []
    system_parts = []
    out_msgs = []

    def push(role, blocks):
        if not blocks:
            return
        if out_msgs and out_msgs[-1]["role"] == role:
            out_msgs[-1]["content"].extend(blocks)
        else:
            out_msgs.append({"role": role, "content": blocks})

    for msg in src:
        role = (msg.get("role") or "user").lower()
        content = msg.get("content")

        if role in ("system", "developer"):
            system_parts.append(_content_to_text(content))
            continue

        if role == "tool":
            push("user", [{
                "type": "tool_result",
                "tool_use_id": str(msg.get("tool_call_id") or ""),
                "content": _content_to_text(content) or "",
            }])
            continue

        if role == "assistant":
            blocks = []
            text = _content_to_text(content)
            if text:
                blocks.append({"type": "text", "text": text})
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args) if args.strip() else {}
                    except Exception:
                        args = {"_raw": args}
                elif not isinstance(args, dict):
                    args = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id") or ("toolu_" + uuid.uuid4().hex[:16]),
                    "name": fn.get("name") or tc.get("name") or "",
                    "input": args,
                })
            push("assistant", blocks)
            continue

        push("user", [{"type": "text", "text": _content_to_text(content)}])

    # Anthropic 要求首条必须是 user
    if not out_msgs:
        out_msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    elif out_msgs[0]["role"] != "user":
        out_msgs.insert(0, {"role": "user", "content": [{"type": "text", "text": "hi"}]})

    mt = payload.get("max_tokens")
    try:
        mt = int(mt) if mt is not None else 0
    except Exception:
        mt = 0
    if mt <= 0:
        mt = ANTHROPIC_MAX_TOKENS

    out = {"model": payload.get("model"), "max_tokens": mt, "messages": out_msgs}
    merged_sys = "\n\n".join([p for p in system_parts if p])
    if merged_sys:
        out["system"] = merged_sys

    # Anthropic 的 temperature 上限是 1，超出会被拒
    if "temperature" in payload:
        try:
            t = float(payload["temperature"])
            out["temperature"] = max(0.0, min(1.0, t))
        except Exception:
            pass
    if "top_p" in payload:
        out["top_p"] = payload["top_p"]
    if payload.get("stop"):
        stop = payload["stop"]
        out["stop_sequences"] = stop if isinstance(stop, list) else [stop]

    tools = tools_to_anthropic(payload.get("tools"))
    if tools:
        out["tools"] = tools
        tc = tool_choice_to_anthropic(payload.get("tool_choice"))
        if tc is not None:
            out["tool_choice"] = tc

    return out


def messages_to_chat_response(resp_json, model):
    """Anthropic Messages 返回体 -> Chat Completions 响应结构。

    实测内容块类型：text / thinking / tool_use。
    """
    texts, reasonings, tool_calls = [], [], []

    for blk in resp_json.get("content", []) or []:
        if not isinstance(blk, dict):
            continue
        btype = blk.get("type")

        if btype in ("text", "output_text"):
            t = blk.get("text")
            if isinstance(t, str) and t:
                texts.append(t)
        elif btype in ("thinking", "reasoning"):
            # qwen 会返回 {"type":"thinking","thinking":"...","signature":""}
            v = blk.get("thinking") or blk.get("text") or ""
            if isinstance(v, str) and v:
                reasonings.append(v)
        elif btype == "tool_use":
            args = blk.get("input")
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            tool_calls.append({
                "id": blk.get("id") or ("call_" + uuid.uuid4().hex[:16]),
                "type": "function",
                "function": {"name": blk.get("name") or "", "arguments": args},
            })

    usage = resp_json.get("usage", {}) or {}
    pt = usage.get("input_tokens", 0) or 0
    ct = usage.get("output_tokens", 0) or 0
    stop = resp_json.get("stop_reason")

    message = {"role": "assistant", "content": "".join(texts)}
    if reasonings:
        message["reasoning_content"] = "\n".join(reasonings)
    if tool_calls:
        message["tool_calls"] = tool_calls

    if tool_calls or stop == "tool_use":
        finish_reason = "tool_calls"
    elif stop == "max_tokens":
        finish_reason = "length"
    else:
        finish_reason = "stop"

    return {
        "id": resp_json.get("id", "chatcmpl-" + uuid.uuid4().hex[:24]),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason,
        }],
        "usage": {
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
        },
    }


# ======================================================================
#  启动前检查
# ======================================================================
def _require_api_key():
    if not API_KEY:
        print("=" * 70)
        print("  [ERROR] Environment variable OPENCODE_API_KEY is not set.")
        print("")
        print("  Set it before starting the proxy:")
        print("    Git Bash :  export OPENCODE_API_KEY=oc_sk_xxxx")
        print("    CMD      :  set OPENCODE_API_KEY=oc_sk_xxxx")
        print("")
        print("  Or edit the KEY line inside start_proxy.bat")
        print("=" * 70)
        return False
    return True


def _port_in_use_hint(err):
    print("=" * 70)
    print("  [ERROR] Cannot bind port. It is probably already in use.")
    print("  Detail: %s" % err)
    print("")
    print("  Fix options:")
    print("    1) Close the other proxy window / old process")
    print("    2) Use another port:  set LUNA_PROXY_PORT=8788")
    print("=" * 70)


def _probe_existing_instance():
    """Windows 允许 SO_REUSEADDR 重复绑定端口，会出现'新实例绑定成功但请求仍被旧实例接走'
    的诡异现象。启动前先探测端口是否已有服务，有就明确报错并退出。"""
    probe = urlrequest.Request(
        "http://%s:%s/" % (LISTEN_HOST, LISTEN_PORT),
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urlrequest.urlopen(probe, timeout=2) as r:
            info = r.read(200).decode("utf-8", errors="replace")
    except Exception:
        return False  # 端口空闲，正常

    print("=" * 70)
    print("  [ERROR] Port %s is already serving something." % LISTEN_PORT)
    print("  Response: %s" % info[:200])
    print("")
    print("  Another proxy instance (maybe an OLD version) is still running.")
    print("  Please CLOSE that window / kill that process, then start again.")
    print("  Tip: netstat -ano | findstr :%s  ->  taskkill /PID <pid> /F" % LISTEN_PORT)
    print("=" * 70)
    return True


# ======================================================================
#  HTTP 处理
# ======================================================================
class InjectHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[oc-proxy] " + (fmt % args) + "\n")

    # ---- 健康检查 / 模型列表 ----
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path.endswith("/models"):
            data = []
            seen = set()
            advertised = ([DEFAULT_MODEL, DEFAULT_LUNA, DEFAULT_MUSE]
                          + sorted(RESPONSES_IDS) + sorted(ANTHROPIC_IDS))
            for mid in advertised:
                if mid in seen:
                    continue
                seen.add(mid)
                data.append({
                    "id": mid,
                    "object": "model",
                    "created": 0,
                    "owned_by": "opencode-go-proxy",
                })
            self._send_json(200, {"object": "list", "data": data})
        else:
            self._send_json(200, {
                "status": "ok",
                "proxy": "opencode-go-adapter",
                "version": VERSION,
                "protocols": ["chat", "responses", "anthropic"],
            })

    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _upstream_headers(self, protocol, want_stream):
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % API_KEY,
            "x-opencode-session": str(self.session_id),
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
            "Accept": "text/event-stream" if want_stream else "application/json",
        }
        if protocol == "anthropic":
            # 实测：/messages 只认 x-api-key，光有 Authorization 会 401 "Missing API key."
            headers["x-api-key"] = API_KEY
            headers["anthropic-version"] = ANTHROPIC_VERSION
        return headers

    # ---- 核心 ----
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b""

        payload = {}
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        incoming_model = payload.get("model", "")
        upstream_model, protocol = resolve_model(incoming_model)
        want_stream = bool(payload.get("stream"))

        self.session_id = (payload.get("user") or payload.get("session_id")
                           or ("wb-" + uuid.uuid4().hex[:16]))

        tool_names = []
        for t in payload.get("tools") or []:
            norm = _norm_chat_tool(t)
            if norm:
                tool_names.append(norm[0])

        sys.stderr.write(
            "[oc-proxy] model-in=%r -> upstream=%r protocol=%s stream=%s tools=%s\n"
            % (incoming_model, upstream_model, protocol, want_stream,
               tool_names or "-")
        )

        headers = self._upstream_headers(protocol, want_stream)

        if protocol == "responses":
            self._handle_responses(payload, upstream_model, want_stream, headers)
        elif protocol == "anthropic":
            self._handle_anthropic(payload, upstream_model, want_stream, headers)
        else:
            self._handle_chat(payload, upstream_model, want_stream, headers)

    # ---- 上游错误统一处理 ----
    def _upstream_error(self, e, label):
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        sys.stderr.write("[oc-proxy] upstream %s error %s: %s\n"
                         % (label, e.code, detail[:300]))
        self._send_json(e.code, {"error": {
            "message": "upstream %s: %s" % (e.code, detail[:1000]),
            "type": "upstream_error",
        }})

    def _open_upstream(self, url, body, headers, label):
        """返回 (response, None) 或 (None, None)（错误已回给客户端）。"""
        req = urlrequest.Request(
            url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            return urlrequest.urlopen(req, timeout=TIMEOUT), None
        except HTTPError as e:
            self._upstream_error(e, label)
            return None, None
        except URLError as e:
            self._send_json(502, {"error": {"message": "upstream unreachable: %s" % e}})
            return None, None

    def _start_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    # ---------- Chat Completions 透传 ----------
    def _handle_chat(self, payload, upstream_model, want_stream, headers):
        payload = dict(payload)
        payload["model"] = upstream_model

        up, _ = self._open_upstream(UPSTREAM_BASE + "/chat/completions",
                                    payload, headers, "chat")
        if up is None:
            return

        if want_stream:
            self._start_sse()
            try:
                while True:
                    chunk = up.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except Exception as e:
                sys.stderr.write("[oc-proxy] stream error: %s\n" % e)
            finally:
                up.close()
        else:
            data = up.read()
            ctype = up.headers.get("Content-Type", "application/json; charset=utf-8")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            up.close()

    # ---------- Responses 协议翻译 ----------
    def _handle_responses(self, payload, upstream_model, want_stream, headers):
        payload = dict(payload)
        payload["model"] = upstream_model
        upstream_body = chat_to_responses(payload)
        upstream_body["stream"] = bool(want_stream)

        up, _ = self._open_upstream(UPSTREAM_BASE + "/responses",
                                   upstream_body, headers, "responses")
        if up is None:
            return

        if want_stream:
            self._relay_responses_stream(up, upstream_model)
            return

        try:
            resp_raw = up.read().decode("utf-8", errors="replace")
        finally:
            try:
                up.close()
            except Exception:
                pass

        try:
            resp_json = json.loads(resp_raw)
        except Exception:
            self._send_json(502, {"error": {"message": "upstream non-json: %s" % resp_raw[:500]}})
            return

        text = extract_text(resp_json)
        reasoning = extract_reasoning(resp_json)
        tool_calls = extract_tool_calls(resp_json)
        chat_resp = build_chat_response(text, upstream_model, resp_json, reasoning, tool_calls)
        self._send_json(200, chat_resp)

    # ---------- Responses 流式 -> Chat Completions SSE ----------
    def _relay_responses_stream(self, up, model):
        """把上游 /responses 的 SSE 事件实时翻译成 Chat Completions chunk。

        关键映射：
          response.reasoning_summary_text.delta   -> delta.reasoning_content  (思考)
          response.output_text.delta              -> delta.content            (正文)
          response.output_item.added              -> delta.tool_calls[].{id,name} (工具头)
          response.function_call_arguments.delta  -> delta.tool_calls[].function.arguments
        WorkBuddy 的流式解析器同时识别 reasoning_content / reasoning 两个字段名。
        """
        self._start_sse()

        cid = "chatcmpl-" + uuid.uuid4().hex[:24]
        created = int(time.time())

        # output_index -> {"chat_index":n, "id":..., "name":...}
        tool_state = {}
        counters = {"tool": 0}
        flags = {"tool": False}

        def emit(delta, finish_reason=None):
            chunk = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
            }
            self.wfile.write(("data: %s\n\n" % json.dumps(chunk, ensure_ascii=False)).encode("utf-8"))
            self.wfile.flush()

        def tool_head(output_index, item):
            """登记并推出一个 tool_call 的头部（id + name）。"""
            ci = counters["tool"]
            counters["tool"] += 1
            state = {
                "chat_index": ci,
                "id": item.get("call_id") or item.get("id") or "",
                "name": item.get("name") or "",
            }
            tool_state[output_index] = state
            flags["tool"] = True
            emit({"tool_calls": [{
                "index": ci,
                "id": state["id"],
                "type": "function",
                "function": {"name": state["name"], "arguments": ""},
            }]})

        emit({"role": "assistant"})

        try:
            while True:
                line = up.readline()
                if not line:
                    break
                line = line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    ev = json.loads(raw)
                except Exception:
                    continue

                etype = ev.get("type", "")

                if etype == "response.reasoning_summary_text.delta":
                    piece = ev.get("delta") or ""
                    if piece:
                        emit({"reasoning_content": piece})

                elif etype == "response.output_text.delta":
                    piece = ev.get("delta") or ""
                    if piece:
                        emit({"content": piece})

                elif etype == "response.output_item.added":
                    item = ev.get("item") or {}
                    if item.get("type") == "function_call":
                        tool_head(ev.get("output_index", len(tool_state)), item)

                elif etype == "response.output_item.done":
                    item = ev.get("item") or {}
                    oi = ev.get("output_index", 0)
                    # 兜底：万一上游没发 added 事件，这里补一个完整的 tool_call
                    if item.get("type") == "function_call" and oi not in tool_state:
                        tool_head(oi, item)
                        args = item.get("arguments") or ""
                        if args:
                            emit({"tool_calls": [{
                                "index": tool_state[oi]["chat_index"],
                                "function": {"arguments": args},
                            }]})

                elif etype == "response.function_call_arguments.delta":
                    oi = ev.get("output_index", 0)
                    state = tool_state.get(oi)
                    if state is None:
                        # 没见过头部事件，先补一个空的
                        tool_head(oi, {})
                        state = tool_state[oi]
                    piece = ev.get("delta") or ""
                    if piece:
                        emit({"tool_calls": [{
                            "index": state["chat_index"],
                            "function": {"arguments": piece},
                        }]})

                elif etype == "response.completed":
                    break

                elif etype in ("response.failed", "response.incomplete", "error"):
                    detail = json.dumps(ev.get("response", ev), ensure_ascii=False)[:400]
                    emit({"content": "\n[upstream %s] %s" % (etype, detail)})
                    break

        except Exception as e:
            sys.stderr.write("[oc-proxy] responses stream error: %s\n" % e)
        finally:
            try:
                up.close()
            except Exception:
                pass

        emit({}, finish_reason="tool_calls" if flags["tool"] else "stop")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    # ---------- Anthropic Messages 协议翻译 ----------
    def _handle_anthropic(self, payload, upstream_model, want_stream, headers):
        payload = dict(payload)
        payload["model"] = upstream_model
        upstream_body = chat_to_messages(payload)
        upstream_body["stream"] = bool(want_stream)

        up, _ = self._open_upstream(UPSTREAM_BASE + "/messages",
                                   upstream_body, headers, "messages")
        if up is None:
            return

        if want_stream:
            self._relay_messages_stream(up, upstream_model)
            return

        try:
            resp_raw = up.read().decode("utf-8", errors="replace")
        finally:
            try:
                up.close()
            except Exception:
                pass

        try:
            resp_json = json.loads(resp_raw)
        except Exception:
            self._send_json(502, {"error": {"message": "upstream non-json: %s" % resp_raw[:500]}})
            return

        self._send_json(200, messages_to_chat_response(resp_json, upstream_model))

    # ---------- Anthropic 流式 -> Chat Completions SSE ----------
    def _relay_messages_stream(self, up, model):
        """把上游 /messages 的 SSE 事件实时翻译成 Chat Completions chunk。

        关键映射：
          content_block_start(type=text)                        -> 建块
          content_block_start(type=thinking)                    -> 建块（思考）
          content_block_delta(type=text_delta)                  -> delta.content
          content_block_delta(type=thinking_delta)              -> delta.reasoning_content
          content_block_start(type=tool_use)                    -> delta.tool_calls[].{id,name}
          content_block_delta(type=input_json_delta)            -> delta.tool_calls[].function.arguments
          message_delta(stop_reason)                            -> finish_reason
        """
        self._start_sse()

        cid = "chatcmpl-" + uuid.uuid4().hex[:24]
        created = int(time.time())

        blocks = {}          # 上游 content block index -> {"kind":..., "chat_index":int|None}
        counters = {"tool": 0}
        flags = {"tool": False}
        stop = {"reason": None}

        def emit(delta, finish_reason=None):
            chunk = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
            }
            self.wfile.write(("data: %s\n\n" % json.dumps(chunk, ensure_ascii=False)).encode("utf-8"))
            self.wfile.flush()

        emit({"role": "assistant"})

        try:
            while True:
                line = up.readline()
                if not line:
                    break
                line = line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    ev = json.loads(raw)
                except Exception:
                    continue

                etype = ev.get("type", "")

                if etype == "content_block_start":
                    idx = ev.get("index", 0)
                    cb = ev.get("content_block") or {}
                    btype = cb.get("type")
                    if btype == "tool_use":
                        ci = counters["tool"]
                        counters["tool"] += 1
                        flags["tool"] = True
                        blocks[idx] = {"kind": "tool_use", "chat_index": ci}
                        emit({"tool_calls": [{
                            "index": ci,
                            "id": cb.get("id") or "",
                            "type": "function",
                            "function": {"name": cb.get("name") or "", "arguments": ""},
                        }]})
                    elif btype in ("thinking", "reasoning"):
                        blocks[idx] = {"kind": "thinking", "chat_index": None}
                    else:
                        blocks[idx] = {"kind": "text", "chat_index": None}

                elif etype == "content_block_delta":
                    idx = ev.get("index", 0)
                    d = ev.get("delta") or {}
                    dtype = d.get("type")
                    if dtype == "text_delta":
                        piece = d.get("text") or ""
                        if piece:
                            emit({"content": piece})
                    elif dtype in ("thinking_delta", "reasoning_delta"):
                        piece = d.get("thinking") or d.get("text") or ""
                        if piece:
                            emit({"reasoning_content": piece})
                    elif dtype == "input_json_delta":
                        piece = d.get("partial_json") or ""
                        st = blocks.get(idx)
                        if st is None or st.get("chat_index") is None:
                            # 上游没给 content_block_start 时兜底
                            ci = counters["tool"]
                            counters["tool"] += 1
                            flags["tool"] = True
                            blocks[idx] = {"kind": "tool_use", "chat_index": ci}
                            emit({"tool_calls": [{
                                "index": ci, "id": "", "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }]})
                            st = blocks[idx]
                        if piece:
                            emit({"tool_calls": [{
                                "index": st["chat_index"],
                                "function": {"arguments": piece},
                            }]})

                elif etype == "message_delta":
                    d = ev.get("delta") or {}
                    if d.get("stop_reason"):
                        stop["reason"] = d["stop_reason"]

                elif etype == "message_stop":
                    break

                elif etype == "error":
                    detail = json.dumps(ev.get("error", ev), ensure_ascii=False)[:400]
                    emit({"content": "\n[upstream error] %s" % detail})
                    break

        except Exception as e:
            sys.stderr.write("[oc-proxy] messages stream error: %s\n" % e)
        finally:
            try:
                up.close()
            except Exception:
                pass

        if flags["tool"] or stop["reason"] == "tool_use":
            finish = "tool_calls"
        elif stop["reason"] == "max_tokens":
            finish = "length"
        else:
            finish = "stop"

        emit({}, finish_reason=finish)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def main():
    if not _require_api_key():
        sys.exit(1)

    if _probe_existing_instance():
        sys.exit(3)

    print("=" * 70, flush=True)
    print("  OpenCode Go  -  Unified Adapter Proxy  v%s" % VERSION, flush=True)
    print("=" * 70, flush=True)
    print("  Listen    : http://%s:%s" % (LISTEN_HOST, LISTEN_PORT), flush=True)
    print("  Upstream  : %s" % UPSTREAM_BASE, flush=True)
    print("  API Key   : %s..." % API_KEY[:12], flush=True)
    print("  Fallback  : %s (chat)" % DEFAULT_MODEL, flush=True)
    print("  Luna      : %s (responses)" % DEFAULT_LUNA, flush=True)
    print("  Muse      : %s (responses)" % DEFAULT_MUSE, flush=True)
    print("  Reasoning : summary=%s effort=%s" % (REASONING_SUMMARY or "(off)", REASONING_EFFORT), flush=True)
    print("  Protocol  : chat / responses / anthropic  (全部支持工具调用)", flush=True)
    print("  User-Agent: %s" % USER_AGENT, flush=True)
    print("-" * 70, flush=True)
    print("  In WorkBuddy, set your custom model to:", flush=True)
    print("    Base URL : http://%s:%s/v1" % (LISTEN_HOST, LISTEN_PORT), flush=True)
    print("    Model    : deepseek-v4.1-flash", flush=True)
    print("    API Key  : any non-empty value", flush=True)
    print("-" * 70, flush=True)
    print("  Keep this window OPEN. Press Ctrl+C to stop.", flush=True)
    print("=" * 70, flush=True)

    try:
        srv = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), InjectHandler)
    except OSError as e:
        _port_in_use_hint(e)
        sys.exit(2)

    print("  [OK] Proxy is running. Waiting for requests...", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[oc-proxy] stopped.", flush=True)
        srv.server_close()


if __name__ == "__main__":
    main()
