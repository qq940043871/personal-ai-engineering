from whoosh.index import create_in
from whoosh.fields import Schema, TEXT, ID
from whoosh.qparser import QueryParser

# 定义索引的模式
schema = Schema(title=TEXT(stored=True), path=ID(stored=True), content=TEXT)

# 创建索引目录
import os.path
if not os.path.exists("indexdir"):
    os.mkdir("indexdir")

# 创建索引对象
ix = create_in("indexdir", schema)
writer = ix.writer()

# 添加文档到索引中
documents = [
    {"title": "Document 1", "content": "This is the first document."},
    {"title": "Document 2", "content": "The second document is here."},
    {"title": "Document 3", "content": "And this is the third one."}
]

try:
    with open('D:\\workspace\\p001_ai_study_py\\04_ollama_rag\\dataset\\example.txt', 'r', encoding='utf-8') as file:
        lines = file.readlines()
        for i in range(len(lines)):
            documents.append({"title": "custom"+str(i), "content": lines[i].strip()})
except FileNotFoundError:
    print("错误：文件未找到！")
except Exception as e:
    print(f"发生未知错误：{e}")

print(documents)

for doc in documents:
    writer.add_document(title=doc["title"], path=f"/a/{doc['title']}", content=doc["content"])

# 提交更改
writer.commit()

# 进行搜索
with ix.searcher() as searcher:
    query = QueryParser("content", ix.schema).parse("豪华手表")
    results = searcher.search(query)
    for hit in results:
        print(hit)
    