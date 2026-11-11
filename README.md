# personal-ai-engineering

个人 AI 工程学习工作区，聚合多个子项目：多智能体框架实践、AI 技术栈学习主工程、本地大模型实验、Dify/RAGFlow 知识库工具、自研 RAG 工程、AI 课程站与面试题库、独立小工具集合、教程视频生成管线。

## 目录结构

```
personal-ai-engineering/
├── ai-agent-harness/ # 多智能体运行时框架（课程跟学实践）
├── ai-study-labs/    # AI 学习主工程（框架学习代码 / 提示词）
├── ai-study-note/    # AI 课程站 + 大模型面试题库（静态站点）
├── ai-rag-ollama/    # 本地 Ollama 对话与 RAG 实验
├── ai-rag-dify/      # Dify / RAGFlow 知识库上传工具与笔记
├── ai-rag-self-engineering/  # 自研 RAG 工程（ownrag：不依赖 Dify 的完整链路，设计文档 + 代码骨架）
├── ai-tools/         # 独立小工具集合（2026-11 由 ai-study-labs/50_tools 迁入并扩充）
├── ai-tutorial-video/  # 教程视频生成管线（HTML 动画 → 抓帧 → ffmpeg MP4，含 TTS 旁白）
├── README.md
├── CODEBUDDY.md
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
| `10_prompts/` | 提示词集合（SQL 提示词等） |
| `20_learn/` | 框架学习代码：PyTorch、Paddle、HuggingFace、ModelScope、LangChain、OCR 等 |

> 原 `50_tools/` 及其中的工具项目已于 2026-11 整体迁出为顶层 [ai-tools](ai-tools/)，见下文。

### [ai-study-note](ai-study-note/README.md)

从机器学习基础到大语言模型的课程站，并入大模型面试题库（纯静态站点，无构建步骤）。

- 课程页：ML / DL / LLM / 学习路线图（`courses/`）
- 课件：大模型基础 1.0 / 2.0 分页幻灯片（`slides/`，由 `ai-study-labs/30_slides` 迁入）
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

- `01-minerU-block/`：中文长文层级分段灌库脚本（`@!@`/`@@` 预埋切分标记 → 父/子分段），详见 [01-minerU-block/README.md](ai-rag-dify/01-minerU-block/README.md)
- `03-dify-uploader/`、`04-ragflow-uploader/`：Tkinter 上传器、PyInstaller 打包配置与 HTTP API 笔记
- `notes/`：Dify 工作流与知识库 API 学习笔记

> 上传工具内为硬编码 API 地址与 Key（已脱敏为占位符），运行前需自行填入。

### ai-rag-self-engineering

自研 RAG 工程（ownrag）：回答「**不用 Dify，智能层 + 业务层完全自研长什么样**」。2026-11-02 从 `personal-investment-notes/02-AI智能体/04-自研RAG工程/` 迁入并重命名。

- 设计文档 7 篇：总览口径 / 总体架构（Dify 能力对照）/ 低代码编排与中台机制 / 三条解析管道（MinerU · ffmpeg+ASR · Excel）/ 索引检索生成与两道闸门 / 评测运维与路线图 / **全链路梳理与视频 RAG 对照（06，含可验证性清单）**
- 代码骨架 `ownrag/`：Python 3.10+ / FastAPI，15 步骤类型 · 3 管道 DSL · 混合检索 RRF · SSE 问答 · 评测集与评测脚本 · pytest 测试 56 例（全离线）
- **口径**：个人实战工程，与 Agent Harness 同一条个人线，**不是公司平台技术栈**；全部指标 `【设计】`/`【待实测】`

```bash
cd ai-rag-self-engineering/ownrag
pip install -e .            # 最小化安装；全组件加 [pdf,excel,vector,asr]
python -m pytest            # 契约测试（执行器/闸门/切分），不依赖外部服务
```

> 跨库引用（Harness 六机制、MinerU 选型、直击库三层等）写 `../personal-investment-notes/...`。

### ai-tools

独立小工具与实验项目的集合：2026-11 由 `ai-study-labs/50_tools/` 整体迁入，并陆续加入了几个新的独立项目。没有统一入口，各脚本在各自目录内单独运行。

- 下载与数据处理：`01_dydown/`（抖音）、`02_bibidown/`（B 站）、`03_import_wset/`（WSET 导入）、`04_currency_list/`
- 编号通用脚本 `10_*`–`43_*`：mock 数据、地图可视化、目录扫描、批量重命名、MD5、Gitee 批量操作等
- 独立项目：`doubao/`（方舟图片/视频、PDF 合同比对）、`time_task/`、`opengauss/`、`disk_cleaner/`、`doubao_multi_login/`、`meeting_minutes/`、`personal-wechat-jobs/`、`opencode-go-proxy/`
- `meeting_minutes/`、`personal-wechat-jobs/` 各自带 `requirements.txt` / `setup.py`；目录内有 12 个独立 `test_*.py` 脚本

> 运行产物不入库：下载视频（`video/`）、`*.db`、会议录音 `*.wav`、`jvm_diag_*/` 诊断快照，以及含登录态 cookie 的 `dy-*.yaml`（仅保留 `dy-config.example.yaml` 脱敏模板）。部分脚本含历史绝对路径，运行前需改。

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
- **`ai-tools/` 凭证与产物不入库**：`dy-*.yaml`（cookie）、`*.db`、会议录音 `*.wav`、`jvm_diag_*/`、`cookie_*.txt` 与代理配置条目；仅 `dy-config.example.yaml` 脱敏模板入库。
- **密钥已脱敏**：代码中的真实 API Key 已替换为 `sk-REPLACE_WITH_YOUR_KEY`、`REPLACE_WITH_YOUR_TOKEN` 等占位符，本地运行前需自行填入。
- **路径注意**：部分学习脚本内含历史绝对路径，运行前请改为当前路径或相对路径（各子项目 README 中有说明）。
