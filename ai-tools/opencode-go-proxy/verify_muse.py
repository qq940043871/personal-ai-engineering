#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenCode Go 隐私开关验证器（Muse Spark）

用途：
    去 OpenCode 控制台开完「Allow models that train on request data」
    之后，跑这个脚本确认 Muse Spark 是否已经放行。

它**直连** https://opencode.ai/zen/go/v1/responses（绕过本地代理），
发一个最小请求，然后按返回内容给出分类诊断。开关有没有生效，一测便知，
不用猜菜单文字。

用法（Git Bash）：
    export PYTHONUTF8=1
    C:/Users/qq940/.workbuddy/binaries/python/versions/3.13.12/python.exe verify_muse.py

API key 来源优先级：
    1) 环境变量 OPENCODE_API_KEY
    2) 同目录的 start_proxy.sh / start_proxy.bat 里正则提取
"""
import json
import os
import re
import sys
import uuid
import urllib.error
import urllib.request

BASE = "https://opencode.ai/zen/go/v1/responses"
MODEL = "muse-spark-1.3-contributor"
# 期望的思考档位（改这里或传环境变量 VERIFY_EFFORT）
EFFORT = os.environ.get("VERIFY_EFFORT", "medium")


def find_key():
    k = os.environ.get("OPENCODE_API_KEY", "").strip()
    if k:
        return k, "环境变量 OPENCODE_API_KEY"
    here = os.path.dirname(os.path.abspath(__file__))
    for fn in ("start_proxy.sh", "start_proxy.bat"):
        p = os.path.join(here, fn)
        if not os.path.exists(p):
            continue
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        m = re.search(r"oc_sk_[A-Za-z0-9_]+", txt)
        if m:
            return m.group(0), fn
    return "", None


def post(url, key, model, session):
    body = json.dumps({
        "model": model,
        "input": "ping",
        "max_output_tokens": 64,
        # 代理就是这样向上游注入的；这里照抄一份，用来验证档位是否被接受并回显
        "reasoning": {"effort": EFFORT, "summary": "concise"},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer %s" % key)
    req.add_header("x-opencode-session", session)
    # Cloudflare 会按 UA 拦 urllib 默认签名（error 1010），必须伪装成正常客户端
    req.add_header("User-Agent", "opencode/1.0.0 (workbuddy-proxy-verify)")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, "TRANSPORT: %s" % e


def classify(status, text):
    low = text.lower()
    if status == 200:
        return "OK", ("[OK] 已放行！隐私开关生效，Muse Spark 现在可以用了。\n"
                      "     -> 关掉代理再重启一次（让 medium 档位生效），然后完全重启 WorkBuddy。")
    if "train on request data" in low or "privacy settings" in low:
        return "PRIVACY", ("[X] 开关还没生效。上游仍认为你没同意「用请求数据训练」。\n"
                           "    -> 去 OpenCode 控制台打开 Allow models that train on request data，\n"
                           "       保存后等 1-2 分钟，再跑一次本脚本。")
    if ("geograph" in low or "not available in your" in low
            or ("region" in low and "limit" in low)):
        return "REGION", ("[!] 隐私开关已过，但卡在**地域限制**（Meta Geographic Use Policy）。\n"
                          "    这是设置里解决不了的，中国大陆大概率不可用。")
    if "missing session" in low or "sessionid" in low:
        return "SESSION", "[X] 缺 x-opencode-session 头（脚本问题，不是你的配置问题）。"
    if "model is unavailable" in low:
        return "MODEL", "[X] 模型名不被上游识别。"
    if "invalid" in low and "key" in low:
        return "KEY", "[X] API key 无效或被吊销。"
    if "insufficient" in low or "quota" in low or "balance" in low:
        return "QUOTA", "[X] 余额/额度不足。"
    return "OTHER", "[?] 未分类的返回，看下面的原文自己判断。"


def main():
    key, src = find_key()
    if not key:
        print("[FAIL] 找不到 API key。")
        print("       先设置环境变量再跑：export OPENCODE_API_KEY=oc_sk_xxxx")
        return 1
    print("API key 来源 : %s" % src)
    print("目标端点     : %s" % BASE)
    print("模型         : %s" % MODEL)
    print()
    print("请求中 ...")
    session = "wb-verify-" + uuid.uuid4().hex
    status, text = post(BASE, key, MODEL, session)
    print("HTTP %s" % status)
    try:
        print(json.dumps(json.loads(text), ensure_ascii=False, indent=2)[:1600])
    except Exception:
        print(text[:1600])
    print()
    tag, msg = classify(status, text)
    print("=" * 64)
    print("[%s] %s" % (tag, msg))
    print("=" * 64)

    # 额外验证：上游是否接受并回显了我们要求的思考档位
    if status == 200:
        try:
            obj = json.loads(text)
        except Exception:
            obj = None
        if isinstance(obj, dict):
            got = (obj.get("reasoning") or {}).get("effort")
            rtok = (((obj.get("usage") or {}).get("output_tokens_details") or {})
                    .get("reasoning_tokens"))
            print()
            print("思考档位回显 : %s   (本脚本请求 = %s)" % (got, EFFORT))
            print("思考 token   : %s" % rtok)
            if got and got != EFFORT:
                print("[!] 回显与请求不一致：上游可能忽略低档位，或强制抬到 %s。" % got)
            elif got == EFFORT:
                print("[OK] 档位一致，%s 已被上游接受。" % EFFORT)
    return 0 if tag == "OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
