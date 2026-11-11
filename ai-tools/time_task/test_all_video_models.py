#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量测试所有视频模型
"""

import requests
import json
import time
import os

API_KEY = "REPLACE_WITH_YOUR_TOKEN"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

model_list_path = os.path.join(os.path.dirname(__file__), "video_model.txt")

with open(model_list_path, "r", encoding="utf-8") as f:
    models = [line.strip() for line in f if line.strip()]

print("="*80)
print("🎬 Doubao Video Generation API - 批量模型测试")
print("="*80)
print(f"\n📡 API地址: {API_URL}")
print(f"📋 待测试模型数: {len(models)}")
print("\n" + "-"*80)

success_count = 0
failed_models = []

for i, model in enumerate(models, 1):
    print(f"\n[{i}/{len(models)}] 正在测试: {model}")
    print("-"*60)
    
    data = {
        "model": model,
        "content": [
            {
                "type": "text",
                "text": "请生成一个简单的动画视频，主题是彩色粒子在空中飞舞 --ratio 1:1 --fps 24"
            }
        ]
    }
    
    try:
        response = requests.post(API_URL, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        
        print(f"✅ 请求成功!")
        print(f"📋 响应: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")
        
        success_count += 1
            
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP错误: {e}")
        if e.response is not None:
            try:
                error_info = e.response.json()
                print(f"   错误详情: {error_info.get('error', {}).get('message', str(error_info))}")
            except:
                print(f"   响应: {e.response.text[:200]}")
        failed_models.append(model)
    except requests.exceptions.Timeout:
        print(f"⚠️  请求超时")
        failed_models.append(model)
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        failed_models.append(model)
    
    if i < len(models):
        time.sleep(1)

print("\n" + "="*80)
print(f"\n📊 测试完成: {success_count}/{len(models)} 成功")
if failed_models:
    print(f"❌ 失败模型: {', '.join(failed_models)}")
else:
    print(f"🎉 全部成功!")
print("\n" + "="*80)