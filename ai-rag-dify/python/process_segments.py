import os
import sys
import requests

# 添加当前目录到Python路径，以便导入post_segments.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def post_seg(content):
    url = f'http://10.17.1.134:30001/v1/datasets/b3fba3f5-f288-4bfb-9aa2-b643709feb20/documents/49dbf95d-ae81-432c-98a0-af4485f5f36a/segments'
    headers = {
        'Authorization': 'Bearer dataset-REPLACE_WITH_YOUR_KEY',  # 请替换{api_key}为实际的API密钥
        'Content-Type': 'application/json'
    }
    payload = {
        "segments": [
            {
                "content": content,
                "answer": ""
            }
        ]
    }
    # 发送POST请求
    response = requests.post(url, headers=headers, json=payload)
    # 处理响应
    print(f"状态码: {response.status_code}")
    if response.status_code == 200:
        print("响应数据:", response.json())
    else:
        print("请求失败:", response.text)

def process_file(file_path):
    # 读取文件内容
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 根据@!@分割内容
    segments = content.split('@!@')

    # 过滤掉空的段落
    segments = [seg.strip() for seg in segments if seg.strip()]

    print(f"成功分割出 {len(segments)} 个段落")

    # 调用post_segments.py中的方法处理每个段落
    for i, segment in enumerate(segments):
        print(f"处理第 {i+1} 个段落...")
        # 这里我们假设post_segments.py中有一个process_segment函数
        # 实际调用时请根据post_segments.py中的实际函数名进行调整
        try:
            # 构建请求
            post_seg(segment)
            # 调用post_segments.py中的方法
            # 注意：这里只是演示，实际使用时需要根据post_segments.py的具体实现进行调整
            print(f"段落内容: {segment[:50]}...")
            print("处理完成")
        except Exception as e:
            print(f"处理第 {i+1} 个段落时出错: {str(e)}")

if __name__ == "__main__":
    file_path = 'D:\\郑大乾坤鉴\\1_1_new_process.md'
    process_file(file_path)