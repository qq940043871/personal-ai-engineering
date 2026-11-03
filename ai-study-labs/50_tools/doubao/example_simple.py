#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音视频智能体 - 简单示例
演示如何使用智能体生成视频
"""

import sys
from pathlib import Path

# 添加项目路径
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

from douyin_agent.video_agent import DouyinVideoAgent


def main():
    print("=" * 60)
    print("抖音视频智能体 - 简单示例")
    print("=" * 60)

    # 初始化智能体
    agent = DouyinVideoAgent()
    
    # 查看可用模板
    print("\n📋 可用模板:")
    templates = agent.list_templates()
    for template in templates:
        print(f"  - {template.id}: {template.name}")

    # 生成单个视频
    print("\n🎬 开始生成视频...")
    result = agent.generate_video(
        topic="可爱的小猫玩耍",
        style="温馨可爱",
        audience="爱猫人士",
        use_template=True,
        template_id="douyin_video"
    )

    if result["success"]:
        print(f"\n✅ 视频生成成功!")
        print(f"   视频文件: {result['output_file']}")
        print(f"   在线地址: {result['video_url']}")
    else:
        print(f"\n❌ 视频生成失败: {result.get('error')}")


if __name__ == "__main__":
    main()