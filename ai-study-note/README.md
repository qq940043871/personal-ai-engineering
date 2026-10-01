# AI 学习系统（ai-study-note）

从机器学习基础到大语言模型的课程站，并入大模型面试题库。本目录是 `personal-ai-engineering` 工作区的子项目之一。

- 入口：`index.html`
- 本地预览：运行 `start.bat`（端口 **3001**），或 `python -m http.server 3001`
- 题库：侧栏「面试题库」→ `courses/exam/index.html`
- 架构图：`exam/大模型平台.html`
- Markdown 查看：`md-viewer.html?file=<相对路径>`

## 目录结构

```text
ai-study-note/
├── index.html              # 站点入口
├── md-viewer.html          # Markdown 查看器（?file=exam/... 或 courses 相对路径）
├── start.bat               # 启动本地服务 :3001
├── courses/                # 课程页（ml / dl / llm / exam 总览 / roadmap）
├── exam/                   # 面试题库：专项 / 期数 / 综合 / 架构图 / scripts
├── documents/              # 文档资料
├── assets/                 # 图片等静态资源
├── css/
├── favicon.png
└── README.md
```

## 主题边界

- 本工程：**AI 课程 + 大模型面试题库**唯一正文来源
- `library/17年技术经验总结/09-技术知识库/pages/06_ai`（位于本仓库之外）：仅导读与链接桩页
