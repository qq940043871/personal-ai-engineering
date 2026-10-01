# GPUStack 快速学习手册

## 📋 概述

GPUStack 是一个用于管理本地 GPU 资源的平台，支持多 GPU 调度和管理。

## 🏗️ 架构设计

```
┌─────────────────────────────────────────┐
│            GPUStack Platform            │
├─────────────────────────────────────────┤
│  Web UI  │  API Server  │  Scheduler    │
├─────────────────────────────────────────┤
│        GPU Resource Manager             │
├─────────────────────────────────────────┤
│   GPU 1    │   GPU 2    │   GPU N      │
└─────────────────────────────────────────┘
```

## 🚀 快速开始

### 1. 安装

```bash
# 使用 pip 安装
pip install gpustack

# 或者使用 Docker
docker pull gpustack/gpustack
```

### 2. 配置

创建配置文件 `config.yaml`:

```yaml
server:
  host: "0.0.0.0"
  port: 8000

gpus:
  - name: "gpu-0"
    type: "NVIDIA"
    memory: "16GB"
```

### 3. 启动服务

```bash
gpustack start --config config.yaml
```

## ⚙️ 核心功能

### GPU 管理

```python
from gpustack import GPUManager

# 初始化GPU管理器
gpu_manager = GPUManager()

# 获取可用GPU列表
available_gpus = gpu_manager.list_gpus()
print(f"可用GPU数量: {len(available_gpus)}")

# 获取特定GPU信息
gpu_info = gpu_manager.get_gpu(0)
print(f"GPU名称: {gpu_info.name}")
print(f"GPU内存: {gpu_info.memory}")
```

### 任务调度

```python
from gpustack import TaskScheduler

scheduler = TaskScheduler()

# 提交GPU任务
task_id = scheduler.submit_task(
    name="model_inference",
    gpu_required=True,
    memory_required="8GB",
    command="python inference.py"
)

# 查询任务状态
status = scheduler.get_task_status(task_id)
print(f"任务状态: {status}")
```

### 资源监控

```python
from gpustack import Monitor

monitor = Monitor()

# 获取实时GPU指标
metrics = monitor.get_gpu_metrics(gpu_id=0)
print(f"GPU使用率: {metrics.utilization}%")
print(f"显存使用: {metrics.memory_used}/{metrics.memory_total}")
```

## 💡 最佳实践

### 1. 多GPU负载均衡

```python
from gpustack import LoadBalancer

lb = LoadBalancer(strategy="round_robin")

# 注册多个GPU
lb.add_gpu(0)
lb.add_gpu(1)
lb.add_gpu(2)

# 获取下一个可用GPU
selected_gpu = lb.select_gpu()
```

### 2. 任务优先级

```python
scheduler.submit_task(
    name="high_priority_task",
    priority=10,
    gpu_required=True
)

scheduler.submit_task(
    name="low_priority_task",
    priority=1,
    gpu_required=False  # 可以使用CPU
)
```

### 3. 资源限制

```yaml
# config.yaml
limits:
  max_concurrent_tasks: 4
  max_memory_per_task: "8GB"
  timeout_seconds: 3600
```

## 🔧 API 参考

### 基础 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/gpus` | GET | 获取GPU列表 |
| `/api/gpus/{id}` | GET | 获取特定GPU信息 |
| `/api/tasks` | POST | 提交新任务 |
| `/api/tasks/{id}` | GET | 获取任务状态 |
| `/api/metrics` | GET | 获取监控指标 |

### 使用示例

```bash
# 获取GPU列表
curl http://localhost:8000/api/gpus

# 提交任务
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"name": "test", "command": "nvidia-smi"}'
```

## 📊 监控面板

访问 `http://localhost:8000` 查看 Web UI，可以实时看到：

- GPU 利用率图表
- 显存使用情况
- 任务队列状态
- 系统资源汇总

## 🐛 常见问题

### Q: GPU 未被识别？

```bash
# 检查 NVIDIA 驱动
nvidia-smi

# 确认 CUDA 版本
nvcc --version
```

### Q: 如何设置默认 GPU？

```yaml
# config.yaml
default_gpu: 0
```

### Q: 任务超时如何处理？

```python
scheduler.submit_task(
    name="long_task",
    timeout_seconds=7200,  # 2小时
    retry_on_failure=True
)
```

## 📚 相关资源

- 官方文档: https://gpustack.readthedocs.io
- GitHub: https://github.com/gpustack/gpustack
- 社区论坛: https://discuss.gpustack.io