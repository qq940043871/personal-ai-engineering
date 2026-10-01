# Elasticsearch 向量数据库 快速学习手册

## 📋 概述

Elasticsearch 是一个功能强大的搜索引擎，通过向量插件可以实现向量搜索能力，成为完整的向量数据库解决方案。

**核心优势：**
- 成熟的分布式架构
- 强大的查询能力（向量+传统搜索）
- 完整的生态系统
- 企业级可靠性

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────┐
│                 ES 向量搜索架构                      │
├─────────────────────────────────────────────────────┤
│  客户端 → REST API → 节点 → 分片 → 倒排索引 + 向量索引  │
│                                                     │
│  文本 → 嵌入模型 → 向量 → ES 索引 → 向量搜索          │
└─────────────────────────────────────────────────────┘
```

## 🚀 快速开始

### 1. 安装部署

```bash
# 安装 Elasticsearch 8.x
docker pull docker.elastic.co/elasticsearch/elasticsearch:8.12.0
docker run -d -p 9200:9200 -p 9300:9300 \
  -e "discovery.type=single-node" \
  -e "ES_JAVA_OPTS=-Xms1g -Xmx1g" \
  -e "xpack.security.enabled=false" \
  --name es docker.elastic.co/elasticsearch/elasticsearch:8.12.0

# 检查状态
curl http://localhost:9200/
```

### 2. 安装向量插件

```bash
# 安装 ELSER 插件（内置向量模型）
docker exec -it es bin/elasticsearch-plugin install analysis-elser

# 或安装 KNN 插件（通用向量搜索）
docker exec -it es bin/elasticsearch-plugin install analysis-knn

# 重启 ES
docker restart es
```

## 🔧 核心配置

### 1. 索引创建

```python
import requests

def create_vector_index(index_name):
    """创建向量索引"""
    url = f"http://localhost:9200/{index_name}"
    headers = {"Content-Type": "application/json"}
    
    mapping = {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0
            }
        },
        "mappings": {
            "properties": {
                "text": {
                    "type": "text"
                },
                "vector": {
                    "type": "dense_vector",
                    "dims": 768,  # 向量维度
                    "index": True,
                    "similarity": "cosine"  # 相似度计算方式
                }
            }
        }
    }
    
    response = requests.put(url, headers=headers, json=mapping)
    return response.json()

# 创建商品索引
create_vector_index("products")
```

### 2. 向量数据写入

```python
def index_document(index_name, document_id, text, vector):
    """索引文档和向量"""
    url = f"http://localhost:9200/{index_name}/_doc/{document_id}"
    headers = {"Content-Type": "application/json"}
    
    data = {
        "text": text,
        "vector": vector
    }
    
    response = requests.put(url, headers=headers, json=data)
    return response.json()

# 示例：索引商品
product_vector = [0.1, 0.2, 0.3, ...]  # 768维向量
index_document(
    "products",
    "1",
    "iPhone 15 智能手机",
    product_vector
)
```

## 🛍️ 商品管理

### 1. 添加商品

```python
import numpy as np
from sentence_transformers import SentenceTransformer

# 加载嵌入模型
model = SentenceTransformer('all-MiniLM-L6-v2')

def add_product(product_id, name, price, description, category):
    """添加商品到 ES"""
    # 生成文本向量
    text = f"{name} {description} {category}"
    vector = model.encode(text).tolist()
    
    # 索引文档
    document = {
        "name": name,
        "price": price,
        "description": description,
        "category": category,
        "vector": vector
    }
    
    url = f"http://localhost:9200/products/_doc/{product_id}"
    headers = {"Content-Type": "application/json"}
    response = requests.put(url, headers=headers, json=document)
    
    return response.json()

# 添加商品示例
add_product(
    "1",
    "iPhone 15",
    5999.99,
    "苹果智能手机，搭载 A16 芯片",
    "电子产品"
)
```

### 2. 删除商品

```python
def delete_product(product_id):
    """删除商品"""
    url = f"http://localhost:9200/products/_doc/{product_id}"
    response = requests.delete(url)
    return response.json()

