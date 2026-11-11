# -*- coding: utf-8 -*-
"""诊断：逐个浏览器试读 weread cookie，打印真实错误。"""
import sys

import browser_cookie3

BROWSERS = ["edge", "chrome", "brave", "firefox"]


def try_browser(name):
    print(f"\n{'='*60}\n[{name}]")
    fn = getattr(browser_cookie3, name, None)
    if fn is None:
        print("  该版本 browser_cookie3 不支持这个浏览器")
        return
    # 先不带域名限制，看能不能读到任何 cookie
    try:
        jar_all = fn()
        print(f"  读取全部 cookie: OK, 共 {len(jar_all)} 条")
    except Exception as exc:
        print(f"  读取全部 cookie 失败: {type(exc).__name__}: {exc}")
        jar_all = None

    try:
        jar = fn(domain_name="weread.qq.com")
        names = [c.name for c in jar]
        print(f"  weread.qq.com cookie: {len(names)} 条 -> {names[:12]}")
        if "wr_skey" in names:
            print("  >>> 命中 wr_skey！这条链可用")
        else:
            print("  >>> 没有 wr_skey")
    except Exception as exc:
        print(f"  weread.qq.com 读取失败: {type(exc).__name__}: {exc}")


print("browser_cookie3 版本:", getattr(browser_cookie3, "__version__", "未知"))
print("Python:", sys.version.split()[0])
for b in BROWSERS:
    try_browser(b)

print(f"\n{'='*60}")
print("完毕")
