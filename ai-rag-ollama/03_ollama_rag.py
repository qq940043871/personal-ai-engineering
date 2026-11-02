from langchain.document_loaders import TextLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import Chroma
from langchain.llms import Ollama
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from modelscope.hub.snapshot_download import snapshot_download
import os

# 下载嵌入模型
model_dir = snapshot_download('damo/nlp_corom_sentence-embedding_chinese-base')
os.environ['TRANSFORMERS_CACHE'] = model_dir

# 构建相对路径（以脚本所在目录为基准，从任意 cwd 运行均可）
_here = os.path.dirname(os.path.abspath(__file__))
file_path = os.path.join(_here, 'dataset', 'example.txt')

# 加载文档，指定编码格式为 utf-8
loader = TextLoader(file_path, encoding='utf-8')
documents = loader.load()

# 分割文档
text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
docs = text_splitter.split_documents(documents)

# 采用 modelscope 下载的国产嵌入模型
embeddings = HuggingFaceEmbeddings(model_name=model_dir)

# 创建向量数据库
db = Chroma.from_documents(docs, embeddings)

# 创建 Ollama 语言模型实例，使用 qwen 模型
ollama = Ollama(model="qwen2.5:0.5b")

# 自定义提示模板
prompt_template = """以下是一些相关文档内容：
{context}

问题：{question}
请根据上述文档内容回答问题。"""
PROMPT = PromptTemplate(
    template=prompt_template, input_variables=["context", "question"]
)

# 创建检索问答链，指定提示模板
qa = RetrievalQA.from_chain_type(
    llm=ollama,
    chain_type="stuff",
    retriever=db.as_retriever(),
    chain_type_kwargs={"prompt": PROMPT}
)

# 提出问题
query = "我想买台笔记本电脑，预算5000元，帮我推荐一台？要求和文档精确匹配"

# 手动执行检索步骤
retriever = db.as_retriever()
relevant_docs = retriever.get_relevant_documents(query)
context = "\n".join([doc.page_content for doc in relevant_docs])

# 生成发送给大模型的提示词
input_prompt = PROMPT.format(context=context, question=query)
print("发送给大模型的数据：")
print(input_prompt)

# 执行问答链获取最终回答
result = qa.run(query)
print("\n最终生成的回答：")
print(result)
    
        