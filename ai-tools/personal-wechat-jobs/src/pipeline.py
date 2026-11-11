# -*- coding: utf-8 -*-
"""编排入口。

用法：
    python -m src.pipeline                 # 按 config.yaml 跑全流程
    python -m src.pipeline --limit 20      # 只处理最近 20 条
    python -m src.pipeline --config my.yaml
    python -m src.pipeline --dry-run       # 只看过滤结果，不落库不出报告
"""
from __future__ import annotations

import argparse
import sys
from typing import List

from .config import load_config
from .extract import extract_jobs
from .fetch import fetch_articles
from .filters import split
from .mailer import mail_window_days, send_report, window_label
from .report import render_email_html, write_reports
from .store import connect, query, query_recent, upsert


def run(config_path: str | None = None, limit: int | None = None,
        dry_run: bool = False, no_mail: bool = False) -> int:
    cfg = load_config(config_path)
    if no_mail:
        cfg["output"].setdefault("mail", {})["enabled"] = False
    account = cfg["source"].get("account_name", "")

    # 显示真实的采集源，而不是永远不变的 rss_url（type: weread 时那栏是 "mock"）
    stype = (cfg["source"].get("type") or "").strip().lower()
    if not stype:
        raw_url = (cfg["source"].get("rss_url") or "mock").strip()
        stype = ("weread" if raw_url.startswith("weread://")
                 else "mock" if raw_url in ("mock", "", "demo") else "rss")
    if stype == "weread":
        wcfg = cfg["source"].get("weread") or {}
        src_desc = f"微信读书接口 ← {wcfg.get('book_id') or '(未配置 book_id)'}"
    elif stype == "rss":
        src_desc = f"RSS ← {cfg['source'].get('rss_url')}"
    else:
        src_desc = "内置示例数据"

    print(f"[1/5] 采集  ← {src_desc}")
    if account:
        print(f"      目标公众号：{account}")
    articles = fetch_articles(cfg)
    if limit:
        articles = articles[:limit]
    print(f"      共取到 {len(articles)} 篇文章")

    print("[2/5] 过滤  ← 关键词命中判定")
    candidates, log = split(articles, cfg["filter"])
    for row in log:
        flag = "✓ 招聘" if row["is_job"] else "· 跳过"
        print(f"      {flag}  {row['title'][:42]}")
    print(f"      候选 {len(candidates)} 篇")

    if not candidates:
        print("没有筛出招聘类文章，流程结束。")
        if not dry_run:
            write_reports([], cfg, 0, 0)
        return 0

    print(f"[3/5] 抽取  ← 模式 {cfg['extract'].get('mode')}")
    jobs = extract_jobs(candidates, cfg)
    for job in jobs:
        print(f"      {job.unit or '(未识别单位)'} | {job.headcount or '人数未知'} | 截止 {job.apply_end or '未注明'}")

    if dry_run:
        print("[dry-run] 跳过落库与报告生成。")
        return 0

    print("[4/5] 去重入库")
    conn = connect(cfg["output"]["data_dir"])
    new_count, dup_count, new_jobs = upsert(conn, [j.to_dict() for j in jobs])
    print(f"      新增 {new_count} 条，跳过重复 {dup_count} 条")

    print("[5/5] 生成日报（本地存档用，含全部历史）")
    recent = query(conn, limit=200)
    paths = write_reports(recent, cfg, new_count, dup_count)
    for p in paths:
        print(f"      → {p}")

    # 邮件只发「最近 N 天」（output.mail.window_days，默认 7）：
    # 正文是完整 HTML 日报，不带附件、不留摘要落差。
    # 注意与本地存档分离——本地仍写全量历史，只有邮件按窗口裁剪。
    days = mail_window_days(cfg)
    send_jobs = query_recent(conn, days=days)
    print(f"[6] 投递邮件  ← {window_label(days)} {len(send_jobs)} 条"
          f"（本次新入库 {len(new_jobs)} 条；库内共 {len(recent)} 条，窗口外的已排除）")
    try:
        html_doc = render_email_html(send_jobs, cfg, days)
        result = send_report(cfg, send_jobs, len(new_jobs), html_body=html_doc,
                             window_days=days)
        status = result.get("status")
        if status == "sent":
            print(f"      已发送 → {', '.join(result['to'])}")
        elif status == "pending_agent":
            print(f"      待发送（Agent Mail）→ {', '.join(result['to'])}")
            print(f"      from={result['from']}  subject={result['subject']}")
            if result.get("body_path"):
                print(f"      邮件正文已落盘 → {result['body_path']}"
                      f"  (format={result.get('body_format', 'PLAIN')})")
        else:
            print(f"      跳过：{result.get('reason')}")
    except Exception as exc:
        print(f"      [warn] 邮件投递失败：{exc}")

    conn.close()
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="公众号招聘信息监听流水线")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少篇文章")
    parser.add_argument("--dry-run", action="store_true", help="只做过滤与抽取，不落库")
    parser.add_argument("--no-mail", action="store_true", help="本次不投递邮件")
    args = parser.parse_args(argv)
    try:
        return run(args.config, args.limit, args.dry_run, args.no_mail)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
