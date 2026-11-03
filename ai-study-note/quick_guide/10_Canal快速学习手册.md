# Canal 快速学习手册

## 📋 概述

Canal 是阿里巴巴开源的数据库 Binlog 订阅工具，用于实时数据同步和变更捕获，是构建实时数据管道的核心组件。

**核心功能：**
- MySQL Binlog 实时订阅
- 数据变更实时捕获
- 高可靠性和可扩展性
- 多种消费模式支持

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────┐
│                    Canal 架构                         │
├─────────────────────────────────────────────────────┤
│  MySQL → Binlog → Canal Server → Canal Client → 目标系统  │
│                                                     │
│  1. MySQL 开启 Binlog                              │
│  2. Canal 模拟 slave 连接                          │
│  3. 解析 Binlog 事件                               │
│  4. 发送到客户端处理                               │
└─────────────────────────────────────────────────────┘
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 1. 开启 MySQL Binlog
# 修改 my.cnf
[mysqld]
log-bin=mysql-bin  # 开启 binlog
binlog-format=ROW  # 选择 ROW 模式
server_id=1        # 服务器 ID

# 2. 重启 MySQL
systemctl restart mysql

# 3. 创建 Canal 用户
mysql -u root -p
CREATE USER 'canal'@'%' IDENTIFIED BY 'canal';
GRANT SELECT, REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO 'canal'@'%';
FLUSH PRIVILEGES;
```

### 2. 安装 Canal

```bash
# 下载 Canal
wget https://github.com/alibaba/canal/releases/download/canal-1.1.7/canal.deployer-1.1.7.tar.gz

# 解压
mkdir /opt/canal
tar -zxvf canal.deployer-1.1.7.tar.gz -C /opt/canal

# 配置
cd /opt/canal/conf/example
vi instance.properties
```

### 3. 配置 Canal

```properties
# instance.properties 配置
canal.instance.master.address=127.0.0.1:3306
canal.instance.dbUsername=canal
canal.instance.dbPassword=canal
canal.instance.connectionCharset=UTF-8
canal.instance.tsdb.enable=true
canal.instance.gtidon=false

# 表过滤规则
canal.instance.filter.regex=.*\..*
canal.instance.filter.black.regex=mysql\.slave_.*
```

### 4. 启动 Canal

```bash
# 启动 Canal 服务
cd /opt/canal/bin
./startup.sh

# 查看日志
cd /opt/canal/logs/example
tail -f example.log
```

## 🔧 核心配置

### 1. 服务端配置

| 配置文件 | 路径 | 说明 |
|---------|------|------|
| canal.properties | conf/canal.properties | 全局配置 |
| instance.properties | conf/example/instance.properties | 实例配置 |

### 2. 全局配置

```properties
# conf/canal.properties
canal.id=1
canal.ip=127.0.0.1
canal.port=11111

# 解析线程数
canal.instance.parser.parallelThreadSize=16

# 内存限制
canal.instance.memory.buffer.size=16384
canal.instance.memory.buffer.memunit=KB

# 存储模式
canal.instance.mode=memory
# canal.instance.mode=persistence
```

### 3. 实例配置

```properties
# conf/example/instance.properties

# MySQL 连接信息
canal.instance.master.address=127.0.0.1:3306
canal.instance.dbUsername=canal
canal.instance.dbPassword=canal

# 起始位置
canal.instance.master.journal.name=
canal.instance.master.position=
canal.instance.master.timestamp=
canal.instance.gtid=

# 表过滤
canal.instance.filter.regex=test\..*
# 黑名单
canal.instance.filter.black.regex=test\.test_black
```

## 📡 客户端开发

### 1. Java 客户端

```java
import com.alibaba.otter.canal.client.CanalConnector;
import com.alibaba.otter.canal.client.CanalConnectors;
import com.alibaba.otter.canal.protocol.CanalEntry;
import com.alibaba.otter.canal.protocol.Message;

import java.net.InetSocketAddress;
import java.util.List;

public class CanalClient {
    public static void main(String[] args) {
        // 创建连接
        CanalConnector connector = CanalConnectors.newSingleConnector(
            new InetSocketAddress("127.0.0.1", 11111),
            "example", "", ""
        );
        
        try {
            // 连接
            connector.connect();
            // 订阅所有表
            connector.subscribe("\".*\\..*\"");
            // 回滚到上次位置
            connector.rollback();
            
            while (true) {
                // 获取消息
                Message message = connector.getWithoutAck(100);
                long batchId = message.getId();
                
                if (batchId == -1 || message.getEntries().isEmpty()) {
                    try {
                        Thread.sleep(1000);
                    } catch (InterruptedException e) {
                        e.printStackTrace();
                    }
                    continue;
                }
                
                // 处理消息
                handleEntries(message.getEntries());
                
                // 确认消息
                connector.ack(batchId);
            }
        } finally {
            connector.disconnect();
        }
    }
    
