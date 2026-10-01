import requests

def file_chunk_list():
    input_file_path = '04_ollama_rag\\dataset\\example.txt'  # 替换为您的文件路径
    with open(input_file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    chunk_list = content.split('\n\n')  # 这里假设每个函数或类定义之间用两个换行符分隔
    chunk_list = [chunk.strip() for chunk in chunk_list if chunk.strip()]  # 过滤掉空的部分
    return chunk_list

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

def run():
    chunk_list = file_chunk_list()
    for chunk in chunk_list:
        vector = ollama_embedding_by_api(chunk)
        print(chunk)

if __name__ == '__main__':
    run()