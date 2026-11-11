#!/usr/bin/env python3
"""
使用Nuitka打包会议纪要智能工具
"""

import os
import shutil
from pathlib import Path

# 清理之前的构建产物
def clean_build():
    """清理之前的构建产物"""
    print("🧹 清理之前的构建产物...")
    
    # 删除构建目录
    build_dirs = [
        Path("build")
    ]
    
    for build_dir in build_dirs:
        if build_dir.exists():
            shutil.rmtree(build_dir)
            print(f"✅ 删除 {build_dir} 目录")

# 打包命令行界面
def build_cli():
    """打包命令行界面"""
    print("\n📦 打包命令行界面...")
    
    # 构建命令
    cmd = [
        "python", "-m", "nuitka",
        "--onefile",
        "--output-dir=build/cli",
        "--output-filename=meeting_minutes_cli.exe",
        "--no-pyi-file",
        "--follow-imports",
        "--include-data-file=.env.example=.env.example",
        "src/app.py"
    ]
    
    print(f"执行命令: {' '.join(cmd)}")
    os.system(' '.join(cmd))

# 打包GUI界面
def build_gui():
    """打包GUI界面"""
    print("\n📦 打包GUI界面...")
    
    # 构建命令
    cmd = [
        "python", "-m", "nuitka",
        "--onefile",
        "--output-dir=build/gui",
        "--output-filename=meeting_minutes_gui.exe",
        "--no-pyi-file",
        "--follow-imports",
        "--include-data-file=.env.example=.env.example",
        "run_gui.py"
    ]
    
    print(f"执行命令: {' '.join(cmd)}")
    os.system(' '.join(cmd))

# 主函数
def main():
    """主函数"""
    print("🚀 开始使用Nuitka打包会议纪要智能工具...")
    
    # 清理之前的构建产物
    clean_build()
    
    # 打包命令行界面
    build_cli()
    
    # 打包GUI界面
    build_gui()
    
    print("\n🎉 打包完成！")
    print("\n📁 可执行文件位置:")
    print("- 命令行界面: build/cli/meeting_minutes_cli.exe")
    print("- GUI界面: build/gui/meeting_minutes_gui.exe")
    print("\n💡 使用说明:")
    print("1. 复制 .env.example 为 .env 并填写相关配置")
    print("2. 将 .env 文件放在可执行文件同目录下")
    print("3. 运行相应的可执行文件")

if __name__ == "__main__":
    main()
