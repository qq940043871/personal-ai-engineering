import os
import requests
from typing import List, Dict, Any, Optional
from langchain.document_loaders import TextLoader, DirectoryLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import Chroma
from langchain.llms import OpenAI
from langchain.chat_models import ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.schema import Document
from langchain.embeddings.base import Embeddings
from langchain.embeddings.openai import OpenAIEmbeddings

class SiliconFlowEmbeddings(Embeddings):
    """
    SiliconFlow嵌入模型的LangChain集成
    """
    def __init__(self, api_key: str, model_id: str = "BAAI/bge-large-en-v1.5"):
        """
        初始化SiliconFlow嵌入模型
        
        Args:
            api_key: SiliconFlow的API密钥
            model_id: 嵌入模型ID，默认为BAAI/bge-large-en-v1.5
        """
        self.api_key = api_key
        self.model_id = model_id
        self.api_url = "https://api.siliconflow.cn/v1/embeddings"
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        为文档列表嵌入向量
        
        Args:
            texts: 文档文本列表
            
        Returns:
            嵌入向量列表
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        data = {
            "model": self.model_id,
            "input": texts
        }
        
        try:
            response = requests.post(self.api_url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            return [item["embedding"] for item in result["data"]]
        except Exception as e:
            raise ValueError(f"调用SiliconFlow嵌入API失败: {str(e)}")
    
    def embed_query(self, text: str) -> List[float]:
        """
        为查询文本嵌入向量
        
        Args:
            text: 查询文本
            
        Returns:
            嵌入向量
        """
        return self.embed_documents([text])[0]

class RAGService:
    """使用SiliconFlow嵌入模型的检索增强生成(RAG)服务实现"""
    
    def __init__(self, 
                 data_dir: str = "./data",
                 vector_db_dir: str = "./vector_db",
                 embedding_model: str = "siliconflow",  # 默认为siliconflow
                 embedding_model_id: str = "BAAI/bge-large-en-v1.5",
                 llm_model: str = "gpt-3.5-turbo",
                 use_chat_model: bool = True):
        """
        初始化RAG服务
        
        Args:
            data_dir: 文档数据目录
            vector_db_dir: 向量数据库存储目录
            embedding_model: 嵌入模型类型
            embedding_model_id: 嵌入模型ID
            llm_model: LLM模型名称
            use_chat_model: 是否使用聊天模型
        """
        self.data_dir = data_dir
        self.vector_db_dir = vector_db_dir
        self.embedding_model = embedding_model
        self.embedding_model_id = embedding_model_id
        self.llm_model = llm_model
        self.use_chat_model = use_chat_model
        
        # 初始化组件
        self.embeddings = self._init_embeddings()
        self.llm = self._init_llm()
        self.vector_store = None
        self.qa_chain = None
        
        # 创建数据目录（如果不存在）
        os.makedirs(self.data_dir, exist_ok=True)
        
    def _init_embeddings(self) -> Embeddings:
        """初始化嵌入模型"""
        if self.embedding_model.lower() == "siliconflow":
            # 从环境变量获取SiliconFlow API密钥
            api_key = "sk-REPLACE_WITH_YOUR_KEY"
            if not api_key:
                raise ValueError("请设置SILICONFLOW_API_KEY环境变量")
            return SiliconFlowEmbeddings(
                api_key=api_key,
                model_id=self.embedding_model_id
            )
        elif self.embedding_model.lower() == "openai":
            return OpenAIEmbeddings()
        else:
            raise ValueError(f"不支持的嵌入模型: {self.embedding_model}")
    
    def _init_llm(self) -> Any:
        """初始化LLM模型"""
        if self.use_chat_model:
            return ChatOpenAI(model_name=self.llm_model, temperature=0)
        else:
            return OpenAI(model_name=self.llm_model, temperature=0)
    
    def load_documents(self) -> List[Document]:
        """从数据目录加载文档"""
        loader = DirectoryLoader(
            self.data_dir,
            glob="*.txt",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"}
        )
        documents = loader.load()
        print(f"加载了 {len(documents)} 个文档")
        return documents
    
    def split_documents(self, documents: List[Document]) -> List[Document]:
        """将文档分割为小块"""
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len
        )
        splits = text_splitter.split_documents(documents)
        print(f"文档分割为 {len(splits)} 个片段")
        return splits
    
    def create_vector_store(self, splits: List[Document]) -> Chroma:
        """创建向量存储"""
        # 持久化向量存储
        vector_store = Chroma.from_documents(
            documents=splits,
            embedding=self.embeddings,
            persist_directory=self.vector_db_dir
        )
        vector_store.persist()
        print(f"向量存储已创建并保存到 {self.vector_db_dir}")
        return vector_store
    
    def load_vector_store(self) -> Chroma:
        """加载已存在的向量存储"""
        if not os.path.exists(self.vector_db_dir):
            raise FileNotFoundError(f"向量存储目录不存在: {self.vector_db_dir}")
            
        vector_store = Chroma(
            persist_directory=self.vector_db_dir,
            embedding_function=self.embeddings
        )
        print(f"已加载向量存储，包含 {vector_store._collection.count()} 个文档片段")
        return vector_store
    
    def initialize_qa_chain(self, retriever_search_kwargs: Dict[str, Any] = {"k": 3}) -> None:
        """初始化问答链"""
        # 如果向量存储未初始化，则尝试加载
        if self.vector_store is None:
            try:
                self.vector_store = self.load_vector_store()
            except FileNotFoundError:
                # 尝试从文档创建向量存储
                documents = self.load_documents()
                splits = self.split_documents(documents)
                self.vector_store = self.create_vector_store(splits)
        
        # 创建检索器
        retriever = self.vector_store.as_retriever(search_kwargs=retriever_search_kwargs)
        
        # 自定义提示模板
        prompt_template = """使用下面提供的上下文来回答问题。如果不知道答案，就说不知道，不要编造答案。

        上下文:
        {context}

        问题:
        {question}

        回答:"""
        
        PROMPT = PromptTemplate(
            template=prompt_template,
            input_variables=["context", "question"]
        )
        
        # 创建QA链
        self.qa_chain = RetrievalQA.from_chain_type(
            llm=self.llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=True,
            chain_type_kwargs={"prompt": PROMPT}
        )
        
        print("QA链已初始化")
    
    def answer_query(self, query: str) -> Dict[str, Any]:
        """
        回答用户查询
        
        Args:
            query: 用户问题
            
        Returns:
            包含回答和源文档的字典
        """
        if self.qa_chain is None:
            self.initialize_qa_chain()
            
        result = self.qa_chain({"query": query})
        
        # 整理结果
        return {
            "question": query,
            "answer": result["result"],
            "source_documents": [
                {
                    "page_content": doc.page_content[:200] + "...",  # 截断显示
                    "metadata": doc.metadata
                } for doc in result["source_documents"]
            ]
        }

