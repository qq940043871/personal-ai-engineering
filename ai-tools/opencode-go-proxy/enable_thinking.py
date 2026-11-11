#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 OpenCode Go 的自定义模型条目补上推理配置，让 WorkBuddy 真正开启思考。

背景（从 WorkBuddy 打包产物里读出来的逻辑）：

  configureThinkingSettings() 里：
      if (!modelInfo.supportsReasoning) { 删除 reasoning; return }
      ...
      let effort = 会话override ?? 全局reasoningEffort ?? cfg.reasoning?.defaultEffort ?? cfg.reasoning?.effort;
      if (effort) { reasoning.effort = ...; reasoning.summary ||= cfg.reasoning?.summary ?? "auto" }

  所以只写 supportsReasoning: true 是**不够**的：
    - 没有 cfg.reasoning，就不会往请求里附加任何 reasoning 参数
    - 没有 onlyReasoning，模型会被判定为"可以关闭思考"，
      于是那个「已关闭」的会话覆盖不会像内置推理模型那样被重置回开启

  WorkBuddy 内置推理模型的写法（product.json 实测）：
      "supportsReasoning": true, "onlyReasoning": true,
      "reasoning": { "effort": "high", "summary": "auto" }

本脚本把自定义条目对齐成同样的形状。
"""
import json
import os
import shutil
import datetime

MODELS = r"C:\Users\qq940\.workbuddy\models.json"
TARGET_PREFIX = "opencode-go-"

# 三个 OpenCode Go 模型统一启用思考。
# supportedEfforts 决定 UI「深度思考」下拉里能选哪几档；
# canDisableThinking=false + onlyReasoning=true => 「关闭」选项消失，思考强制开启。
REASONING = {
    "defaultEffort": "medium",     # 用户指定：默认中等思考
    "effort": "medium",
    "summary": "concise",          # 实测：上游只有 concise 会真正返回摘要文本
    "supportedEfforts": ["low", "medium", "high"],
    "canDisableThinking": False,
}


def main():
    with open(MODELS, encoding="utf-8") as fh:
        models = json.load(fh)

    if not isinstance(models, list):
        print("[FAIL] models.json 顶层不是数组，格式与预期不符，已中止。")
        return 1

    # 备份
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = "%s.bak-%s" % (MODELS, stamp)
    shutil.copy2(MODELS, backup)
    print("已备份 -> %s" % os.path.basename(backup))

    changed = 0
    for m in models:
        mid = m.get("id") or ""
        if not mid.startswith(TARGET_PREFIX):
            continue
        before = {k: m.get(k) for k in ("supportsReasoning", "onlyReasoning", "reasoning")}
        m["supportsReasoning"] = True
        m["onlyReasoning"] = True
        m["reasoning"] = dict(REASONING)
        after = {k: m.get(k) for k in ("supportsReasoning", "onlyReasoning", "reasoning")}
        if before != after:
            changed += 1
            print("  更新 %s" % m.get("name"))
            print("      onlyReasoning = True")
            print("      reasoning     = %s" % json.dumps(m["reasoning"], ensure_ascii=False))

    if not changed:
        print("没有需要更新的条目。")
        return 0

    tmp = MODELS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(models, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, MODELS)

    # 复核
    with open(MODELS, encoding="utf-8") as fh:
        check = json.load(fh)
    print()
    print("复核（共 %d 条）：" % len(check))
    for m in check:
        mid = m.get("id") or ""
        if mid.startswith(TARGET_PREFIX):
            print("  %-46s onlyReasoning=%s reasoning=%s"
                  % (m.get("name"),
                     m.get("onlyReasoning"),
                     json.dumps(m.get("reasoning"), ensure_ascii=False)))
    print()
    print("[OK] 写入完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
