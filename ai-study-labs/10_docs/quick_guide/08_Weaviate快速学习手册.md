# Weaviate 快速学习手册

## 📋 概述

Weaviate 是一个开源的向量数据库，支持语义搜索、多模态数据和可扩展架构，特别适合构建智能应用。

**核心特性：**
- 向量搜索 + 传统搜索
- 图数据库能力
- 自动 schema 检测
- 多租户支持
- 企业级安全

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────┐
│                 Weaviate 架构                         │
├─────────────────────────────────────────────────────┤
│  客户端 → API 层 → 认证层 → 向量索引 → 存储层         │
│                                                     │
│  租户 1 → 类 1 → 对象 1,2,3                          │
│  租户 2 → 类 2 → 对象 4,5,6                          │
└─────────────────────────────────────────────────────┘
```

## 🚀 快速开始

### 1. 安装部署

```bash
# Docker 部署
 docker run -d -p 8080:8080 \
  -e AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=false \
  -e AUTHENTICATION_APIKEY_ENABLED=true \
  -e AUTHENTICATION_APIKEY_ALLOWED_KEYS=your-api-key \
  -e AUTHENTICATION_APIKEY_USERS=admin \
  semitechnologies/weaviate:1.24.2

# 或使用 docker-compose
curl -o docker-compose.yml https://raw.githubusercontent.com/weaviate/weaviate/main/docker-compose.yml
docker-compose up -d
```

### 2. 基本操作

```bash
# 健康检查
curl http://localhost:8080/v1/meta

# 创建 schema
curl -X POST http://localhost:8080/v1/schema \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -d '{
    "classes": [{
      "class": "Product",
      "description": "商品信息",
      "properties": [
        {"name": "name", "dataType": ["string"]},
        {"name": "price", "dataType": ["number"]},
        {"name": "description", "dataType": ["text"]}
      ]
    }]
  }'
```

## 🔐 用户权限管理

### 1. 认证配置

```bash
# docker-compose.yml 配置
version: '3.4'
services:
  weaviate:
    image: semitechnologies/weaviate:1.24.2
    ports:
      - "8080:8080"
    environment:
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "false"
      AUTHENTICATION_APIKEY_ENABLED: "true"
      AUTHENTICATION_APIKEY_ALLOWED_KEYS: "user1-key,user2-key,admin-key"
      AUTHENTICATION_APIKEY_USERS: "user1,user2,admin"
      AUTHORIZATION_ADMINLIST_ENABLED: "true"
      AUTHORIZATION_ADMINLIST_USERS: "admin"
```

### 2. 角色与权限

| 角色 | 权限 | API Key |
|------|------|---------|
| admin | 所有操作 | admin-key |
| user1 | 只读/有限写入 | user1-key |
| user2 | 只读/有限写入 | user2-key |

### 3. 访问控制实现

```python
import weaviate

# 管理员客户端
client_admin = weaviate.Client(
    url="http://localhost:8080",
    auth_client_secret=weaviate.AuthApiKey(api_key="admin-key")
)

# 用户客户端
client_user1 = weaviate.Client(
    url="http://localhost:8080",
    auth_client_secret=weaviate.AuthApiKey(api_key="user1-key")
)

# 检查权限
try:
    # 只有管理员可以创建 schema
    client_admin.schema.create_class({
        "class": "Product",
        "properties": [
            {"name": "name", "dataType": ["string"]}
        ]
    })
    print("管理员权限正常")
except Exception as e:
    print(f"权限错误: {e}")
```

## 🏢 多租户管理

### 1. 命名空间配置

```python
# 创建用户专属命名空间
def create_user_namespace(user_id):
    """为每个用户创建独立的命名空间"""
    return f"user_{user_id}_namespace"