# 删除商品示例
delete_product("1")
```

### 3. 批量操作

```python
def bulk_index_products(products):
    """批量索引商品"""
    url = "http://localhost:9200/_bulk"
    headers = {"Content-Type": "application/json"}
    
    bulk_data = []
    for product in products:
        # 生成向量
        text = f"{product['name']} {product['description']} {product['category']}"
        vector = model.encode(text).tolist()
        
        # 添加索引操作
        bulk_data.append({"index": {"_index": "products", "_id": product['id']}})
        bulk_data.append({
            "name": product['name'],
            "price": product['price'],
            "description": product['description'],
            "category": product['category'],
            "vector": vector
        })
    
    # 转换为字符串格式
    bulk_payload = "\n".join([json.dumps(item) for item in bulk_data]) + "\n"
    
    response = requests.post(url, headers=headers, data=bulk_payload)
    return response.json()

# 批量添加示例
products = [
    {"id": "1", "name": "iPhone 15", "price": 5999.99, "description": "苹果手机", "category": "电子产品"},
    {"id": "2", "name": "MacBook Pro", "price": 12999, "description": "苹果笔记本", "category": "电子产品"}
]
bulk_index_products(products)
```

## 🔍 向量搜索

### 1. 基本向量搜索

```python
def vector_search(query, k=5):
    """向量搜索"""
    # 生成查询向量
    query_vector = model.encode(query).tolist()
    
    url = "http://localhost:9200/products/_search"
    headers = {"Content-Type": "application/json"}
    
    search_body = {
        "knn": {
            "field": "vector",
            "query_vector": query_vector,
            "k": k,
            "num_candidates": 100  # 候选数量
        },
        "_source": ["name", "price", "description", "category"]
    }
    
    response = requests.get(url, headers=headers, json=search_body)
    return response.json()

# 搜索示例
results = vector_search("智能手机")
for hit in results['hits']['hits']:
    print(f"商品: {hit['_source']['name']}, 得分: {hit['_score']}")
```

### 2. 混合搜索

```python
def hybrid_search(query, filters=None, k=5):
    """混合搜索（向量+关键词）"""
    query_vector = model.encode(query).tolist()
    
    url = "http://localhost:9200/products/_search"
    headers = {"Content-Type": "application/json"}
    
    search_body = {
        "query": {
            "bool": {
                "should": [
                    {
                        "knn": {
                            "field": "vector",
                            "query_vector": query_vector,
                            "k": k,
                            "num_candidates": 100
                        }
                    },
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["name^2", "description", "category"]
                        }
                    }
                ]
            }
        },
        "size": k
    }
    
    # 添加过滤条件
    if filters:
        search_body['query']['bool']['filter'] = filters
    
    response = requests.get(url, headers=headers, json=search_body)
    return response.json()

# 带价格过滤的搜索
filters = {
    "range": {
        "price": {
            "lte": 6000
        }
    }
}

results = hybrid_search("手机", filters=filters)
```

### 3. 聚合分析

```python
def category_aggregation():
    """按分类聚合商品"""
    url = "http://localhost:9200/products/_search"
    headers = {"Content-Type": "application/json"}
    
    aggregation_body = {
        "size": 0,
        "aggs": {
            "categories": {
                "terms": {
                    "field": "category.keyword"
                },
                "aggs": {
                    "avg_price": {
                        "avg": {
                            "field": "price"
                        }
                    },
                    "count": {
                        "value_count": {
                            "field": "name"
                        }
                    }
                }
            }
        }
    }
    
    response = requests.get(url, headers=headers, json=aggregation_body)
    return response.json()

# 分析结果
agg_results = category_aggregation()
for bucket in agg_results['aggregations']['categories']['buckets']:
    print(f"分类: {bucket['key']}, 数量: {bucket['count']['value']}, 平均价格: {bucket['avg_price']['value']}")
```

## 🏢 用户权限管理

### 1. 安全配置

```bash
# 启用安全功能
docker exec -it es bin/elasticsearch-reset-password -u elastic -i

# 创建用户
curl -X POST "http://localhost:9200/_security/user/user1" \
  -H "Content-Type: application/json" \
  -u elastic:password \
  -d '{
    "password": "user1password",
    "roles": ["reader"]
  }'

# 创建角色
curl -X POST "http://localhost:9200/_security/role/product_manager" \
  -H "Content-Type: application/json" \
  -u elastic:password \
  -d '{
    "cluster": ["monitor"],
    "indices": [
      {
        "names": ["products"],
        "privileges": ["read", "write", "create_index"]
      }
    ]
  }'
