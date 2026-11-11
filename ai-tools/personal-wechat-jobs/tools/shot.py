# -*- coding: utf-8 -*-
"""用 Playwright 把日报 HTML 渲染成 PNG，用于人工核对版式。"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
html_files = sorted((ROOT / "out").glob("jobs_*.html"))
if not html_files:
    sys.exit("没有找到日报 HTML")
target = html_files[-1]
shot = ROOT / "out" / "preview.png"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1200, "height": 1000},
                            device_scale_factor=2)
    page.goto(target.as_uri())
    page.wait_for_timeout(400)
    page.screenshot(path=str(shot), full_page=True)
    browser.close()

print(f"OK -> {shot}")
