# -*- coding: utf-8 -*-
"""课程页 HTML → 分幕剧本草稿。

把 ai-study-note/courses/**.html 这类单页课程（h1 标题 + h2 章节卡片）
解析成 build_video.py 可用的 storyboard JSON 草稿，供人工润色后出片。

用法:
  python src/extract_course.py ../../ai-study-note/courses/llm/transformer.html \
      --out storyboards/transformer.json --id transformer --voice zh-CN-XiaoxiaoNeural
"""
import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


class CourseParser(HTMLParser):
    """按文档顺序收集 h1/h2/h3/p/li/blockquote 文本，跳过 script/style/nav。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []          # (tag, text)
        self._stack = []         # 跳过的容器
        self._buf_tag = None
        self._buf = []

    SKIP = {"script", "style", "nav", "head"}
    CAPTURE = {"h1", "h2", "h3", "p", "li", "blockquote"}

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._stack.append(tag)
        elif tag in self.CAPTURE:
            self._buf_tag = tag
            self._buf = []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._stack:
            self._stack.pop()
        elif tag == self._buf_tag:
            text = re.sub(r"\s+", "", "".join(self._buf))  # 中文去空白
            if text:
                self.items.append((tag, text))
            self._buf_tag = None
            self._buf = []

    def handle_data(self, data):
        if self._stack or self._buf_tag is None:
            return
        self._buf.append(data)


def split_sentences(text, max_len=42):
    """把整段中文按句号切成短句列表，超长句再按逗号二切。"""
    parts = re.split(r"(?<=[。！？!?])", text)
    out = []
    for p in parts:
        p = p.strip("。；;，, ")
        if not p:
            continue
        while len(p) > max_len:
            cut = p.rfind("，", 0, max_len)
            cut = cut if cut > 12 else max_len
            out.append(p[:cut].rstrip("，,"))
            p = p[cut:].lstrip("，,")
        if p:
            out.append(p)
    return out


def build_storyboard(html_path, sid, title_override, voice):
    doc = Path(html_path).read_text(encoding="utf-8")
    parser = CourseParser()
    parser.feed(doc)

    h1 = next((t for tag, t in parser.items if tag == "h1"), None)
    title = title_override or h1 or sid
    intro = next((t for tag, t in parser.items if tag == "blockquote"), "")

    # 按 h2 分节（跳过目录/导航类卡片）
    sections = []
    for tag, text in parser.items:
        if tag == "h2":
            if re.fullmatch(r"(目录|导航|TOC|Contents?)", text, re.I):
                continue
            sections.append({"title": text, "h3": [], "paras": []})
        elif sections:
            if tag == "h3":
                sections[-1]["h3"].append(text)
            elif tag in ("p", "li", "blockquote"):
                sections[-1]["paras"].append(text)

    scenes = [{
        "id": "s01", "type": "title",
        "kicker": "AI 学习教程",
        "title": title,
        "subtitle": intro[:40] if intro else "",
        "narration": (intro or title) + "。这一讲，我们系统学习" + title + "。",
    }]
    idx = 1
    for sec in sections:
        idx += 1
        body = "".join(sec["paras"])
        narr = "".join(sec["paras"])
        if len(narr) > 220:
            narr = narr[:200] + "等等，更多细节请看完整课程页。"
        scene = {
            "id": f"s{idx:02d}", "type": "bullets",
            "title": sec["title"][:26],
            "narration": narr or sec["title"],
        }
        subs = sec["h3"]
        if subs:
            scene["bullets"] = [{"text": s[:24]} for s in subs[:5]]
        else:
            sents = split_sentences(body)
            scene["bullets"] = [{"text": s[:24]} for s in sents[:4]]
        if not scene["bullets"]:
            scene["type"] = "quote"
            scene["text"] = sec["title"]
        scenes.append(scene)

    return {
        "meta": {
            "id": sid,
            "title": title,
            "subtitle": intro[:40],
            "voice": voice,
            "source": str(html_path),
            "draft": True,
        },
        "scenes": scenes,
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="课程页 HTML → 分幕剧本草稿")
    ap.add_argument("html", help="课程页 HTML 路径")
    ap.add_argument("--out", required=True, help="输出 storyboard JSON 路径")
    ap.add_argument("--id", default=None, help="meta.id（默认取文件名）")
    ap.add_argument("--title", default=None, help="覆盖标题")
    ap.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    args = ap.parse_args()

    sid = args.id or Path(args.html).stem
    data = build_storyboard(args.html, sid, args.title, args.voice)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✔ 剧本草稿: {out}")
    print(f"  标题: {data['meta']['title']} ｜ {len(data['scenes'])} 幕")
    print("  注意: draft=true，旁白与要点为机器抽取，建议人工润色后再出片")


if __name__ == "__main__":
    main()
