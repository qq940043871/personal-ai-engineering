import requests
import json

# 请求的 URL
url = "https://www.doubao.com/samantha/chat/completion?aid=497858&device_id=7432482555897071115&device_platform=web&language=zh&pc_version=2.12.0&pkg_type=release_version&real_aid=497858&region=CN&samantha_web=1&sys_region=CN&tea_uuid=7432489190358550035&use-olympus-account=1&version_code=20800&web_id=7432489190358550035&msToken=Jr_34aATxzBiS69hImAkRZhr9HfiS6qCJavLRp4KL5w_idBWvA9nggSEYXxWrFyCyO8VM-_l2tHZu_xBI8W4bKb4Zxr1JZByAaIdbIGSv23PyPzjjaJpvNU%3D&a_bogus=Dj-dvchJMsm128hRuXkz9jpA3KY0YW4HgZENmbNektqW"

# 请求头
headers = {
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "agw-js-conv": "str",
    "cache-control": "no-cache",
    "content-type": "application/json",
    "last-event-id": "undefined",
    "pragma": "no-cache",
    "priority": "u=1, i",
    "sec-ch-ua": "\"Chromium\";v=\"134\", \"Not:A-Brand\";v=\"24\", \"Microsoft Edge\";v=\"134\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "x-flow-trace": "04-0002d0b027de3a60001a4a4a9bccfa0a-00157c8c6f052359-01",
    "cookie": "_uetvid=9c05a45098ba11efb991bd5cfc91e7dc; _ga=GA1.1.458439523.1736749149; n_mh=tl55ngZbCMzUelHfOUZG27iaebRJA0jDfIQnKn-AvOk; uid_tt=03bf989645650856975a5a72852794e6; uid_tt_ss=03bf989645650856975a5a72852794e6; sid_tt=REPLACE_WITH_YOUR_TOKEN; sessionid=REPLACE_WITH_YOUR_TOKEN; sessionid_ss=REPLACE_WITH_YOUR_TOKEN; is_staff_user=false; store-region=cn-ha; store-region-src=uid; gd_random=eyJtYXRjaCI6ZmFsc2UsInBlcmNlbnQiOjAuNDIxNjg5OTEyNzAzNzExMzd9.cW9KpRgj4MkJSxhsLfT2aCvCutdVQpz5gw78YX/qRdk=; gd_random_1831904=eyJtYXRjaCI6ZmFsc2UsInBlcmNlbnQiOjAuNDIxNjg5OTEyNzAzNzExMzd9.cW9KpRgj4MkJSxhsLfT2aCvCutdVQpz5gw78YX/qRdk=; sid_guard=REPLACE_WITH_YOUR_TOKEN%7C1743383110%7C5184000%7CFri%2C+30-May-2025+01%3A05%3A10+GMT; sid_ucp_v1=1.0.0-KDVlNDdkMGE0MWUwZjExYTMxNzc5N2YxODdmOTc3OGQ4Mjk0MGQ4ODkKIAj8o4DGps3iAxDG1Ke_BhjCsR4gDDDRmJqtBjgHQPQHGgJscSIgMjNlZGM3MDI1MzE4ZTExYzc5Y2RhOGJiZTNmYWI2MGQ; ssid_ucp_v1=1.0.0-KDVlNDdkMGE0MWUwZjExYTMxNzc5N2YxODdmOTc3OGQ4Mjk0MGQ4ODkKIAj8o4DGps3iAxDG1Ke_BhjCsR4gDDDRmJqtBjgHQPQHGgJscSIgMjNlZGM3MDI1MzE4ZTExYzc5Y2RhOGJiZTNmYWI2MGQ; tt_scid=w98v3FXl6RKUKwbiH.siRlfsJqeRt0nZNCjE9J0OFDX8JY1tWaXAidWdedmnyc90b22f; ttwid=1%7CCQ6p_CxjGezfQzJO8df6u6Rvi6F3-FIl73lideZKEpQ%7C1743383849%7C05fde3697bdc8cab8c8e7454e511e63c137ac1e8d0b0c8a55229f9d435521f96; msToken=0wLWv8-LEjd9mDaBj9n3ZEutdQog6qaYIjBs63qzec8OuZonorqBbxebTybeQkJd7dPJx3-q1YwQgFh6bNWrQZKFxXfOUCSFA8FVCHol1FPdIhnAJjwRPCc=; passport_fe_beating_status=true; odin_tt=c0f5c0f9971091cda095e12a01ff3f60ab28951dd87d8abcaae613b20e6ba34a9bfb35d5435c79872430f780e6fd2556f6cf6b0493ef2e8ebf4963542f2ab1f0; _ga_G8EP5CG8VZ=GS1.1.1743383113.5.1.1743384639.0.0.0",
    "Referer": "https://www.doubao.com/chat/local_9322620493224153?type=2",
    "Referrer-Policy": "strict-origin-when-cross-origin"
}

# 请求体
body = {
    "messages": [
        {
            "content": "{\"text\":\"我想创作一首歌曲，用AI 帮我写歌词。这首歌是流行音乐风格，传达快乐的情绪，使用女声音色\"}",
            "content_type": 2015,
            "attachments": [],
            "references": []
        }
    ],
    "completion_option": {
        "is_regen": False,
        "with_suggest": True,
        "need_create_conversation": True,
        "launch_stage": 1,
        "is_replace": False,
        "is_delete": False,
        "message_from": 0,
        # 是否深度思考
        "use_deep_think": False,
        "event_id": "0"
    },
    "conversation_id": "0",
    "local_conversation_id": "local_9322620493224153",
}

try:
    # 发送 POST 请求
    response = requests.post(url, headers=headers, json=body, stream=True)
    # 设置响应的字符编码为 UTF-8
    response.encoding = 'utf-8'
    # 检查响应状态码
    response.raise_for_status()
    # 打印响应内容
    # 逐行读取并打印响应内容
    for line in response.iter_lines():
        if line:
            line_str = line.decode('utf-8')
            if "data:" in line_str:
                # 截取 data: 之后的内容
                json_str = line_str.split("data: ", 1)[1]
                try:
                    # 解析 JSON 数据
                    json_data = json.loads(json_str)
                    # 格式化输出 JSON 数据
                    formatted_json = json.dumps(json_data, indent=4, ensure_ascii=False)
                    # 要检查的键
                    key_to_check = "event_data"
                    # 使用 in 运算符判断键是否存在
                    if key_to_check in formatted_json:
                        print(formatted_json)
                except json.JSONDecodeError:
                    print(f"Failed to decode JSON: {json_str}")
except requests.exceptions.HTTPError as http_err:
    print(f"HTTP error occurred: {http_err}")
except requests.exceptions.RequestException as req_err:
    print(f"Request error occurred: {req_err}")
