#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模拟 CodeBuddy 的请求打到本地代理，验证端到端链路（支持流式）。

用法：
    python test_via_proxy.py                       # 三个模型，默认问题，非流式
    python test_via_proxy.py <model-id> [...]      # 指定模型
环境变量：
    PROMPT   提问内容
    MAXTOK   最大输出 token（默认 2000）
    STREAM   置 1 走流式 SSE（贴近 CodeBuddy 的真实行为）
"""
import io
import json
import os
import sys
import urllib.error
import urllib.request

PROXY = "http://127.0.0.1:8787/v1/chat/completions"
PROMPT = os.environ.get("PROMPT", "只回复两个字：收到")
MAXTOK = int(os.environ.get("MAXTOK", "2000"))
STREAM = os.environ.get("STREAM", "0") == "1"


def build_body(model):
    return json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": MAXTOK,
        "stream": STREAM,
    }).encode("utf-8")


def call(model):
    req = urllib.request.Request(PROXY, data=build_body(model), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer local-proxy")
    req.add_header("User-Agent", "codebuddy/2.159.0")
    if STREAM:
        req.add_header("Accept", "text/event-stream")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, "TRANSPORT: %s" % e


def report_stream(text):
    """统计 SSE 里 reasoning_content 与 content 的增量。"""
    n_reason = n_content = 0
    snap_r, snap_c = [], []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        for ch in obj.get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("reasoning_content"):
                n_reason += 1
                if len(snap_r) < 3:
                    snap_r.append(d["reasoning_content"])
            if d.get("content"):
                n_content += 1
                if len(snap_c) < 3:
                    snap_c.append(d["content"])
    print("  流式事件数 : reasoning=%d, content=%d" % (n_reason, n_content))
    if snap_r:
        print("  思考片段   : %r" % ("".join(snap_r)[:100],))
    if snap_c:
        print("  正文片段   : %r" % ("".join(snap_c)[:100],))


def report_json(text):
    obj = json.loads(text)
    msg = (obj.get("choices") or [{}])[0].get("message") or {}
    content = msg.get("content")
    reasoning = msg.get("reasoning_content")
    print("  content          : %r" % (content if content is None else content[:120]))
    print("  reasoning_content: %s" % ("有 %d 字" % len(reasoning) if reasoning else "无/空"))
    if obj.get("error"):
        print("  error            : %s" % json.dumps(obj["error"], ensure_ascii=False)[:300])
    u = obj.get("usage") or {}
    if u:
        print("  usage            : %s" % json.dumps(u, ensure_ascii=False))


def main():
    models = sys.argv[1:] or [
        "opencode-go-deepseek-v4.1-flash",
        "opencode-go-gpt-6-luna",
        "opencode-go-muse-spark-1.3-contributor",
    ]
    print("提示词: %r   流式: %s   max_tokens: %d" % (PROMPT[:40], STREAM, MAXTOK))
    print()
    for m in models:
        print("=" * 66)
        print("模型: %s" % m)
        status, text = call(m)
        print("HTTP %s" % status)
        try:
            if STREAM:
                report_stream(text)
            else:
                report_json(text)
        except Exception as e:
            print("  解析失败(%s)，原始返回: %s" % (e, text[:400]))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
