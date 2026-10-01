# 1.读取文件内容
input_file_path = '04_ollama_rag\dataset\example.txt'  # 替换为您的文件路径
with open(input_file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# 2.分割代码为多个部分，每个部分包含一个函数或类的定义
chunk_list = content.split('\n\n')  # 这里假设每个函数或类定义之间用两个换行符分隔
chunk_list = [chunk.strip() for chunk in chunk_list if chunk.strip()]  # 过滤掉空的部分
print(chunk_list)