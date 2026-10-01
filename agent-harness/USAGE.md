# Agent Harness 使用说明

本文档详细介绍 Agent Harness 的安装、配置和使用方法。

---

## 目录

1. [环境要求](#环境要求)
2. [安装步骤](#安装步骤)
3. [配置说明](#配置说明)
4. [运行模式](#运行模式)
   - [CLI 模式](#cli-模式命令行)
   - [Web UI 模式](#web-ui-模式浏览器)
   - [GUI 模式](#gui-模式桌面应用)
5. [工具系统](#工具系统)
6. [高级功能](#高级功能)
7. [常见问题](#常见问题)

---

## 环境要求

| 项目 | 要求 |
|------|------|
| **Python** | 3.10, 3.11, 3.12, 3.13 |
| **Conda** | Anaconda / Miniconda (推荐) |
| **操作系统** | Windows / macOS / Linux |

---

## 安装步骤

### 方式一：一键安装脚本（推荐）

**Windows:**
```bash
setup_env.bat
```

**Linux / macOS:**
```bash
chmod +x setup_env.sh
./setup_env.sh
```

### 方式二：手动安装

```bash
# 1. 创建虚拟环境
conda create -n agent-harness python=3.11 -y

# 2. 激活环境
conda activate agent-harness

# 3. 安装依赖
pip install -r requirements.txt
```

### 验证安装

```bash
python --version
python -c "import anthropic, openai, yaml; print('依赖检查通过')"
python main.py --help
```

---

## 配置说明

### 1. 配置 API Key

**方式 A：环境变量（推荐）**

Linux/macOS:
```bash
export ANTHROPIC_API_KEY="sk-ant-your-key"
export OPENAI_API_KEY="sk-your-key"
export DOUBAO_API_KEY="your-doubao-key"
export DASHSCOPE_API_KEY="your-qwen-key"
export DEEPSEEK_API_KEY="your-deepseek-key"
```

Windows PowerShell:
```powershell
$env:ANTHROPIC_API_KEY="sk-ant-your-key"
$env:OPENAI_API_KEY="sk-your-key"
```

Windows CMD:
```cmd
set ANTHROPIC_API_KEY=sk-ant-your-key
set OPENAI_API_KEY=sk-your-key
```

**方式 B：配置文件**

```bash
cp config.yaml.example config.yaml
```

编辑 `config.yaml`:
```yaml
default_provider: doubao

providers:
  doubao:
    type: doubao
    api_key: "your-api-key-here"  # 或使用 "${DOUBAO_API_KEY}"
    model: doubao-pro-32k

agent:
  max_turns: 50
  max_tokens_per_turn: 8192
```

### 2. 支持的 Provider

| Provider | 类型 | 模型示例 | 环境变量 |
|----------|------|----------|----------|
| Claude | claude | claude-opus-4-5 | `ANTHROPIC_API_KEY` |
| OpenAI | openai | gpt-4o | `OPENAI_API_KEY` |
| 豆包 | doubao | doubao-pro-32k | `DOUBAO_API_KEY` |
| 通义千问 | qwen | qwen-max | `DASHSCOPE_API_KEY` |
| DeepSeek | deepseek | deepseek-chat | `DEEPSEEK_API_KEY` |

---

## 运行模式

Agent Harness 提供三种运行模式，满足不同使用场景。

### CLI 模式（命令行）

**适用场景**：快速执行任务、脚本集成、CI/CD 流程

#### 基本用法

```bash
# 进入交互模式
python main.py

# 执行单次任务
python main.py "帮我分析当前目录的项目结构"

# 指定工作目录
python main.py -w /path/to/project "找出所有 TODO 注释"

# 使用特定 Provider
python main.py --provider openai "分析代码质量"

# 显示详细日志
python main.py -v "任务描述"
```

#### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `task` | 要执行的任务 | 无（交互模式） |
| `-w, --workspace` | 工作目录 | `.` |
| `--provider` | LLM Provider | 配置文件默认值 |
| `-c, --config` | 配置文件路径 | `config.yaml` |
| `-i, --interactive` | 强制交互模式 | `False` |
| `-v, --verbose` | 详细日志 | `False` |

#### 交互模式操作

```
>>> 你好，请帮我分析项目
[Agent 执行中...]

>>> 继续分析测试覆盖率
[Agent 执行中...]

>>> exit    # 退出
>>> quit    # 退出
```

---

### Web UI 模式（浏览器）

**适用场景**：可视化操作、实时监控、团队协作

#### 启动服务

```bash
python web.py
```

服务启动后访问：http://localhost:8000

#### 功能说明

| 功能 | 说明 |
|------|------|
| **任务输入** | 输入自然语言任务描述 |
| **实时输出** | 流式显示 Agent 思考和执行过程 |
| **工具调用** | 显示工具名称、参数和执行结果 |
| **Token 统计** | 实时显示 Token 消耗和成本 |
| **停止任务** | 可随时中断正在执行的任务 |
| **专家模式** | 切换不同专家角色 |

#### API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Web UI 主页 |
| `/ws` | WebSocket | 实时通信 |
| `/api/config` | GET | 获取配置信息 |
| `/api/experts` | GET | 获取专家列表 |
| `/api/workspaces` | GET | 获取工作空间列表 |

---

### GUI 模式（桌面应用）

**适用场景**：本地开发、离线使用、偏好桌面应用

#### 启动应用

```bash
python gui.py
```

#### 界面布局

```
┌─────────────────────────────────────────────────────────┐
│  菜单栏: 文件 | 编辑 | 视图 | 帮助                        │
├─────────────────────────────────────────────────────────┤
│  工具栏: [运行] [停止] [清空] │ Provider: [下拉选择]     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  输出区域（显示 Agent 执行过程）                          │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  输入区域: [输入任务...]                    [发送]       │
├─────────────────────────────────────────────────────────┤
│  状态栏: Token: 1234 | 成本: $0.05 | 轮次: 3/50         │
└─────────────────────────────────────────────────────────┘
```

#### 功能说明

| 功能 | 操作 |
|------|------|
| **执行任务** | 输入任务后点击"发送"或按 Enter |
| **停止任务** | 点击工具栏"停止"按钮 |
| **切换 Provider** | 工具栏下拉选择 |
| **打开工作目录** | 菜单 → 文件 → 打开工作目录 |
| **查看日志** | 菜单 → 视图 → 显示日志 |

---

## 工具系统

### 内置工具

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `read_file` | 读取文件内容 | `path`, `limit`, `offset` |
| `write_file` | 写入文件 | `path`, `content` |
| `edit_file` | 编辑文件（搜索替换） | `path`, `old_str`, `new_str` |
| `list_dir` | 列出目录内容 | `path` |
| `glob` | 文件模式匹配 | `pattern`, `path` |
| `grep` | 内容搜索 | `pattern`, `path`, `output_mode` |
| `run_command` | 执行命令 | `command`, `blocking` |
| `web_search` | 网络搜索 | `query` |
| `web_fetch` | 获取网页内容 | `url` |

### 工具使用示例

Agent 会自动选择合适的工具执行任务：

```
用户: 找出项目中所有的 TODO 注释

Agent 执行:
1. 使用 grep 工具搜索 "TODO"
2. 分析搜索结果
3. 整理并返回结果
```

---

## 高级功能

### Session 管理

每个会话独立存储在 `sessions/` 目录：

```
sessions/
├── session_20260423_143052/
│   ├── messages.jsonl      # 对话历史
│   ├── memory.md           # 会话记忆
│   └── trace.json          # 执行追踪
```

### 记忆系统

Agent 自动维护 `MEMORY.md` 文件，存储：
- 用户偏好
- 项目上下文
- 重要决策

### Context Compaction

当上下文超过 Token 限制时，自动压缩：
- 轻度压缩：移除冗余信息
- 中度压缩：生成摘要
- 重度压缩：LLM 摘要压缩

### 成本追踪

实时统计 Token 消耗和成本：

```python
# 配置模型价格
MODEL_PRICES = {
    "claude-opus-4-5": {"input": 0.015, "output": 0.075},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "doubao-pro-32k": {"input": 0.0008, "output": 0.002},
}
```

---

## 常见问题

### Q1: conda 命令找不到？

**A:** 确保正确安装了 Anaconda 或 Miniconda，并重启终端。

### Q2: pip 安装失败？

**A:** 尝试更新 pip：
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Q3: PyQt6 安装失败？

**A:** 
- Linux: `sudo apt-get install python3-pyqt6`
- macOS: `brew install pyqt`
- Windows: 使用 conda 安装 `conda install pyqt`

### Q4: API Key 无效？

**A:** 
1. 检查环境变量是否正确设置
2. 检查 config.yaml 中的 API Key 格式
3. 确认 API Key 未过期

### Q5: Web UI 无法访问？

**A:**
1. 检查防火墙设置
2. 确认 8000 端口未被占用
3. 尝试指定其他端口：`python web.py --port 8080`

### Q6: Agent 执行超时？

**A:** 调整配置：
```yaml
agent:
  max_turns: 100  # 增加最大轮次
  max_tokens_per_turn: 16384  # 增加 Token 限制
```

### Q7: 如何切换语言？

**A:** Agent 会根据系统语言自动选择，也可在 `AGENTS.md` 中指定。

---

## 进阶使用

### 自定义工具

```python
from harness.tools import ToolRegistry

registry = ToolRegistry()

@registry.register
def my_custom_tool(param: str) -> str:
    """工具描述"""
    return f"处理结果: {param}"
```

### 自定义 Provider

```python
from harness.provider.base import BaseProvider

class MyProvider(BaseProvider):
    async def chat(self, messages, tools=None):
        # 实现自定义逻辑
        pass
```

### 中间件

```python
from harness.middleware import MiddlewareChain

chain = MiddlewareChain()
chain.add(lambda x: print(f"调用工具: {x}"))
```

---

## 相关文档

- [README.md](./README.md) - 项目概述
- [ARCHITECTURE.md](./ARCHITECTURE.md) - 架构设计
- [QUICKSTART.md](./QUICKSTART.md) - 快速开始
- [AGENTS.md](./AGENTS.md) - Agent 行为规范

---

*最后更新：2026-04-29*
