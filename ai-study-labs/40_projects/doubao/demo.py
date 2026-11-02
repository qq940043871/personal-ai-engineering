#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音视频智能体 - 演示版
使用项目现有代码直接演示
"""

import sys
from pathlib import Path
import requests
import time
import json

print("="*60)
print("🎬 抖音视频智能体 - 演示版")
print("="*60)

# 配置
API_KEY = "REPLACE_WITH_YOUR_KEY"
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
MODEL_ID = "ep-20250329164058-hq8tm"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

print(f"\n📋 配置信息:")
print(f"   API端点: {BASE_URL}")
print(f"   模型ID: {MODEL_ID}")
print(f"   API密钥: {API_KEY[:10]}...")

# 用户输入
topic = input("\n🎯 请输入视频主题: ").strip()
if not topic:
    topic = "可爱的小猫"

duration = input("⏱️ 请输入视频时长（秒，默认20）: ").strip()
duration = int(duration) if duration.isdigit() else 20

style = input("🎨 请输入视频风格（如：温馨、炫酷、唯美，默认：温馨）: ").strip()
style = style or "温馨"

# 构建提示词
prompt = f"""请生成一个高质量的抖音短视频，要求如下：
主题：{topic}
风格：{style}
受众：年轻人
详细要求：
视频时长：{duration}秒
画面比例：9:16（竖屏）
画面流畅，有吸引力
色彩鲜艳，视觉冲击力强
适合抖音平台播放"""

print(f"\n📝 生成提示词:\n{prompt}")
print("\n" + "-"*60)

# 提交任务
data = {
    "model": MODEL_ID,
    "content": [
        {
            "type": "text",
            "text": f"{prompt} --ratio 9:16 --fps 24 --dur {duration}"
        }
    ]
}

print(f"\n🚀 正在提交视频生成任务...")
try:
    response = requests.post(BASE_URL, headers=headers, json=data)
    response.raise_for_status()
    result = response.json()
    print(f"✅ 任务提交成功!")
    print(f"   响应: {json.dumps(result, ensure_ascii=False, indent=2)}")
    
    if 'data' in result and 'id' in result['data']:
        task_id = result['data']['id']
        print(f"\n📋 任务ID: {task_id}")
        
        # 等待完成
        print("\n⏳ 等待视频生成...")
        max_checks = 30
        for i in range(max_checks):
            print(f"   检查 {i+1}/{max_checks}...")
            
            # 查询状态
            params = {
                "page_num": 1,
                "page_size": 10,
                "filter.task_ids": [task_id]
            }
            
            check_response = requests.get(BASE_URL, headers=headers, params=params)
            
            if check_response.status_code == 200:
                check_result = check_response.json()
                tasks = check_result.get('data', [])
                
                if tasks:
                    status = tasks[0].get('status', 'unknown')
                    print(f"      当前状态: {status}")
                    
                    if status == 'succeeded':
                        print("\n✅ 视频生成成功!")
                        outputs = tasks[0].get('output', {})
                        video_info = outputs.get('result', [])
                        if video_info:
                            video_url = video_info[0].get('url')
                            print(f"📹 视频地址: {video_url}")
                        
                        print("\n" + "="*60)
                        print("🎉 恭喜! 视频已成功生成!")
                        print("="*60)
                        break
                    
                    elif status == 'failed':
                        print(f"\n❌ 视频生成失败!")
                        print(f"详细信息: {json.dumps(check_result, ensure_ascii=False, indent=2)}")
                        break
                    
            time.sleep(10)
        
        else:
            print(f"\n⏱️  等待超时，可稍后自行查询任务状态")

except requests.exceptions.HTTPError as e:
    print(f"\n❌ HTTP错误: {e}")
    if e.response is not None:
        print(f"   响应内容: {e.response.text}")
except Exception as e:
    print(f"\n❌ 发生错误: {e}")

print("\n📁 提示: 可以使用 3.查询视频结果.py 查询现有任务状态")