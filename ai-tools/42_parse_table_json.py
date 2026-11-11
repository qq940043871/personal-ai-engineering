"""从表格识别结果的转储里提取 HTML。

用法：python 42_parse_table_json.py [样本文件]
默认读同目录的 43_table_sample.json。该文件是 Python 字面量（单引号 + 元组），
且 HTML 字符串被硬折行，因此用 ast.literal_eval 解析前需去掉换行。
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def extract_table_html(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 样本中的 HTML 字符串被硬折行，先拼回一行再按 Python 字面量解析
    data = ast.literal_eval(content.replace("\n", ""))
    return data['blocks'][0]['lines'][0]['spans'][0]['html']


if __name__ == '__main__':
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "43_table_sample.json"
    print("提取的HTML内容：")
    print(extract_table_html(json_path))
