#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音视频智能体 - 图片生成示例
"""

import sys
from pathlib import Path

# 添加项目路径
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

from douyin_agent.video_agent import DouyinVideoAgent


def main():
    print("="*60)
    print("🎨 图片生成示例")
    print("="*60)

    # 初始化智能体
    agent = DouyinVideoAgent()

    # 示例1：简单图片生成
    print("\n" + "-"*60)
    print("示例1：简单图片生成")
    print("-"*60)
    result = agent.generate_image(
        prompt="可爱的猫咪在花园里玩耍，阳光明媚",
        style="温馨",
        use_template=True,
        template_id="image_generation"
    )

    # 示例2：更复杂的提示词
    print("\n" + "-"*60)
    print("示例2：详细描述图片")
    print("-"*60)
    result = agent.generate_image(
        prompt="星际穿越，黑洞，黑洞里冲出一辆快支离破碎的复古列车，强视觉冲击力，电影大片，末日既视感，动感，对比色，oc渲染，光线追踪，动态模糊，景深，超现实主义，深蓝，画面通过细腻的丰富的色彩层次塑造主体与场景，质感真实，暗黑风背景的光影效果营造出氛围，整体兼具艺术幻想感，夸张的广角透视效果，耀光，反射，极致的光影，强引力，吞噬",
        style="电影大片",
        use_template=False
    )

    print("\n" + "="*60)
    print("🎉 示例运行完成！")
    print("="*60)


if __name__ == "__main__":
    main()