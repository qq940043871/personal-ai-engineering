#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把走 Anthropic /messages 协议的模型（Qwen / MiniMax）接入两个客户端。

代理 v1.4 已经能翻译 /messages 协议（含工具调用），但**客户端还得先有模型条目**
才能在下拉里选中它们 —— 这就是本脚本干的事。

两个客户端的差异（与 add_codebuddy_models.py 里核对过的一致）：
    WorkBuddy : 顶层是**数组**      url 只填到 /v1
    CodeBuddy : 顶层是 {"models":[]} url 必须是完整路径（/chat/completions 结尾）

幂等：重复跑不会重复加；已有同 id 条目会被新配置覆盖。
安全：先按时间戳备份，再原子写入（.tmp + os.replace），最后重新读盘复核。

用法：
    python add_anthropic_models.py            # 预演，只打印不写盘
    python add_anthropic_models.py --apply    # 真写
    python add_anthropic_models.py --apply --client workbuddy
"""
import argparse
import datetime
import io
import json
import os
import shutil

PROXY_HOST = "http://127.0.0.1:8787/v1"

# 条目里思考相关字段与现有配置保持一致（WorkBuddy / CodeBuddy 同源）
REASONING = {
    "defaultEffort": "medium",
    "effort": "medium",
    "summary": "concise",
    "supportedEfforts": ["low", "medium", "high"],
    "canDisableThinking": False,
}

# 要接入的模型。
#   maxInputTokens / maxOutputTokens 取**保守值**（客户端只拿它做上限提示，
#   不影响真实调用；真实上限由上游决定）。
ANTHROPIC_MODELS = [
    {
        "id": "opencode-go-qwen3.8-flash",
        "name": "OpenCode Go · Qwen3.8 Flash (代理)",
        "maxInputTokens": 128000,
        "maxOutputTokens": 32000,
        "supportsImages": False,
    },
    {
        "id": "opencode-go-qwen3.8-max",
        "name": "OpenCode Go · Qwen3.8 Max (代理)",
        "maxInputTokens": 128000,
        "maxOutputTokens": 32000,
        "supportsImages": False,
    },
    {
        "id": "opencode-go-minimax-m3",
        "name": "OpenCode Go · MiniMax M3 (代理)",
        "maxInputTokens": 200000,
        "maxOutputTokens": 32000,
        "supportsImages": False,
    },
]

CLIENTS = {
    "workbuddy": {
        "path": os.path.join(os.path.expanduser("~"), ".workbuddy", "models.json"),
        "wrap": False,                     # 顶层是纯数组
        "url": PROXY_HOST,                 # 只到 /v1
    },
    "codebuddy": {
        "path": os.path.join(os.path.expanduser("~"), ".codebuddy", "models.json"),
        "wrap": True,                      # 顶层是 {"models": [...]}
        "url": PROXY_HOST + "/chat/completions",
    },
}


def build_entry(spec, url):
    e = {
        "id": spec["id"],
        "name": spec["name"],
        "vendor": "Custom",
        "url": url,
        "apiKey": "local-proxy",           # 真 key 只在代理进程里
        "maxInputTokens": spec["maxInputTokens"],
        "maxOutputTokens": spec["maxOutputTokens"],
        "supportsToolCall": True,          # v1.4 起代理支持工具调用
        "supportsImages": spec["supportsImages"],
        "supportsReasoning": True,
        "onlyReasoning": True,
        "reasoning": dict(REASONING),
    }
    return e


def process(name, cfg_info, apply_changes):
    path = cfg_info["path"]
    print("=" * 72)
    print("  %s  ->  %s" % (name, path))
    print("=" * 72)

    if not os.path.exists(path):
        print("  [SKIP] 文件不存在")
        return 0

    with io.open(path, encoding="utf-8") as fh:
        raw = json.load(fh)

    if isinstance(raw, list):
        models = raw
        top_is_list = True
    elif isinstance(raw, dict) and isinstance(raw.get("models"), list):
        models = raw["models"]
        top_is_list = False
    else:
        print("  [FAIL] 结构不符合预期，跳过")
        return 1

    # 结构校验：与客户端约定一致才动手
    if top_is_list == cfg_info["wrap"]:
        print("  [WARN] 顶层结构与预期相反（wrap=%s），按实际结构处理"
              % cfg_info["wrap"])

    new_ids = {m["id"] for m in ANTHROPIC_MODELS}
    kept, replaced = [], []
    for m in models:
        if m.get("id") in new_ids:
            replaced.append(m.get("id"))
        else:
            kept.append(m)

    for mid in replaced:
        print("  [~] 覆盖已有条目: %s" % mid)
    for spec in ANTHROPIC_MODELS:
        print("  [+] 新增条目: %-36s -> %s" % (spec["id"], cfg_info["url"]))

    if not apply_changes:
        print("  (预演，未写盘)")
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = "%s.bak-%s" % (path, stamp)
    shutil.copy2(path, backup)
    print("  已备份 -> %s" % os.path.basename(backup))

    for spec in ANTHROPIC_MODELS:
        kept.append(build_entry(spec, cfg_info["url"]))

    out = kept if top_is_list else {**raw, "models": kept}

    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(out, ensure_ascii=False, indent=2))
    os.replace(tmp, path)

    # 复核：重新读盘
    with io.open(path, encoding="utf-8") as fh:
        check = json.load(fh)
    check_models = check if isinstance(check, list) else check.get("models", [])
    got = {m.get("id") for m in check_models}
    missing = new_ids - got
    print("  复核：共 %d 条，新增命中 %d/%d %s"
          % (len(check_models), len(new_ids) - len(missing), len(new_ids),
             "OK" if not missing else "[FAIL] 缺 %s" % missing))
    for m in check_models:
        if m.get("id") in new_ids:
            print("     %-36s tool=%s reasoning=%s"
                  % (m["id"], m.get("supportsToolCall"), "有" if m.get("reasoning") else "无"))
    print()
    return 1 if missing else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真写盘（默认只预演）")
    ap.add_argument("--client", default="both",
                    choices=["workbuddy", "codebuddy", "both"])
    args = ap.parse_args()

    targets = (["workbuddy", "codebuddy"] if args.client == "both" else [args.client])
    bad = 0
    for t in targets:
        bad += process(t, CLIENTS[t], args.apply)
        print()

    if not args.apply:
        print("以上为预演。确认无误后加 --apply 真写。")
        print("写完后需**完全重启客户端**才会加载新模型。")
    else:
        print("[OK] 完成。请完全退出并重开客户端，然后在下拉里选新模型。")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
