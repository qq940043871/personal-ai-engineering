# LangChain 快速学习手册

## 📋 概述

LangChain 是一个用于构建 LLM 应用的开发框架，提供模块化组件，支持 Chains、Agents、Memory、Tools 等核心功能。

**定位对比：**
- Dify = "记忆管理的成品解决方案"（低代码）
- LangChain = "记忆管理的乐高积木"（高灵活度）

## 🏗️ 核心架构

```
┌─────────────────────────────────────────────────────┐
│                   LangChain 架构                      │
├─────────────────────────────────────────────────────┤
│  应用层: Agent │ Chain │ Tool │ Memory             │
├─────────────────────────────────────────────────────┤
│  模型层: ChatGPT │ Llama │ SiliconFlow │ Ollama   │
├─────────────────────────────────────────────────────┤
│  数据层: DocumentLoader │ VectorStore │ Embeddings │
├─────────────────────────────────────────────────────┤
│  工具层: Search │ API │ Database │ FileSystem      │
└─────────────────────────────────────────────────────┘
```

## 🚀 快速开始

### 1. 安装

```bash
pip install langchain langchain-community langchain-core
pip install langchain[openai]  # 如果使用 OpenAI
```

### 2. 基本使用

```python
from langchain.schema import HumanMessage
from langchain.chat_models import ChatOpenAI

# 初始化聊天模型
chat = ChatOpenAI(temperature=0.7, model="gpt-3.5-turbo")

# 发送消息
response = chat([HumanMessage(content="你好，请介绍一下自己")])
print(response.content)
```

## 📚 项目代码示例

项目中包含 `03_langchain` 目录下的多个完整示例。

### 1. SiliconFlow LLM 封装

```python
import requests
from typing import Optional, List, Dict, Any
from langchain.llms.base import LLM
from langchain_core.callbacks import CallbackManagerForLLMRun

class SiliconFlowLLM(LLM):
    """SiliconFlow LLM 的 LangChain 集成"""

    def __init__(
        self,
        api_key: str,
        model_id: str = "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        temperature: float = 0.7,
        max_tokens: int = 512
    ):
        self.api_key = api_key
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.api_url = "https://api.siliconflow.cn/v1/chat/completions"

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None
    ) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        data = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

        if stop:
            data["stop"] = stop

        response = requests.post(self.api_url, headers=headers, json=data)
        response.raise_for_status()

        return response.json()["choices"][0]["message"]["content"]

    @property
    def _llm_type(self) -> str:
        return "siliconflow"
```

### 2. SiliconFlow Embeddings 封装

```python
from langchain.embeddings.base import Embeddings

class SiliconFlowEmbeddings(Embeddings):
    """SiliconFlow嵌入模型的LangChain集成"""

    def __init__(self, api_key: str, model_id: str = "BAAI/bge-large-en-v1.5"):
        self.api_key = api_key
        self.model_id = model_id
        self.api_url = "https://api.siliconflow.cn/v1/embeddings"

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        data = {
            "model": self.model_id,
            "input": texts
        }

        response = requests.post(self.api_url, headers=headers, json=data)
        response.raise_for_status()

        return [item["embedding"] for item in response.json()["data"]]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]
```

### 3. 完整 RAG 服务实现

