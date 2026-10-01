import requests

# 请求的 URL
url = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"

# 请求头
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer REPLACE_WITH_YOUR_TOKEN"
}

# 请求体
data = {
    "model": "doubao-seedance-1-0-pro-250528",
    "content": [
        {
            "type": "text",
            "text": "请生成一个火柴人视频的脚本，主题可以自由发挥 --ratio 1:1 --fps 24"
        }
    ]
}

try:
    # 发送 POST 请求
    response = requests.post(url, headers=headers, json=data, timeout=60)
    print(f"状态码: {response.status_code}")
    print(f"响应内容: {response.text}")
    response.raise_for_status()
    # 打印响应内容
    print(response.json())
except requests.exceptions.HTTPError as http_err:
    print(f"HTTP error occurred: {http_err}")
    if http_err.response is not None:
        print(f"响应状态码: {http_err.response.status_code}")
        print(f"错误响应内容: {http_err.response.text}")
except requests.exceptions.RequestException as req_err:
    print(f"Request error occurred: {req_err}")