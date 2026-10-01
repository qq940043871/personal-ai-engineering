#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新图片生成API - 基于images/generations接口
"""

import requests
import json

# 配置
API_KEY = "REPLACE_WITH_YOUR_KEY"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/images/generations"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

# 请求参数
data = {
    "model": "doubao-seedream-4-5-251128",
    "prompt": "星际穿越，黑洞，黑洞里冲出一辆快支离破碎的复古列车，强视觉冲击力，电影大片，末日既视感，动感，对比色，oc渲染，光线追踪，动态模糊，景深，超现实主义，深蓝，画面通过细腻的丰富的色彩层次塑造主体与场景，质感真实，暗黑风背景的光影效果营造出氛围，整体兼具艺术幻想感，夸张的广角透视效果，耀光，反射，极致的光影，强引力，吞噬",
    "sequential_image_generation": "disabled",
    "response_format": "url",
    "size": "2K",
    "stream": False,
    "watermark": True
}

print("="*60)
print("🎨 图片生成测试")
print("="*60)
print(f"\n📡 API地址: {API_URL}")
print(f"🎨 模型: {data['model']}")
print(f"📐 尺寸: {data['size']}")
print(f"💧 水印: {data['watermark']}")
print(f"\n📝 提示词:\n{data['prompt']}")
print("\n" + "-"*60)
print("🚀 正在发送请求...")

try:
    response = requests.post(API_URL, headers=headers, json=data)
    response.raise_for_status()
    
    result = response.json()
    print(f"\n✅ 请求成功!")
    print(f"\n📋 完整响应:\n{json.dumps(result, ensure_ascii=False, indent=2)}")
    
    # 尝试提取图片URL
    if 'data' in result and isinstance(result['data'], list):
        print(f"\n📥 生成结果:")
        for i, item in enumerate(result['data'], 1):
            url = item.get('url', 'N/A')
            print(f"   图片{i}: {url}")

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