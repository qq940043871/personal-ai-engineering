#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本 - 验证模块导入
"""

import sys
from pathlib import Path

# 添加项目路径
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

print("="*60)
print("测试模块导入测试")
print("="*60)

# 测试配置管理器
print("\n📋 测试配置管理器...")
try:
    from douyin_agent.config.config_manager import ConfigManager
    config = ConfigManager()
    print("✅ 配置管理器导入成功")
    print(f"   API端点: {config.get('volcengine.endpoint')}")
except Exception as e:
    print(f"❌ 配置管理器导入失败: {e}")

# 测试API模块
print("\n🔌 测试API模块...")
try:
    from douyin_agent.api.volcengine_api import VolcEngineAPI
    print("✅ API模块导入成功")
except Exception as e:
    print(f"❌ API模块导入失败: {e}")

# 测试模板管理器
print("\n📝 测试模板管理器...")
try:
    from douyin_agent.templates.template_manager import TemplateManager
    tm = TemplateManager()
    print(f"✅ 模板管理器导入成功")
    templates = tm.list_templates()
    print(f"   已加载 {len(templates)} 个模板")
except Exception as e:
    print(f"❌ 模板管理器导入失败: {e}")

# 测试智能体
print("\n🎬 测试视频智能体...")
try:
    from douyin_agent.video_agent import DouyinVideoAgent
    print("✅ 视频智能体导入成功")
except Exception as e:
    print(f"❌ 视频智能体导入失败: {e}")

print("\n" + "="*60)
print("🎉 所有模块导入测试完成")
print("="*60)