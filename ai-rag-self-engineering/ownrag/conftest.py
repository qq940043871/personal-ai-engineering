"""pytest 根 conftest：把项目根加入 sys.path（免安装即可跑测试）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
