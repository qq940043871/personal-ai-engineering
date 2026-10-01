#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音视频智能体 - 高级示例
演示批量生成、自定义模板等功能
"""

import sys
from pathlib import Path

# 添加项目路径
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

from douyin_agent.video_agent import DouyinVideoAgent
from douyin_agent.templates.template_manager import init_default_templates


def main():
    print("=" * 60)
    print("抖音视频智能体 - 高级示例")
    print("=" * 60)

    # 初始化智能体
    agent = DouyinVideoAgent()

    # 初始化默认模板
    print("\n📚 初始化模板...")
    init_default_templates(agent.template_manager)

    # 查看所有模板分类
    print("\n📂 模板分类:")
    categories = agent.list_templates()
    for template in categories:
        print(f"  - [{template.category}] {template.id}: {template.name}")

    # 添加自定义模板
    print("\n➕ 添加自定义模板...")
    custom_template = agent.add_template(
        template_id="custom_video",
        name="自定义视频模板",
        description="我的专属视频生成模板",
        content="""请生成一个独特风格的视频：
主题：{topic}
风格：{style}
时长：{duration}秒
务必精彩动人！""",
        variables=["topic", "style", "duration"],
        category="custom"
    )
    print(f"✅ 已添加模板: {custom_template.name}")

    # 批量生成视频
    print("\n🎬 批量生成视频...")
    topics = [
        "美丽的日落",
        "城市夜景",
        "森林小动物",
        "海边风光",
        "冬日雪景"
    ]

    results = agent.batch_generate(
        topics,
        style="唯美",
        audience="摄影爱好者",
        use_template=True,
        template_id="douyin_video"
    )

    # 输出结果
    print(f"\n📊 生成完成，共 {len(results)} 个视频:")
    for i, result in enumerate(results, 1):
        status = "✅ 成功" if result["success"] else "❌ 失败"
        print(f"  {i}. {result['topic']} - {status}")
        if result["success"]:
            print(f"     文件: {result['output_file']}")

    print("\n" + "=" * 60)
    print("🎉 示例运行完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()