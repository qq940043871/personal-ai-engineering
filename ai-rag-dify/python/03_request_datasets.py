import requests

url = 'http://10.17.1.134:30001/v1/datasets'
headers = {
    'Authorization': 'Bearer dataset-REPLACE_WITH_YOUR_KEY'  # 请替换{api_key}为实际的API密钥
}
params = {
    'page': 1,
    'limit': 30
}

# 发送GET请求
response = requests.get(url, headers=headers, params=params)

# 处理响应
print(f"状态码: {response.status_code}")
if response.status_code == 200:
    print("响应数据:", response.json())
else:
    print("请求失败:", response.text)