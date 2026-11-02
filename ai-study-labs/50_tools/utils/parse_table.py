import ast
import json

def extract_table_html(json_path):
    # 读取JSON文件内容
    with open(json_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # 解析Python风格的字典字符串（处理单引号问题）
    data = json.dumps(content, ensure_ascii=False, indent=4)
    print('json',data)
    # 提取HTML内容（根据JSON结构导航）
    html_content = data['blocks'][0]['lines'][0]['spans'][0]['html']
    
    return html_content

if __name__ == '__main__':
    # 表格JSON文件路径
    json_path = r'd:/workspace/p001_ai_study_py/00_utils/table.json'
    
    # 提取并打印HTML内容
    table_html = extract_table_html(json_path)
    print("提取的HTML内容：")
    print(table_html)