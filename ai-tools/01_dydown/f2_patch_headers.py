"""修复 f2 的 get_content_length 不发请求头的问题。

f2/utils/http/utils.py 的 get_content_length() 接收 headers 参数、构造了
optimized_headers（UA / Accept / Referer / Cookie ...），但三处请求
（HEAD / GET stream / GET）都是裸调用，没有把 headers 传进去。

抖音 CDN 对无 UA、无 Referer 的裸请求直接 403，被判定为「响应大小为 0 字节」，
进而跳过该链接。表现就是：接口能拿到地址，但下载全是 0 字节。

用法（f2 重装或升级后重新执行即可）：
    python f2_patch_headers.py           # 应用
    python f2_patch_headers.py --check   # 只检查
    python f2_patch_headers.py --revert  # 还原
"""
import argparse
import os
import sys

PAIRS = [
    (
        "                response = await aclient.head(url)\n",
        "                response = await aclient.head(url, headers=optimized_headers)\n",
    ),
    (
        '            async with aclient.stream("GET", url) as response:\n',
        '            async with aclient.stream("GET", url, headers=optimized_headers) as response:\n',
    ),
    (
        "            response = await aclient.get(url)\n",
        "            response = await aclient.get(url, headers=optimized_headers)\n",
    ),
]

MARKER = "headers=optimized_headers"


def target():
    try:
        import f2
    except ImportError:
        sys.exit("找不到 f2，请先确认已安装")
    p = os.path.join(os.path.dirname(f2.__file__), "utils", "http", "utils.py")
    if not os.path.isfile(p):
        sys.exit(f"找不到目标文件: {p}")
    return p


def main():
    ap = argparse.ArgumentParser(description="修复 f2 下载探测请求不带请求头")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="只检查，不修改")
    g.add_argument("--revert", action="store_true", help="从 .bak 还原")
    a = ap.parse_args()

    path = target()
    bak = path + ".bak"
    with open(path, encoding="utf-8") as f:
        text = f.read()

    done = text.count(MARKER)
    print(f"目标文件: {path}")
    print(f"当前状态: 已修复 {done}/3 处" if done else "当前状态: 未修复")

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

    if done == 3:
        print("无需重复打补丁")
        return

    if not os.path.isfile(bak):
        with open(bak, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已备份: {bak}")

    changed = 0
    for old, new in PAIRS:
        if new in text:
            continue
        if old not in text:
            print(f"!! 未匹配到目标代码，跳过: {old.strip()[:60]}")
            continue
        text = text.replace(old, new, 1)
        changed += 1

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"补丁已应用，修改 {changed} 处")


if __name__ == "__main__":
    main()
