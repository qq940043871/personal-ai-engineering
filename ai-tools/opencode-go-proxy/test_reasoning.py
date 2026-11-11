#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 v1.3 的思考（reasoning）支持。

覆盖：
  1. chat_to_responses 会把 reasoning 参数翻译进 Responses 请求体
  2. summary=auto/detailed 会被收敛成 concise（上游只有 concise 出文本）
  3. extract_reasoning 能抽出摘要文本
  4. 端到端：mock 上游返回 reasoning_summary_text.delta，
     代理必须把它翻译成 delta.reasoning_content 推给客户端
"""
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import socket


def _free_port():
    """要一个空闲端口：写死端口会被本机遗留进程抢占（Windows 允许 SO_REUSEADDR）。"""
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


# ---------------- 1) 纯函数 ----------------
print("=== 1. chat_to_responses 的 reasoning 翻译 ===")
out = P.chat_to_responses({
    "model": "gpt-6-luna",
    "messages": [{"role": "user", "content": "hi"}],
    "reasoning": {"effort": "medium", "summary": "auto"},
})
check("reasoning 字段被保留", out.get("reasoning") is not None, str(out.get("reasoning")))
check("summary=auto 被收敛为 concise", out["reasoning"]["summary"] == "concise", str(out["reasoning"]))
check("effort 透传", out["reasoning"]["effort"] == "medium", str(out["reasoning"]))

out2 = P.chat_to_responses({
    "model": "gpt-6-luna",
    "messages": [{"role": "user", "content": "hi"}],
    "reasoning_effort": "low",
    "reasoning_summary": "detailed",
})
check("reasoning_effort 顶格字段被识别", out2["reasoning"]["effort"] == "low", str(out2["reasoning"]))
check("reasoning_summary=detailed 被收敛", out2["reasoning"]["summary"] == "concise", str(out2["reasoning"]))

out3 = P.chat_to_responses({
    "model": "gpt-6-luna",
    "messages": [{"role": "user", "content": "hi"}],
})
check("未指定时走默认档位",
      out3["reasoning"]["summary"] == P.REASONING_SUMMARY and out3["reasoning"]["effort"] == P.REASONING_EFFORT,
      str(out3.get("reasoning")))

print()
print("=== 2. extract_reasoning ===")
sample = {
    "output": [
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "**Explaining decimals**"}],
         "content": [], "encrypted_content": "xxx"},
        {"type": "message", "content": [{"type": "output_text", "text": "9.9 更大"}]},
    ]
}
check("抽出摘要文本", P.extract_reasoning(sample) == "**Explaining decimals**",
      repr(P.extract_reasoning(sample)))
check("正文抽取不受影响", P.extract_text(sample) == "9.9 更大", repr(P.extract_text(sample)))
check("空摘要返回空串", P.extract_reasoning({"output": [{"type": "reasoning", "summary": [], "content": []}]}) == "")

chat_resp = P.build_chat_response("正文", "gpt-6-luna", sample, "思考内容")
check("build_chat_response 带 reasoning_content",
      chat_resp["choices"][0]["message"].get("reasoning_content") == "思考内容")
check("不传 reasoning 时不加该字段",
      "reasoning_content" not in P.build_chat_response("x", "m", {"usage": {}})["choices"][0]["message"])


# ---------------- 3) mock 上游 ----------------
class MockUpstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        CAPTURED["body"] = body
        CAPTURED["path"] = self.path
        CAPTURED["session"] = self.headers.get("x-opencode-session")

        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            events = [
                {"type": "response.created", "response": {"id": "resp_mock"}},
                {"type": "response.reasoning_summary_text.delta", "delta": "先比小数位"},
                {"type": "response.reasoning_summary_text.delta", "delta": "，9.90 更大。"},
                {"type": "response.output_text.delta", "delta": "9.9 更大。"},
                {"type": "response.completed", "response": {"id": "resp_mock", "usage": {}}},
            ]
            for ev in events:
                self.wfile.write(("data: %s\n\n" % json.dumps(ev, ensure_ascii=False)).encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            payload = {
                "id": "resp_mock",
                "output": [
                    {"type": "reasoning", "summary": [{"type": "summary_text", "text": "先比小数位"}],
                     "content": [], "encrypted_content": "zzz"},
                    {"type": "message", "content": [{"type": "output_text", "text": "9.9 更大。"}]},
                ],
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }
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

print()
print("=== 3. 端到端：非流式 ===")
req = urllib.request.Request(
    "http://127.0.0.1:%d/v1/chat/completions" % PROXY_PORT,
    data=json.dumps({
        "model": "opencode-go-gpt-6-luna",
        "messages": [{"role": "user", "content": "9.11 和 9.9 哪个大"}],
        "reasoning": {"effort": "high", "summary": "auto"},
    }).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=10) as r:
    body = json.loads(r.read().decode("utf-8"))

msg = body["choices"][0]["message"]
check("打到 /v1/responses", CAPTURED["path"].endswith("/responses"), CAPTURED["path"])
check("上游收到 summary=concise", CAPTURED["body"]["reasoning"]["summary"] == "concise",
      str(CAPTURED["body"].get("reasoning")))
check("上游收到 effort=high", CAPTURED["body"]["reasoning"]["effort"] == "high")
check("session 头已注入", bool(CAPTURED.get("session")), str(CAPTURED.get("session")))
check("正文回译正确", msg["content"] == "9.9 更大。", repr(msg["content"]))
check("思考回译正确", msg.get("reasoning_content") == "先比小数位", repr(msg.get("reasoning_content")))

print()
print("=== 4. 端到端：流式（关键）===")
req2 = urllib.request.Request(
    "http://127.0.0.1:%d/v1/chat/completions" % PROXY_PORT,
    data=json.dumps({
        "model": "opencode-go-gpt-6-luna",
        "messages": [{"role": "user", "content": "9.11 和 9.9 哪个大"}],
        "stream": True,
        "reasoning": {"effort": "high", "summary": "concise"},
    }).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
reasoning_txt = ""
content_txt = ""
finish = None
with urllib.request.urlopen(req2, timeout=10) as r:
    for line in r:
        line = line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw == "[DONE]":
            break
        obj = json.loads(raw)
        for ch in obj.get("choices", []):
            d = ch.get("delta", {})
            reasoning_txt += d.get("reasoning_content", "") or ""
            content_txt += d.get("content", "") or ""
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]

check("流式：reasoning_content 增量被转发", reasoning_txt == "先比小数位，9.90 更大。", repr(reasoning_txt))
check("流式：正文增量被转发", content_txt == "9.9 更大。", repr(content_txt))
check("流式：以 stop 收尾", finish == "stop", str(finish))

print()
mock.shutdown()
proxy.shutdown()

print("=" * 60)
if FAILED:
    print("失败 %d 项：%s" % (len(FAILED), FAILED))
    sys.exit(1)
print("全部通过 ✅")
