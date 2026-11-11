"""从币种 JSON 提取 currencyDisplayName，输出到同目录 41_currency_display_names.txt。

用法：python 40_parse_currency_json.py [输入文件]
默认输入为相邻的 04_currency_list/币种.txt。
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
file_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "04_currency_list" / "币种.txt"
output_file_path = HERE / "41_currency_display_names.txt"

try:
    # 打开文件并读取内容
    with open(file_path, 'r', encoding='utf-8') as file:
        # 解析 JSON 数据
        data = json.load(file)

    # 打开输出文件以写入模式
    with open(output_file_path, 'w', encoding='utf-8') as output_file:
        for currency in data:
            # 提取 currencyDisplayName 字段
            display_name = currency.get('currencyDisplayName')
            if display_name:
                # 将 display_name 写入输出文件并换行
                output_file.write(display_name + '\n')
                # 同时打印到控制台
                print(display_name)

except FileNotFoundError:
    print(f"文件 {file_path} 未找到。")
except json.JSONDecodeError:
    print(f"文件 {file_path} 不是有效的 JSON 格式。")