    private static void handleEntries(List<CanalEntry.Entry> entries) {
        for (CanalEntry.Entry entry : entries) {
            if (entry.getEntryType() == CanalEntry.EntryType.TRANSACTIONBEGIN || 
                entry.getEntryType() == CanalEntry.EntryType.TRANSACTIONEND) {
                continue;
            }
            
            CanalEntry.RowChange rowChange;
            try {
                rowChange = CanalEntry.RowChange.parseFrom(entry.getStoreValue());
            } catch (Exception e) {
                throw new RuntimeException("解析数据失败", e);
            }
            
            CanalEntry.EventType eventType = rowChange.getEventType();
            String tableName = entry.getHeader().getTableName();
            
            System.out.println("表名: " + tableName + ", 操作: " + eventType);
            
            for (CanalEntry.RowData rowData : rowChange.getRowDatasList()) {
                if (eventType == CanalEntry.EventType.DELETE) {
                    printColumns(rowData.getBeforeColumnsList());
                } else if (eventType == CanalEntry.EventType.INSERT) {
                    printColumns(rowData.getAfterColumnsList());
                } else {
                    System.out.println("更新前:");
                    printColumns(rowData.getBeforeColumnsList());
                    System.out.println("更新后:");
                    printColumns(rowData.getAfterColumnsList());
                }
            }
        }
    }
    
    private static void printColumns(List<CanalEntry.Column> columns) {
        for (CanalEntry.Column column : columns) {
            System.out.println(column.getName() + " : " + column.getValue() + 
                           " (更新: " + column.getUpdated() + ")");
        }
    }
}
```

### 2. Python 客户端

```python
from canal.client import Client
from canal.protocol import EntryProtocol_pb2

class CanalPythonClient:
    def __init__(self, host='127.0.0.1', port=11111, destination='example'):
        self.client = Client()
        self.client.connect(host=host, port=port)
        self.client.check_valid()
        self.client.subscribe(destination=destination, filter='.*\..*')
    
    def run(self):
        while True:
            message = self.client.get(100)
            entries = message['entries']
            
            for entry in entries:
                entry_type = entry.entryType
                
                if entry_type in [EntryProtocol_pb2.EntryType.TRANSACTIONBEGIN, 
                                 EntryProtocol_pb2.EntryType.TRANSACTIONEND]:
                    continue
                
                row_change = EntryProtocol_pb2.RowChange()
                row_change.ParseFromString(entry.storeValue)
                
                event_type = row_change.eventType
                table_name = entry.header.tableName
                
                print(f"表名: {table_name}, 操作: {event_type}")
                
                for row_data in row_change.rowDatas:
                    if event_type == EntryProtocol_pb2.EventType.DELETE:
                        self._print_columns(row_data.beforeColumns)
                    elif event_type == EntryProtocol_pb2.EventType.INSERT:
                        self._print_columns(row_data.afterColumns)
                    else:
                        print("更新前:")
                        self._print_columns(row_data.beforeColumns)
                        print("更新后:")
                        self._print_columns(row_data.afterColumns)
            
            self.client.ack(message['id'])
    
    def _print_columns(self, columns):
        for column in columns:
            print(f"{column.name} : {column.value} (更新: {column.updated})")
    
    def close(self):
        self.client.disconnect()

if __name__ == '__main__':
    client = CanalPythonClient()
    try:
        client.run()
    finally:
        client.close()
```

## 📊 数据同步场景

### 1. 实时数据同步

```java
public class DataSyncHandler {
    public void handleDataChange(CanalEntry.Entry entry) {
        CanalEntry.RowChange rowChange = parseRowChange(entry);
        String tableName = entry.getHeader().getTableName();
        
        // 根据表名路由到不同的处理逻辑
        switch (tableName) {
            case "user":
                handleUserTable(rowChange);
                break;
            case "order":
                handleOrderTable(rowChange);
                break;
            default:
                break;
        }
    }
    
    private void handleUserTable(CanalEntry.RowChange rowChange) {
        for (CanalEntry.RowData rowData : rowChange.getRowDatasList()) {
            if (rowChange.getEventType() == CanalEntry.EventType.INSERT) {
                // 处理插入
                insertUser(rowData.getAfterColumnsList());
            } else if (rowChange.getEventType() == CanalEntry.EventType.UPDATE) {
                // 处理更新
                updateUser(rowData.getAfterColumnsList());
            } else if (rowChange.getEventType() == CanalEntry.EventType.DELETE) {
                // 处理删除
                deleteUser(rowData.getBeforeColumnsList());
            }
        }
    }
    
