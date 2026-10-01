#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Doubao Responses API - 通用对话接口
"""

import requests
import json

API_KEY = "REPLACE_WITH_YOUR_TOKEN"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

data = {
    "model": "doubao-seed-1-6-flash-250828",
    "input": [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "你好"
                }
            ]
        }
    ]
}

print("="*60)
print("🤖 Doubao Responses API 测试")
print("="*60)
print(f"\n📡 API地址: {API_URL}")
print(f"🤖 模型: {data['model']}")
print(f"\n📝 输入内容:")
for msg in data['input']:
    for content in msg['content']:
        print(f"   {msg['role']}: {content.get('text', '')}")
print("\n" + "-"*60)
print("🚀 正在发送请求...")

try:
    response = requests.post(API_URL, headers=headers, json=data)
    response.raise_for_status()
    
    result = response.json()
    print(f"\n✅ 请求成功!")
    print(f"\n📋 完整响应:\n{json.dumps(result, ensure_ascii=False, indent=2)}")
    
    if 'output' in result:
        print(f"\n📥 输出结果:")
        for content in result['output']:
            if content.get('type') == 'output_text':
                print(f"\n{content.get('text', '')}")

except requests.exceptions.HTTPError as e:
    print(f"\n❌ HTTP错误: {e}")
    if e.response is not None:
        print(f"\n📄 响应内容:")
        try:
            print(json.dumps(e.response.json(), ensure_ascii=False, indent=2))
        except:
            print(e.response.text)
except Exception as e:
    print(f"\n❌ 发生错误: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
