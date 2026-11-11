#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 CodeBuddy 里"声明了 supportsReasoning 但缺 reasoning 配置"的模型补齐配置。

背景（与 WorkBuddy 同源，已在 codebuddy-lite-wb.mjs 中核对）：
    configureThinkingSettings() 里
        if (!modelInfo.supportsReasoning) { 删 reasoning; return }
    也就是说只有 supportsReasoning 是**不够**的，必须带 reasoning 对象，
    否则请求里根本不会附加任何推理参数；onlyReasoning 则决定「思考」能否被关掉。

用法：
    python enable_thinking_cb.py            # 预演（dry-run），只打印不改
    python enable_thinking_cb.py --apply    # 真正写入（自动备份）
"""
import io
import json
import os
import shutil
import sys
import datetime

MODELS = os.path.join(os.path.expanduser("~"), ".codebuddy", "models.json")

REASONING = {
    "defaultEffort": "medium",
    "effort": "medium",
    "summary": "concise",
    "supportedEfforts": ["low", "medium", "high"],
    "canDisableThinking": False,
}

# 只处理这些（本次用户点名要补的三个直连模型）
TARGET_IDS = {"qwen3.8-max", "qwen3.8-flash", "mimo-v2.6-pro"}


def main():
    apply = "--apply" in sys.argv

    with io.open(MODELS, encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg, dict) or not isinstance(cfg.get("models"), list):
        print("[FAIL] 结构不符合预期")
        return 1

    hits = []
    for m in cfg["models"]:
        mid = m.get("id", "")
        if mid not in TARGET_IDS:
            continue
        need = (m.get("supportsReasoning") is True
                and not m.get("reasoning"))
        if need:
            hits.append(m)

    if not hits:
        print("没有需要补的条目（都已具备 reasoning 配置）。")
        return 0

    print("待补条目 %d 个：" % len(hits))
    for m in hits:
        print("  %-18s supportsReasoning=%s  reasoning=%s"
              % (m.get("id"), m.get("supportsReasoning"), m.get("reasoning")))
    print()

    if not apply:
        print("[DRY-RUN] 未写入。加 --apply 才真正修改。")
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = "%s.bak-%s" % (MODELS, stamp)
    shutil.copy2(MODELS, backup)
    print("已备份 -> %s" % os.path.basename(backup))

    for m in hits:
        m["onlyReasoning"] = True
        m["reasoning"] = dict(REASONING)

    tmp = MODELS + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(cfg, ensure_ascii=False, indent=2))
    os.replace(tmp, MODELS)

    with io.open(MODELS, encoding="utf-8") as fh:
        check = json.load(fh)
    print("\n复核：")
    for m in check["models"]:
        if m.get("id") in TARGET_IDS:
            print("  %-18s onlyReasoning=%s reasoning=%s"
                  % (m.get("id"), m.get("onlyReasoning"),
                     "有" if m.get("reasoning") else "无"))
    print("\n[OK] 写入完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
