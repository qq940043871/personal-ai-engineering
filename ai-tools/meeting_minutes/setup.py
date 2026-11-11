#!/usr/bin/env python3
"""
使用cx-Freeze打包会议纪要智能工具
"""

from cx_Freeze import setup, Executable
import os
import sys

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# 基础配置
base = None
if os.name == "nt":
    base = "Win32GUI"  # GUI应用程序

# 包含的文件
include_files = [
    (".env.example", ".env.example")
]

# 打包命令行界面
cli_executable = Executable(
    script="src/app.py",
    base=None,  # 命令行应用程序
    target_name="meeting_minutes_cli.exe",
    icon=None
)

# 打包GUI界面
gui_executable = Executable(
    script="run_gui.py",
    base=base,  # GUI应用程序
    target_name="meeting_minutes_gui.exe",
    icon=None
)

# 安装配置
setup(
    name="meeting_minutes_tool",
    version="1.0",
    description="会议纪要智能工具",
    author="",
    author_email="",
    options={
        "build_exe": {
            "include_files": include_files,
            "excludes": [],
            "include_msvcr": True  # 包含Microsoft Visual C++运行时
        }
    },
    executables=[cli_executable, gui_executable]
)
