# Agent Harness 学习项目

&gt; 基于《从 0 开始构建 Agent Harness》课程的个人学习实践

## 项目背景

偶然看到《从 0 开始构建 Agent Harness》课程目录，被其完整的架构设计和循序渐进的课程内容吸引。决定以此为学习路线，亲手实践课程中讲解的每个技术点，记录自己的学习历程和思考。

## 学习目标

1. 深入理解 Agent Harness 的设计哲学
2. 亲手实现课程中的每个核心模块
3. 记录学习过程中的思考和遇到的问题
4. 最终构建一个完整可用的 Agent 运行时

---

## ✨ 项目特性

| 特性 | 说明 |
|------|------|
| **多 Provider 支持** | 支持 Claude、OpenAI、豆包、通义千问、DeepSeek 等 |
| **三种运行模式** | CLI 命令行、Web UI 浏览器、GUI 桌面应用 |
| **实时流式输出** | 支持 WebSocket 实时显示 Agent 执行过程 |
| **工具系统** | 内置文件操作、搜索、命令执行等工具，支持扩展 |
| **Session 管理** | 会话持久化、记忆系统、上下文压缩 |
| **可观测性** | Token 统计、成本追踪、执行路径追踪 |
| **中间件机制** | 支持工具调用拦截、审批流程 |

---

## 🚀 快速开始

### 安装

```bash
# 一键安装（Windows）
setup_env.bat

# 或手动安装
conda create -n agent-harness python=3.11 -y
conda activate agent-harness
pip install -r requirements.txt
```

### 配置

```bash
# 复制配置文件
cp config.yaml.example config.yaml

# 设置 API Key（任选其一）
export ANTHROPIC_API_KEY="your-key"    # Claude
export OPENAI_API_KEY="your-key"       # OpenAI
export DOUBAO_API_KEY="your-key"       # 豆包
```

### 运行

```bash
# CLI 模式
python main.py "帮我分析项目结构"

# Web UI 模式
python web.py
# 访问 http://localhost:8000

# GUI 模式
python gui.py
```

📖 **详细使用说明请查看 [USAGE.md](./USAGE.md)**

---

## 📚 原课程目录

| 序号 | 标题 | 核心内容 | 学习状态 |
|---|---|---|---|
| 01 | [架构演进：从 Framework 到 Harness](./chapter01/01_架构演进.md) | Framework 的困境，Harness 设计哲学，OpenClaw 架构总览 | ⏳ 待学习 |
| 02 | [核心心脏：手写 Agent 的 Main Loop](./chapter01/02_核心心脏.md) | ReAct 循环实现，终止条件设计，状态机模型 | ⏳ 待学习 |
| 03 | [慢思考与自省：剥离独立 Thinking 阶段](./chapter01/03_慢思考与自省.md) | 两阶段调用，Claude Extended Thinking，自适应慢思考 | ⏳ 待学习 |
| 04 | [大脑接入：抽象 Provider 接口](./chapter01/04_大脑接入.md) | Provider 抽象层，Claude/OpenAI 适配，Provider 工厂模式 | ⏳ 待学习 |
| 05 | [动作延伸：构建 Tool Registry 与分发机制](./chapter02/05_动作延伸.md) | 装饰器注册，Schema 自动推断，工具分组与插件化 | ⏳ 待学习 |
| 06 | [大道至简：最简工具集法则与 YOLO 哲学](./chapter02/06_大道至简.md) | 5 个核心工具，YOLO 执行哲学，工具设计七原则 | ⏳ 待学习 |
| 07 | [容错艺术：支持多级模糊匹配的 Edit 工具](./chapter02/07_容错艺术.md) | 精确/空白标准化/模糊匹配，边界案例处理 | ⏳ 待学习 |
| 08 | [并发提效：并行调用多个独立工具](./chapter02/08_并发提效.md) | asyncio.gather 并发，Semaphore 限流，超时控制 | ⏳ 待学习 |
| 09 | [飞书集成：接入飞书机器人的事件流](./chapter02/09_飞书集成.md) | Webhook 接收，消息回复，卡片消息，异步处理 | ⏳ 待学习 |
| 10 | [提示词组装：动态加载 AGENTS.md 与外挂 Skills](./chapter03/10_提示词组装.md) | PromptBuilder，AGENTS.md，Skills 插件化 | ⏳ 待学习 |
| 11 | [会话管理：Session 物理隔离与 Working Memory](./chapter03/11_会话管理.md) | Session 目录结构，JSONL 持久化，SessionManager | ⏳ 待学习 |
| 12 | [突破内存：基于阶梯降级的 Context Compaction](./chapter03/12_突破内存.md) | 轻/中/重三级压缩，LLM 摘要压缩，Token 估算 | ⏳ 待学习 |
| 13 | [记忆沉淀：持久化记忆与待办管理](./chapter03/13_记忆沉淀.md) | MEMORY.md 结构，MemoryManager，TodoManager | ⏳ 待学习 |
| 14 | [错误自愈：上下文感知的 Error Recovery](./chapter03/14_错误自愈.md) | 错误分类，恢复提示模板，ErrorRecoverySystem | ⏳ 待学习 |
| 15 | [行为干预：防止 Agent 陷入"死循环"的 System Reminders](./chapter04/15_行为干预.md) | 里程碑提醒，连续错误检测，重复调用预警 | ⏳ 待学习 |
| 16 | [防御纵深：Middleware 拦截与飞书人工审批](./chapter04/16_防御纵深.md) | 危险命令检测，MiddlewareChain，飞书审批卡片 | ⏳ 待学习 |
| 17 | [任务委派：Subagent 隔离复杂探索任务](./chapter04/17_任务委派.md) | Subagent 模式，上下文隔离，并发 Subagent | ⏳ 待学习 |
| 18 | [成本与状态追踪：Token 消耗与执行耗时](./chapter05/18_成本追踪.md) | 模型价格表，CostTracker，Provider 装饰器拦截 | ⏳ 待学习 |
| 19 | [洞察黑盒：Tracing 机制复盘失败决策路径](./chapter05/19_洞察黑盒.md) | TurnTrace，AgentTrace，Tracer，失败点定位 | ⏳ 待学习 |
| 20 | [科学度量：Benchmark 自动化评估脚本](./chapter05/20_科学度量.md) | BenchmarkTask，BenchmarkRunner，CI 集成 | ⏳ 待学习 |
| 21 | [实战（一）：完整 CLI 引擎与文件探索 Bug 修复](./chapter06/21_实战一.md) | 完整工程结构，模块拼装，实战演示 | ⏳ 待学习 |
| 22 | [实战（二）：飞书 AgentOps 小助手](./chapter06/22_实战二.md) | 日志分析工具，运维操作，飞书审批全流程 | ⏳ 待学习 |

