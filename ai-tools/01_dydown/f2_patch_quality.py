"""修复 f2 抖音选档缺陷：优先"像素多但码率低"的假高清档。

抖音的 bit_rate 列表里存在 1920x1200@1109kbps(h265) 与 1728x1080@1748kbps(h264)
这类档位，f2 原实现先比面积（width*height）、面积相同才比码率，会选中前者，
实际画质更糊且 hevc 兼容性差。

本补丁把判据改为「面积 × 码率 的几何平均」，兼顾分辨率与码率。

用法（f2 重装或升级后重新执行即可）：
    python f2_patch_quality.py           # 应用
    python f2_patch_quality.py --check   # 只检查当前状态
    python f2_patch_quality.py --revert  # 从 .bak 还原
"""
import argparse
import os
import sys

OLD = '''    def quality(item: dict) -> tuple:
        play_addr = item["play_addr"]
        area = _to_int(play_addr.get("width")) * _to_int(play_addr.get("height"))
        return area, _to_int(item.get("bit_rate"))'''

NEW = '''    def quality(item: dict) -> tuple:
        play_addr = item["play_addr"]
        area = _to_int(play_addr.get("width")) * _to_int(play_addr.get("height"))
        rate = _to_int(item.get("bit_rate"))
        # [patch] 面积与码率的几何平均：避免选中"像素多但码率低"的假高清档
        return ((area * max(rate, 1)) ** 0.5, rate)'''

MARKER = "[patch] 面积与码率的几何平均"


def target():
    try:
        import f2
    except ImportError:
        sys.exit("找不到 f2，请先确认已安装")
    p = os.path.join(os.path.dirname(f2.__file__), "apps", "douyin", "utils.py")
    if not os.path.isfile(p):
        sys.exit(f"找不到目标文件: {p}")
    return p


def main():
    ap = argparse.ArgumentParser(description="修复 f2 抖音选档缺陷")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="只检查，不修改")
    g.add_argument("--revert", action="store_true", help="从 .bak 还原")
    a = ap.parse_args()

    path = target()
    bak = path + ".bak"
    with open(path, encoding="utf-8") as f:
        text = f.read()

    patched = MARKER in text
    print(f"目标文件: {path}")
    print(f"当前状态: {'已打补丁' if patched else '未打补丁'}")

    if a.check:
        return

    if a.revert:
        if not os.path.isfile(bak):
            sys.exit("没有找到备份文件，无法还原")
        with open(bak, encoding="utf-8") as f:
            orig = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(orig)
        print("已从 .bak 还原")
        return

    if patched:
        print("无需重复打补丁")
        return

    if OLD not in text:
        print("!! 未找到预期的原函数，可能有版本差异。以下是当前 quality 函数：")
        i = text.find("def quality(item")
        print(text[i - 60:i + 320] if i > 0 else "(完全找不到 quality 函数)")
        sys.exit(1)

    if not os.path.isfile(bak):
        with open(bak, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已备份: {bak}")

    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(OLD, NEW, 1))
    print("补丁已应用")


if __name__ == "__main__":
    main()