    private void insertUser(List<CanalEntry.Column> columns) {
        // 构建用户对象并插入目标系统
        Map<String, String> userMap = new HashMap<>();
        for (CanalEntry.Column column : columns) {
            userMap.put(column.getName(), column.getValue());
        }
        // 插入到目标系统
        userService.insert(userMap);
    }
}
```

### 2. 数据清洗和转换

```java
public class DataTransformer {
    public Map<String, Object> transformUser(Map<String, String> rawData) {
        Map<String, Object> transformed = new HashMap<>();
        
        // 字段映射
        transformed.put("userId", rawData.get("id"));
        transformed.put("userName", rawData.get("name"));
        transformed.put("email", rawData.get("email"));
        
        // 数据清洗
        String phone = rawData.get("phone");
        if (phone != null) {
            transformed.put("phone", phone.replaceAll("\\s+", ""));
        }
        
        // 时间转换
        String createTime = rawData.get("create_time");
        if (createTime != null) {
            transformed.put("createTime", parseDateTime(createTime));
        }
        
        return transformed;
    }
}
```

## 🔍 监控与管理

### 1. 监控指标

| 指标 | 说明 | 查看命令 |
|------|------|---------|
| 解析延迟 | Binlog 解析延迟 | `curl http://localhost:8080/metrics` |
| 消费延迟 | 客户端消费延迟 | `curl http://localhost:8080/metrics` |
| 队列大小 | 内存队列大小 | `curl http://localhost:8080/metrics` |

### 2. 管理 API

```bash
# 获取实例状态
curl http://localhost:8080/api/v1/instance/example/status

# 获取统计信息
curl http://localhost:8080/api/v1/instance/example/stats

# 手动触发切换
curl -X POST http://localhost:8080/api/v1/instance/example/switch

# 重置位置
curl -X POST http://localhost:8080/api/v1/instance/example/reset
```

### 3. 日志管理

```bash
# 服务端日志
/opt/canal/logs/canal/canal.log

# 实例日志
/opt/canal/logs/example/example.log

# 查看错误
grep -i error /opt/canal/logs/example/example.log

# 查看同步位置
grep -i position /opt/canal/logs/example/example.log
```

## 🛠️ 高级功能

### 1. 集群部署

```properties
# conf/canal.properties
canal.zkServers=127.0.0.1:2181
canal.instance.global.spring.xml=classpath:spring/default-instance.xml
canal.instance.global.lazy=true
```

### 2. 高可用配置

```properties
# conf/example/instance.properties
canal.instance.master.address=192.168.1.100:3306
canal.instance.master.journal.name=
canal.instance.master.position=

# 备库配置
canal.instance.standby.address=192.168.1.101:3306
canal.instance.standby.journal.name=
canal.instance.standby.position=
```

### 3. 过滤规则

| 规则类型 | 示例 | 说明 |
|---------|------|------|
| 白名单 | `test\.user,test\.order` | 只同步指定表 |
| 黑名单 | `mysql\.slave_.*` | 排除指定表 |
| 正则表达式 | `test\..*` | 匹配所有 test 库的表 |

### 4. 性能优化

| 优化项 | 配置 | 建议值 |
|--------|------|--------|
| 解析线程 | `canal.instance.parser.parallelThreadSize` | 16 |
| 内存缓冲区 | `canal.instance.memory.buffer.size` | 16384 |
| 批处理大小 | `canal.instance.transaction.size` | 1024 |
| 客户端批量 | `connector.getWithoutAck(100)` | 100-500 |

## 🐛 常见问题

### Q: Binlog 解析失败？

```bash
# 检查 MySQL Binlog 配置
mysql> show variables like 'binlog_format';
# 确保为 ROW 模式

# 检查 Canal 用户权限
mysql> show grants for 'canal'@'%';
# 确保有 REPLICATION SLAVE 权限

# 查看 Canal 日志
tail -f /opt/canal/logs/example/example.log
```

### Q: 消费延迟高？

```java
// 1. 增加批量处理大小
Message message = connector.getWithoutAck(500);  // 增加批量大小

// 2. 并行处理
ExecutorService executor = Executors.newFixedThreadPool(10);
for (CanalEntry.Entry entry : message.getEntries()) {
    executor.submit(() -> handleEntry(entry));
}

// 3. 优化处理逻辑
// 减少处理时间，使用异步处理
```

### Q: 连接断开？

```properties
# 增加心跳检测
canal.client.idleTimeout=60
canal.client.soTimeout=60

# 重连机制
public void reconnect() {
    while (true) {
        try {
            connector.connect();
            connector.subscribe("\".*\\..*\"");
            break;
        } catch (Exception e) {
            logger.error("重连失败", e);
            try {
                Thread.sleep(5000);
            } catch (InterruptedException ie) {
                break;
            }
        }
    }
}
```

## 📚 相关资源

- **官方文档**: https://github.com/alibaba/canal/wiki
- **GitHub**: https://github.com/alibaba/canal
- **客户端 SDK**: https://github.com/alibaba/canal/tree/master/client
- **示例代码**: https://github.com/alibaba/canal/tree/master/example
- **常见问题**: https://github.com/alibaba/canal/wiki/FAQ