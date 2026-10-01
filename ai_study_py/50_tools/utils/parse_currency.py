import json

# 定义文件路径
file_path = 'd:\\workspace\\p001_ai_study_py\\00_utils\\币种.txt'
output_file_path = 'd:\\workspace\\p001_ai_study_py\\00_utils\\currency_display_names.txt'

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