#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.4 测试：Responses 工具调用 + Anthropic Messages 协议翻译。

覆盖：
  A. 纯函数：chat_to_responses 的工具/历史翻译
  B. 纯函数：chat_to_messages / messages_to_chat_response
  C. mock 上游端到端：responses 工具（非流式 + 流式）
  D. mock 上游端到端：anthropic 工具（非流式 + 流式）、鉴权头、多轮回灌
"""
import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import socket


def _free_port():
    """向系统要一个空闲端口。

    不能写死端口：本机常有遗留进程占用（实测 8899 被一个
    `python -m http.server` 占着，而 Windows 允许 SO_REUSEADDR 重复绑定，
    会导致"绑定成功但请求被旧进程接走"——表现为莫名其妙的 501/404）。
    """
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


MOCK_PORT = _free_port()
PROXY_PORT = _free_port()

os.environ["LUNA_PROXY_PORT"] = str(PROXY_PORT)
os.environ["OPENCODE_API_KEY"] = "test-key"
os.environ["OPENCODE_BASE"] = "http://127.0.0.1:%d/v1" % MOCK_PORT

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oc_session_proxy as P  # noqa: E402

FAILED = []
CAPTURED = {}


def check(name, cond, extra=""):
    print("  [%s] %s %s" % ("OK" if cond else "FAIL", name, extra))
    if not cond:
        FAILED.append(name)


CHAT_TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询城市天气",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string"}},
                       "required": ["city"]},
    },
}]


# ======================================================================
print("=== A. chat_to_responses 工具翻译 ===")

out = P.chat_to_responses({
    "model": "gpt-6-luna",
    "messages": [{"role": "user", "content": "北京天气"}],
    "tools": CHAT_TOOLS,
    "tool_choice": "auto",
})
check("tools 被翻译成平铺结构",
      out.get("tools") == [{"type": "function", "name": "get_weather",
                            "description": "查询城市天气",
                            "parameters": CHAT_TOOLS[0]["function"]["parameters"]}],
      json.dumps(out.get("tools"), ensure_ascii=False))
check("tool_choice 透传", out.get("tool_choice") == "auto")
check("无工具时不加 tools 字段",
      "tools" not in P.chat_to_responses({"model": "m", "messages": []}))

# tool_choice = 指定函数
out_tc = P.chat_to_responses({
    "model": "m", "messages": [],
    "tools": CHAT_TOOLS,
    "tool_choice": {"type": "function", "function": {"name": "get_weather"}},
})
check("tool_choice=指定函数被拍平",
      out_tc.get("tool_choice") == {"type": "function", "name": "get_weather"},
      str(out_tc.get("tool_choice")))

# 多轮：assistant.tool_calls + tool 结果
multi = P.chat_to_responses({
    "model": "gpt-6-luna",
    "messages": [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "北京天气"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_abc", "type": "function",
             "function": {"name": "get_weather", "arguments": "{\"city\":\"北京\"}"}}]},
        {"role": "tool", "tool_call_id": "call_abc",
         "content": "{\"temp\":25}"},
    ],
    "tools": CHAT_TOOLS,
})
items = multi["input"]
check("system 进 instructions", multi.get("instructions") == "你是助手")
check("assistant 的 tool_calls 变成 function_call 条目",
      any(i["type"] == "function_call" and i["call_id"] == "call_abc"
          and i["name"] == "get_weather"
          and i["arguments"] == "{\"city\":\"北京\"}" for i in items),
      json.dumps(items, ensure_ascii=False)[:260])
check("role=tool 变成 function_call_output",
      any(i["type"] == "function_call_output" and i["call_id"] == "call_abc"
          and i["output"] == "{\"temp\":25}" for i in items),
      json.dumps(items, ensure_ascii=False)[:260])
check("空的 assistant content 不产生空 message 条目",
      not any(i.get("type") == "message" and i.get("role") == "assistant"
              and i.get("content", [{}])[0].get("text") == "" for i in items))

print()
print("=== A2. extract_tool_calls / build_chat_response ===")
sample_fc = {"id": "resp_1", "output": [
    {"id": "fc_1", "type": "function_call", "status": "completed",
     "name": "get_weather", "call_id": "call_abc", "arguments": "{\"city\":\"北京\"}"}],
    "usage": {"input_tokens": 10, "output_tokens": 5}}
calls = P.extract_tool_calls(sample_fc)
check("抽出 tool_calls", calls == [{"id": "call_abc", "type": "function",
                                   "function": {"name": "get_weather",
                                                "arguments": "{\"city\":\"北京\"}"}}],
      json.dumps(calls, ensure_ascii=False))

cr = P.build_chat_response("", "gpt-6-luna", sample_fc, "")
check("有工具时 finish_reason=tool_calls",
      cr["choices"][0]["finish_reason"] == "tool_calls", cr["choices"][0]["finish_reason"])
check("message.tool_calls 已带上", cr["choices"][0]["message"].get("tool_calls") is not None)
check("无思考时不加 reasoning_content",
      "reasoning_content" not in cr["choices"][0]["message"])
check("纯文本时 finish_reason=stop",
      P.build_chat_response("hi", "m", {"usage": {}})["choices"][0]["finish_reason"] == "stop")


# ======================================================================
print()
print("=== B. Anthropic 协议翻译（纯函数）===")

amt = P.chat_to_messages({
    "model": "qwen3.8-flash",
    "messages": [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "北京天气"},
        {"role": "assistant", "content": "我查一下", "tool_calls": [
            {"id": "call_abc", "type": "function",
             "function": {"name": "get_weather", "arguments": "{\"city\":\"北京\"}"}}]},
        {"role": "tool", "tool_call_id": "call_abc", "content": "{\"temp\":25}"},
    ],
    "tools": CHAT_TOOLS,
    "tool_choice": "required",
})
check("system 提到顶层", amt.get("system") == "你是助手")
check("max_tokens 有兜底值", isinstance(amt.get("max_tokens"), int) and amt["max_tokens"] > 0,
      str(amt.get("max_tokens")))
check("tools 的 parameters 改名 input_schema",
      amt["tools"] == [{"name": "get_weather", "description": "查询城市天气",
                        "input_schema": CHAT_TOOLS[0]["function"]["parameters"]}],
      json.dumps(amt.get("tools"), ensure_ascii=False))
check("tool_choice=required -> any", amt.get("tool_choice") == {"type": "any"},
      str(amt.get("tool_choice")))

roles = [m["role"] for m in amt["messages"]]
check("角色交替（无连续同角色）",
      all(roles[i] != roles[i + 1] for i in range(len(roles) - 1)), str(roles))
check("首条是 user", roles[0] == "user", str(roles))

asst = [m for m in amt["messages"] if m["role"] == "assistant"][-1]
blocks = asst["content"]
check("assistant 文本 -> text 块",
      any(b["type"] == "text" and b["text"] == "我查一下" for b in blocks),
      json.dumps(blocks, ensure_ascii=False))
check("assistant.tool_calls -> tool_use 块（arguments 反序列化成 input）",
      any(b["type"] == "tool_use" and b["id"] == "call_abc"
          and b["name"] == "get_weather" and b["input"] == {"city": "北京"} for b in blocks),
      json.dumps(blocks, ensure_ascii=False))

toolmsg = [m for m in amt["messages"] if m["role"] == "user"][-1]
check("role=tool -> user 里的 tool_result 块",
      any(b["type"] == "tool_result" and b["tool_use_id"] == "call_abc"
          and b["content"] == "{\"temp\":25}" for b in toolmsg["content"]),
      json.dumps(toolmsg, ensure_ascii=False))

check("temperature 被夹到 [0,1]",
      P.chat_to_messages({"model": "m", "messages": [], "temperature": 2})["temperature"] == 1.0)
check("缺 messages 时不崩",
      P.chat_to_messages({"model": "m"})["messages"][0]["role"] == "user")

print()
print("=== B2. messages_to_chat_response ===")
mresp = {
    "id": "msg_1", "type": "message", "role": "assistant",
    "stop_reason": "tool_use", "model": "minimax-m3",
    "content": [
        {"type": "thinking", "thinking": "先想一下", "signature": ""},
        {"type": "text", "text": "我查一下"},
        {"type": "tool_use", "id": "toolu_1", "name": "get_weather",
         "input": {"city": "北京"}},
    ],
    "usage": {"input_tokens": 20, "output_tokens": 8},
}
mc = P.messages_to_chat_response(mresp, "minimax-m3")
msg = mc["choices"][0]["message"]
check("text 块 -> content", msg["content"] == "我查一下", repr(msg["content"]))
check("thinking 块 -> reasoning_content", msg.get("reasoning_content") == "先想一下",
      repr(msg.get("reasoning_content")))
check("tool_use -> tool_calls（input 序列化成 arguments）",
      msg["tool_calls"][0]["id"] == "toolu_1"
      and msg["tool_calls"][0]["function"]["name"] == "get_weather"
      and json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"city": "北京"},
      json.dumps(msg.get("tool_calls"), ensure_ascii=False))
check("stop_reason=tool_use -> finish_reason=tool_calls",
      mc["choices"][0]["finish_reason"] == "tool_calls")
check("usage 映射", mc["usage"] == {"prompt_tokens": 20, "completion_tokens": 8,
                                    "total_tokens": 28}, str(mc["usage"]))
check("max_tokens -> length",
      P.messages_to_chat_response({"content": [], "stop_reason": "max_tokens"},
                                  "m")["choices"][0]["finish_reason"] == "length")


# ======================================================================
class MockUpstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        CAPTURED["body"] = body
        CAPTURED["path"] = self.path
        CAPTURED["headers"] = {k.lower(): v for k, v in self.headers.items()}

        is_responses = self.path.endswith("/responses")
        stream = bool(body.get("stream"))

        if is_responses and stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            events = [
                {"type": "response.created", "response": {"id": "resp_mock"}},
                {"type": "response.reasoning_summary_text.delta", "delta": "看看天气"},
                {"type": "response.output_item.added", "output_index": 0, "item": {
                    "id": "fc_1", "type": "function_call", "status": "in_progress",
                    "name": "get_weather", "call_id": "call_abc", "arguments": ""}},
                {"type": "response.function_call_arguments.delta", "output_index": 0,
                 "item_id": "fc_1", "delta": "{\"city\":"},
                {"type": "response.function_call_arguments.delta", "output_index": 0,
                 "item_id": "fc_1", "delta": "\"北京\"}"},
                {"type": "response.output_item.done", "output_index": 0, "item": {
                    "id": "fc_1", "type": "function_call", "status": "completed",
                    "name": "get_weather", "call_id": "call_abc",
                    "arguments": "{\"city\":\"北京\"}"}},
                {"type": "response.completed", "response": {"id": "resp_mock"}},
            ]
            for ev in events:
                self.wfile.write(("data: %s\n\n" % json.dumps(ev, ensure_ascii=False)).encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        if is_responses:
            payload = {"id": "resp_mock",
                       "output": [
                           {"type": "reasoning", "summary": [{"type": "summary_text",
                                                              "text": "看看天气"}],
                            "content": [], "encrypted_content": "zzz"},
                           {"id": "fc_1", "type": "function_call", "status": "completed",
                            "name": "get_weather", "call_id": "call_abc",
                            "arguments": "{\"city\":\"北京\"}"},
                       ],
                       "usage": {"input_tokens": 12, "output_tokens": 6}}
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        # ---- /messages ----
        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            events = [
                {"type": "message_start", "message": {"id": "msg_mock",
                                                      "usage": {"input_tokens": 9}}},
                {"type": "content_block_start", "index": 0,
                 "content_block": {"type": "thinking", "thinking": ""}},
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "thinking_delta", "thinking": "先看看"}},
                {"type": "content_block_stop", "index": 0},
                {"type": "content_block_start", "index": 1,
                 "content_block": {"type": "tool_use", "id": "toolu_1",
                                   "name": "get_weather", "input": {}}},
                {"type": "content_block_delta", "index": 1,
                 "delta": {"type": "input_json_delta", "partial_json": "{\"city\":"}},
                {"type": "content_block_delta", "index": 1,
                 "delta": {"type": "input_json_delta", "partial_json": "\"上海\"}"}},
                {"type": "content_block_stop", "index": 1},
                {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
                 "usage": {"output_tokens": 7}},
                {"type": "message_stop"},
            ]
            for ev in events:
                self.wfile.write(("data: %s\n\n" % json.dumps(ev, ensure_ascii=False)).encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        payload = {"id": "msg_mock", "type": "message", "role": "assistant",
                   "stop_reason": "tool_use", "model": "minimax-m3",
                   "content": [
                       {"type": "thinking", "thinking": "先看看", "signature": ""},
                       {"type": "tool_use", "id": "toolu_1", "name": "get_weather",
                        "input": {"city": "上海"}}],
                   "usage": {"input_tokens": 9, "output_tokens": 7}}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


mock = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockUpstream)
threading.Thread(target=mock.serve_forever, daemon=True).start()

proxy = ThreadingHTTPServer(("127.0.0.1", PROXY_PORT), P.InjectHandler)
threading.Thread(target=proxy.serve_forever, daemon=True).start()
time.sleep(0.4)

# 自检：确认监听在 MOCK_PORT 的真是我们自己的 mock，而不是别的遗留进程
_probe = urllib.request.Request(
    "http://127.0.0.1:%d/v1/responses" % MOCK_PORT,
    data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(_probe, timeout=5) as _r:
        if not _r.headers.get("Content-Type", "").startswith("application/json"):
            raise RuntimeError("mock 端口被别的进程占用（Content-Type=%s）"
                               % _r.headers.get("Content-Type"))
except Exception as _e:
    print("[FATAL] mock 上游不可用：%s" % _e)
    sys.exit(2)
print("  (自检) mock 上游听在 127.0.0.1:%d，代理端口 %d" % (MOCK_PORT, PROXY_PORT))


def call(model, stream=False, extra=None):
    body = {"model": model,
            "messages": [{"role": "user", "content": "北京天气"}],
            "tools": CHAT_TOOLS,
            "max_tokens": 256}
    if extra:
        body.update(extra)
    if stream:
        body["stream"] = True
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % PROXY_PORT,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer x"},
        method="POST")
    if not stream:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    # 流式：聚合成 chat 结构
    content, reasoning, finish = "", "", None
    tool_calls = {}

    def merge_delta(d):
        nonlocal content, reasoning, finish
        content += d.get("content") or ""
        reasoning += d.get("reasoning_content") or ""
        for tc in d.get("tool_calls") or []:
            slot = tool_calls.setdefault(tc.get("index", 0),
                                         {"id": "", "type": "function",
                                          "function": {"name": "", "arguments": ""}})
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["function"]["name"] = fn["name"]
            slot["function"]["arguments"] += fn.get("arguments") or ""

    with urllib.request.urlopen(req, timeout=15) as r:
        for line in r:
            line = line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            rawl = line[5:].strip()
            if rawl == "[DONE]":
                break
            obj = json.loads(rawl)
            for ch in obj.get("choices", []):
                merge_delta(ch.get("delta") or {})
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
    return {"content": content, "reasoning": reasoning, "finish": finish,
            "tool_calls": [tool_calls[k] for k in sorted(tool_calls)]}


print()
print("=== C. 端到端：Responses 工具调用 ===")

r = call("opencode-go-gpt-6-luna", stream=False)
check("打到 /responses", CAPTURED["path"].endswith("/responses"), CAPTURED["path"])
check("上游收到 tools（平铺）",
      CAPTURED["body"]["tools"][0]["name"] == "get_weather"
      and "function" not in CAPTURED["body"]["tools"][0],
      json.dumps(CAPTURED["body"]["tools"], ensure_ascii=False))
m = r["choices"][0]["message"]
check("非流式：tool_calls 回译",
      m["tool_calls"][0]["id"] == "call_abc"
      and m["tool_calls"][0]["function"]["name"] == "get_weather"
      and m["tool_calls"][0]["function"]["arguments"] == "{\"city\":\"北京\"}",
      json.dumps(m.get("tool_calls"), ensure_ascii=False))
check("非流式：finish_reason=tool_calls",
      r["choices"][0]["finish_reason"] == "tool_calls")
check("非流式：思考仍保留", m.get("reasoning_content") == "看看天气")
check("session 头已注入", bool(CAPTURED["headers"].get("x-opencode-session")))

rs = call("opencode-go-gpt-6-luna", stream=True)
check("流式：tool_calls 名字", rs["tool_calls"][0]["function"]["name"] == "get_weather",
      json.dumps(rs["tool_calls"], ensure_ascii=False))
check("流式：tool_call id（call_id）", rs["tool_calls"][0]["id"] == "call_abc",
      rs["tool_calls"][0]["id"])
check("流式：arguments 逐片拼回完整 JSON",
      json.loads(rs["tool_calls"][0]["function"]["arguments"]) == {"city": "北京"},
      repr(rs["tool_calls"][0]["function"]["arguments"]))
check("流式：finish_reason=tool_calls", rs["finish"] == "tool_calls", str(rs["finish"]))
check("流式：思考增量仍转发", rs["reasoning"] == "看看天气", repr(rs["reasoning"]))

print()
print("=== D. 端到端：Anthropic /messages ===")

a = call("minimax-m3", stream=False)
check("打到 /messages", CAPTURED["path"].endswith("/messages"), CAPTURED["path"])
check("带上 x-api-key（上游必需）",
      CAPTURED["headers"].get("x-api-key") == "test-key",
      str(CAPTURED["headers"].get("x-api-key")))
check("带上 anthropic-version", bool(CAPTURED["headers"].get("anthropic-version")))
check("上游收到 tools（input_schema）",
      CAPTURED["body"]["tools"][0].get("input_schema") is not None
      and "parameters" not in CAPTURED["body"]["tools"][0],
      json.dumps(CAPTURED["body"]["tools"], ensure_ascii=False))
check("上游 body 有 max_tokens", CAPTURED["body"].get("max_tokens") == 256,
      str(CAPTURED["body"].get("max_tokens")))
am = a["choices"][0]["message"]
check("非流式：tool_use 回译成 tool_calls",
      am["tool_calls"][0]["id"] == "toolu_1"
      and json.loads(am["tool_calls"][0]["function"]["arguments"]) == {"city": "上海"},
      json.dumps(am.get("tool_calls"), ensure_ascii=False))
check("非流式：thinking -> reasoning_content",
      am.get("reasoning_content") == "先看看", repr(am.get("reasoning_content")))
check("非流式：finish_reason=tool_calls",
      a["choices"][0]["finish_reason"] == "tool_calls")

as_ = call("minimax-m3", stream=True)
check("流式：tool_use 头 + input_json_delta 拼回",
      len(as_["tool_calls"]) == 1
      and as_["tool_calls"][0]["id"] == "toolu_1"
      and as_["tool_calls"][0]["function"]["name"] == "get_weather"
      and json.loads(as_["tool_calls"][0]["function"]["arguments"]) == {"city": "上海"},
      json.dumps(as_["tool_calls"], ensure_ascii=False))
check("流式：thinking_delta -> reasoning_content",
      as_["reasoning"] == "先看看", repr(as_["reasoning"]))
check("流式：finish_reason=tool_calls", as_["finish"] == "tool_calls", str(as_["finish"]))

# 多轮回灌：assistant tool_calls + tool 结果 应被翻译成 tool_use / tool_result
call("minimax-m3", stream=False, extra={"messages": [
    {"role": "user", "content": "北京天气"},
    {"role": "assistant", "content": None, "tool_calls": [
        {"id": "toolu_1", "type": "function",
         "function": {"name": "get_weather", "arguments": "{\"city\":\"北京\"}"}}]},
    {"role": "tool", "tool_call_id": "toolu_1", "content": "{\"temp\":25}"},
    {"role": "user", "content": "那明天呢"},
]})
sent = CAPTURED["body"]["messages"]
check("多轮：工具历史含 tool_use 块",
      any(b.get("type") == "tool_use" for msg_ in sent for b in msg_.get("content", [])),
      json.dumps(sent, ensure_ascii=False)[:300])
check("多轮：工具历史含 tool_result 块",
      any(b.get("type") == "tool_result" and b.get("tool_use_id") == "toolu_1"
          for msg_ in sent for b in msg_.get("content", [])),
      json.dumps(sent, ensure_ascii=False)[:300])
check("多轮：角色仍交替",
      all(sent[i]["role"] != sent[i + 1]["role"] for i in range(len(sent) - 1)),
      str([x["role"] for x in sent]))

print()
print("=== E. 回归：resolve_model ===")
check("anthropic 模型解析",
      P.resolve_model("opencode-go-qwen3.8-max") == ("qwen3.8-max", "anthropic"))
check("qwen 系列名兜底",
      P.resolve_model("qwen")[1] == "anthropic", str(P.resolve_model("qwen")))
check("minimax 系列名兜底",
      P.resolve_model("minimax")[1] == "anthropic", str(P.resolve_model("minimax")))
check("deepseek 仍走 chat",
      P.resolve_model("opencode-go-deepseek-v4.1-flash") == ("deepseek-v4.1-flash", "chat"))
check("luna 仍走 responses",
      P.resolve_model("opencode-go-gpt-6-luna") == ("gpt-6-luna", "responses"))

mock.shutdown()
proxy.shutdown()

print()
print("=" * 66)
if FAILED:
    print("失败 %d 项：" % len(FAILED))
    for f in FAILED:
        print("   -", f)
    sys.exit(1)
print("全部通过 ✅")