```

### 2. 多租户实现

```python
def create_user_index(user_id):
    """为用户创建专属索引"""
    index_name = f"products_{user_id}"
    
    mapping = {
        "settings": {
            "index": {
                "number_of_shards": 1
            }
        },
        "mappings": {
            "properties": {
                "name": {"type": "text"},
                "price": {"type": "float"},
                "vector": {
                    "type": "dense_vector",
                    "dims": 768,
                    "index": True,
                    "similarity": "cosine"
                }
            }
        }
    }
    
    url = f"http://localhost:9200/{index_name}"
    headers = {"Content-Type": "application/json"}
    response = requests.put(url, headers=headers, json=mapping, auth=('elastic', 'password'))
    return response.json()

# 为用户创建索引
create_user_index("user1")
```

### 3. 访问控制

```python
def add_product_to_user_index(user_id, product):
    """向用户索引添加商品"""
    index_name = f"products_{user_id}"
    product_id = product['id']
    
    # 生成向量
    text = f"{product['name']} {product['description']}"
    vector = model.encode(text).tolist()
    
    document = product.copy()
    document['vector'] = vector
    
    url = f"http://localhost:9200/{index_name}/_doc/{product_id}"
    headers = {"Content-Type": "application/json"}
    response = requests.put(url, headers=headers, json=document, auth=('user1', 'user1password'))
    return response.json()
```

## 📊 性能优化

### 1. 向量索引优化

```python
def optimize_vector_index(index_name):
    """优化向量索引"""
    url = f"http://localhost:9200/{index_name}/_forcemerge?max_num_segments=1"
    response = requests.post(url)
    return response.json()

# 优化索引
optimize_vector_index("products")
```

### 2. 查询性能优化

| 优化策略 | 配置参数 | 适用场景 |
|---------|---------|----------|
| 增加候选数 | `num_candidates: 100` | 提高召回率 |
| 减少维度 | `dims: 384` | 内存受限场景 |
| 使用 HNSW | `index: true` | 高并发查询 |
| 缓存优化 | `index.queries.cache.size: 10%` | 重复查询 |

### 3. 存储优化

```python
def update_index_settings(index_name):
    """更新索引设置"""
    url = f"http://localhost:9200/{index_name}/_settings"
    headers = {"Content-Type": "application/json"}
    
    settings = {
        "index": {
            "queries": {
                "cache": {
                    "size": "10%"
                }
            },
            "refresh_interval": "30s",
            "number_of_replicas": 1
        }
    }
    
    response = requests.put(url, headers=headers, json=settings)
    return response.json()
```

## 🐛 常见问题

### Q: 向量搜索速度慢？

```python
# 检查索引状态
response = requests.get("http://localhost:9200/products/_stats")
print(response.json())

# 优化查询
search_body = {
    "knn": {
        "field": "vector",
        "query_vector": query_vector,
        "k": 5,
        "num_candidates": 50  # 减少候选数
    }
}
```

### Q: 内存使用过高？

```bash
# 检查内存使用
docker stats es

# 调整 JVM 堆大小
docker run -d -p 9200:9200 \
  -e "ES_JAVA_OPTS=-Xms2g -Xmx2g" \
  --name es elasticsearch:8.12.0

# 减少向量维度
# 使用 384 维替代 768 维
```

### Q: 权限认证失败？

```python
# 检查用户权限
response = requests.get(
    "http://localhost:9200/_security/user/user1",
    auth=('elastic', 'password')
)
print(response.json())

# 测试认证
response = requests.get(
    "http://localhost:9200/products/_search",
    auth=('user1', 'user1password')
)
print(f"状态码: {response.status_code}")
```

## 📚 相关资源

- **官方文档**: https://www.elastic.co/guide/en/elasticsearch/reference/current/knn-search.html
- **向量搜索指南**: https://www.elastic.co/guide/en/elasticsearch/reference/current/knn-approximate-search.html
- **Python 客户端**: https://elasticsearch-py.readthedocs.io/
- **ELSER 插件**: https://www.elastic.co/guide/en/elasticsearch/reference/current/elser.html
- **安全配置**: https://www.elastic.co/guide/en/elasticsearch/reference/current/security.html