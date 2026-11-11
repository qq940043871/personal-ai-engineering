#!/usr/bin/env python3
"""
运行会议纪要智能工具的GUI界面
"""

import os
import sys

# 添加src目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

if __name__ == "__main__":
    try:
        from src.gui import main
        print("启动会议纪要智能工具GUI界面...")
        main()
    except ImportError as e:
        print(f"导入错误: {e}")
        print("请确保所有依赖已安装")
        sys.exit(1)
    except Exception as e:
        print(f"启动错误: {e}")
        sys.exit(1)
