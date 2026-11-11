#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 OpenCode Go 的三个模型配置到 CodeBuddy（~/.codebuddy/models.json）。

与 WorkBuddy 的两处关键差异（已核对官方文档 + 打包产物）：

  1. 顶层结构不同：CodeBuddy 是 {"models": [...]} 对象，WorkBuddy 是纯数组。
  2. url 必须写**完整路径**（官方文档明确："必须是接口完整路径，一般以
     /chat/completions 结尾"），而 WorkBuddy 只填到 /v1、由它自己拼。

思考配置与 WorkBuddy 同源（同一份代码里的 canDisableThinking /
configureThinkingSettings），所以字段可以直接照搬：
    supportsReasoning + onlyReasoning + reasoning{...}

另外移除一个坏条目：旧的 `deepseek-v4.1-flash` 直连 opencode.ai
（缺 x-opencode-session 头，必然 400 MissingSessionID）。
"""
import io
import json
import os
import shutil
import datetime

MODELS = os.path.join(os.path.expanduser("~"), ".codebuddy", "models.json")
PROXY_URL = "http://127.0.0.1:8787/v1/chat/completions"
PROXY_KEY = "local-proxy"

REASONING = {
    "defaultEffort": "medium",
    "effort": "medium",
    "summary": "concise",          # 代理会把 auto/detailed 收敛成 concise
    "supportedEfforts": ["low", "medium", "high"],
    "canDisableThinking": False,
}

# 要移除的坏条目 id（直连上游、且 supportsReasoning=false）
DROP_IDS = {"deepseek-v4.1-flash"}

NEW_MODELS = [
    {
        "id": "opencode-go-deepseek-v4.1-flash",
        "name": "OpenCode Go · DeepSeek V4.1 Flash (代理)",
        "vendor": "Custom",
        "url": PROXY_URL,
        "apiKey": PROXY_KEY,
        "maxInputTokens": 1000000,
        "maxOutputTokens": 64000,
        "supportsToolCall": True,
        "supportsImages": False,
        "supportsReasoning": True,
        "onlyReasoning": True,
        "reasoning": dict(REASONING),
    },
    {
        "id": "opencode-go-gpt-6-luna",
        "name": "OpenCode Go · GPT-6 Luna (代理)",
        "vendor": "Custom",
        "url": PROXY_URL,
        "apiKey": PROXY_KEY,
        "maxInputTokens": 272000,
        "maxOutputTokens": 32000,
        "supportsToolCall": True,
        "supportsImages": False,
        "supportsReasoning": True,
        "onlyReasoning": True,
        "reasoning": dict(REASONING),
    },
    {
        "id": "opencode-go-muse-spark-1.3-contributor",
        "name": "OpenCode Go · Muse Spark 1.3 Contributor (代理)",
        "vendor": "Custom",
        "url": PROXY_URL,
        "apiKey": PROXY_KEY,
        "maxInputTokens": 1000000,
        "maxOutputTokens": 32000,
        "supportsToolCall": True,
        "supportsImages": True,
        "supportsReasoning": True,
        "onlyReasoning": True,
        "reasoning": dict(REASONING),
    },
]


def main():
    if not os.path.exists(MODELS):
        print("[FAIL] 找不到 %s" % MODELS)
        return 1

    with io.open(MODELS, encoding="utf-8") as fh:
        cfg = json.load(fh)

    # 兼容：必须是 {"models": [...]} 对象（与 WorkBuddy 的数组不同）
    if isinstance(cfg, list):
        print("[WARN] 顶层是数组，转为 {'models': [...]} 以符合 CodeBuddy 格式")
        cfg = {"models": cfg}
    if not isinstance(cfg, dict) or not isinstance(cfg.get("models"), list):
        print("[FAIL] 结构不符合预期，已中止。")
        return 1

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = "%s.bak-%s" % (MODELS, stamp)
    shutil.copy2(MODELS, backup)
    print("已备份 -> %s" % os.path.basename(backup))
    print()

    before = cfg["models"]
    new_ids = {m["id"] for m in NEW_MODELS}

    # 1) 移除坏条目 + 同名旧条目（以新配置为准）
    kept, dropped = [], []
    for m in before:
        mid = m.get("id", "")
        if mid in DROP_IDS or mid in new_ids:
            dropped.append(mid)
        else:
            kept.append(m)

    for d in dropped:
        print("  [-] 移除旧条目: %s" % d)

    # 2) 追加新条目
    for m in NEW_MODELS:
        kept.append(m)
        print("  [+] 新增条目: %-46s -> %s" % (m["id"], m["url"]))

    cfg["models"] = kept

    tmp = MODELS + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(cfg, ensure_ascii=False, indent=2))
    os.replace(tmp, MODELS)

    # 3) 复核（重新读盘）
    with io.open(MODELS, encoding="utf-8") as fh:
        check = json.load(fh)
    print()
    print("复核（共 %d 条）：" % len(check["models"]))
    for m in check["models"]:
        mid = m.get("id", "")
        mark = "  <== 新增" if mid in new_ids else ""
        print("  %-46s reasoning=%s%s"
              % (mid,
                 "有" if m.get("reasoning") else "无",
                 mark))
    print()
    print("[OK] 写入完成 -> %s" % MODELS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
