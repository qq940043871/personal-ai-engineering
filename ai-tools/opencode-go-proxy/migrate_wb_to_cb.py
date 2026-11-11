#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 WorkBuddy 的自定义模型迁移到 CodeBuddy。

源:   ~/.workbuddy/models.json   （顶层是数组 [{...}]）
目标: ~/.codebuddy/models.json   （顶层是对象 {"models": [{...}]}）

规则：
  1. 按 id 去重，只追加 CodeBuddy 里还没有的模型（绝不改动已有条目）。
  2. url 补全：CodeBuddy 要求 url 以 /chat/completions 结尾，
     而 WorkBuddy 只填到 /v1，所以结尾缺 /chat/completions 的统一补上。
  3. vendor 统一写成 Custom（WorkBuddy 内置的 vendor=Buddy 条目在 CodeBuddy
     里也作为自定义模型，避免不认识的 vendor 导致分组/识别异常）。
  4. 备份 + 原子写入（先 .tmp 再 replace）。

用法：
  python migrate_wb_to_cb.py           # 预演，只打印将写入什么
  python migrate_wb_to_cb.py --apply   # 真写（自动备份）
"""
import json
import os
import shutil
import sys
import time

HOME = os.path.expanduser("~")
WB = os.path.join(HOME, ".workbuddy", "models.json")
CB = os.path.join(HOME, ".codebuddy", "models.json")


def fix_url(url):
    url = (url or "").strip()
    if url.endswith("/chat/completions"):
        return url
    return url.rstrip("/") + "/chat/completions"


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    apply = "--apply" in sys.argv

    wb = load(WB)
    cb = load(CB)
    existing_ids = {m.get("id") for m in cb.get("models", [])}

    migrated = []
    for m in wb:
        mid = m.get("id")
        if not mid or mid in existing_ids:
            continue
        item = dict(m)
        item["url"] = fix_url(item.get("url", ""))
        item["vendor"] = "Custom"
        migrated.append(item)

    if not migrated:
        print("没有需要迁移的新模型：WorkBuddy 里的模型已全部存在于 CodeBuddy。")
        return

    print(f"将迁移 {len(migrated)} 个模型到 CodeBuddy：")
    for m in migrated:
        print(f"  - {m['id']:28s} -> {m['url']}")

    if not apply:
        print("\n[预演] 未写入。确认无误后加 --apply 真写。")
        return

    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = f"{CB}.bak-{ts}"
    shutil.copy2(CB, bak)

    result = {"models": cb.get("models", []) + migrated}
    tmp = CB + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, CB)

    print(f"\n已写入 {len(migrated)} 个模型。")
    print(f"备份：{bak}")
    print("注意：CodeBuddy 模型配置热重载（约 1 秒生效），无需重启。")


if __name__ == "__main__":
    main()
