# ai-rag-dify

Dify / RAGFlow 知识库操作工具与学习笔记。2026-10 自 `ai-study-labs/20_learn/dify/` 迁出独立成顶层工程（原路径不再维护）。

核心场景：把中文 Markdown 长文档按自定义分隔符切成「父分段 + 子分段」的层级结构灌入 Dify 知识库，精确控制 RAG 检索切块粒度（Dify 内置自动切分对中文长文控制力弱，故自写脚本，用 `@!@`、`@@` 预埋切分标记）。

## 目录结构

```text
ai-rag-dify/
├── python/    # Dify 知识库 API 脚本：切分标记预埋 → 补标题切片 → 层级分段灌库
├── dify/      # Dify Tkinter 上传器（dify_uploader.py）+ PyInstaller 打包配置
├── ragflow/   # RAGFlow HTTP API 笔记（httpapi.md）+ 打包配置
└── notes/     # Dify 工作流 / 知识库 API 学习笔记与样例文档
```

## 使用

- `python/` 的完整思路、文件清单与调用链见 [python/README.md](python/README.md)
- 打包：各目录内 `pipinstaller.bat` 一键打包（产物 `*.exe` 已被 .gitignore 排除）

## 注意

- **上传工具内为硬编码 API 地址与 Key（已脱敏为占位符），运行前需自行填入**
- 脚本面向本机 Dify 实例编写，接口版本变化时需对照 `ragflow/httpapi.md`、`notes/dify_api.md` 校准
