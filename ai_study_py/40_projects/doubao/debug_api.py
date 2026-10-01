#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试脚本 - 测试API连接
"""

import sys
from pathlib import Path

# 添加项目路径
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

import requests

print("="*60)
print("🔍 API连接调试")
print("="*60)

# 测试配置
api_key = "REPLACE_WITH_YOUR_KEY"
url = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"

print(f"\n📡 API地址: {url}")
print(f"🔑 API密钥: {api_key[:10]}...")

# 简单测试 - GET请求（不带认证）
print("\n🧪 测试1: 简单GET请求（不带认证）")
try:
    response = requests.get(url)
    print(f"   状态码: {response.status_code}")
    print(f"   响应: {response.text[:200]}")
except Exception as e:
    print(f"   错误: {e}")

# 测试带认证的GET
print("\n🧪 测试2: 带认证的GET请求")
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}
try:
    response = requests.get(url, headers=headers)
    print(f"   状态码: {response.status_code}")
    print(f"   响应: {response.text[:300]}")
except Exception as e:
    print(f"   错误: {e}")

# 尝试发送一个简单的POST
print("\n🧪 测试3: 尝试发送视频任务")
data = {
    "model": "ep-20250329164058-hq8tm",
    "content": [
        {
            "type": "text",
            "text": "test --ratio 1:1 --fps 24 --dur 5"
        }
    ]
}
try:
    response = requests.post(url, headers=headers, json=data)
    print(f"   状态码: {response.status_code}")
    print(f"   响应头: {dict(response.headers)}")
    print(f"   响应内容: {response.text}")
except Exception as e:
    print(f"   错误: {e}")

print("\n" + "="*60)
print("💡 提示: 如果401错误持续，可能是API密钥已过期或无效")
print("="*60)