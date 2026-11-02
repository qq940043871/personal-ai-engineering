import requests

url = 'http://10.17.1.134:30001/v1/datasets/59f9e257-803a-4bcf-8d7f-ff8f0945dd22/documents/5dad34be-6238-48ae-b0c0-e2dc172899f2/segments'
headers = {
    'Authorization': 'Bearer dataset-REPLACE_WITH_YOUR_KEY',  # 请替换{api_key}为实际的API密钥
    'Content-Type': 'application/json'
}
payload = {
    "segments": [
        {
            "content": "1",
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