
import re
import logging

logger = logging.getLogger(__name__)

WX_CSS = """
<style>
body {
    font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "PingFang SC",
                 "Microsoft YaHei", "Source Han Sans SC", sans-serif;
    font-size: 15px;
    color: #333;
    line-height: 1.8;
    padding: 0 10px;
    word-wrap: break-word;
}
h2 {
    font-size: 18px;
    font-weight: bold;
    color: #1a1a1a;
    margin: 30px 0 15px;
    padding-left: 10px;
    border-left: 4px solid #3b82f6;
}
h3 {
    font-size: 16px;
    font-weight: bold;
    color: #333;
    margin: 20px 0 10px;
}
p {
    margin: 10px 0;
    text-align: justify;
}
strong, b {
    color: #1a56db;
    font-weight: bold;
}
blockquote {
    border-left: 4px solid #e5e7eb;
    background: #f9fafb;
    padding: 10px 15px;
    margin: 15px 0;
    color: #555;
    font-style: italic;
}
code {
    background: #f1f5f9;
    color: #e11d48;
    padding: 2px 5px;
    border-radius: 3px;
    font-size: 13px;
    font-family: "SF Mono", "Menlo", "Consolas", monospace;
}
pre {
    background: #1e293b;
    color: #e2e8f0;
    padding: 15px;
    border-radius: 6px;
    overflow-x: auto;
    margin: 15px 0;
    font-size: 13px;
    line-height: 1.6;
}
pre code {
    background: none;
    color: inherit;
    padding: 0;
}
img {
    max-width: 100%;
    border-radius: 6px;
    margin: 10px auto;
    display: block;
}
ul, ol {
    padding-left: 20px;
    margin: 10px 0;
}
li {
    margin: 5px 0;
}
hr {
    border: none;
    border-top: 1px solid #e5e7eb;
    margin: 25px 0;
}
</style>
"""


def markdown_to_wechat_html(md_text: str) -> str:
    html = _convert_md_to_html(md_text)
    html = WX_CSS + "\n" + html
    return html


def _convert_md_to_html(text: str) -> str:
    lines = text.split("\n")
    html_parts = []
    in_code_block = False
    code_buffer = []
    code_lang = ""

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code_block:
                code_content = "\n".join(code_buffer)
                html_parts.append(f"<pre><code>{_escape_html(code_content)}</code></pre>")
                code_buffer = []
                in_code_block = False
            else:
                in_code_block = True
                code_lang = stripped[3:].strip()
            continue

        if in_code_block:
            code_buffer.append(line)
            continue

        if stripped.startswith("### "):
            html_parts.append(f"<h3>{_process_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            html_parts.append(f"<h2>{_process_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            html_parts.append(f"<h2>{_process_inline(stripped[2:])}</h2>")
        elif stripped.startswith("> "):
            html_parts.append(f"<blockquote><p>{_process_inline(stripped[2:])}</p></blockquote>")
        elif stripped.startswith("---") or stripped.startswith("***"):
            html_parts.append("<hr>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            html_parts.append(f"<li>{_process_inline(stripped[2:])}</li>")
        elif re.match(r"^\d+\.\s", stripped):
            content = re.sub(r"^\d+\.\s", "", stripped)
            html_parts.append(f"<li>{_process_inline(content)}</li>")
        elif stripped == "":
            html_parts.append("")
        else:
            html_parts.append(f"<p>{_process_inline(stripped)}</p>")

    html = "\n".join(html_parts)

    html = re.sub(r"(<li>.*?</li>(\n<li>.*?</li>)+)", r"<ul>\n\1\n</ul>", html)

    html = re.sub(r"</blockquote>\n<blockquote>", "", html)
    html = re.sub(r"</ul>\n<ul>", "", html)
    html = re.sub(r"<p></p>", "", html)

    return html


def _process_inline(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
    return text


def _escape_html(text: str) -> str:
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def extract_digest(html: str, max_len: int = 120) -> str:
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] + "..." if len(text) > max_len else text
