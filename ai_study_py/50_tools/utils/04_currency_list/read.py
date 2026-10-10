import json

# 读取文件内容
with open('币种.txt', 'r', encoding='utf-8') as file:
    content = file.read()

# 将JSON字符串转换为Python列表
data = json.loads(content)

# 提取currencyDisplayName属性值，生成列表
display_name_list = [currency['currencyDisplayName'] for currency in data]

for item in display_name_list:
    print(item)