# 本地效果与 GitHub Pages 的关系

## 一句话结论

站点是纯静态的（HTML/CSS/JS + 相对路径），**不需要后端、不需要数据库，直接托管到 GitHub Pages 就能跑**。本地那个 `python -m http.server 3001` 只是开发预览用，线上完全不需要它。

## 唯一硬约束：所有链接必须是相对路径

Pages 项目站的地址是 `https://<user>.github.io/<repo>/`，站点根目录变成 `/<repo>/` 而不是 `/`。

所以：

- ✅ 用 `loadPage('courses/home.html')`、`<iframe src="courses/home.html">`、`href="md-viewer.html?file=..."`
- ❌ 不要出现 `href="/courses/home.html"`、`src="http://localhost:3001/..."`、`C:/...` 这类绝对路径

本仓当前的 `index.html` 全部是相对路径，可以直接上。

## 发布方式：Actions 只发这一个子目录

因为仓库是个 monorepo（8 个子项目平铺），不能用「Deploy from a branch」把整个仓库发出去——那样 `ai-agent-harness/` 的 Python 代码也会被当成静态资源暴露。也不能去 Settings 里配 `docs/`，因为站点不在那儿。

用的是 `.github/workflows/deploy-ai-study-note.yml`：

1. 触发：push 到 `main` 且改动落在 `ai-study-note/**`（或手动 `workflow_dispatch`）
2. build：把 `ai-study-note/` 整个复制到 `_site/`，补一个 `.nojekyll` 关掉 Jekyll
3. deploy：`upload-pages-artifact` + `deploy-pages` 推到 Pages

`ai-study-note/` 之外的东西一律不进产物体。

## 首次开启 Pages（必须手工一次）

仓库 → **Settings → Pages → Build and deployment → Source** 选 **GitHub Actions**。
选完再推代码，workflow 才会有发布目标；否则 `deploy-pages` 会报 `Get Pages site failed`。

> 你没有管理员权限时这一步做不了——需要仓库 owner 操作，或改用自定义 token + `peaceiris/actions-gh-pages`（权限更麻烦，不推荐）。

## 关于 `.nojekyll`

GitHub Pages 默认跑 Jekyll。Jekyll 会忽略以下划线开头的文件/目录（`_site`、`_next` 之类），也会对某些文件名报错。本项目目前没有下划线目录，但 `touch .nojekyll` 是一行保险，成本为零。

## 上线后的自查清单

- [ ] `https://<user>.github.io/<repo>/` 打开是首页，左侧导航可点
- [ ] 点「机器学习概述」等条目，iframe 里内容能加载（不是 404）
- [ ] 中文文件名（`exam/大模型平台.html`）能正常打开——Pages 对 UTF-8 路径支持没问题，但 URL 里会是 `%E5%A4%A7...`
- [ ] `md-viewer.html?file=<路径>` 能正确渲染
- [ ] `documents/` 下 PDF 能在线预览

## 迁到自定义域名（可选）

1. 在 `ai-study-note/` 下放 `CNAME` 文件，内容一行：`study.example.com`
2. 域名 DNS 加一条 `CNAME` 记录指向 `<user>.github.io`
3. Settings → Pages → Custom domain 填同一个域名，勾 Enforce HTTPS

注意：用了自定义域名后页面根路径变成 `/`，相对路径写法依然有效，无需改代码。

## 为什么不用其它方案

| 方案 | 结论 |
|---|---|
| 仓库根目录新建 index.html 去引用子目录 | 会打断 `courses/` 等相对路径，且 Pages 只会以那一个文件为根 |
| Deploy from a branch（main / root） | 整个 monorepo 上线，Python/Java 源码全暴露，且没有站点入口 |
| Deploy from a branch + `docs/` | 站点在 `ai-study-note/`，不在 `docs/`，得搬目录 |
| Vercel / Netlify | 可以，但要在控制台配 Root Directory = `ai-study-note`，与 GitHub 仓库双份配置，没必要 |
