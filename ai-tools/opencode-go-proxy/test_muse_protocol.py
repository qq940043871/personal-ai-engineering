#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 muse / anthropic 模型的协议路由：
用一个 mock 上游记录「代理实际打过来的路径」，绕开真实账户的隐私限制。

结论不看代理日志（那只是 resolve_model 的输出），而看 mock 端收到的真实 path。

v1.4 起：anthropic（qwen / minimax）不再是 501，而是真的打到 /messages 并回译。
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import http.server
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
PYEXE = sys.executable


def _free_port():
    """要一个空闲端口：写死端口会被本机遗留进程抢占（Windows 允许 SO_REUSEADDR，
    表现为"绑定成功但请求被旧进程接走"）。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


MOCK_PORT = _free_port()
PROXY_PORT = _free_port()

received = []


class MockUpstream(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {}
        received.append({
            "path": self.path,
            "model": payload.get("model"),
            "has_session": bool(self.headers.get("x-opencode-session")),
        })

        if self.path.endswith("/responses"):
            resp = {
                "id": "resp_mock",
                "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": "MUSE-OK"}]}],
                "usage": {"input_tokens": 5, "output_tokens": 3},
            }
        elif self.path.endswith("/messages"):
            # Anthropic 协议形状（v1.4 起代理会翻译它）
            resp = {
                "id": "msg_mock", "type": "message", "role": "assistant",
                "stop_reason": "end_turn", "model": "anthropic-mock",
                "content": [{"type": "text", "text": "ANTHROPIC-OK"}],
                "usage": {"input_tokens": 5, "output_tokens": 3},
            }
        else:
            resp = {"choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": "CHAT-OK"}}]}
        b = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def main():
    mock = http.server.ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockUpstream)
    threading.Thread(target=mock.serve_forever, daemon=True).start()

    env = dict(os.environ)
    env["OPENCODE_API_KEY"] = "test-key"
    env["OPENCODE_BASE"] = "http://127.0.0.1:%d/v1" % MOCK_PORT
    env["LUNA_PROXY_PORT"] = str(PROXY_PORT)
    env["PYTHONUTF8"] = "1"

    proc = subprocess.Popen(
        [PYEXE, "-u", os.path.join(HERE, "oc_session_proxy.py")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=HERE,
    )
    time.sleep(2.5)

    def call(model):
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 50,
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:%d/v1/chat/completions" % PROXY_PORT,
            data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer x"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))

    fail = 0

    def check(label, model, expect_path):
        nonlocal fail
        before = len(received)
        resp = call(model)
        got = received[before] if len(received) > before else None
        ok = got is not None and got["path"].endswith(expect_path)
        if not ok:
            fail += 1
        print("%s  %-46s -> upstream path=%-22s model=%s" % (
            "[OK]" if ok else "[FAIL]", model,
            got["path"] if got else "(no request)", got["model"] if got else "-"))
        if not ok:
            print("        期望 path 后缀: %s" % expect_path)
        return resp

    print("=" * 78)
    print(" 协议路由验证（mock 上游记录真实路径）")
    print("=" * 78)

    # muse 走 /responses
    r = check("muse", "opencode-go-muse-spark-1.3-contributor", "/responses")
    print("         -> 回译 content =", repr(r["choices"][0]["message"]["content"]))

    # muse 只写系列名
    check("muse-series", "muse", "/responses")

    # luna 依然走 /responses（回归）
    check("luna", "opencode-go-gpt-6-luna", "/responses")

    # deepseek 依然走 /chat/completions（回归）
    check("deepseek", "opencode-go-deepseek-v4.1-flash", "/chat/completions")

    # anthropic 模型（v1.4 起已支持）：应打到 /messages，并把正文回译出来
    r = check("anthropic", "qwen3.8-max", "/messages")
    print("         -> 回译 content =", repr(r["choices"][0]["message"]["content"]))
    check("minimax 也走 /messages", "minimax-m3", "/messages")

    # 每次请求都带 session 头
    no_session = [r for r in received if not r["has_session"]]
    if no_session:
        print("[FAIL]  有 %d 个请求缺少 x-opencode-session 头" % len(no_session))
        fail += 1
    else:
        print("[OK]  全部 %d 个上游请求都带上了 x-opencode-session 头" % len(received))

    # /v1/models 应列出 muse
    with urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % PROXY_PORT, timeout=5) as r:
        ids = [m["id"] for m in json.loads(r.read().decode("utf-8"))["data"]]
    has_muse = "muse-spark-1.3-contributor" in ids
    if not has_muse:
        fail += 1
    print("%s  /v1/models 含 muse-spark-1.3-contributor: %s" % (
        "[OK]" if has_muse else "[FAIL]", ids))

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    mock.shutdown()

    print()
    print("结果: %s" % ("全部通过" if fail == 0 else "失败 %d 项" % fail))
    raise SystemExit(1 if fail else 0)


if __name__ == "__main__":
    main()
