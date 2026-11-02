# Dify 快速学习手册

## 📋 概述

Dify 是一款开源的大语言模型(LLM)应用开发平台，支持快速构建 AI 应用，提供可视化的工作流编排能力。

**定位对比：**
- Dify = "记忆管理的成品解决方案"（低代码，开箱即用）
- LangChain = "记忆管理的乐高积木"（高灵活度，需更多开发成本）

## 🏗️ 核心概念

```
┌─────────────────────────────────────────────────────┐
│                    Dify 架构                         │
├─────────────────────────────────────────────────────┤
│  应用层: 对话应用 │ Agent │ 工作流 │ Chatflow       │
├─────────────────────────────────────────────────────┤
│  能力层: RAG引擎 │ 提示词 │ 工具插件 │ 变量上下文   │
├─────────────────────────────────────────────────────┤
│  模型层: OpenAI │ Anthropic │ 本地模型 │ API网关    │
├─────────────────────────────────────────────────────┤
│  数据层: 文件上传 │ 知识库 │ 向量数据库              │
└─────────────────────────────────────────────────────┘
```

## 🚀 快速开始

### 1. 安装部署

```bash
# 使用 Docker 部署
git clone https://github.com/langgenius/dify.git
cd dify/docker
cp .env.example .env
docker-compose up -d

# 访问 http://localhost:80
```

### 2. API 调用

```bash
# 获取 API Key
# 设置 -> API

# 调用对话 API
curl -X POST 'http://localhost:80/v1/chat-messages' \
  -H 'Authorization: Bearer {api_key}' \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "什么是人工智能？",
    "response_mode": "blocking",
    "conversation_id": "",
    "user": "user_123"
  }'
```

## 📚 项目代码示例

项目中包含 `02_dify` 目录下的完整示例代码。

### 1. Dify API 上传文档

```python
import requests

class DifyUploader:
    def __init__(self, api_base_url, api_key):
        self.api_base_url = api_base_url.rstrip('/')
        self.api_key = api_key

    def create_document_by_text(self, dataset_id, name, text):
        """通过文本创建文档"""
        url = f"{self.api_base_url}/v1/datasets/{dataset_id}/document/create-by-text"

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        data = {
            "name": name,
            "text": text,
            "indexing_technique": "high_quality",
            "process_rule": {
                "mode": "automatic"
            }
        }

        response = requests.post(url, headers=headers, json=data)
        return response.json()

    def get_document_status(self, dataset_id, document_id):
        """查询文档处理状态"""
        url = f"{self.api_base_url}/v1/datasets/{dataset_id}/documents/{document_id}"
        headers = {'Authorization': f'Bearer {self.api_key}'}
        response = requests.get(url, headers=headers)
        return response.json()
```

### 2. RagFlow 文档上传器（类似实现）

```python
import requests
import tempfile
import uuid

class RagflowDocumentUploader:
    def __init__(self, api_base_url, api_key):
        self.api_base_url = api_base_url
        self.api_key = api_key

    def upload_document(self, dataset_id, file_path, chunk_delimiter="@@"):
        """上传文档到 RagFlow"""

        # 1. 创建空文档
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md') as f:
            temp_file_name = f.name

        with open(temp_file_name, 'rb') as f:
            files = {'file': (file_path, f, 'text/plain')}
            headers = {'Authorization': f'Bearer {self.api_key}'}

            url = f"{self.api_base_url}/api/v1/datasets/{dataset_id}/documents"
            response = requests.post(url, headers=headers, files=files)

        document_id = response.json()["data"][0]["id"]

        # 2. 上传文档内容
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        chunks = content.split(chunk_delimiter)
        for i, chunk in enumerate(chunks):
            self.upload_chunk(dataset_id, document_id, chunk, i)

        return document_id
```

## 🔧 核心功能配置

### 1. 知识库配置

```yaml
# 文档处理规则
process_rule:
  mode: "hierarchical"  # 层级模式
  rules:
    pre_processing_rules:
      - id: "remove_extra_spaces"
        enabled: true
      - id: "remove_urls_emails"
        enabled: false
    segmentation:
      separator: "**********page_ending**********"
      max_tokens: 1024
      chunk_overlap: 0
    parent_mode: "paragraph"
```

### 2. 应用类型

| 类型 | 适用场景 | 特点 |
|------|---------|------|
| Chatbot | 智能客服 | 多轮对话 |
| Agent | 自主任务 | 工具调用 |
| Workflow | 业务流程 | 可视化编排 |
| Chatflow | 对话流 | 简化对话编排 |

### 3. 提示词模板

```jinja2
# 系统提示词
你是一个专业的{{role}}，擅长回答{{domain}}相关问题。
请用简洁清晰的语言回答用户的问题。

# 用户问题
{{query}}

# 上下文
{{context}}
```

## 📊 Dify vs LangChain 对比

