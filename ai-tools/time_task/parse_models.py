#!/usr/bin/env python3
"""列出模型清单（默认读同目录 model.json，也可传路径覆盖）。"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
model_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "model.json"

with open(model_path, "r", encoding="utf-8") as f:
    data = json.load(f)

items = data.get("Result", {}).get("Items", [])
print(f"共找到 {len(items)} 个模型:\n")

for i, item in enumerate(items, 1):
    model_name = item.get("FoundationModelName", "N/A")
    state = item.get("State", "N/A")
    print(f"{i:2}. {model_name:<40} [{state}]")