# 为用户1创建命名空间
user1_namespace = create_user_namespace("user1")
user2_namespace = create_user_namespace("user2")
```

### 2. 多知识库实现

```python
def create_user_knowledge_base(user_id, client):
    """为用户创建专属知识库"""
    namespace = create_user_namespace(user_id)
    
    # 创建用户专属的商品类
    class_name = f"Product_{user_id}"
    
    schema = {
        "class": class_name,
        "description": f"用户 {user_id} 的商品知识库",
        "properties": [
            {"name": "name", "dataType": ["string"]},
            {"name": "price", "dataType": ["number"]},
            {"name": "description", "dataType": ["text"]},
            {"name": "category", "dataType": ["string"]}
        ]
    }
    
    try:
        client.schema.create_class(schema)
        return class_name
    except Exception as e:
        print(f"创建知识库失败: {e}")
        return None

# 为不同用户创建知识库
user1_class = create_user_knowledge_base("user1", client_admin)
user2_class = create_user_knowledge_base("user2", client_admin)
```

### 3. 数据隔离

```python
def add_product_to_user_kb(user_id, product_data, client):
    """向用户知识库添加商品"""
    class_name = f"Product_{user_id}"
    
    # 生成 UUID（可选）
    import uuid
    product_id = str(uuid.uuid4())
    
    data_object = {
        "id": product_id,
        "class": class_name,
        "properties": product_data
    }
    
    try:
        client.data_object.create(
            data_object=data_object,
            class_name=class_name
        )
        return product_id
    except Exception as e:
        print(f"添加商品失败: {e}")
        return None
```

## 🛍️ 商品信息管理

### 1. 添加商品

```python
def add_product(user_id, name, price, description, category, client):
    """添加商品到用户知识库"""
    product_data = {
        "name": name,
        "price": price,
        "description": description,
        "category": category
    }
    
    return add_product_to_user_kb(user_id, product_data, client)

# 示例：为用户1添加商品
product_id = add_product(
    user_id="user1",
    name="iPhone 15",
    price=5999.99,
    description="苹果智能手机",
    category="电子产品",
    client=client_user1
)
print(f"商品添加成功，ID: {product_id}")
```

### 2. 删除商品

```python
def delete_product(user_id, product_id, client):
    """从用户知识库删除商品"""
    class_name = f"Product_{user_id}"
    
    try:
        client.data_object.delete(
            uuid=product_id,
            class_name=class_name
        )
        return True
    except Exception as e:
        print(f"删除商品失败: {e}")
        return False

# 示例：删除商品
success = delete_product(
    user_id="user1",
    product_id=product_id,
    client=client_user1
)
if success:
    print("商品删除成功")
```

### 3. 批量操作

```python
def batch_add_products(user_id, products, client):
    """批量添加商品"""
    class_name = f"Product_{user_id}"
    
    # 开始批量操作
    with client.batch as batch:
        batch.batch_size = 10  # 每批处理10个
        
        for product in products:
            product_id = str(uuid.uuid4())
            batch.add_data_object(
                data_object=product,
                class_name=class_name,
                uuid=product_id
            )
    
    return True

# 批量添加示例
products = [
    {"name": "MacBook Pro", "price": 12999, "category": "电子产品"},
    {"name": "AirPods Pro", "price": 1999, "category": "配件"},
    {"name": "iPad Air", "price": 4799, "category": "平板电脑"}
]

batch_add_products("user1", products, client_user1)
```

## 🔍 语义搜索

### 1. 向量搜索

```python
def search_products(user_id, query, client, limit=5):
    """搜索用户知识库中的商品"""
    class_name = f"Product_{user_id}"
    
    response = client.query.get(
        class_name,
        ["name", "price", "description", "category"]
    ).with_near_text(
        {
            "concepts": [query],
            "certainty": 0.7  # 相似度阈值
        }
    ).with_limit(limit).do()
    
    return response.get("data", {}).get("Get", {}).get(class_name, [])

# 搜索示例
results = search_products(
    user_id="user1",
    query="智能手机",
    client=client_user1
)

for product in results:
    print(f"商品: {product['name']}, 价格: {product['price']}")
```

### 2. 混合搜索

```python
def hybrid_search(user_id, query, filters=None, client=None):
    """混合搜索（向量+关键词）"""
    class_name = f"Product_{user_id}"
    
    response = client.query.get(
        class_name,
        ["name", "price", "description", "category"]
    ).with_hybrid(
        query=query,
        properties=["name^2", "description"],  # 字段权重
        alpha=0.7  # 向量搜索权重
    )
    
    # 添加过滤条件
    if filters:
        response = response.with_where(filters)
    
    return response.with_limit(5).do()

