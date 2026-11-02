import requests

url = 'http://10.17.1.134:30001/v1/datasets/{dataset_id}/documents/{document_id}/segments/{segment_id}/child_chunks'
headers = {
    'Authorization': 'Bearer {api_key}',  # 请替换{api_key}为实际的API密钥
    'Content-Type': 'application/json'
}
payload = {
    "content": "子分段内容"
}

# 发送POST请求
response = requests.post(url, headers=headers, json=payload)

# 处理响应
print(f"状态码: {response.status_code}")
if response.status_code == 200:
    print("响应数据:", response.json())
else:
    print("请求失败:", response.text)