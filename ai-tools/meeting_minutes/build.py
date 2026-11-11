#!/usr/bin/env python3
"""
打包脚本，使用PyInstaller将会议纪要智能工具打包成可执行文件
"""

import os
import sys
import shutil
from pathlib import Path

# 清理之前的构建产物
def clean_build():
    """清理之前的构建产物"""
    print("🧹 清理之前的构建产物...")
    
    # 删除build和dist目录
    build_dir = Path("build")
    dist_dir = Path("dist")
    
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print("✅ 删除build目录")
    
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
        print("✅ 删除dist目录")

# 打包命令行界面
def build_cli():
    """打包命令行界面"""
    print("\n📦 打包命令行界面...")
    
    # 构建命令
    cmd = [
        "pyinstaller",
        "--name", "meeting_minutes_cli",
        "--onefile",
        "--console",
        "--add-data", ".env.example;.",
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
        "pyinstaller",
        "--name", "meeting_minutes_gui",
        "--onefile",
        "--windowed",  # 无控制台窗口
        "--add-data", ".env.example;.",
        "run_gui.py"
    ]
    
    print(f"执行命令: {' '.join(cmd)}")
    os.system(' '.join(cmd))

# 主函数
def main():
    """主函数"""
    print("🚀 开始打包会议纪要智能工具...")
    
    # 清理之前的构建产物
    clean_build()
    
    # 打包命令行界面
    build_cli()
    
    # 打包GUI界面
    build_gui()
    
    print("\n🎉 打包完成！")
    print("\n📁 可执行文件位置:")
    print("- 命令行界面: dist/meeting_minutes_cli.exe")
    print("- GUI界面: dist/meeting_minutes_gui.exe")
    print("\n💡 使用说明:")
    print("1. 复制 .env.example 为 .env 并填写相关配置")
    print("2. 将 .env 文件放在可执行文件同目录下")
    print("3. 运行相应的可执行文件")

if __name__ == "__main__":
    main()
