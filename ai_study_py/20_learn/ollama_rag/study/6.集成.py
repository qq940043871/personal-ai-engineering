from flask import Flask, request, jsonify, render_template, Response
from flask_cors import CORS
import uuid
import chromadb
import requests

app = Flask(__name__)
CORS(app)

# Ollama的API端点
API_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:0.5b"

def stream_with_ollama(prompt):
    data = {
        "model": MODEL,
        "prompt": prompt,
        "stream": True
    }
    try:
        response = requests.post(API_URL, json=data, stream=True)
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                try:
                    chunk = line.decode('utf-8')
                    # 确保符合 SSE 格式
                    yield f"data: {chunk}\n\n"
                except UnicodeDecodeError:
                    print("解码错误，跳过此块")
    except requests.RequestException as e:
        print(f"请求出错: {e}")

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

def nostream_with_ollama(prompt, model="qwen2.5:0.5b"):
    """
    向Ollama发送请求以获取回复
    :param prompt: 用户输入的提示信息
    :param model: 要使用的模型，默认为llama2
    :return: 模型生成的回复内容
    """
    data = {
        "model": model,
        "prompt": prompt,
        "stream": False  # 不使用流式输出
    }
    try:
        response = requests.post(API_URL, json=data)
        response.raise_for_status()
        result = response.json()
        reply = result.get("response", "")
        if reply:
            print("Ollama的回复:")
            print(reply)
        return reply
    except requests.RequestException as e:
        print(f"请求出错: {e}")
    except ValueError:
        print("无法解析JSON响应")
    return None

def file_chunk_list():
    input_file_path = '04_ollama_rag\\dataset\\example.txt'  # 替换为您的文件路径
    with open(input_file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    chunk_list = content.split('\n\n')  # 这里假设每个函数或类定义之间用两个换行符分隔
    chunk_list = [chunk.strip() for chunk in chunk_list if chunk.strip()]  # 过滤掉空的部分
    return chunk_list

def init_db():
  chient = chromadb.PersistentClient(path='db/chroma_db')

  # 创建集合
  # chient.delete_collection(name='collection_v1')
  collection = chient.get_or_create_collection(name='collection_v1')

  #构建数据
  document_list = file_chunk_list()
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

def rag_run(qs):
  # 连接数据库
  chient = chromadb.PersistentClient(path='db/chroma_db')
  # 获取向量数据
  collection = chient.get_collection(name='collection_v1')
  # 查询
  qs_embedding = ollama_embedding_by_api(qs)
  res = collection.query(
      query_embeddings=[qs_embedding],
      query_texts=[qs],
      n_results=2
  )
  result = res['documents'][0]
  context = "\n".join(result)
  print(context)

  prompt_template = """你是专家，任务是根据参考信息回答用户问题，
  如果参考信息不足回复不知道：
  请用中文回答。
  参考信息：{context}
  来回答问题：{qs}
  """
  prompt_template = prompt_template.format(context=context, qs=qs)

  print(prompt_template)   
  return prompt_template
     

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/chat', methods=['GET'])
def chat():
    prompt = request.args.get('prompt')
    prompt = rag_run(prompt)
    if prompt:
        return Response(stream_with_ollama(prompt), mimetype='text/event-stream')
    return jsonify({"error": "未提供有效的提示信息"}), 400


if __name__ == '__main__':
    app.run(debug=True)
    #初始化向量数据
    #init_db()
    #qs = "我想买个笔记本"
    #run(qs)