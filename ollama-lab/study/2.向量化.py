import requests

text = "你好"
 
res = requests.post(
     url="http://localhost:11434/api/embeddings",
     json={
        "model": "nomic-embed-text", "prompt": text
        }

)

embeddings_list = res.json()["embedding"]
print(text)
print(len(embeddings_list),embeddings_list)