---



## 🗂️ 工程目录结构

```
openclaw/                        # 参考实现根目录
├── harness/
│   ├── main_loop.py             # 第 02 节：Main Loop
│   ├── provider/                # 第 04 节：Provider 抽象
│   │   ├── base.py
│   │   ├── claude.py
│   │   └── openai_compat.py
│   ├── tools/                   # 第 05-08 节：工具系统
│   │   ├── registry.py
│   │   ├── executor.py
│   │   ├── edit.py
│   │   └── plugins/
│   ├── prompt/                  # 第 10 节：Prompt 构建
│   ├── session/                 # 第 11 节：Session 管理
│   ├── context/                 # 第 12 节：Context 压缩
│   ├── memory/                  # 第 13 节：记忆管理
│   ├── stability/               # 第 15 节：System Reminders
│   ├── middleware/              # 第 16 节：中间件
│   └── observability/           # 第 18-19 节：可观测性
├── integrations/
│   └── feishu/                  # 第 09/16 节：飞书集成
├── benchmark/                   # 第 20 节：Benchmark
├── main.py                      # 第 21 节：CLI 入口
├── AGENTS.md                    # Agent 行为规范
└── config.yaml                  # 配置文件
```

---

## 📖 核心概念速查

| 概念 | 定义 | 对应章节 |
|---|---|---|
| **Harness** | 最小化、可观测、可组合的 Agent 运行时 | 第一章 |
| **Main Loop** | 驱动 Think → Act → Observe 循环的引擎 | 02 |
| **Provider** | 抽象 LLM 接口的适配层 | 04 |
| **Tool Registry** | 工具的注册、查询、分发系统 | 05 |
| **YOLO 哲学** | 信任 LLM，减少不必要保护层 | 06 |
| **Context Compaction** | 上下文窗口压缩策略 | 12 |
| **System Reminders** | 关键时刻自动注入的行为干预提示 | 15 |
| **Middleware** | 工具调用前的拦截与处理层 | 16 |
| **Subagent** | 具有独立上下文的子 Agent 实例 | 17 |
| **Tracer** | 记录完整决策路径的可观测工具 | 19 |

---

## 📑 文档导航

| 文档 | 说明 |
|------|------|
| [USAGE.md](./USAGE.md) | 详细使用说明（安装、配置、三种运行模式） |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 架构设计文档 |
| [ARCHITECTURE_ANALYSIS.md](./ARCHITECTURE_ANALYSIS.md) | 架构优劣势分析 |
| [QUICKSTART.md](./QUICKSTART.md) | 快速开始指南 |
| [AGENTS.md](./AGENTS.md) | Agent 行为规范 |

---

## 📄 许可证

MIT License - 仅供学习交流使用。

---

*原课程作者：OpenClaw Team*  
*学习项目创建：2026-04-23*
