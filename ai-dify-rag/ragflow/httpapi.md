Upload documents
POST /api/v1/datasets/{dataset_id}/documents

Uploads documents to a specified dataset.

Request
Method: POST
URL: /api/v1/datasets/{dataset_id}/documents
Headers:
'Content-Type: multipart/form-data'
'Authorization: Bearer <YOUR_API_KEY>'
Form:
'file=@{FILE_PATH}'
Request example
curl --request POST \
     --url http://{address}/api/v1/datasets/{dataset_id}/documents \
     --header 'Content-Type: multipart/form-data' \
     --header 'Authorization: Bearer <YOUR_API_KEY>' \
     --form 'file=@./test1.txt' \
     --form 'file=@./test2.pdf'

Request parameters
dataset_id: (Path parameter)
The ID of the dataset to which the documents will be uploaded.
'file': (Body parameter)
A document to upload.
Response
Success:

{
    "code": 0,
    "data": [
        {
            "chunk_method": "naive",
            "created_by": "69736c5e723611efb51b0242ac120007",
            "dataset_id": "527fa74891e811ef9c650242ac120006",
            "id": "b330ec2e91ec11efbc510242ac120004",
            "location": "1.txt",
            "name": "1.txt",
            "parser_config": {
                "chunk_token_num": 128,
                "delimiter": "\\n",
                "html4excel": false,
                "layout_recognize": true,
                "raptor": {
                    "use_raptor": false
                }
            },
            "run": "UNSTART",
            "size": 17966,
            "thumbnail": "",
            "type": "doc"
        }
    ]
}

Failure:

{
    "code": 101,
    "message": "No file part!"
}




Add chunk
POST /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks

Adds a chunk to a specified document in a specified dataset.

Request
Method: POST
URL: /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks
Headers:
'content-Type: application/json'
'Authorization: Bearer <YOUR_API_KEY>'
Body:
"content": string
"important_keywords": list[string]
Request example
curl --request POST \
     --url http://{address}/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks \
     --header 'Content-Type: application/json' \
     --header 'Authorization: Bearer <YOUR_API_KEY>' \
     --data '
     {
          "content": "<CHUNK_CONTENT_HERE>"
     }'

Request parameters
dataset_id: (Path parameter)
The associated dataset ID.
document_ids: (Path parameter)
The associated document ID.
"content": (Body parameter), string, Required
The text content of the chunk.
"important_keywords(Body parameter), list[string]
The key terms or phrases to tag with the chunk.
"questions"(Body parameter), list[string] If there is a given question, the embedded chunks will be based on them
Response
Success:

{
    "code": 0,
    "data": {
        "chunk": {
            "content": "who are you",
            "create_time": "2024-12-30 16:59:55",
            "create_timestamp": 1735549195.969164,
            "dataset_id": "72f36e1ebdf411efb7250242ac120006",
            "document_id": "61d68474be0111ef98dd0242ac120006",
            "id": "12ccdc56e59837e5",
            "important_keywords": [],
            "questions": []
        }
    }
}

Failure:

{
    "code": 102,
    "message": "`content` is required"
}