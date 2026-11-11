#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 resolve_model 的翻译逻辑（无需网络）。"""
import importlib.util
import os

spec = importlib.util.spec_from_file_location("ocproxy", os.path.join(os.path.dirname(os.path.abspath(__file__)), "oc_session_proxy.py"))
m = importlib.util.module_from_spec(spec)
# 避免 require key 导致退出：模块级不做退出，可安全导入
spec.loader.exec_module(m)

cases = [
    # (WorkBuddy 发来的 model, 期望上游模型, 期望协议)
    ("opencode-go-deepseek-v4.1-flash", "deepseek-v4.1-flash", "chat"),
    ("deepseek-v4.1-flash", "deepseek-v4.1-flash", "chat"),
    ("deepseek-v4-pro", "deepseek-v4-pro", "chat"),
    ("kimi-k3", "kimi-k3", "chat"),
    ("glm-5.3", "glm-5.3", "chat"),
    ("opencode-go-gpt-6-luna", "gpt-6-luna", "responses"),
    ("opencode-go-gpt-5.6-luna", "gpt-5.6-luna", "responses"),
    ("gpt-6-luna", "gpt-6-luna", "responses"),
    ("gpt-5.6-luna", "gpt-5.6-luna", "responses"),
    ("luna", "gpt-6-luna", "responses"),
    ("grok-4.7", "grok-4.7", "responses"),
    ("grok-4.6", "grok-4.6", "responses"),
    # --- Muse Spark（Responses 协议，Meta 贡献者模型）---
    ("muse-spark-1.3-contributor", "muse-spark-1.3-contributor", "responses"),
    ("opencode-go-muse-spark-1.3-contributor", "muse-spark-1.3-contributor", "responses"),
    ("muse-spark-1.2-contributor", "muse-spark-1.2-contributor", "responses"),
    ("muse", "muse-spark-1.3-contributor", "responses"),
    ("opencode-go-muse", "muse-spark-1.3-contributor", "responses"),
    # --- Anthropic Messages 协议：识别出来但代理会明确报 501（不静默兜底）---
    ("qwen3.8-max", "qwen3.8-max", "anthropic"),
    ("qwen3.8-flash", "qwen3.8-flash", "anthropic"),
    ("minimax-m3", "minimax-m3", "anthropic"),
    # 最长优先：避免 mimo-v2.5 抢先命中 mimo-v2.5-pro
    ("mimo-v2.5-pro", "mimo-v2.5-pro", "chat"),
    ("opencode-go-mimo-v2.5-pro", "mimo-v2.5-pro", "chat"),
    ("deepseek-v4-flash-vision-exp", "deepseek-v4-flash-vision-exp", "chat"),
    ("", "deepseek-v4.1-flash", "chat"),
    ("some-random-junk", "deepseek-v4.1-flash", "chat"),
]

fail = 0
for inp, exp_model, exp_proto in cases:
    got_model, got_proto = m.resolve_model(inp)
    ok = (got_model == exp_model and got_proto == exp_proto)
    if not ok:
        fail += 1
    print("%s  %-32r -> %-22s %-9s" % ("[OK]" if ok else "[FAIL]", inp, got_model, got_proto))
    if not ok:
        print("        期望: %s / %s" % (exp_model, exp_proto))

print()
print("结果: %d/%d 通过" % (len(cases) - fail, len(cases)))
raise SystemExit(1 if fail else 0)
