import requests
import json

file_path = "D:\\郑大乾坤鉴\\1.md"
with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

# 替换为实际的dataset_id和api_key
dataset_id = "59f9e257-803a-4bcf-8d7f-ff8f0945dd22"
api_key = "dataset-REPLACE_WITH_YOUR_KEY"
url = f"http://10.17.1.134:30001/v1/datasets/{dataset_id}/document/create-by-text"

print('url',url)
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

data = {
    "name": "test",
    "text": f"{content}",
    "indexing_technique": "high_quality",
    "process_rule": {
        "mode": "automatic",
        "doc_form": "hierarchical_model",
    }
}

# 发送POST请求
response = requests.post(url, headers=headers, json=data, timeout=120)

# 处理响应
print(f"状态码: {response.status_code}")
print("响应内容:", response.json())