# Qwen 大模型 快速学习手册

## 📋 概述

Qwen（通义千问）是阿里云开发的大语言模型系列，支持多种参数规模，可本地部署或通过 API 调用。

## 🏗️ 模型系列

```
┌─────────────────────────────────────────────────────┐
│                  Qwen 模型家族                        │
├─────────────────────────────────────────────────────┤
│  Qwen2.5      │  最新一代，支持超长上下文            │
│  Qwen2        │  高性能，支持128K上下文             │
│  Qwen1.5      │  轻量级，适合本地部署               │
│  Qwen-Max     │  超大规模，云端专用                 │
├─────────────────────────────────────────────────────┤
│  参数规模: 0.5B / 1.5B / 7B / 14B / 72B / 110B    │
└─────────────────────────────────────────────────────┘
```

## 🚀 快速开始

### 1. Ollama 本地部署

```bash
# 安装 Ollama
# macOS/Linux: brew install ollama
# Windows: 下载安装包

# 拉取 Qwen 模型
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b

# 运行模型
ollama run qwen2.5:7b
```

### 2. API 调用

```python
import requests

response = requests.post(
    "http://localhost:11434/api/generate",
    json={
        "model": "qwen2.5:7b",
        "prompt": "你好，请介绍一下自己",
        "stream": False
    }
)

print(response.json()["response"])
```

## 📚 项目代码示例

### 1. LangChain + Ollama + Qwen

```python
from langchain_community.llms import Ollama
from langchain.chains import RetrievalQA
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings

# 初始化 Qwen 模型
ollama = Ollama(model="qwen2.5:0.5b")

# 创建 RAG 问答链
qa_chain = RetrievalQA.from_chain_type(
    llm=ollama,
    chain_type="stuff",
    retriever=vector_store.as_retriever()
)

# 查询
result = qa_chain({"query": "什么是人工智能？"})
print(result["result"])
```

### 2. SiliconFlow API 调用 Qwen

```python
import requests

def chat_with_qwen(prompt, model_id="Qwen/Qwen2.5-7B-Instruct"):
    """通过 SiliconFlow API 调用 Qwen"""

    response = requests.post(
        "https://api.siliconflow.cn/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": model_id,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 1024
        }
    )

    return response.json()["choices"][0]["message"]["content"]

# 使用示例
result = chat_with_qwen("用Python写一个快速排序")
print(result)
```

### 3. 本地部署 Qwen + Ollama RAG

```python
from langchain.document_loaders import TextLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import Chroma
from langchain.llms import Ollama
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate

# 1. 加载文档
file_path = 'dataset/example.txt'
loader = TextLoader(file_path, encoding='utf-8')
documents = loader.load()

# 2. 分割文档
text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
docs = text_splitter.split_documents(documents)

# 3. Embeddings（使用中文模型）
embeddings = HuggingFaceEmbeddings(
    model_name="damo/nlp_corom_sentence-embedding_chinese-base"
)

# 4. 创建向量数据库
db = Chroma.from_documents(docs, embeddings)

# 5. 初始化 Qwen 模型
ollama = Ollama(model="qwen2.5:0.5b")

# 6. 创建 QA 链
prompt_template = """基于以下文档内容回答问题：
{context}

问题：{question}
请根据上述内容回答。"""

PROMPT = PromptTemplate(
    template=prompt_template,
    input_variables=["context", "question"]
)

qa_chain = RetrievalQA.from_chain_type(
    llm=ollama,
    chain_type="stuff",
    retriever=db.as_retriever(),
    chain_type_kwargs={"prompt": PROMPT}
)

# 7. 查询
result = qa_chain({"query": "文档主要内容是什么？"})
print(result["result"])
```

### 4. 多轮对话

```python
# 使用 Ollama 进行多轮对话
ollama = Ollama(model="qwen2.5:7b")

messages = [
    {"role": "system", "content": "你是一个有帮助的AI助手。"},
    {"role": "user", "content": "什么是机器学习？"},
]

# 第一轮对话
response1 = ollama.invoke(messages)
messages.append({"role": "assistant", "content": response1})

# 第二轮对话（带上下文）
messages.append({"role": "user", "content": "它和深度学习有什么区别？"})
response2 = ollama.invoke(messages)

print(response2)
```

## 🔧 模型配置参数

### 1. 生成参数

```python
config = {
    "temperature": 0.7,        # 创造性（0-2）
    "top_p": 0.9,              # 核采样
    "top_k": 40,              # Top-K 采样
    "repeat_penalty": 1.1,    # 重复惩罚
    "seed": 42,               # 随机种子
    "num_predict": 256,        # 最大生成长度
    "stop": ["\n\n", "用户："]  # 停止序列
}

response = ollama.generate(model="qwen2.5:7b", prompt="你好", options=config)
```

### 2. GPU 配置

```bash
# 查看 GPU 使用情况
nvidia-smi

# 设置 GPU 设备
export CUDA_VISIBLE_DEVICES=0,1

# 量化模型（减少显存）
ollama pull qwen2.5:7b-q4_0   # 4位量化
ollama pull qwen2.5:7b-q8_0   # 8位量化
```

### 3. Ollama 配置文件

```yaml
# ~/.ollama/config.json
{
  "gpu": true,
  "num_gpu": 1,
  "fallback": ["cpu"],
  "keep_alive": "5m",
  "timeout": "120s"
}
```

## 📊 Qwen vs 其他模型对比

| 模型 | 参数量 | 上下文 | 中文能力 | 本地部署 |
|------|--------|--------|---------|---------|
| Qwen2.5-7B | 7B | 128K | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Qwen2.5-14B | 14B | 128K | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| Llama3-8B | 8B | 8K | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| ChatGLM3-6B | 6B | 128K | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |

## 🐛 常见问题

### Q: 模型选择哪个版本？

```bash
# 资源有限（CPU推理）
ollama pull qwen2.5:0.5b

# 资源一般（GPU 8GB+）
ollama pull qwen2.5:3b

# 资源充足（GPU 16GB+）
ollama pull qwen2.5:7b

# 高质量输出（GPU 24GB+）
ollama pull qwen2.5:14b
```

### Q: 如何提高生成质量？

```python
# 1. 使用更长的上下文
ollama = Ollama(model="qwen2.5:7b", num_ctx=8192)

# 2. 调整 temperature
ollama = Ollama(model="qwen2.5:7b", temperature=0.3)  # 更确定性

# 3. 使用few-shot提示
prompt = """示例：
问题：1+1=?
答案：2

问题：2+2=?
答案：4

问题：3+3=?
答案："""
```

### Q: Ollama 服务无法启动？

```bash
# 检查服务状态
ollama serve

# 查看日志
journalctl -u ollama

# 重启服务
sudo systemctl restart ollama
```

## 📚 相关资源

- 通义千问官网: https://tongyi.aliyun.com/
- Ollama 官网: https://ollama.com/
- Qwen GitHub: https://github.com/QwenLM/Qwen
- 模型下载: https://ollama.com/library/qwen2.5