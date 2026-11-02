# AI 驱动构建的具体成果

> 本文档记录 Agent Harness 项目中使用 AI/Agent 驱动开发的具体成果

---

## 一、核心架构成果

### 1. Main Loop - Agent 核心引擎

**文件**: [harness/main_loop.py](file:///d:/ai_coder/p000_agent_harness/harness/main_loop.py)

**AI 驱动成果**:

| 组件 | 说明 |
|------|------|
| `LoopStatus` 状态机 | 5 种执行状态：RUNNING、COMPLETED、MAX_TURNS_REACHED、ERROR、STOPPED |
| `LoopStats` 统计器 | 实时追踪 turns、tokens、tool_calls、elapsed、error_count |
| `LoopResult` 结果封装 | 统一的执行结果格式，支持成功判断 |
| `TurnResult` 单轮结果 | 记录每轮的 response、tool_results、elapsed |
| 事件系统 | `on()`/`off()`/`_emit()` 支持事件驱动扩展 |
| 停止机制 | `_running` 状态控制，支持优雅中断 |

**设计亮点**:
```python
class MainLoop:
    async def run(self, user_message: str) -> LoopResult:
        for turn in range(self.max_turns):
            if not self._running:
                return LoopResult(status=LoopStatus.STOPPED, ...)
            
            response = await self.provider.complete(messages, tools)
            
            if not response.tool_calls:
                return LoopResult(status=LoopStatus.COMPLETED, ...)
            
            tool_results = await self._execute_tools(response.tool_calls)
```

---

### 2. Provider 抽象层 - LLM 统一接口

**文件**: [harness/provider/base.py](file:///d:/ai_coder/p000_agent_harness/harness/provider/base.py)

**AI 驱动成果**:

| 组件 | 说明 |
|------|------|
| `ToolCall` | 统一的工具调用请求格式 |
| `Usage` | Token 使用统计（input_tokens、output_tokens） |
| `LLMResponse` | 统一的 LLM 响应格式 |
| `BaseProvider` | 抽象基类，定义完整接口契约 |

**支持的 Provider**:

| Provider | 类型 | 模型 | 特性 |
|----------|------|------|------|
| Claude | claude | claude-opus-4-5 | Extended Thinking |
| OpenAI | openai | gpt-4o | 标准接口 |
| 豆包 | doubao | doubao-pro-32k | 国产模型 |
| 通义千问 | qwen | qwen-max | 国产模型 |
| DeepSeek | deepseek | deepseek-chat | 国产模型 |

---

### 3. Tool Registry - 工具注册与分发系统

**文件**: [harness/tools/registry.py](file:///d:/ai_coder/p000_agent_harness/harness/tools/registry.py)

**AI 驱动成果**:

| 功能 | 实现方式 |
|------|----------|
| 装饰器注册 | `@registry.tool(description="...")` |
| 动态注册 | `registry.register(ToolDefinition(...))` |
| Schema 自动推断 | `infer_schema(fn)` 从函数签名生成 JSON Schema |
| 并发执行 | `asyncio.gather()` 并行执行独立工具 |
| 分类管理 | `category` 参数支持工具分组 |

**工具注册示例**:
```python
@registry.tool(
    description="读取文件内容",
    category="filesystem",
)
async def read_file(path: str, start_line: int = 1) -> str:
    ...
```

---

## 二、工具系统成果

### 内置工具集

**文件**: [harness/tools/plugins/filesystem.py](file:///d:/ai_coder/p000_agent_harness/harness/tools/plugins/filesystem.py)

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `list_dir` | 列出目录内容 | `path` |
| `read_file` | 读取文件内容 | `path`, `start_line`, `max_lines` |
| `write_file` | 写入文件 | `path`, `content` |
| `edit_file` | 编辑文件（搜索替换） | `path`, `old_str`, `new_str` |
| `run_command` | 执行 Shell 命令 | `command`, `timeout` |
| `glob` | 文件模式匹配 | `pattern`, `path` |
| `grep` | 内容搜索 | `pattern`, `path`, `output_mode` |

**容错设计**:
- 精确匹配优先
- 空白标准化匹配
- 模糊匹配兜底
- 边界案例处理

---

## 三、可观测性成果

### 1. Context Compaction - 上下文压缩

**文件**: [harness/context_compactor.py](file:///d:/ai_coder/p000_agent_harness/harness/context_compactor.py)

**阶梯降级策略**:

```
优先级（高→低）:
1. SYSTEM     - System Prompt（永不压缩）
2. AGENTS     - AGENTS.md 规范文件
3. TOOL_DEFS  - 工具定义
4. RECENT     - 最近 N 轮对话
5. MIDDLE     - 中间消息（摘要压缩）
6. OLD        - 早期消息（丢弃或摘要）
```

**压缩级别**:
- `NONE` - 不压缩
- `TRUNCATE` - 直接截断
- `SUMMARY` - 生成摘要
- `MIXED` - 混合策略

---

### 2. Tracer - 链路追踪系统

**文件**: [harness/tracer.py](file:///d:/ai_coder/p000_agent_harness/harness/tracer.py)

**Span 类型**:

| 类型 | 说明 |
|------|------|
| `LLM_CALL` | LLM 调用 |
| `TOOL_CALL` | 工具调用 |
| `COMPACTION` | 上下文压缩 |
| `THOUGHT` | 思考过程 |
| `ACTION` | 行动 |
| `OBSERVATION` | 观察 |
| `RESPONSE` | 响应 |
| `ERROR` | 错误 |

**追踪能力**:
- 完整执行链路记录
- 失败决策路径复盘
- 性能分析（duration_ms）
- 可视化追踪（JSON 导出）

---

### 3. Cost Tracker - 成本追踪

**文件**: [harness/cost_tracker.py](file:///d:/ai_coder/p000_agent_harness/harness/cost_tracker.py)

**功能**:
- 实时 Token 统计
- 成本计算（按模型定价）
- 预算预警
- 历史记录

---

## 四、用户界面成果

### 1. Web UI（WebSocket 实时通信）

**文件**: [web.py](file:///d:/ai_coder/p000_agent_harness/web.py)

**AI 驱动成果**:

| 功能 | 实现 |
|------|------|
| WebSocket 连接管理 | `ConnectionManager` 类 |
| 任务取消 | `running_tasks` 字典 + `task.cancel()` |
| 实时流式输出 | 事件驱动推送 |
| 专家模式 | `experts.yaml` 配置 |
| 多工作空间 | `workspaces.json` 配置 |

**关键代码**:
```python
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.running_tasks: dict[str, asyncio.Task] = {}
    
    def cancel_task(self, session_id: str):
        if session_id in self.running_tasks:
            task = self.running_tasks.pop(session_id)
            if not task.done():
                task.cancel()
```

---

### 2. GUI（PyQt6 桌面应用）

**文件**: [gui.py](file:///d:/ai_coder/p000_agent_harness/gui.py)

**AI 驱动成果**:

| 组件 | 功能 |
|------|------|
| `AgentWorker` | 后台线程运行 Agent |
| 信号系统 | `finished`、`error`、`token_update`、`tool_called` |
| 停止机制 | `_running` 状态 + `main_loop.stop()` |
| Provider 切换 | 下拉选择框 |
| 状态栏 | Token、成本、轮次实时显示 |

---

### 3. CLI（命令行界面）

**文件**: [main.py](file:///d:/ai_coder/p000_agent_harness/main.py)

**AI 驱动成果**:

| 功能 | 参数 |
|------|------|
| 单次任务 | `python main.py "任务"` |
| 交互模式 | `python main.py` |
| 工作目录 | `-w, --workspace` |
| Provider 选择 | `--provider` |
| 详细日志 | `-v, --verbose` |

---

## 五、稳定性成果

### 1. System Reminders - 行为干预

**文件**: [harness/system_reminders.py](file:///d:/ai_coder/p000_agent_harness/harness/system_reminders.py)

**干预类型**:
- 里程碑提醒
- 连续错误检测
- 重复调用预警
- Token 预算警告

---

### 2. Middleware - 中间件拦截

**文件**: [harness/middleware.py](file:///d:/ai_coder/p000_agent_harness/harness/middleware.py)

**功能**:
- 危险命令检测
- 审批流程
- 请求拦截
- 日志记录

---

### 3. Error Recovery - 错误自愈

**功能**:
- 错误分类
- 恢复提示模板
- 自动重试
- 上下文感知

---

## 六、成果统计

| 类别 | 数量 | 说明 |
|------|------|------|
| **核心模块** | 12 | main_loop、provider、tools、session 等 |
| **工具数量** | 9+ | 文件操作、搜索、命令执行等 |
| **Provider 支持** | 5 | Claude、OpenAI、豆包、通义千问、DeepSeek |
| **运行模式** | 3 | CLI、Web UI、GUI |
| **代码文件** | 20+ | Python 模块 |
| **文档文件** | 8 | README、USAGE、ARCHITECTURE 等 |

---

## 七、技术亮点总结

### 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                      Main Loop                          │
│           (Think → Act → Observe 循环引擎)              │
└────────────────────┬────────────────────────────────────┘
                     │
    ┌────────────────┼────────────────┐
    │                │                │
    ▼                ▼                ▼
┌─────────┐    ┌─────────┐    ┌─────────┐
│Provider │    │ Tools   │    │ Session │
│ (LLM)   │    │Registry │    │Manager  │
└─────────┘    └─────────┘    └─────────┘
                     │
    ┌────────────────┼────────────────┐
    │                │                │
    ▼                ▼                ▼
┌─────────┐    ┌─────────┐    ┌─────────┐
│Tracer   │    │Middleware│   │Compactor│
│(追踪)   │    │(拦截)   │    │(压缩)   │
└─────────┘    └─────────┘    └─────────┘
```

### 设计原则

1. **最小化 Harness** - 只提供核心运行时能力
2. **可观测性** - 完整链路追踪和成本统计
3. **可组合性** - 模块化设计，插件化工具
4. **YOLO 哲学** - 信任 LLM，减少不必要保护层

---

*文档生成时间：2026-04-29*