# 使用示例
if __name__ == "__main__":
    # 确保设置了必要的API密钥
    if "SILICONFLOW_API_KEY" not in os.environ:
        # 这里仅为示例，实际使用中不要硬编码密钥
        os.environ["SILICONFLOW_API_KEY"] = "your-siliconflow-api-key"
        
    if "OPENAI_API_KEY" not in os.environ:
        os.environ["OPENAI_API_KEY"] = "your-openai-api-key"
    
    # 初始化RAG服务，使用SiliconFlow嵌入模型
    rag_service = RAGService(
        data_dir="./data",
        vector_db_dir="./vector_db",
        embedding_model="siliconflow",
        embedding_model_id="BAAI/bge-large-en-v1.5",  # 可以替换为其他SiliconFlow支持的嵌入模型
        llm_model="gpt-3.5-turbo",
        use_chat_model=True
    )
    
    # 初始化QA链（会自动加载或创建向量存储）
    rag_service.initialize_qa_chain()
    
    # 示例查询
    queries = [
        "什么是人工智能？",
        "机器学习和深度学习有什么区别？",
        "自然语言处理的主要应用领域有哪些？"
    ]
    
    # 回答查询
    for query in queries:
        print(f"\n问题: {query}")
        result = rag_service.answer_query(query)
        print(f"回答: {result['answer']}")
        print("来源文档:")
        for i, doc in enumerate(result['source_documents'], 1):
            print(f"  {i}. {doc['metadata']['source']}: {doc['page_content']}")
