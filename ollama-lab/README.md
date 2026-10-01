# ollama-lab

本地 Ollama / RAG 实验（原 `hello_ollama_rag`）。

- 演示对话：`01_ollama对话.py` / `01_ollama多轮对话.py`（Flask + `templates/`）
- 检索：`02_search_engine.py`
- RAG：`03_ollama_rag.py`
- 分步教程：`study/`
- 数据：`dataset/`

## 运行前提

- 本机已安装 Ollama，且拉取模型（脚本默认如 `qwen2.5:0.5b`、`nomic-embed-text`）
- Python 依赖：`flask`、`flask-cors`、`requests`、`chromadb`、`langchain` 等（按所跑脚本安装）

## 注意

- 脚本内路径应使用**相对本目录**的路径；历史绝对路径（`D:\workspace\...`）需在使用前改掉  
- `study/` 与根目录 `templates/` 曾出现重复文件，以可运行入口为准  
