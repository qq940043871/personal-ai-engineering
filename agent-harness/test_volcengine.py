#!/usr/bin/env python3
"""
火山引擎 Coding Plan 连接测试脚本
"""

import asyncio
import sys
sys.path.insert(0, '.')

from harness.provider.openai_compat import VolcenginePlanProvider


async def test_volcengine_connection():
    """测试火山引擎 API 连接"""
    
    # 从配置文件读取 API Key
    try:
        import yaml
        with open('config.yaml', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        api_key = config['providers']['volcengine_plan']['api_key']
        model = config['providers']['volcengine_plan']['model']
    except Exception as e:
        print(f"❌ 读取配置失败: {e}")
        return
    
    print(f"🔑 API Key: {api_key[:10]}...")
    print(f"🧠 Model: {model}")
    
    try:
        # 创建 Provider
        provider = VolcenginePlanProvider(api_key=api_key, model=model)
        print("✅ Provider 创建成功")
        
        # 测试调用
        print("\n📡 正在测试 API 调用...")
        messages = [
            {"role": "system", "content": "你是一个助手"},
            {"role": "user", "content": "Hello"}
        ]
        
        response = await provider.complete(messages, max_tokens=100)
        print(f"✅ API 调用成功!")
        print(f"📝 响应: {response.content[:50]}...")
        print(f"📊 Token使用: {response.usage.input_tokens} input, {response.usage.output_tokens} output")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_volcengine_connection())
