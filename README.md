# personal-ai-engineering

个人 AI 工程学习工作区，聚合多个子项目：多智能体框架实践、AI 技术栈学习主工程、本地大模型实验、Dify/RAGFlow 知识库工具、自研 RAG 工程、AI 课程站与面试题库、AI 工作台门户、教程视频生成管线。

## 目录结构

```
personal-ai-engineering/
├── ai-agent-harness/ # 多智能体运行时框架（课程跟学实践）
├── ai-study-labs/    # AI 学习主工程（框架学习 / 项目 / 工具）
├── ai-study-note/    # AI 课程站 + 大模型面试题库（静态站点）
├── ai-rag-ollama/    # 本地 Ollama 对话与 RAG 实验
├── ai-rag-dify/      # Dify / RAGFlow 知识库上传工具与笔记
├── ai-rag-self-engineering/  # 自研 RAG 工程（ownrag：不依赖 Dify 的完整链路，设计文档 + 代码骨架）
├── ai-workbench/     # AI 工作台首页（触屏门户，单文件 HTML）
├── ai-tutorial-video/  # 教程视频生成管线（HTML 动画 → 抓帧 → ffmpeg MP4，含 TTS 旁白）
├── README.md
└── .gitignore
```

## 子项目简介

### [ai-agent-harness](ai-agent-harness/README.md)

基于《从 0 开始构建 Agent Harness》课程的个人学习实践，目标是亲手实现一个完整可用的 Agent 运行时。

- 多 Provider 支持：Claude、OpenAI、豆包、通义千问、DeepSeek 等
- 三种运行模式：CLI 命令行、Web UI（WebSocket 流式输出）、GUI 桌面应用
- 工具系统、Session 管理、上下文压缩、Token 成本统计、中间件审批机制

```bash
cd ai-agent-harness
pip install -r requirements.txt
cp config/config.yaml.example config/config.yaml   # 填入 API Key（config/config.yaml 不入库）
python main.py
```

### [ai-study-labs](ai-study-labs/README.md)

个人 AI 学习与实践主工程，顶层目录按用途编号分类：

| 目录 | 内容 |
|---|---|
| `10_docs/` | 学习手册、RAGFlow 部署记录、提示词集合 |
| `20_learn/` | 框架学习代码：PyTorch、Paddle、HuggingFace、ModelScope、LangChain、Dify、OCR 等 |
| `30_slides/` | 大模型基础 HTML 课件 |
| `40_projects/` | 成型项目：豆包/方舟图片视频生成、自媒体 Agent、PDF 合同比对、小游戏 |
| `50_tools/` | 独立小工具与运维脚本 |

### [ai-study-note](ai-study-note/README.md)

从机器学习基础到大语言模型的课程站，并入大模型面试题库（纯静态站点，160 个文件）。

- 课程页：ML / DL / LLM / 学习路线图（`courses/`）
- 面试题库：专项、期数、综合测试与架构图（`exam/`）
- 内置 Markdown 在线查看器（`md-viewer.html`）

```bash
cd ai-study-note
start.bat                        # 或 python -m http.server 3001
# 浏览器打开 http://localhost:3001
```

### [ai-rag-ollama](ai-rag-ollama/README.md)

本地 Ollama 实验：Flask 对话演示、检索增强生成（RAG）、搜索引擎集成，含分步教程（`study/`）。运行前提是本机已安装 Ollama 并拉取对应模型。

### [ai-rag-dify](ai-rag-dify/README.md)

Dify / RAGFlow 知识库操作工具与学习笔记（2026-10 自 `ai-study-labs/20_learn/dify/` 迁出独立）。

- `python/`：中文长文层级分段灌库脚本（`@!@`/`@@` 预埋切分标记 → 父/子分段），详见 [python/README.md](ai-rag-dify/python/README.md)
- `dify/`、`ragflow/`：Tkinter 上传器、PyInstaller 打包配置与 HTTP API 笔记
- `notes/`：Dify 工作流与知识库 API 学习笔记

> 上传工具内为硬编码 API 地址与 Key（已脱敏为占位符），运行前需自行填入。

### ai-rag-self-engineering

自研 RAG 工程（ownrag）：回答「**不用 Dify，智能层 + 业务层完全自研长什么样**」。2026-11-02 从 `personal-investment-notes/02-AI智能体/04-自研RAG工程/` 迁入并重命名。

- 设计文档 6 篇：总览口径 / 总体架构（Dify 能力对照）/ 低代码编排与中台机制 / 三条解析管道（MinerU · ffmpeg+ASR · Excel）/ 索引检索生成与两道闸门 / 评测运维与路线图
- 代码骨架 `ownrag/`：Python 3.10+ / FastAPI，14 步骤类型 · 3 管道 DSL · 混合检索 RRF · SSE 问答 · 评测脚本 · pytest 测试 33 例
- **口径**：个人实战工程，与 Agent Harness 同一条个人线，**不是公司平台技术栈**；全部指标 `【设计】`/`【待实测】`

```bash
cd ai-rag-self-engineering/ownrag
pip install -e .            # 最小化安装；全组件加 [pdf,excel,vector,asr]
python -m pytest            # 契约测试（执行器/闸门/切分），不依赖外部服务
```

> 跨库引用（Harness 六机制、MinerU 选型、直击库三层等）写 `../personal-investment-notes/...`。

### [ai-workbench](ai-workbench/index.html)

工作区门户首页：暗色炫酷风格的单文件 HTML 工作台，聚合六个子项目的导航、启动命令与常用链接收藏。

- 首页：问候 Hero、子项目统计、项目导航卡片（点击直达）
- 启动页：各子项目启动命令一键复制，入口链接可视化编辑
- 链接页：常用网址收藏（localStorage 本地存储，支持增删）

双击 `ai-workbench/index.html` 即可在浏览器打开，离线可用，无需任何依赖。

### [ai-tutorial-video](ai-tutorial-video/README.md)

AI 学习教程视频生成管线：「HTML 场景动画 → Playwright 逐帧抓帧 → ffmpeg 合成 MP4」，把课程站与课件内容变成连贯的学习视频。

- 剧本驱动：`storyboards/*.json` 分幕编排，9 种幕类型（标题/章节/要点/流程图/对比/代码/引言/总结/片尾）
- edge-tts 中文旁白，幕时长自动按旁白对齐；无网络自动降级无声字幕
- 确定性动画时间轴（逐帧可复现）、幕级缓存断点续跑、系列一键合并

```bash
cd ai-tutorial-video
pip install -r requirements.txt
python -m playwright install chromium
python src/build_video.py --storyboard storyboards/llm_base10.json   # → output/llm_base10.mp4
```

## 仓库约定

- **大文件不入库**：模型权重（`*.pth/.onnx` 等）、下载视频、运行数据（`db/`、`vector_db/`、`output/`）、打包产物（`build/`、`dist/`、`*.exe`）均被 `.gitignore` 排除。
- **密钥已脱敏**：代码中的真实 API Key 已替换为 `sk-REPLACE_WITH_YOUR_KEY`、`REPLACE_WITH_YOUR_TOKEN` 等占位符，本地运行前需自行填入。
- **路径注意**：部分学习脚本内含历史绝对路径，运行前请改为当前路径或相对路径（各子项目 README 中有说明）。
