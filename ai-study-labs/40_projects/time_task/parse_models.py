#!/usr/bin/env python3
import json

with open(r"d:\ai_coder\p000_ai_study_py\00_utils\05_ark\model.json", "r", encoding="utf-8") as f:
    data = json.load(f)

items = data.get("Result", {}).get("Items", [])
print(f"共找到 {len(items)} 个模型:\n")

for i, item in enumerate(items, 1):
    model_name = item.get("FoundationModelName", "N/A")
    state = item.get("State", "N/A")
    print(f"{i:2}. {model_name:<40} [{state}]")