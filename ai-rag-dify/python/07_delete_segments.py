import requests

def get_all_segments(dataset_id, document_id, api_key):
    """获取文档所有分段"""
    url = f"http://10.17.1.134:30001/v1/datasets/{dataset_id}/documents/{document_id}/segments?limit=100"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()['data']  # 返回分段列表
    except requests.exceptions.RequestException as e:
        print(f"获取分段失败: {e}")
        return None


def delete_segment_chunk(dataset_id, document_id, segment_id, api_key):
    """删除分段的子块"""
    url = f"http://10.17.1.134:30001/v1/datasets/{dataset_id}/documents/{document_id}/segments/{segment_id}"
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    try:
        response = requests.delete(url, headers=headers, timeout=10)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"删除失败(segment_id={segment_id}): {e}")
        return False


def main():
    # 配置参数
    dataset_id = "59f9e257-803a-4bcf-8d7f-ff8f0945dd22"  # 替换为实际dataset_id
    document_id = "fa2c38af-7470-4502-a319-3ea550a74841"  # 替换为实际document_id
    api_key = "dataset-REPLACE_WITH_YOUR_KEY"          # 替换为实际api_key

    # 1. 获取所有分段
    segments = get_all_segments(dataset_id, document_id, api_key)
    if not segments:
        print("未获取到分段数据，程序退出")
        return

    print(f"共发现 {len(segments)} 个分段，开始删除...")

    # 2. 遍历删除每个分段的子块
    for index, segment in enumerate(segments, 1):
        segment_id = segment['id']
        print(f"正在处理第 {index} 个分段 (segment_id: {segment_id})...")
        if delete_segment_chunk(dataset_id, document_id, segment_id, api_key):
            print(f"第 {index} 个分段删除成功")
        else:
            print(f"第 {index} 个分段删除失败")

    print("所有分段处理完毕")


if __name__ == "__main__":
    main()