## 查询文档详情
Request:
curl -X GET 'http://10.17.1.134:30001/v1/datasets/{dataset_id}/documents/{document_id}' \
-H 'Authorization: Bearer {api_key}'
Response:
{
"id": "f46ae30c-5c11-471b-96d0-464f5f32a7b2", 
"position": 1, 
"data_source_type": "upload_file", 
"data_source_info": {
    "upload_file": {
        ...
    }
}, 
"dataset_process_rule_id": "24b99906-845e-499f-9e3c-d5565dd6962c", 
"dataset_process_rule": {
    "mode": "hierarchical", 
    "rules": {
        "pre_processing_rules": [
            {
                "id": "remove_extra_spaces", 
                "enabled": true
            }, 
            {
                "id": "remove_urls_emails", 
                "enabled": false
            }
        ], 
        "segmentation": {
            "separator": "**********page_ending**********", 
            "max_tokens": 1024, 
            "chunk_overlap": 0
        }, 
        "parent_mode": "paragraph", 
        "subchunk_segmentation": {
            "separator": "\n", 
            "max_tokens": 512, 
            "chunk_overlap": 0
        }
    }
}, 
"document_process_rule": {
    "id": "24b99906-845e-499f-9e3c-d5565dd6962c", 
    "dataset_id": "48a0db76-d1a9-46c1-ae35-2baaa919a8a9", 
    "mode": "hierarchical", 
    "rules": {
        "pre_processing_rules": [
            {
                "id": "remove_extra_spaces", 
                "enabled": true
            }, 
            {
                "id": "remove_urls_emails", 
                "enabled": false
            }
        ], 
        "segmentation": {
            "separator": "**********page_ending**********", 
            "max_tokens": 1024, 
            "chunk_overlap": 0
        }, 
        "parent_mode": "paragraph", 
        "subchunk_segmentation": {
            "separator": "\n", 
            "max_tokens": 512, 
            "chunk_overlap": 0
        }
    }
}, 
"name": "xxxx", 
"created_from": "web", 
"created_by": "17f71940-a7b5-4c77-b60f-2bd645c1ffa0", 
"created_at": 1750464191, 
"tokens": null, 
"indexing_status": "waiting", 
"completed_at": null, 
"updated_at": 1750464191, 
"indexing_latency": null, 
"error": null, 
"enabled": true, 
"disabled_at": null, 
"disabled_by": null, 
"archived": false, 
"segment_count": 0, 
"average_segment_length": 0, 
"hit_count": null, 
"display_status": "queuing", 
"doc_form": "hierarchical_model", 
"doc_language": "Chinese Simplified"
}

## 查询分段
Request:
curl --location --request GET 'http://10.17.1.134:30001/v1/datasets/{dataset_id}/documents/{document_id}/segments' \
--header 'Authorization: Bearer {api_key}' \
--header 'Content-Type: application/json'

Response:
{
  "data": [{
    "id": "",
    "position": 1,
    "document_id": "",
    "content": "1",
    "answer": "1",
    "word_count": 25,
    "tokens": 0,
    "keywords": [
        "a"
    ],
    "index_node_id": "",
    "index_node_hash": "",
    "hit_count": 0,
    "enabled": true,
    "disabled_at": null,
    "disabled_by": null,
    "status": "completed",
    "created_by": "",
    "created_at": 1695312007,
    "indexing_at": 1695312007,
    "completed_at": 1695312007,
    "error": null,
    "stopped_at": null
  }],
  "doc_form": "text_model",
  "has_more": false,
  "limit": 20,
  "total": 9,
  "page": 1
}

## 删除分段
curl --location --request DELETE 'http://10.17.1.134:30001/v1/datasets/{dataset_id}/documents/{document_id}/segments/{segment_id}/child_chunks/{child_chunk_id}' \
--header 'Authorization: Bearer {api_key}'

## 上传分段
Request:
curl --location --request POST 'http://10.17.1.134:30001/v1/datasets/{dataset_id}/documents/{document_id}/segments' \
--header 'Authorization: Bearer {api_key}' \
--header 'Content-Type: application/json' \
--data-raw '{"segments": [{"content": "1","answer": "1","keywords": ["a"]}]}'

Response:
{
  "data": [{
    "id": "",
    "position": 1,
    "document_id": "",
    "content": "1",
    "answer": "1",
    "word_count": 25,
    "tokens": 0,
    "keywords": [
        "a"
    ],
    "index_node_id": "",
    "index_node_hash": "",
    "hit_count": 0,
    "enabled": true,
    "disabled_at": null,
    "disabled_by": null,
    "status": "completed",
    "created_by": "",
    "created_at": 1695312007,
    "indexing_at": 1695312007,
    "completed_at": 1695312007,
    "error": null,
    "stopped_at": null
  }],
  "doc_form": "text_model"
}
