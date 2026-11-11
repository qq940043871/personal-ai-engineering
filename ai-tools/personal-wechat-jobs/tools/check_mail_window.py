# -*- coding: utf-8 -*-
"""诊断工具：查看「邮件时间窗」当前会发出哪些岗位，不落盘、不发信。

用途：改了 window_days、或怀疑窗口口径不对时，先跑这个看一眼，
      再决定要不要真跑流水线（流水线要重新抓 60 篇正文，约 2 分钟）。

用法：
    python tools/check_mail_window.py          # 用 config.yaml 里的 window_days
    python tools/check_mail_window.py --days 1 # 临时试算其它窗口，不改配置
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config                      # noqa: E402
from src.mailer import build_subject, mail_window_days, window_label  # noqa: E402
from src.report import render_email_html                # noqa: E402
from src.store import connect, query, query_recent      # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="查看邮件时间窗内的岗位")
    ap.add_argument("--days", type=int, default=None, help="临时覆盖 window_days")
    args = ap.parse_args()

    cfg = load_config(None)
    days = args.days or mail_window_days(cfg)

    conn = connect(cfg["output"]["data_dir"])
    all_jobs = query(conn, limit=5000)
    win = query_recent(conn, days=days, limit=5000)
    keys = {j["fingerprint"] for j in win}

    print(f"window_days = {days}   （{window_label(days)}）")
    print(f"库内总计 {len(all_jobs)} 条 ｜ 窗口内 {len(win)} 条 ｜ 窗口外排除 {len(all_jobs) - len(win)} 条")
    print(f"邮件标题 = {build_subject(cfg, len(win), days)}")
    doc = render_email_html(win, cfg, days)
    print(f"正文体积 = {len(doc.encode('utf-8')) / 1024:.1f} KB"
          f"（SendMessage 单次建议 ≤ 12KB，超出需分批）\n")

    dup = len(win) - len({j["url"] or j["article_title"] for j in win})
    if dup:
        print(f"⚠ 窗口内有 {dup} 条重复（同一篇文章出现多次），检查指纹逻辑\n")

    for i, j in enumerate(win, 1):
        print(f"{i:2d}. [{j.get('published') or '日期未知'}] {j.get('article_title')}")
        print(f"    单位={j.get('unit') or '(未识别)'} ｜ 人数={j.get('headcount') or '-'} "
              f"｜ 学历={j.get('education') or '-'} ｜ 截止={j.get('apply_end') or '-'}")

    out_of = [j for j in all_jobs if j["fingerprint"] not in keys]
    if out_of:
        dates = sorted({j.get("published") for j in out_of}, reverse=True)
        print(f"\n窗口外最早/最新发布日期：{dates[0]} ~ {dates[-1]}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
