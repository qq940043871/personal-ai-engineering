import uuid
import chromadb
import requests

def ollama_embedding_by_api(text):
    res = requests.post(
        url="http://localhost:11434/api/embeddings",
        json={
            "model": "nomic-embed-text", 
            "prompt": text
        }
    )
    embeddings_list = res.json()["embedding"]
    return embeddings_list

chient = chromadb.PersistentClient(path='db/chroma_db')

# 创建集合
# client.delete_collection(name='collection_v1')
collection = chient.get_or_create_collection(name='collection_v1')

#构建数据
document_list = ["苹果","西瓜","水果"]
#创建唯一标识id
ids = [str(uuid.uuid4()) for _ in document_list]
#构建向量
embeddings = [ollama_embedding_by_api(text) for text in document_list]

# 插入数据
collection.add(
    ids=ids,
    documents=document_list,
    embeddings=embeddings,
)

# 查询
qs = "苹果"
qs_embedding = ollama_embedding_by_api(qs)
res = collection.query(
    query_embeddings=[qs_embedding],
    query_texts=[qs],
    n_results=2
)
print(res)