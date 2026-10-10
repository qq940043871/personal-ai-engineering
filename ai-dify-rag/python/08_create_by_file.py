import requests
import json

# 固定参数（根据你的 curl 修改）
dataset_id = "59f9e257-803a-4bcf-8d7f-ff8f0945dd22"
api_key = "dataset-REPLACE_WITH_YOUR_KEY"
file_path = r"D:\郑大乾坤鉴\1_1_new_process.md"

url = f"http://10.17.1.134:30001/v1/datasets/{dataset_id}/document/create-by-file"

headers = {
    "Authorization": f"Bearer {api_key}"
}

# 构造 data 参数的 JSON 字符串
data_json = {
    "indexing_technique": "high_quality",
    "doc_form":"hierarchical_model",
    "process_rule": {
        "rules": {
            "pre_processing_rules": [
                {"id": "remove_extra_spaces", "enabled": True},
                {"id": "remove_urls_emails", "enabled": True}
            ],
            "segmentation": {
                "separator": "@!@",
                "max_tokens": 2000
            },
            "subchunk_segmentation ": {
                "separator": "@@",
                "max_tokens": 500
            }
        },
        "mode": "custom"
    }
}

# 将字典转为字符串格式
data_str = json.dumps(data_json, ensure_ascii=False)

# 准备 multipart/form-data 数据
data = {
    # 注意：这里使用 ('', ...) 的形式模拟 --form 'data="...";type=text/html'
    'data': (None, data_str, 'text/html')
}

# 打开文件
with open(file_path, 'rb') as f:
    files = {
        'file': f
    }

    # 发送 POST 请求
    response = requests.post(
        url,
        headers=headers,
        data=data,
        files=files
    )

# 输出响应结果
print("Status Code:", response.status_code)
print("Response Body:", response.text)