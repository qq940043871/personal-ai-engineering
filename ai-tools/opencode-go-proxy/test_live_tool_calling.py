#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实上游端到端：验证 v1.4 的「工具调用」和「Anthropic 协议」确实可用。

不是 mock —— 真的启动代理、真的打 opencode.ai。

覆盖：
  1. Responses（Luna）非流式工具调用
  2. Responses（Luna）流式工具调用
  3. 两轮完整工具闭环：模型要工具 -> 回灌结果 -> 模型给最终答案
  4. Anthropic（MiniMax / Qwen）非流式 + 流式工具调用
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PYEXE = sys.executable
KEY = os.environ.get("OPENCODE_API_KEY", "").strip()
if not KEY:
    print("需要 OPENCODE_API_KEY")
    sys.exit(1)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PROXY_PORT = _free_port()
BASE = "http://127.0.0.1:%d/v1" % PROXY_PORT

FAILED = []


def check(name, cond, extra=""):
    print("  [%s] %s %s" % ("OK" if cond else "FAIL", name, extra))
    if not cond:
        FAILED.append(name)


TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市的实时天气",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string",
                                               "description": "城市名，如 北京"}},
                       "required": ["city"]},
    },
}]


def call(model, messages, stream=False, tools=TOOLS, max_tokens=512):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
    if stream:
        body["stream"] = True
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer local-proxy"},
        method="POST")

    if not stream:
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print("      HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:400]))
            return None

    content, reasoning, finish, tool_calls = "", "", None, {}

    def merge(d):
        nonlocal content, reasoning
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

    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            for line in r:
                line = line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    break
                obj = json.loads(raw)
                for ch in obj.get("choices", []):
                    merge(ch.get("delta") or {})
                    if ch.get("finish_reason"):
                        finish = ch["finish_reason"]
    except urllib.error.HTTPError as e:
        print("      HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:400]))
        return None
    return {"choices": [{"message": dict(
        {"role": "assistant", "content": content},
        **({"reasoning_content": reasoning} if reasoning else {}),
        **({"tool_calls": [tool_calls[k] for k in sorted(tool_calls)]} if tool_calls else {}),
    ), "finish_reason": finish}]}


env = dict(os.environ)
env["OPENCODE_API_KEY"] = KEY
env["LUNA_PROXY_PORT"] = str(PROXY_PORT)
env["PYTHONUTF8"] = "1"
env.pop("OPENCODE_BASE", None)   # 用真实上游

proc = subprocess.Popen([PYEXE, "-u", os.path.join(HERE, "oc_session_proxy.py")],
                        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        cwd=HERE, text=True, encoding="utf-8", errors="replace")
time.sleep(2.5)

try:
    print("=" * 74)
    print(" 1. Responses 协议（gpt-6-luna）工具调用")
    print("=" * 74)
    r = call("opencode-go-gpt-6-luna",
             [{"role": "user", "content": "北京现在天气怎么样？必须调用 get_weather 工具。"}])
    if r is None:
        check("Luna 非流式有响应", False, "请求失败")
    else:
        ch = r["choices"][0]
        m = ch["message"]
        tcs = m.get("tool_calls") or []
        check("非流式：返回了 tool_calls", bool(tcs),
              json.dumps(tcs, ensure_ascii=False)[:200])
        check("非流式：finish_reason=tool_calls", ch["finish_reason"] == "tool_calls",
              str(ch["finish_reason"]))
        if tcs:
            check("非流式：工具名正确", tcs[0]["function"]["name"] == "get_weather")
            try:
                args = json.loads(tcs[0]["function"]["arguments"])
                check("非流式：arguments 是合法 JSON", isinstance(args, dict), str(args))
                check("非流式：城市参数合理", "北京" in str(args.get("city", "")),
                      str(args))
            except Exception as e:
                check("非流式：arguments 是合法 JSON", False, "%s / %r"
                      % (e, tcs[0]["function"]["arguments"]))
        check("非流式：call id 非空", bool(tcs and tcs[0]["id"]),
              tcs[0]["id"] if tcs else "-")

    print()
    print("=" * 74)
    print(" 2. Responses 协议流式工具调用")
    print("=" * 74)
    rs = call("opencode-go-gpt-6-luna",
              [{"role": "user", "content": "上海现在天气怎么样？必须调用 get_weather 工具。"}],
              stream=True)
    if rs is None:
        check("Luna 流式有响应", False, "请求失败")
    else:
        ch = rs["choices"][0]
        tcs = ch["message"].get("tool_calls") or []
        check("流式：拼出 tool_calls", bool(tcs), json.dumps(tcs, ensure_ascii=False)[:200])
        check("流式：finish_reason=tool_calls", ch["finish_reason"] == "tool_calls",
              str(ch["finish_reason"]))
        if tcs:
            check("流式：工具名正确", tcs[0]["function"]["name"] == "get_weather")
            try:
                check("流式：arguments 拼回合法 JSON",
                      isinstance(json.loads(tcs[0]["function"]["arguments"]), dict),
                      tcs[0]["function"]["arguments"])
            except Exception as e:
                check("流式：arguments 拼回合法 JSON", False,
                      "%s / %r" % (e, tcs[0]["function"]["arguments"]))

    print()
    print("=" * 74)
    print(" 3. 两轮完整工具闭环（要工具 -> 回灌结果 -> 最终答复）")
    print("=" * 74)
    first = call("opencode-go-gpt-6-luna",
                 [{"role": "user", "content": "北京现在天气怎么样？必须调用 get_weather 工具。"}])
    tc = None
    if first:
        tcs = first["choices"][0]["message"].get("tool_calls") or []
        tc = tcs[0] if tcs else None
    if not tc:
        check("第 1 轮拿到工具调用", False, "没有 tool_calls，无法闭环")
    else:
        check("第 1 轮拿到工具调用", True, tc["function"]["name"])
        second = call("opencode-go-gpt-6-luna", [
            {"role": "user", "content": "北京现在天气怎么样？必须调用 get_weather 工具。"},
            {"role": "assistant", "content": None, "tool_calls": [tc]},
            {"role": "tool", "tool_call_id": tc["id"],
             "content": json.dumps({"city": "北京", "temp_c": 25, "weather": "晴"},
                                   ensure_ascii=False)},
        ])
        if second is None:
            check("第 2 轮（回灌 function_call_output）成功", False, "请求失败")
        else:
            ch = second["choices"][0]
            txt = (ch["message"].get("content") or "")
            check("第 2 轮成功返回最终答复", bool(txt.strip()), repr(txt[:120]))
            check("第 2 轮答复引用了工具结果（含 25 或 晴 或 北京）",
                  any(k in txt for k in ("25", "晴", "北京")), repr(txt[:120]))
            check("第 2 轮不再是 tool_calls", ch["finish_reason"] != "tool_calls",
                  str(ch["finish_reason"]))

    print()
    print("=" * 74)
    print(" 4. Anthropic 协议（/messages）工具调用")
    print("=" * 74)
    for model, label in (("minimax-m3", "MiniMax M3"),
                         ("qwen3.8-flash", "Qwen3.8 Flash")):
        print("  --- %s (%s) ---" % (label, model))
        a = call(model, [{"role": "user",
                          "content": "广州现在天气怎么样？必须调用 get_weather 工具。"}])
        if a is None:
            check("%s 非流式有响应" % label, False, "请求失败")
            continue
        ch = a["choices"][0]
        tcs = ch["message"].get("tool_calls") or []
        check("%s 非流式：返回 tool_calls" % label, bool(tcs),
              json.dumps(tcs, ensure_ascii=False)[:160])
        if tcs:
            check("%s：工具名正确" % label, tcs[0]["function"]["name"] == "get_weather")
            try:
                check("%s：arguments 合法 JSON" % label,
                      isinstance(json.loads(tcs[0]["function"]["arguments"]), dict),
                      tcs[0]["function"]["arguments"])
            except Exception as e:
                check("%s：arguments 合法 JSON" % label, False, str(e))

        at = call(model, [{"role": "user",
                           "content": "深圳现在天气怎么样？必须调用 get_weather 工具。"}],
                  stream=True)
        if at is None:
            check("%s 流式有响应" % label, False, "请求失败")
        else:
            tcs2 = at["choices"][0]["message"].get("tool_calls") or []
            check("%s 流式：拼出 tool_calls" % label, bool(tcs2),
                  json.dumps(tcs2, ensure_ascii=False)[:160])
            if tcs2:
                try:
                    check("%s 流式：arguments 合法 JSON" % label,
                          isinstance(json.loads(tcs2[0]["function"]["arguments"]), dict),
                          tcs2[0]["function"]["arguments"])
                except Exception as e:
                    check("%s 流式：arguments 合法 JSON" % label, False, str(e))
        print()

finally:
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=5)
    except Exception:
        proc.kill()
        out = ""
    print("-" * 74)
    print("代理日志（末尾 20 行）：")
    for ln in (out or "").strip().splitlines()[-20:]:
        print("   ", ln)

print()
print("=" * 74)
if FAILED:
    print("失败 %d 项：" % len(FAILED))
    for f in FAILED:
        print("   -", f)
    sys.exit(1)
print("真实上游全部通过 ✅")
