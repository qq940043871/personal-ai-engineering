import re
import os
import sys
from collections import defaultdict

def add_split_to_periods(input_path, output_path):
    # 读取文件内容并删除空行
    with open(input_path, 'r', encoding='utf-8') as file:
        # 读取所有行，过滤掉空行
        lines = [line.strip() for line in file if line.strip()]
        content = '\n'.join(lines)
    
    # 步骤1：在3.2.1这种编号格式前添加@@（已存在的不重复添加）
    # 匹配类似x.x.x的编号格式，确保前面没有@@
    modified_content = re.sub(r'(?<!@@)^((\d+\.)+\d+)', r'@@\1', content, flags=re.MULTILINE)
    # modified_content = content
    # 步骤2：在句号后添加@@（已存在的不重复添加）
    # modified_content = re.sub(r'。(?!@@)', r'。@@', content)
    
    # 保存修改后的内容到新文件
    with open(output_path, 'w', encoding='utf-8') as file:
        file.write(modified_content)
    
    print(f"处理完成！输出文件：{output_path}")

def main():  
    if len(sys.argv) < 2:
        print("请提供输入文件名作为参数")
        print("用法: python script.py <input_file.md> [output_file.md]")
        return

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "1_1_new_process.md"

    # 检查输入文件是否存在
    if os.path.exists(input_file):
        add_split_to_periods(input_file, output_file)
    else:
        print(f"错误：输入文件不存在 - {input_file}")

if __name__ == "__main__":
    main()