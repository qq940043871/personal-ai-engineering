## 查询知识库的文档列表
Request:
curl --location --request GET 'http://172.16.1.101/v1/datasets/{dataset_id}' \
--header 'Authorization: Bearer {api_key}'

Response:
{
  "id": "eaedb485-95ac-4ffd-ab1e-18da6d676a2f",
  "name": "Test Knowledge Base",
  "description": "",
  "provider": "vendor",
  "permission": "only_me",
  "data_source_type": null,
  "indexing_technique": null,
  "app_count": 0,
  "document_count": 0,
  "word_count": 0,
  "created_by": "e99a1635-f725-4951-a99a-1daaaa76cfc6",
  "created_at": 1735620612,
  "updated_by": "e99a1635-f725-4951-a99a-1daaaa76cfc6",
  "updated_at": 1735620612,
  "embedding_model": null,
  "embedding_model_provider": null,
  "embedding_available": true,
  "retrieval_model_dict": {
    "search_method": "semantic_search",
    "reranking_enable": false,
    "reranking_mode": null,
    "reranking_model": {
      "reranking_provider_name": "",
      "reranking_model_name": ""
    },
    "weights": null,
    "top_k": 2,
    "score_threshold_enabled": false,
    "score_threshold": null
  },
  "tags": [],
  "doc_form": null,
  "external_knowledge_info": {
    "external_knowledge_id": null,
    "external_knowledge_api_id": null,
    "external_knowledge_api_name": null,
    "external_knowledge_api_endpoint": null
  },
  "external_retrieval_model": {
    "top_k": 2,
    "score_threshold": 0.0,
    "score_threshold_enabled": null
  }
}

## 通过文本创建文档
Request:
curl --location --request POST 'http://172.16.1.101/v1/datasets/{dataset_id}/document/create-by-text' \
--header 'Authorization: Bearer {api_key}' \
--header 'Content-Type: application/json' \
--data-raw '{"name": "text","text": "text","indexing_technique": "high_quality","process_rule": {"mode": "automatic"}}'

Response:
{
  "document": {
    "id": "",
    "position": 1,
    "data_source_type": "upload_file",
    "data_source_info": {
        "upload_file_id": ""
    },
    "dataset_process_rule_id": "",
    "name": "text.txt",
    "created_from": "api",
    "created_by": "",
    "created_at": 1695690280,
    "tokens": 0,
    "indexing_status": "waiting",
    "error": null,
    "enabled": true,
    "disabled_at": null,
    "disabled_by": null,
    "archived": false,
    "display_status": "queuing",
    "word_count": 0,
    "hit_count": 0,
    "doc_form": "text_model"
  },
  "batch": ""
}


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
