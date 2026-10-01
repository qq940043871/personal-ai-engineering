# personal-ai-engineering

个人 AI 工程学习工作区，聚合三个子项目：多智能体框架实践、AI 技术栈学习主工程、本地大模型实验。

## 目录结构

```
personal-ai-engineering/
├── agent-harness/   # 多智能体运行时框架（课程跟学实践）
├── ai_study_py/     # AI 学习主工程（框架学习 / 项目 / 工具）
├── ollama-lab/      # 本地 Ollama 对话与 RAG 实验
└── .gitignore
```

## 子项目简介

### [agent-harness](agent-harness/README.md)

基于《从 0 开始构建 Agent Harness》课程的个人学习实践，目标是亲手实现一个完整可用的 Agent 运行时。

- 多 Provider 支持：Claude、OpenAI、豆包、通义千问、DeepSeek 等
- 三种运行模式：CLI 命令行、Web UI（WebSocket 流式输出）、GUI 桌面应用
- 工具系统、Session 管理、上下文压缩、Token 成本统计、中间件审批机制

```bash
cd agent-harness
pip install -r requirements.txt
cp config.yaml.example config.yaml   # 填入 API Key（config.yaml 不入库）
python main.py
```

### [ai_study_py](ai_study_py/README.md)

个人 AI 学习与实践主工程，顶层目录按用途编号分类：

| 目录 | 内容 |
|---|---|
| `10_docs/` | 学习手册、RAGFlow 部署记录、提示词集合 |
| `20_learn/` | 框架学习代码：PyTorch、Paddle、HuggingFace、ModelScope、LangChain、Dify、OCR 等 |
| `30_slides/` | 大模型基础 HTML 课件 |
| `40_projects/` | 成型项目：豆包/方舟图片视频生成、自媒体 Agent、PDF 合同比对、小游戏 |
| `50_tools/` | 独立小工具与运维脚本 |

### [ollama-lab](ollama-lab/README.md)

本地 Ollama 实验：Flask 对话演示、检索增强生成（RAG）、搜索引擎集成，含分步教程（`study/`）。运行前提是本机已安装 Ollama 并拉取对应模型。

## 仓库约定

- **大文件不入库**：模型权重（`*.pth/.onnx` 等）、下载视频、运行数据（`db/`、`vector_db/`、`output/`）、打包产物（`build/`、`dist/`、`*.exe`）均被 `.gitignore` 排除。
- **密钥已脱敏**：代码中的真实 API Key 已替换为 `sk-REPLACE_WITH_YOUR_KEY`、`REPLACE_WITH_YOUR_TOKEN` 等占位符，本地运行前需自行填入。
- **路径注意**：部分学习脚本内含历史绝对路径，运行前请改为当前路径或相对路径（各子项目 README 中有说明）。
