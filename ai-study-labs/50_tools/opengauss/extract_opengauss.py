from html.parser import HTMLParser
import os

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tbody = False
        self.in_td = False
        self.in_th = False
        self.in_p = False
        self.current_row = []
        self.current_cell = ""
        self.rows = []
        self.is_header = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
            self.rows = []
        elif tag == "thead":
            self.is_header = True
        elif tag == "tbody":
            self.in_tbody = True
            self.is_header = False
        elif tag == "tr":
            self.current_row = []
        elif tag == "th":
            self.in_th = True
            self.current_cell = ""
        elif tag == "td":
            self.in_td = True
            self.current_cell = ""
        elif tag == "p":
            self.in_p = True

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False
        elif tag == "thead":
            self.is_header = False
        elif tag == "tbody":
            self.in_tbody = False
        elif tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
        elif tag == "th":
            self.in_th = False
            if self.is_header:
                self.current_row.append(self.current_cell.strip())
            else:
                self.current_row.append(self.current_cell.strip())
        elif tag == "td":
            self.in_td = False
            self.current_row.append(self.current_cell.strip())
        elif tag == "p":
            self.in_p = False

    def handle_data(self, data):
        if self.in_th or self.in_td or self.in_p:
            self.current_cell += data

def extract_reserved_keywords(html_file, output_file):
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()

    parser = TableParser()
    parser.feed(content)

    reserved_keywords = []
    for row in parser.rows:
        if len(row) >= 2:
            keyword = row[0].strip()
            status = row[1].strip()
            if status.startswith("保留"):
                reserved_keywords.append((keyword, status))

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# OpenGauss 保留关键字\n\n")
        f.write(f"共 {len(reserved_keywords)} 个保留关键字\n\n")
        f.write("| 关键字 | 保留类型 |\n")
        f.write("|--------|----------|\n")
        for keyword, status in reserved_keywords:
            f.write(f"| {keyword} | {status} |\n")

    print(f"已提取 {len(reserved_keywords)} 个保留关键字到 {output_file}")

if __name__ == "__main__":
    html_file = r"d:\ai_coder\p000_ai_study_py\00_utils\html\opengauss.html"
    output_file = r"d:\ai_coder\p000_ai_study_py\00_utils\html\opengauss_reserved.md"
    extract_reserved_keywords(html_file, output_file)