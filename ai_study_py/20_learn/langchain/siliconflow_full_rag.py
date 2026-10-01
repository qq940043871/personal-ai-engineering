import requests
import os
from typing import List, Dict, Any, Optional
# 更新导入路径
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.schema import Document
from langchain.embeddings.base import Embeddings
from langchain.llms.base import LLM
# 更新CallbackManagerForLLMRun的导入路径
from langchain_core.callbacks import CallbackManagerForLLMRun

def ensure_dir_exists(path):
    """确保目录存在"""
    if not os.path.exists(path):
        os.makedirs(path)

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
        
        try:
            # 修复requests.post重复调用的错误
            response = requests.post(self.api_url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            return [item["embedding"] for item in result["data"]]
        except Exception as e:
            raise ValueError(f"SiliconFlow嵌入API调用失败: {str(e)}")
    
    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

class SiliconFlowLLM(LLM):
    """SiliconFlow对话模型的LangChain集成"""
    api_key: str
    model_id: str = "meta-llama/Llama-2-7b-chat-hf"
    temperature: float = 0.7
    max_tokens: int = 1024
    
    @property
    def _llm_type(self) -> str:
        return "siliconflow"
    
    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
    ) -> str:
        url = "https://api.siliconflow.cn/v1/chat/completions"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        data = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stop": stop
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            raise ValueError(f"SiliconFlow对话API调用失败: {str(e)}")
    
    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

class RAGService:
    """完全使用SiliconFlow模型的检索增强生成(RAG)服务"""
    
    def __init__(self, 
                 data_dir: str = "./data",
                 vector_db_dir: str = "./vector_db",
                 embedding_model_id: str = "BAAI/bge-large-en-v1.5",
                 llm_model_id: str = "meta-llama/Llama-2-7b-chat-hf",
                 temperature: float = 0,
                 max_tokens: int = 1024):
        """
        初始化RAG服务
        
        Args:
            data_dir: 文档数据目录
            vector_db_dir: 向量数据库存储目录
            embedding_model_id: SiliconFlow嵌入模型ID
            llm_model_id: SiliconFlow对话模型ID
            temperature: 生成温度参数
            max_tokens: 最大生成token数
        """
        self.data_dir = data_dir
        self.vector_db_dir = vector_db_dir
        self.embedding_model_id = embedding_model_id
        self.llm_model_id = llm_model_id
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # 获取API密钥
        self.api_key = os.environ.get("SILICONFLOW_API_KEY")
        if not self.api_key:
            raise ValueError("请设置SILICONFLOW_API_KEY环境变量")
        
        # 初始化组件
        self.embeddings = self._init_embeddings()
        self.llm = self._init_llm()
        self.vector_store = None
        self.qa_chain = None
        
        # 创建数据目录（如果不存在）
        ensure_dir_exists(self.data_dir)
        ensure_dir_exists(self.vector_db_dir)
    
    def _init_embeddings(self) -> Embeddings:
        """初始化SiliconFlow嵌入模型"""
        return SiliconFlowEmbeddings(
            api_key=self.api_key,
            model_id=self.embedding_model_id
        )
    
    def _init_llm(self) -> LLM:
        """初始化SiliconFlow对话模型"""
        return SiliconFlowLLM(
            api_key=self.api_key,
            model_id=self.llm_model_id,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
    
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
        # 如果向量存储未初始化，则尝试加载或创建
        if self.vector_store is None:
            try:
                self.vector_store = self.load_vector_store()
            except FileNotFoundError:
                # 从文档创建向量存储
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
        """回答用户查询"""
        if self.qa_chain is None:
            self.initialize_qa_chain()
            
        result = self.qa_chain.invoke({"query": query})
        
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
    # 设置API密钥（实际使用中建议通过环境变量设置）
    if "SILICONFLOW_API_KEY" not in os.environ:
        # 注意：在实际使用中请替换为您的真实API密钥
        os.environ["SILICONFLOW_API_KEY"] = "sk-REPLACE_WITH_YOUR_KEY"
        print("警告：未设置SILICONFLOW_API_KEY环境变量")
    
    try:
        # 初始化RAG服务，完全使用SiliconFlow模型
        rag_service = RAGService(
            data_dir="D://ai",
            vector_db_dir="D://ai//vector_db",
            # 中文可以使用 "BAAI/bge-large-zh-v1.5"
            embedding_model_id="BAAI/bge-large-en-v1.5",
            # 可以选择其他模型如 "mistralai/Mistral-7B-Instruct-v0.1"
            llm_model_id="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
            temperature=0.3,
            max_tokens=1024
        )
        
        # 初始化QA链
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
    except Exception as e:
        print(f"程序运行出错: {str(e)}")