```python
from typing import List, Dict, Any, Optional
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.embeddings.base import Embeddings
from langchain.llms.base import LLM

class RAGService:
    """使用SiliconFlow的RAG服务实现"""

    def __init__(
        self,
        data_dir: str = "./data",
        vector_db_dir: str = "./vector_db",
        embedding_model_id: str = "BAAI/bge-large-en-v1.5",
        llm_model_id: str = "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        temperature: float = 0.3,
        max_tokens: int = 1024
    ):
        self.data_dir = data_dir
        self.vector_db_dir = vector_db_dir
        self.embedding_model_id = embedding_model_id
        self.llm_model_id = llm_model_id
        self.temperature = temperature
        self.max_tokens = max_tokens

        # 初始化组件
        self.embeddings = self._init_embeddings()
        self.llm = self._init_llm()
        self.vector_store = None
        self.qa_chain = None

    def _init_embeddings(self) -> Embeddings:
        return SiliconFlowEmbeddings(
            api_key=os.environ.get("SILICONFLOW_API_KEY", ""),
            model_id=self.embedding_model_id
        )

    def _init_llm(self) -> LLM:
        return SiliconFlowLLM(
            api_key=os.environ.get("SILICONFLOW_API_KEY", ""),
            model_id=self.llm_model_id,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )

    def load_and_split_documents(self) -> List[Document]:
        """加载并分割文档"""
        loader = DirectoryLoader(
            self.data_dir,
            glob="*.txt",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"}
        )
        documents = loader.load()

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50
        )

        return text_splitter.split_documents(documents)

    def create_vector_store(self, splits: List[Document]) -> Chroma:
        """创建向量存储"""
        vector_store = Chroma.from_documents(
            documents=splits,
            embedding=self.embeddings,
            persist_directory=self.vector_db_dir
        )
        vector_store.persist()
        return vector_store

    def load_vector_store(self) -> Chroma:
        """加载已存在的向量存储"""
        return Chroma(
            persist_directory=self.vector_db_dir,
            embedding_function=self.embeddings
        )

    def initialize_qa_chain(self):
        """初始化问答链"""
        if not os.path.exists(self.vector_db_dir):
            # 创建新的向量存储
            docs = self.load_and_split_documents()
            self.vector_store = self.create_vector_store(docs)
        else:
            # 加载已有向量存储
            self.vector_store = self.load_vector_store()

        # 创建检索问答链
        self.qa_chain = RetrievalQA.from_chain_type(
            llm=self.llm,
            chain_type="stuff",
            retriever=self.vector_store.as_retriever(),
            chain_type_kwargs={
                "prompt": PromptTemplate(
                    template="""基于以下上下文回答问题：
{context}

问题：{question}

请用中文回答。""",
                    input_variables=["context", "question"]
                )
            }
        )

    def answer_query(self, query: str) -> Dict[str, Any]:
        """回答用户查询"""
        if self.qa_chain is None:
            self.initialize_qa_chain()

        result = self.qa_chain({"query": query})

        return {
            "question": query,
            "answer": result["result"],
            "source_documents": result.get("source_documents", [])
        }
```

### 4. 多 Agent 系统

```python
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferMemory

class MultiAgentSystem:
    """多Agent协作系统"""

    def __init__(self):
        self.agents = {}
        self.memory = ConversationBufferMemory()

    def register_agent(self, name: str, tools: List[Tool], system_prompt: str):
        """注册Agent"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

        agent = create_openai_tools_agent(
            llm=self.llm,
            tools=tools,
            prompt=prompt
        )

        self.agents[name] = AgentExecutor.from_agent_and_tools(
            agent=agent,
            tools=tools,
            memory=self.memory,
            verbose=True
        )

    def run(self, agent_name: str, input_text: str) -> str:
        """运行指定Agent"""
        if agent_name not in self.agents:
            raise ValueError(f"Agent {agent_name} 未注册")

        result = self.agents[agent_name].invoke({"input": input_text})
        return result["output"]
```

## 🔧 核心组件详解

### 1. Chains

| Chain 类型 | 用途 |
|-----------|------|
| LLMChain | 简单 Prompt + LLM |
| RetrievalQA | RAG 问答 |
| ConversationChain | 对话 |
| SQLDatabaseChain | SQL 查询 |

### 2. Memory 类型

| Memory 类型 | 特点 |
|-------------|------|
| BufferMemory | 完整保留对话 |
| SummaryMemory | 生成摘要 |
| EntityMemory | 实体跟踪 |
| VectorStoreMemory | 向量检索历史 |

### 3. Embeddings 模型选择

| 模型 | 维度 | 适用语言 |
|------|------|---------|
| BAAI/bge-large-zh | 1024 | 中文 |
| BAAI/bge-large-en | 1024 | 英文 |
| sentence-transformers | 可变 | 多语言 |

## 🐛 常见问题

### Q: 导入报错？

```python
# 新版本 LangChain 导入路径变更
# 旧版本
from langchain.document_loaders import TextLoader
from langchain.vectorstores import Chroma

# 新版本
from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import Chroma
```

### Q: 向量数据库选择？

```python
# Chroma (轻量级，本地存储)
from langchain_community.vectorstores import Chroma

# Milvus (生产级，分布式)
from langchain.vectorstores import Milvus

# Pinecone (云服务)
from langchain.vectorstores import Pinecone
```

### Q: 如何提高检索质量？

```python
# 1. 调整分割大小
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,  # 减小chunk提高精度
    chunk_overlap=50
)

# 2. 优化检索数量
retriever = vector_store.as_retriever(
    search_kwargs={"k": 5}  # 检索更多相关文档
)

# 3. 使用 MMR 检索
retriever = vector_store.as_retriever(
    search_type="mmr",  # 最大边际相关
    search_kwargs={"k": 5, "fetch_k": 20}
)
```

## 📚 相关资源

- 官方文档: https://python.langchain.com/
- GitHub: https://github.com/langchain-ai/langchain
- 示例代码: `03_langchain/` 目录