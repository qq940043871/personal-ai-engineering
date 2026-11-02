from html.parser import HTMLParser
import re

class DouyinTitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.titles = []
        self.current_title = ""
        self.in_title_tag = False

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            for attr, value in attrs:
                if attr == "class" and value == "EtttsrEw":
                    self.in_title_tag = True
                    self.current_title = ""
                    return

    def handle_endtag(self, tag):
        if tag == "p" and self.in_title_tag:
            if self.current_title.strip():
                self.titles.append(self.current_title.strip())
            self.in_title_tag = False
            self.current_title = ""

    def handle_data(self, data):
        if self.in_title_tag:
            self.current_title += data

html_file = r"d:\ai_coder\p000_ai_study_py\00_self_media\douyin\大模型学习.html"
txt_file = r"d:\ai_coder\p000_ai_study_py\00_self_media\douyin\大模型学习_标题.txt"

with open(html_file, "r", encoding="utf-8") as f:
    html_content = f.read()

parser = DouyinTitleParser()
parser.feed(html_content)

titles_reversed = list(reversed(parser.titles))

with open(txt_file, "w", encoding="utf-8") as f:
    for i, title in enumerate(titles_reversed, 1):
        f.write(f"{i}. {title}\n")

print(f"共解析 {len(parser.titles)} 个标题")
print(f"已倒序保存到: {txt_file}")
print("\n前5个标题（倒序后）:")
for i, title in enumerate(titles_reversed[:5], 1):
    print(f"{i}. {title}")