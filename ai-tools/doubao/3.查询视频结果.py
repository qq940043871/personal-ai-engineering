import requests

# 请求的 URL
base_url = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"

# 请求参数
params = {
    "page_num": 1,
    "page_size": 100,
    "filter.task_ids": ["cgt-20260427170604-ctz6g"]
}

# 请求头
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer REPLACE_WITH_YOUR_TOKEN"
}

try:
    # 发送 GET 请求
    response = requests.get(base_url, headers=headers, params=params)
    # 检查响应状态码
    response.raise_for_status()
    # 打印响应内容
    print(response.json())
except requests.exceptions.HTTPError as http_err:
    print(f"HTTP error occurred: {http_err}")
except requests.exceptions.RequestException as req_err:
    print(f"Request error occurred: {req_err}")