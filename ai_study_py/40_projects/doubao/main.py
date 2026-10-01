#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音视频智能体 - 主程序入口
提供交互式界面使用智能体
"""

import sys
from pathlib import Path

# 添加项目路径
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

from douyin_agent.video_agent import DouyinVideoAgent
from douyin_agent.templates.template_manager import init_default_templates


def print_menu():
    """打印主菜单"""
    print("\n" + "="*60)
    print("🎬 抖音视频智能体 - 主菜单")
    print("="*60)
    print("  1. 生成单个视频")
    print("  2. 批量生成视频")
    print("  3. 生成图片")
    print("  4. 查看可用模板")
    print("  5. 添加自定义模板")
    print("  6. 初始化默认模板")
    print("  7. 查询任务状态")
    print("  0. 退出")
    print("="*60)


def generate_single_video(agent):
    """生成单个视频"""
    print("\n🎬 生成单个视频")
    topic = input("请输入视频主题: ").strip()
    if not topic:
        print("❌ 主题不能为空")
        return

    style = input("请输入视频风格（如：现代、温馨、炫酷） [默认：现代]: ").strip()
    style = style or "现代"

    audience = input("请输入目标受众（如：年轻人、学生、职场人） [默认：年轻人]: ").strip()
    audience = audience or "年轻人"

    # 显示可选模板
    templates = agent.list_templates("video")
    print(f"\n📋 可用视频模板:")
    for i, template in enumerate(templates, 1):
        print(f"  {i}. {template.name} ({template.id})")

    choice = input(f"\n请选择模板编号（直接回车使用默认）: ").strip()
    template_id = "douyin_video"
    if choice.isdigit() and 1 <= int(choice) <= len(templates):
        template_id = templates[int(choice)-1].id

    print(f"\n🚀 开始生成视频: {topic}")
    result = agent.generate_video(
        topic=topic,
        style=style,
        audience=audience,
        use_template=True,
        template_id=template_id
    )

    if result["success"]:
        print(f"\n✅ 视频生成成功！")
        print(f"   视频文件: {result['output_file']}")
        print(f"   任务ID: {result['task_id']}")
    else:
        print(f"\n❌ 视频生成失败: {result.get('error')}")


def batch_generate(agent):
    """批量生成视频"""
    print("\n🎬 批量生成视频")
    print("请输入多个视频主题（每行一个，按回车结束，最后输入空行）:")
    
    topics = []
    while True:
        topic = input("> ").strip()
        if not topic:
            break
        topics.append(topic)

    if not topics:
        print("❌ 没有输入主题")
        return

    style = input("请输入视频风格 [默认：现代]: ").strip() or "现代"
    audience = input("请输入目标受众 [默认：年轻人]: ").strip() or "年轻人"

    confirm = input(f"\n确认生成 {len(topics)} 个视频？(y/n): ").strip().lower()
    if confirm != 'y':
        print("已取消")
        return

    print(f"\n🚀 开始批量生成...")
    results = agent.batch_generate(
        topics,
        style=style,
        audience=audience
    )

    success_count = sum(1 for r in results if r["success"])
    print(f"\n📊 批量生成完成: {success_count}/{len(results)} 成功")


def list_templates(agent):
    """列出模板"""
    print("\n📋 可用模板列表")

    categories = agent.template_manager.list_categories()
    for category in categories:
        print(f"\n📂 分类: {category}")
        templates = agent.list_templates(category)
        for template in templates:
            print(f"  - [{template.id}] {template.name}")
            print(f"    {template.description}")


def add_custom_template(agent):
    """添加自定义模板"""
    print("\n➕ 添加自定义模板")

    template_id = input("请输入模板ID（英文）: ").strip()
    if not template_id:
        print("❌ 模板ID不能为空")
        return

    name = input("请输入模板名称: ").strip()
    description = input("请输入模板描述: ").strip()
    category = input("请输入分类（如：video, image, text） [默认：general]: ").strip() or "general"

    print("\n请输入模板内容（使用 {变量名} 定义变量）:")
    print("输入内容（按 Ctrl+Z 或 Ctrl+D 结束，或连续两次回车）:")
    lines = []
    while True:
        try:
            line = input()
            if not line and lines:
                break
            lines.append(line)
        except EOFError:
            break

    content = "\n".join(lines)
    if not content:
        print("❌ 模板内容不能为空")
        return

    # 提取变量
    variables = []
    import re
    pattern = r'\{([\w]+)\}'
    matches = re.findall(pattern, content)
    variables = list(set(matches))

    confirm = input(f"\n检测到变量: {variables}，确认保存？(y/n): ").strip().lower()
    if confirm == 'y':
        agent.add_template(template_id, name, description, content, variables, category)
        print(f"✅ 模板 {name} 已添加")


def generate_single_image(agent):
    """生成单个图片"""
    print("\n🎨 生成图片")
    prompt = input("请输入图片描述: ").strip()
    if not prompt:
        print("❌ 描述不能为空")
        return

    style = input("请输入风格（如：高质量、唯美、暗黑风） [默认：高质量]: ").strip()
    style = style or "高质量"

    # 显示可选模板
    templates = agent.list_templates("image")
    print(f"\n📋 可用图片模板:")
    for i, template in enumerate(templates, 1):
        print(f"  {i}. {template.name} ({template.id})")

    choice = input(f"\n请选择模板编号（直接回车使用默认）: ").strip()
    template_id = "image_generation"
    if choice.isdigit() and 1 <= int(choice) <= len(templates):
        template_id = templates[int(choice)-1].id

    print(f"\n🚀 开始生成图片: {prompt[:50]}...")
    result = agent.generate_image(
        prompt=prompt,
        style=style,
        use_template=True,
        template_id=template_id
    )

    if result["success"]:
        print(f"\n✅ 图片生成成功！")
        if result.get("output_file"):
            print(f"   图片文件: {result['output_file']}")
        if result.get("image_url"):
            print(f"   在线地址: {result['image_url']}")
    else:
        print(f"\n❌ 图片生成失败: {result.get('error')}")


def check_task_status(agent):
    """查询任务状态"""
    print("\n🔍 查询任务状态")
    task_id = input("请输入任务ID: ").strip()
    if not task_id:
        print("❌ 任务ID不能为空")
        return

    result = agent.get_task_status(task_id)
    if result:
        print(f"任务状态: {result}")
    else:
        print("❌ 查询失败")


def init_templates(agent):
    """初始化默认模板"""
    print("\n📚 初始化默认模板")
    confirm = input("确认初始化默认模板？这会覆盖已有的同名模板。(y/n): ").strip().lower()
    if confirm == 'y':
        init_default_templates(agent.template_manager)
        print("✅ 默认模板已初始化")


def main():
    """主函数"""
    print("🎬 欢迎使用抖音视频智能体！")

    # 初始化智能体
    try:
        agent = DouyinVideoAgent()
        print("✅ 智能体初始化成功")
    except Exception as e:
        print(f"❌ 智能体初始化失败: {e}")
        return

    while True:
        print_menu()
        choice = input("\n请选择功能 (0-7): ").strip()

        if choice == '0':
            print("👋 再见！")
            break
        elif choice == '1':
            generate_single_video(agent)
        elif choice == '2':
            batch_generate(agent)
        elif choice == '3':
            generate_single_image(agent)
        elif choice == '4':
            list_templates(agent)
        elif choice == '5':
            add_custom_template(agent)
        elif choice == '6':
            init_templates(agent)
        elif choice == '7':
            check_task_status(agent)
        else:
            print("❌ 无效的选择，请重新输入")


if __name__ == "__main__":
    main()