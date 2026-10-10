import requests

dataset_id = "59f9e257-803a-4bcf-8d7f-ff8f0945dd22"
url = f'http://10.17.1.134:30001/v1/datasets/{dataset_id}/documents'
headers = {
    'Authorization': 'Bearer dataset-REPLACE_WITH_YOUR_KEY'  # 请替换{api_key}为实际的API密钥
}

# 发送GET请求
response = requests.get(url, headers=headers)

# 处理响应
print(f"状态码: {response.status_code}")
if response.status_code == 200:
    print("响应数据:", response.json())
else:
    print("请求失败:", response.text)