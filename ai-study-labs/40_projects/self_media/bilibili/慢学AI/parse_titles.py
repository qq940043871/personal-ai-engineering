
import os
import re
import glob
from bs4 import BeautifulSoup


def parse_html_titles(html_dir: str) -> list:
    pattern = re.compile(r'bili-video-card__title')
    title_re = re.compile(r'title="(.+?)"')
    subtitle_re = re.compile(r'<span>(\d{2}-\d{2})</span>')
    bvid_re = re.compile(r'video/(BV\w+)')

    all_videos = []

    html_files = sorted(glob.glob(os.path.join(html_dir, "*.html")))

    for html_file in html_files:
        with open(html_file, 'r', encoding='utf-8') as f:
            html = f.read()

        soup = BeautifulSoup(html, 'lxml')

        cards = soup.find_all('div', class_='bili-video-card__title')

        for card in cards:
            title = card.get('title', '').strip()
            if not title:
                a_tag = card.find('a')
                if a_tag:
                    title = a_tag.get_text(strip=True)
            if not title:
                continue

            subtitle_div = card.find_next_sibling('div', class_='bili-video-card__subtitle')
            date_str = ""
            if subtitle_div:
                span = subtitle_div.find('span')
                if span:
                    date_str = span.get_text(strip=True)

            bvid = ""
            a_tag = card.find('a')
            if a_tag and a_tag.get('href'):
                m = bvid_re.search(a_tag['href'])
                if m:
                    bvid = m.group(1)

            all_videos.append({
                "title": title,
                "date": date_str,
                "bvid": bvid,
                "source": os.path.basename(html_file)
            })

    return all_videos


if __name__ == "__main__":
    html_dir = r"d:\ai_coder\p000_ai_study_py\00_self_media\bilibili\慢学AI"

    videos = parse_html_titles(html_dir)

    videos.reverse()

    print(f"共解析 {len(videos)} 个视频标题（倒序排列）:\n")
    for i, v in enumerate(videos, 1):
        date_part = f"[{v['date']}]" if v['date'] else ""
        bvid_part = f"({v['bvid']})" if v['bvid'] else ""
        print(f"{i:3d}. {date_part} {v['title']} {bvid_part}")
