#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量测试所有模型 - 基于0.提示词脚本风格
"""

import requests
import json
import time
import os

API_KEY = "REPLACE_WITH_YOUR_TOKEN"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

model_list_path = os.path.join(os.path.dirname(__file__), "model.txt")

with open(model_list_path, "r", encoding="utf-8") as f:
    models = [line.strip() for line in f if line.strip()]

print("="*60)
print("🤖 Doubao Responses API - 批量模型测试")
print("="*60)
print(f"\n📡 API地址: {API_URL}")
print(f"📋 待测试模型数: {len(models)}")

success_count = 0
failed_models = []

for i, model in enumerate(models, 1):
    print("\n" + "="*60)
    print(f"[{i}/{len(models)}] 🤖 正在测试模型: {model}")
    print("="*60)
    
    data = {
        "model": model,
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
        
        has_output = False
        if 'output' in result:
            print(f"\n📥 输出结果:")
            for content in result['output']:
                if content.get('type') == 'output_text':
                    print(f"\n{content.get('text', '')}")
                    has_output = True
        
        if has_output:
            success_count += 1
        else:
            print("\n⚠️ 未找到输出内容")
            failed_models.append(model)

    except requests.exceptions.HTTPError as e:
        print(f"\n❌ HTTP错误: {e}")
        if e.response is not None:
            print(f"\n📄 响应内容:")
            try:
                print(json.dumps(e.response.json(), ensure_ascii=False, indent=2))
            except:
                print(e.response.text)
        failed_models.append(model)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        failed_models.append(model)
    
    if i < len(models):
        time.sleep(1)

print("\n" + "="*60)
print("📊 测试总结")
print("="*60)
print(f"\n✅ 成功: {success_count}/{len(models)}")
if failed_models:
    print(f"❌ 失败模型: {', '.join(failed_models)}")
else:
    print("🎉 全部成功!")
print("\n" + "="*60)