# 带过滤条件的搜索
filters = {
    "path": ["price"],
    "operator": "GreaterThan",
    "valueNumber": 5000
}

results = hybrid_search(
    user_id="user1",
    query="手机",
    filters=filters,
    client=client_user1
)
```

## 📊 数据管理

### 1. 数据导出

```python
def export_user_products(user_id, client):
    """导出用户商品数据"""
    class_name = f"Product_{user_id}"
    
    # 分页获取所有数据
    results = []
    after = None
    
    while True:
        query = client.query.get(
            class_name,
            ["name", "price", "description", "category"]
        )
        
        if after:
            query = query.with_after(after)
        
        response = query.with_limit(100).do()
        products = response.get("data", {}).get("Get", {}).get(class_name, [])
        
        if not products:
            break
        
        results.extend(products)
        after = products[-1].get("_additional", {}).get("id")
    
    return results

# 导出示例
user1_products = export_user_products("user1", client_user1)
print(f"导出了 {len(user1_products)} 个商品")
```

### 2. 数据导入

```python
def import_products(user_id, products, client):
    """导入商品数据"""
    class_name = f"Product_{user_id}"
    
    with client.batch as batch:
        batch.batch_size = 50
        
        for product in products:
            product_id = product.get("id", str(uuid.uuid4()))
            batch.add_data_object(
                data_object=product,
                class_name=class_name,
                uuid=product_id
            )
    
    return True
```

## 🔧 高级配置

### 1. 向量索引配置

```python
def configure_vector_index(client):
    """配置向量索引"""
    # 注意：这需要在创建类之前配置
    client.schema.create_class({
        "class": "Product",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {
            "skip": False,
            "cleanupIntervalSeconds": 60,
            "maxConnections": 64,
            "efConstruction": 128,
            "ef": 64,
            "dynamicEfMin": 100,
            "dynamicEfMax": 500,
            "dynamicEfFactor": 8,
            "vectorCacheMaxObjects": 1000000,
            "flatSearchCutoff": 40000,
            "distance": "cosine"
        }
    })
```

### 2. 备份与恢复

```bash
# 创建备份
curl -X POST http://localhost:8080/v1/backups/my-backup \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer admin-key" \
  -d '{"include": ["Product_user1", "Product_user2"]}'

# 恢复备份
curl -X POST http://localhost:8080/v1/backups/my-backup/restore \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer admin-key"
```

## 🐛 常见问题

### Q: 权限验证失败？

```python
# 检查 API Key
print(f"API Key: {api_key}")

# 检查认证配置
response = requests.get(
    "http://localhost:8080/v1/meta",
    headers={"Authorization": f"Bearer {api_key}"}
)
print(f"状态码: {response.status_code}")
print(f"响应: {response.json()}")
```

### Q: 商品添加失败？

```python
# 检查 schema 是否存在
response = client.schema.get()
classes = response.get("classes", [])
class_names = [cls["class"] for cls in classes]
print(f"存在的类: {class_names}")

# 检查权限
try:
    client.data_object.create(
        data_object={"name": "Test"},
        class_name="Product_user1"
    )
except Exception as e:
    print(f"错误: {e}")
```

### Q: 搜索结果不准确？

```python
# 调整相似度阈值
response = client.query.get(
    "Product_user1",
    ["name", "price"]
).with_near_text(
    {
        "concepts": ["手机"],
        "certainty": 0.6  # 降低阈值
    }
).do()

# 检查向量索引状态
response = requests.get(
    "http://localhost:8080/v1/nodes",
    headers={"Authorization": f"Bearer {api_key}"}
)
print(f"节点状态: {response.json()}")
```

## 📚 相关资源

- **官方文档**: https://weaviate.io/developers/weaviate
- **GitHub**: https://github.com/weaviate/weaviate
- **Python 客户端**: https://weaviate.io/developers/weaviate/client-libraries/python
- **认证配置**: https://weaviate.io/developers/weaviate/configuration/authentication
- **多租户**: https://weaviate.io/developers/weaviate/configuration/multi-tenancy