| 维度 | Dify | LangChain |
|------|------|-----------|
| **上手难度** | ⭐⭐ 低（可视化配置） | ⭐⭐⭐⭐ 高（需编码） |
| **灵活性** | ⭐⭐⭐ 中等 | ⭐⭐⭐⭐⭐ 极高 |
| **记忆管理** | 自动处理 | 需手动配置 |
| **适用场景** | 80%常见场景 | 100%复杂场景 |
| **部署方式** | 一键部署 | 自行组合 |

### 选择建议

- ✅ **选 Dify**：快速搭建标准化应用、客服机器人、简单问答
- ✅ **选 LangChain**：深度定制、复杂记忆策略、医疗/法律等专业场景

## � 连接 Ragflow 知识库

Ragflow 是一个开源的知识库管理系统，与 Dify 可以完美集成，提供更强大的文档管理能力。

### 1. Ragflow 部署

```bash
# 克隆仓库
git clone https://github.com/infiniflow/ragflow.git
cd ragflow

# 配置环境
cp .env.example .env
# 编辑 .env 文件，设置数据库等配置

# 启动服务
docker-compose up -d

# 访问 http://localhost:30002
```

### 2. 配置 Ragflow API

```python
class RagflowClient:
    def __init__(self, api_base_url, api_key):
        self.api_base_url = api_base_url.rstrip('/')
        self.api_key = api_key
    
    def list_datasets(self):
        """列出所有知识库"""
        url = f"{self.api_base_url}/api/v1/datasets"
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        response = requests.get(url, headers=headers)
        return response.json()
    
    def create_document(self, dataset_id, file_path):
        """上传文档到知识库"""
        url = f"{self.api_base_url}/api/v1/datasets/{dataset_id}/documents"
        headers = {
            'Authorization': f'Bearer {self.api_key}'
        }
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f)}
            response = requests.post(url, headers=headers, files=files)
        return response.json()
```

### 3. 与 Dify 集成

```python
class DifyRagflowIntegration:
    def __init__(self, dify_api_key, ragflow_api_key, ragflow_url="http://localhost:30002"):
        self.dify_api_key = dify_api_key
        self.ragflow_client = RagflowClient(ragflow_url, ragflow_api_key)
    
    def sync_ragflow_to_dify(self, ragflow_dataset_id, dify_app_id):
        """同步 Ragflow 知识库到 Dify"""
        # 1. 获取 Ragflow 文档
        documents = self.ragflow_client.get_documents(ragflow_dataset_id)
        
        # 2. 同步到 Dify
        for doc in documents:
            self._sync_document_to_dify(doc, dify_app_id)
    
    def _sync_document_to_dify(self, document, dify_app_id):
        """同步单个文档"""
        # 实现文档同步逻辑
        pass
```

### 4. 完整的 Ragflow 上传工具

项目中包含完整的 Ragflow 上传工具：`02_dify/ragflow/ragflow_uploader.py`

**主要功能：**
- 可视化界面上传文档
- 支持文档分段上传
- 实时进度显示
- 错误处理和日志记录

**使用步骤：**
1. 启动 Ragflow 服务
2. 运行上传工具：`python ragflow_uploader.py`
3. 配置 API 地址、密钥和知识库 ID
4. 选择本地文件并上传

### 5. API 参考

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v1/datasets` | GET | 获取知识库列表 |
| `/api/v1/datasets/{id}/documents` | POST | 上传文档 |
| `/api/v1/datasets/{id}/documents/{doc_id}/chunks` | POST | 上传文档分段 |
| `/api/v1/datasets/{id}/documents/{doc_id}` | GET | 获取文档信息 |

## � 常见问题

### Q: 文档上传失败？

```python
# 检查文件格式
# 支持: .txt, .markdown, .pdf, .docx, .html

# 检查 API 配置
print(f"API地址: {api_base_url}")
print(f"知识库ID: {dataset_id}")
```

### Q: 如何批量上传？

```python
import os

uploader = DifyUploader(api_base_url, api_key)
dataset_id = "your_dataset_id"

for filename in os.listdir("./documents"):
    with open(filename, 'r') as f:
        content = f.read()
    uploader.create_document_by_text(dataset_id, filename, content)
```

### Q: 分块策略如何选择？

| 策略 | 适用场景 |
|------|---------|
| Automatic | 通用场景，AI自动分块 |
| Hierarchical | 长文档，保留层级结构 |
| Custom | 明确知道分段规则 |

### Q: Ragflow 连接失败？

```python
# 检查 Ragflow 服务状态
import requests

try:
    response = requests.get("http://localhost:30002/api/v1/health")
    print(f"Ragflow 状态: {response.status_code}")
except Exception as e:
    print(f"Ragflow 连接失败: {e}")

# 检查 API 密钥
print(f"API 密钥: {api_key[:10]}...")
```

## 📚 相关资源

- **Dify 资源**:
  - 官方文档: https://docs.dify.ai/
  - GitHub: https://github.com/langgenius/dify
  - 示例代码: `02_dify/` 目录

- **Ragflow 资源**:
  - 官方文档: https://docs.ragflow.io/
  - GitHub: https://github.com/infiniflow/ragflow
  - 上传工具: `02_dify/ragflow/ragflow_uploader.py`