# AI 学习系统（ai-study-note）

机器学习基础到大语言模型的课程站。本目录是 `personal-ai-engineering` 工作区的子项目之一。

- 入口：`index.html`
- 本地预览：运行 `start.bat`（端口 **3001**），或 `python -m http.server 3001`
- Markdown 查看：`md-viewer.html?file=<相对路径>`（当前主要服务于 courses 内部页面）

## 目录结构

```text
ai-study-note/
├── index.html              # 站点入口
├── md-viewer.html          # Markdown 查看器（?file=courses 相对路径）
├── start.bat               # 启动本地服务 :3001
├── courses/                # 课程页（ml / dl / llm / roadmap；exam 总览页的题库正文已迁出）
├── slides/                 # HTML 课件：llm_base10 / llm_base20（index.html 轮播 + slide/ 分页）
├── exam/                   # 仅存 scripts/push_to_tdoc.py（腾讯文档推送工具）；题库正文已于 2026-11-15 迁出
├── documents/              # 文档资料（Attention Is All You Need、Function Calling MCP 两份 PDF）
├── assets/                 # 图片等静态资源
├── css/
├── favicon.png
└── README.md
```

## 主题边界（2026-11-15 更新）

- 本工程：**AI 课程站（courses / slides）**唯一正文来源
- 大模型面试题库与快速学习手册：正文已迁至 `D:\ai_person\personal-knowledge-hub\library\技术\飞书·人工智能\` 的 `10-面试题库/`、`11-快速学习手册/`，本仓不再保有题库正文
- `courses/exam/index.html` 的题库入口，以及 `md-viewer.html`、课程页中对 `exam/`、`quick_guide/` 的历史相对链接随迁移失效，待后续改造成指向知识库的导读页

## 迁移记录（2026-11-15）

`exam/`（期数系列 63 篇 + 专项复习 9 篇 + 综合复习 11 篇 + `大模型平台.html`）与 `quick_guide/`（11 篇）整体迁入知识库 `library/技术/飞书·人工智能/` 的新模块 `10-面试题库/`、`11-快速学习手册/`。正文零改动、目录名保留；`exam/scripts/push_to_tdoc.py` 属工具，留在本仓。
