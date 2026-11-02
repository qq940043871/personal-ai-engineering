from bs4 import BeautifulSoup

# 读取 HTML 文件
html_file_path = 'd:/workspace/p001_ai_study_py/00_utils/架构师.html'
with open(html_file_path, 'r', encoding='utf-8') as file:
    html_content = file.read()

# 使用 BeautifulSoup 解析 HTML
soup = BeautifulSoup(html_content, 'html.parser')

# 查找所有 title 元素
title_elements = soup.find_all('div', class_='title-txt')

# 打开文件以写入结果
output_file_path = 'd:/workspace/p001_ai_study_py/00_utils/架构师.txt'
with open(output_file_path, 'w', encoding='utf-8') as output_file:
    # 输出带顺序号的 title 到文件
    for index, title in enumerate(title_elements, start=1):
        output_file.write(f"{index:03d}. {title.get_text(strip=True)}\n")

print(f"解析结果已保存到 {output_file_path}")