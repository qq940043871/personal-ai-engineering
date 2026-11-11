# wechat-jobs · 微信公众号招聘信息监听流水线

自动监听公众号（默认「郑州发布」）的更新，筛出招聘类文章，抽取结构化岗位信息，
生成每日招聘日报（Markdown + 单文件 HTML）。

> 本仓库自带离线演示数据，**不装任何采集服务也能直接跑通全流程**。

---

## 一、先说清楚：微信公众号为什么难监听

微信没有开放「读取任意公众号文章」的接口。想自动化，只有下面这几条路，
网上大量 2023 年的教程今天已经全部失效，先避坑：

| 方案 | 现状（2026） | 结论 |
|---|---|---|
| 微信公众平台官方接口 | 只能读**自己名下**的号 | ❌ 读不了别人的号 |
| 搜狗微信 `weixin.sogou.com` | 反爬比微信还狠，返回临时链接几小时失效 | ❌ 已废弃 |
| RSSHub 的 wechat 路由 | 公共实例常年 404，多路由失效 | ❌ 基本全灭 |
| `wechat2rss.xlab.app` 免费版 | 正常可用，但**只收录 485+ 个技术/安全/财经号** | ⚠️ 覆盖不到政务号 |
| `wechat2rss` 私有部署 | ¥150/年，可订任意公众号 | ✅ 可用（花钱） |
| `wewe-rss` 自建 | **已于 2026-03 归档停更** | ❌ 停更 |
| **`we-mp-rss` 自建** | Python 3.13 重写，2026-08 仍活跃维护，**Docker 可选**（原生支持纯 Python + SQLite） | ✅ **推荐** |
| **直连微信读书接口** | 本仓库内置（`src/weread.py`），零 Docker 零服务 | ✅ **最轻** |
| PC 微信 Hook / 逆向 | 能全自动，但违反客户端协议 | ❌ 封号 + 法律灰区 |

**关键前提**：本项目**不直接碰微信接口**。它消费的是上游采集服务产出的标准 RSS。
反爬对抗、登录态维持、限频，全由采集服务负责 —— 这样既稳定，也不会因为你的
自动化脚本给账号带来额外风险。

---

## 二、整体架构

```
┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  采集层      │   │  过滤层       │   │  抽取层       │   │  存储层       │   │  输出层       │
│             │   │              │   │              │   │              │   │              │
│ we-mp-rss   │──▶│ 关键词命中    │──▶│ rule 正则     │──▶│ SQLite       │──▶│ Markdown     │
│ 或 wechat2rss│   │ 标题优先      │   │ 或 LLM       │   │ 指纹去重      │   │ HTML 日报     │
│   ↓         │   │ 排除词兜底    │   │ 失败自动回退   │   │              │   │              │
│ 标准 RSS     │   │              │   │              │   │              │   │ 邮件/推送     │
└─────────────┘   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
   src/fetch.py      src/filters.py     src/extract.py      src/store.py      src/report.py
```

设计要点（都是踩过坑才这么写的）：

1. **先粗筛再抽取**。政务号一天推 6~8 条（天气/限行/消费券/招聘混在一起），
   全量丢给大模型既费钱又被噪声污染。先用免费的关键词把候选压到 1~2 条。
2. **报名截止日期不做全文兜底**。公告里同时有报名、笔试、面试三个日期，
   全文扫描极易把笔试日期当成报名截止 —— **给错的截止日期比不给更坑人**。
3. **必须去重**。采集服务按时间窗重复推送，今天 30 条、明天还是这 30 条里的 29 条。
   靠 `单位+岗位+链接` 的指纹去重，否则日报第三天就没人看了。
4. **LLM 抽取失败自动回退 rule**。大模型超时/返回脏数据时，流水线绝不能空手而归。

---

## 三、快速开始（离线演示）

```bash
cd wechat-jobs
pip install -r requirements.txt

# 只看过滤 + 抽取结果，不落库不出报告
python -m src.pipeline --dry-run

# 跑全流程，生成 out/jobs_YYYY-MM-DD.md 和 .html
python -m src.pipeline

# 再跑一次 —— 会看到「新增 0 条，跳过重复 6 条」，去重生效
python -m src.pipeline
```

演示数据在 `mock/zzfabu.sample.xml`，仿「郑州发布」结构，含 6 篇招聘文 + 3 篇干扰文
（天气 / 限行 / 口袋公园），用来验证过滤层能不能把干扰项剔掉。

---

## 四、接入真实公众号（三步）

### 第 1 步：选采集路线

> **不需要 Docker。** we-mp-rss 官方就支持纯 Python 手动部署；
> 如果你只盯一两个公众号，连采集服务都可以不要，直接调微信读书接口（方案 0）。

**方案 0 —— 直连微信读书接口（最轻：零 Docker、零第三方服务）**

we-mp-rss 的本质就是「浏览器登录微信读书 → 调 weread 接口 → 转成 RSS」。
只盯一两个号的话，为它跑一整套 FastAPI + Vue 毫无必要，本仓库已内置这一层：

```bash
# 1) 用浏览器（Chrome/Edge）打开 https://weread.qq.com 扫码登录
# 2) 在微信读书里搜索并「关注」你的目标公众号
# 3) 拿到 bookId —— 三种写法都认，最省事的是直接粘阅读页链接：
python -m src.weread parse "https://weread.qq.com/web/mp/reader/edd420e224d505f..."
#    → bookId = MP_WXS_3925849039
# 4) 写进 config.yaml
```

> ### ⚠️ 选号比选技术重要一百倍（血泪教训）
>
> 本项目实测踩过一个大坑：**同一个品牌下，主号和垂直子号的内容可能完全不同。**
>
> | 公众号 | bookId | 实际内容 |
> |---|---|---|
> | 郑州本地宝（主号） | `MP_WXS_3222425727` | 办事指南：公积金、社保、消费券、人才公寓 |
> | 本地宝郑州招聘（子号） | `MP_WXS_3925849039` | **纯招聘**，日更多条 |
>
> 拿主号的 bookId 去抓招聘，结果就是：**549 篇历史文章，标题 0 命中，正文 60 篇采样只有 1 篇沾边。**
> 你会以为是代码坏了，其实只是**走错了门**。
>
> **验证方法（30 秒，务必先做）**：
>
> ```bash
> python -m src.weread list "MP_WXS_xxxxxxxxxxx" --limit 20
> ```
>
> 先看返回的 `mp_name` 是不是你要的号，再看标题里有没有你要的内容。
> 名字不对、内容不对，**先把号换对，再谈其他**。
>
> **怎么找子号的 bookId？**
> 微信公众号文章的阅读原文链接、或微信读书 App 里搜索子号名字，
> 打开它的阅读页，把地址栏链接粘出来用 `parse` 解析即可。

> **bookId 怎么读出来的？** 微信读书的阅读页地址形如
> `https://weread.qq.com/web/mp/reader/647423d2<编码串>`，
> 其中 `647423d2` 是固定前缀，后面的编码串是 bookId 按 ASCII 逐字节转的十六进制。
> 本项目的 `parse_book_id()` 会自动还原，所以上面三种写法你随便粘哪种都行。
> 详细速查见下方「附录」。

```yaml
source:
  type: weread                      # 或 rss_url: "weread://MP_WXS_xxxxxxxx"
  weread:
    book_id: "MP_WXS_3925849039"    # 也可以直接粘阅读页链接
    cookie_from: browser            # 自动从浏览器读 cookie
    browser: chrome                 # 读不到会自动依次试 edge / brave / firefox
```

cookie 拿不到时（`browser-cookie3` 在 Windows 上偶发要求管理员权限），
改手动：F12 → Network → 任选 weread 请求 → 复制 Cookie 请求头 →

```yaml
    cookie_from: manual
    cookie: "wr_vid=...; wr_skey=...; wr_rt=..."
```

> ### ⚠️ Windows 上读 cookie 的坑（实测踩过）
>
> **症状**：明明浏览器登录了 weread.qq.com，脚本却报「读取 cookie 失败」。
>
> **真实原因**：**跟登录状态无关**。Edge/Chrome 新版给 cookie 数据库加了
> **独占锁 + App-Bound Encryption**，第三方进程直接读文件会被拒。
> 实测 `CreateFileW` 返回 `GetLastError=32`（共享冲突），
> `browser_cookie3` 会把它翻译成含糊的「requires admin」。
>
> **别再折腾直接读文件了，走下面两条路：**
>
> **① CDP 方式（推荐，不用关浏览器）**
>
> ```bash
> python tools/cookie_via_cdp.py --browser edge
> ```
>
> 它会用独立 profile 启动一个带调试端口的 Edge，页面里登录后自动取出 cookie，
> 并存到 `out/cookie.txt`。若你已有开调试端口的浏览器，加 `--attach` 直接连。
>
> **② 手动复制（30 秒）**
>
> 浏览器打开 `weread.qq.com` → **F12** → **Network** → **F5 刷新** →
> 点第一个请求 → **Request Headers** 里找 `Cookie:` →
> 复制**整行值** → 填进 `config.yaml`：
>
> ```yaml
>     cookie_from: manual
>     cookie: "wr_vid=...; wr_skey=...; wr_rt=...; wr_pf=0"
> ```
>
> 手动 cookie 会过期（通常几天到几周），过期后重来一次即可。
> 脚本会明确报「cookie 过期」，不会静默出错。

**方案 A —— 自建 we-mp-rss（Docker 版，功能最全）**

```bash
docker run -d --name we-mp-rss -p 4000:4000 \
  -v $(pwd)/data:/app/data \
  ghcr.io/rachelos/we-mp-rss:latest
```

然后浏览器打开 `http://localhost:4000`：

1. **账号管理 → 添加读书账号** → 微信扫码登录
   ⚠️ **绝对不要勾选「24 小时后自动退出」**，勾了账号一天就失效，得重新扫。
2. **公众号源 → 添加** → 在微信里打开「郑州发布」任意一篇文章 →
   右上角 `···` → 复制链接 → 粘贴提交。
   ⚠️ **添加频率别太快**，触发封控要等 24 小时解封。
3. 回到源列表，点 RSS 按钮拿到订阅地址，形如：
   `http://你的IP:4000/feeds/MP_WXS_xxxxxxxx.rss`

> 建议用一个**专用微信读书小号**做登录态，别用主号。
> 全文模式（`?mode=fulltext`）响应慢且占内存，本流水线已有自己的正文兜底，通常用不上。

**方案 B —— we-mp-rss 手动部署（纯 Python，不用 Docker）**

官方支持直接跑，默认数据库就是 SQLite 文件，**不需要 Docker，也不需要 MySQL**：

```bash
git clone https://github.com/rachelos/we-mp-rss.git
cd we-mp-rss
pip install -r requirements.txt
cp config.example.yaml config.yaml      # 默认 db 是 sqlite:///data/db.db，不用改

# 只跑后端就够；前端 web_ui 只有首次扫码授权时才需要
uvicorn web:app --host 127.0.0.1 --port 8001
# 一次性带初始化也行：python main.py -job True -init True
```

需要授权时临时起前端：`cd web_ui && npm install && npm run dev`，
打开 `http://localhost:8001` 扫码；**配完就能把前端关掉，长期只留后端常驻**。

⚠️ 两个坑：
  1. 默认账号 `admin / admin@123`，但**部分机器上初始化会读 Windows 用户名**，
     实际登录名变成一串数字 —— 去 `config.yaml` 里看 `USERNAME` 就知道了。
  2. Windows 下建议建用户态 venv（`python -m venv venv`），别污染全局 Python。

**方案 C —— wechat2rss 私有部署（花钱省心，也不用 Docker）**

`https://wechat2rss.xlab.app` 自助购买（¥150/年），直接拿到专属订阅地址，
反爬对抗由作者扛，你这边只需要一个 URL。

### 第 2 步：改配置

编辑 `config.yaml`：

```yaml
# 路线 0：直连微信读书（零服务）
source:
  type: weread
  weread:
    book_id: "MP_WXS_xxxxxxxx"
    cookie_from: browser

# 路线 A/B/C：消费 RSS
source:
  type: rss
  rss_url: "http://127.0.0.1:8001/feeds/MP_WXS_xxxxxxxx.rss"
  account_name: "郑州发布"
```

### 第 3 步：跑一次验证

```bash
python -m src.weread probe MP_WXS_xxxxxxxx   # 路线 0 先单独验登录态
python -m src.pipeline --limit 20            # 全流程
```

---

## 五、开启 LLM 抽取（可选，质量更高）

`rule` 模式免费、离线、可解释，但遇到排版混乱、一篇文章含多个单位的公告会力不从心。
换成 `llm` 模式后，模型会把一篇文拆成多条岗位记录，字段也更完整：

```yaml
extract:
  mode: llm
  llm:
    base_url: "https://api.deepseek.com/v1"   # 任意 OpenAI 兼容端点
    api_key: "sk-xxxxxxxx"
    model: "deepseek-chat"
```

兼容 DeepSeek / 通义千问 / 智谱 GLM / 本地 vLLM 等所有 OpenAI 格式端点。
模型调用失败会自动回退 rule，不会中断流水线。

---

## 六、定时任务

**WorkBuddy 自动化**：直接把「每天 8:00 运行本流水线并把 HTML 日报发到邮箱」配成一条定时任务，
不用自己写调度。

**Windows 计划任务**：

```powershell
schtasks /create /tn "WXJobsDaily" /tr "python -m src.pipeline" /sc daily /st 08:00
```

（注意工作目录需设为项目根，否则读不到 `config.yaml`）

**Linux cron**：

```cron
0 8 * * * cd /path/to/wechat-jobs && /usr/bin/python3 -m src.pipeline >> logs/run.log 2>&1
```

---

## 七、抽取字段与已知局限

抽出字段：招聘单位、岗位类别、人数、学历、专业、年龄、工作地点、
报名起止、报名方式、考试安排、薪酬待遇、联系方式、原文链接。

**rule 模式的已知局限（不是 bug，是正则的边界）：**

- **年龄是区间汇总**。公告写「本科 30 以下、硕士 35 以下、博士 40 以下」，
  会汇成「30—40 周岁」，不区分学历。看岗位表原文更准。
- **学历是全文去重汇总**。公告里有一句放宽条件就会被算进去（如「部分岗位放宽至大专」）。
- **一篇文章 = 一条记录**。像「地铁集团招 12 类岗位」只会产出一条汇总记录，
  不会拆成 12 条。要拆细请开 `llm` 模式。
- **人数取最大值**。文章里出现多个数字时取最大的「X 人」，可能与实际不符。

**所有字段都应当以官方公告原文为准，本工具只做线索聚合。**

---

## 八、合规与风险提示

- 本项目仅消费**你自己授权登录后**产生的 RSS，不破解、不绕过任何微信技术措施。
- 采集频率请保持克制，别给被订阅方和采集服务制造压力。
- 全文内容可能被 RSS 阅读器缓存，请仅用于**个人阅读**，不要二次分发。
- 不要把抓取到的招聘信息用于商业转售。
- 政务公告的最终解释权在发布单位，**报名前务必核对原文**。

---

## 目录结构

```
wechat-jobs/
├── config.yaml               # 主配置（唯一需要改的文件）
├── requirements.txt
├── run.bat                   # 一键启动（Windows 双击即可）
├── run.sh                    # 一键启动（Git Bash / Linux / macOS）
├── mock/zzfabu.sample.xml     # 离线演示数据
├── src/
│   ├── config.py             # 配置加载
│   ├── fetch.py              # 采集：RSS 拉取 + 正文兜底 + 源类型路由
│   ├── weread.py             # 采集：直连微信读书接口（免 Docker 路线）
│   ├── filters.py            # 过滤：关键词命中判定
│   ├── extract.py            # 抽取：rule / llm 双模式
│   ├── store.py              # 存储：SQLite 指纹去重
│   ├── report.py             # 输出：Markdown / HTML 日报
│   ├── mailer.py             # 投递：SMTP / Agent Mail
│   └── pipeline.py           # 编排入口
├── data/jobs.db              # 去重库（自动生成）
└── out/jobs_YYYY-MM-DD.*     # 日报（自动生成）
```

---

## 九、一键启动

**Windows**：双击 `run.bat` —— 自动找 Python、缺依赖自动装、跑完自动打开日报。

**Git Bash / Linux / macOS**：

```bash
./run.sh
```

**常用参数**：

```bash
python -m src.pipeline --dry-run     # 只过滤+抽取，不落库不发信
python -m src.pipeline --no-mail     # 跑全流程但不发邮件
python -m src.pipeline --limit 20    # 只处理最近 20 篇
```

---

## 十、邮件投递

配置在 `config.yaml` 的 `output.mail`，两种后端：

### 后端 1：Agent Mail（WorkBuddy 内置邮箱）

```yaml
  mail:
    enabled: true
    backend: agentmail
    to: ["815841365@qq.com"]
    agentmail_from: "dqhw7794@agent.qq.com"
```

发件地址 `dqhw7794@agent.qq.com`，每日 50 封配额，单附件上限 20MB。

⚠️ **这个后端只在 WorkBuddy 会话里能真正发出**：它没有对外 SMTP 凭据，
流水线跑完只会输出一份「待发送清单」，由 Agent 调用邮件工具完成投递。
裸跑 CLI 时它**不会**假装发送成功 —— 宁可不发，也不骗你说发了。

### 后端 2：SMTP（通用，裸跑 CLI 用这个）

```yaml
  mail:
    enabled: true
    backend: smtp
    to: ["815841365@qq.com"]
    smtp_host: "smtp.qq.com"
    smtp_port: 465
    smtp_user: "你的邮箱@qq.com"
    smtp_password: "授权码"        # ← 不是登录密码！
```

QQ 邮箱授权码：设置 → 账号 → POP3/IMAP/SMTP → 开启服务 → 生成授权码。
163、企业邮、自建邮同理，改 `smtp_host` / `smtp_port` 即可。

---

## 十一、定时任务

已配置 WorkBuddy 自动化「郑州发布招聘日报（每日 8:00）」，
每天 08:00 自动执行「跑流水线 → 上传当日日报 → 发信到 815841365@qq.com」。

想自己用系统调度也行：

**Windows 计划任务**

```powershell
schtasks /create /tn "WXJobsDaily" /tr "C:\Users\qq940\anaconda3\python.exe -m src.pipeline" /sc daily /st 08:00
```

⚠️ 需把「起始于」设为项目根目录，否则读不到 `config.yaml`。

**Linux cron**

```cron
0 8 * * * cd /path/to/wechat-jobs && /usr/bin/python3 -m src.pipeline >> logs/run.log 2>&1
```

---

## 附录：bookId 编码速查

微信读书的公众号阅读页地址：

```
https://weread.qq.com/web/mp/reader/647423d224d505f5758535f33323232343235373237d5e
                                   └──────┬──────┘└──────────┬─────────────┘└┬┘
                                      固定前缀          bookId 的 hex       补位
```

拆解（ASCII → 十六进制）：

| 编码片段 | 解码 | 含义 |
|---|---|---|
| `647423d2` | — | 固定前缀，每次都一样 |
| `4d 50 5f 57 58 53 5f` | `MP_WXS_` | bookId 明文前缀 |
| `33 32 32 32 34 32 35 37 32 37` | `3222425727` | 数字部分 |
| `d5e` | — | 补齐用，无意义 |

**结论：`MP_WXS_3222425727`**

自己动手解码（确认一下我没算错）：

```python
import re
uid = "647423d224d505f5758535f33323232343235373237d5e"
body = uid[uid.find("4d505f5758535f"):]
body = body[:len(body) // 2 * 2]
out = ""
for i in range(0, len(body), 2):
    ch = chr(int(body[i:i+2], 16))
    if not (ch.isascii() and (ch.isdigit() or "A" <= ch <= "Z" or ch == "_")):
        break
    out += ch
print(out)   # MP_WXS_3222425727
```

> ⚠️ 判断字符时必须用 **ASCII 白名单**，别用 `str.isalnum()` —— 它会对 `Õ`
> 这类拉丁字母返回 `True`，导致把末尾补位字节一起吃进去。


---

## 附录二：真实数据实测记录（2026-10-06）

配置：`type: weread` + `bookId: MP_WXS_3925849039`（本地宝郑州招聘）+ 手动 cookie。

```
[1/5] 采集  ← 微信读书接口 ← MP_WXS_3925849039
      目标公众号：本地宝郑州招聘
      共取到 60 篇文章
[2/5] 过滤  ← 关键词命中判定
      候选 58 篇
[3/5] 抽取  ← 模式 rule
[4/5] 去重入库
      新增 58 条，跳过重复 0 条
[5/5] 生成日报
      → out/jobs_2026-10-06.md / .html
```

58 条里包含：中国地震局 188 人（截止 2026-10-26）、黄河科技学院附属医院 35 人、
郑州比亚迪 10000 人、新郑市公益性岗位 12 人、兴业银行校招、中国电建华中院、蜜雪冰城等。

### 接口速查（微信读书，2026-10 实测有效）

| 用途 | 路径 | 关键点 |
|---|---|---|
| 文章列表 | `/web/mp/articles` | 参数 `bookId`/`offset`/`count`；结构 `reviews[].subReviews[].review.mpInfo` |
| 文章正文 | `/web/mp/content` | 参数 `reviewId`（**必须是完整 `MP_WXS_xxx_token`**）；**返回 HTML 而非 JSON** |
| 已订阅书架 | `/web/shelf/bookIds` | `data[].bookId`；`MP_WXS_` 开头的即公众号 |
| 取 cookie | CDP `Network.getCookies` | 见 `tools/cookie_via_cdp.py`；握手需 `suppress_origin=True` |

> **最容易踩的坑**：`/web/mp/content` 返回的是**整个阅读页 HTML（约 4MB，`text/plain`）**。
> 如果复用那个「自动 `r.json()`」的通用请求方法，会直接抛「返回非 JSON」——
> 看起来像接口挂了，其实是**调用方拿 JSON 解析器去啃 HTML**。
> 正文在 `<div id="js_content">` 里，需单独处理。

### 抽取层的两个高频误判（已修）

1. **单位名**：本地宝标题排版特殊（`【郑州医院招聘】六险一金！黄河科技学院附属医院招聘！`）。
   最终方案是**优先按机构后缀词抓实体**（集团/公司/医院/学校/局/院/所/中心/银行/交易所…），
   在「招聘」二字之前那段里找，而不是按「招聘」切分。
2. **公众号运营噪声**：`小编工资蹭蹭涨1毛`（求赞文案）会被当成薪酬待遇，
   `回复【地铁】获取郑州地铁招聘信息`（菜单引导语）会被当成报名方式。
   已加 `_is_noise()` 统一过滤。

---

## 附录三：邮件投递改版（2026-10-07）

需求变更：**只发当日新增岗位，正文直接是完整 HTML，不带附件。**

| 项 | 旧 | 新 |
|---|---|---|
| 邮件正文 | 15 条摘要（纯文本） | **完整 HTML 日报**（当日新增的全部条目） |
| 附件 | HTML + Markdown 两个附件 | 无（`output.mail.attach: false`） |
| 内容范围 | 库里最近 200 条（会重复推老岗位） | **仅本次新增** |
| 投递通路 | 会话内工具调用 + 人工确认 | `agently-cli` 命令行，全自动 |

关键实现：

- `store.upsert()` 现在返回 `(新增数, 重复数, 新增岗位列表)`，第三项供邮件使用；
- `report.render_email_html()` 生成邮件专用 HTML：内联样式、不用 CSS 变量与 flex，
  兼容 QQ 邮箱与手机端（`render_html()` 仍是落盘存档用的独立日报页）；
- `mailer.send_agentcli()` 支持 `body_format="html"`，正文经 `--body-file` 传入，
  避开 Windows 命令行约 8K 的长度上限。

### agently-cli 的两个致命坑（都踩过）

1. **node 版本升级会清掉 npm 全局包。**
   CLI 安装在 `binaries/node/versions/<版本>/node_modules` 下，版本目录一换，
   `agently-cli` 连带消失（症状：`FileNotFoundError: node.exe`，因为旧路径也没了）。
   处理：在新版本目录下重新 `npm install -g @tencent-qqmail/agently-cli`，然后重新授权。
   `mailer._discover_cli()` 已改为按目录名倒序 glob 自动找最新版本，但"包被删了"它救不了。

2. **不要手动执行 `agently-cli auth refresh`。**
   官方在 stderr 里明确写着：token 会在下次 API 调用时自动刷新，
   `DO NOT run auth login or auth refresh`。
   手动 refresh 会打乱 refresh token 的轮换，直接把凭证搞废（`invalid_grant`），
   之后只能重新走 OAuth 授权。掉了就直接重新 `auth login`，别试图抢救。

---

## 附录四：投递通路二度改版 —— 放弃 CLI，改走 MCP（2026-10-07）

### 为什么放弃 agently-cli

用户在浏览器完成 OAuth 授权后，页面显示：

> 登录失败 —— Workbuddy已存在智能体邮箱，无需再绑定

根因：MCP `GetMe` 返回的别名 **`q815841365@agent.qq.com`** 与 CLI 想绑的是同一个邮箱。
服务端认为该账号已有智能体邮箱，**直接拒绝设备绑定**。由此：

- `agently-cli auth login` 每次都在 **约 25 秒**内退出（实测 23s / 24s），只输出 `ERROR: login failed`；
- access token 寿命仅 **1 小时**（granted_at → expires_at 相差 1h），refresh 一旦失效即 `invalid_grant`，
  只能重新绑定 —— 而绑定又被拒。**这是个死循环。**

附带坑：`auth login` 的输出**不能用 `> file 2> file` 重定向**，重定向后日志文件根本不落地。

### 新通路：MCP 邮件工具

```
流水线 (backend: agentmail)
  → 把「当日新增」渲染成完整 HTML，落盘 out/mail_body_<日期>.html
  → Agent 读取该文件
  → mcp__agent-mail__SendMessage（body_format=HTML, skip_confirmation=true）
  → 815841365@qq.com
```

| 项 | 值 |
|---|---|
| 发件别名 | `q815841365@agent.qq.com` |
| 日配额 | 50 封 |
| 附件 | 不需要（正文即完整内容） |

### 两个实现要点

1. **正文体积**。MCP 的 `body` 是字符串参数，要由 Agent 逐字搬运。
   早期「每字段一个 div 带完整样式」的写法，58 条会到 **80KB**，既慢又容易在搬运途中出错。
   改成「一个岗位一个带分隔线的块，字段用 ｜ 串成一行 + `<style>` 里的 class」后，
   58 条约 **22.6KB**。单次调用仍建议不超过 ~12000 字符，条数多时分批发送。
2. **单引号规避转义**。生成 HTML 时把属性引号统一写成单引号，
   搬运时无需 JSON 转义，出错概率大幅下降（HTML 标准对两种引号等价）。

---

## 附录五：内容口径改为「最近一周」+ 指纹解耦（2026-10-07）

### 需求

> 只发送最近一周的招聘信息，不要发送所有的。

此后正文范围从「本次新增」改为「**最近 N 天发布的岗位**」。

### 改动一览

| 项 | 旧 | 新 |
|---|---|---|
| 邮件范围 | 本次新增（增量） | **最近 `window_days` 天发布的岗位**（默认 7，含今天） |
| 口径字段 | — | 公众号 `published` 优先；缺失时退 `first_seen` |
| 配置 | — | `output.mail.window_days: 7`（`1` = 回到只发今天） |
| 邮件标题 | `…（58 条）` | `…（近7天 10 条）` |
| 本地存档 | 全量历史 | **不变，仍是全量** （只有邮件按窗口裁剪） |

- 新增 `store.query_recent(conn, days)`：`cutoff = 今天 - (days-1)`，
  用 `COALESCE(NULLIF(published,''), substr(first_seen,1,10))` 兜住发布日期缺失的行。
- 这是**滚动窗口**：一条岗位 7 天内每天都会出现，方便漏看某天时补上。
  想改成「只发一次」需要另加"已发送"标记，当前不做。

### 为什么同一个岗位在邮件里出现了两遍

改完抽取逻辑后重跑，邮件里 `1&2`、`3&4`、`6&7`、`9&10` 全是同一篇文章的两份。
根因是**指纹把抽取结果算了进去**：

```python
# 旧（错）
raw = f"{self.unit}|{self.category}|{self.url or self.article_title}"
```

把单位名从 `郑州节后` 修正成空之后，指纹跟着变，同一篇文章被判为新文章重新入库。
**去重指纹必须与抽取质量解耦**，现在只看文章身份：

```python
# 新（对）
ident = self.url or f"{self.article_title}|{self.published}"
raw = f"{ident}#{self.seq}"     # seq 供 llm 模式一篇拆多条时用
```

配套：`store.upsert()` 命中重复时 **UPDATE 刷新抽取字段**（`first_seen` 不动）。
否则修好的抽取规则对库里的历史行永远不生效——每次跑都只是"跳过重复"。
指纹算法一改，旧库所有行都对不上，需要**备份后删库重建**（`data/jobs.db` → 重跑一次）。

### 抽取层三处收尾（此前遗留）

1. **单位名吞钩子/活动名**。`初中学历可报名！河南凯邦普工` 曾整段当单位名；
   `郑州节后招聘会来了！` 切出假单位 `郑州节后`。
   → ① 钩子词表补 `学历|可报名|应届|经验|不限|年龄`；
     ② 钩子正则末尾加 `(?=.)`，避免结尾的 `！` 把整条标题剥空后回退成"整条标题当单位名"；
     ③ 新增 `_UNIT_BAD` 黑名单（`节前/节后/期间/多家/两家/招聘会/好单位…`），
        命中就返回空——**宁可显示"未识别单位"，也不编一个错的单位名**。
2. **薪酬字段是标题复读**。`薪酬：郑州西门子、赛诺菲招聘，福利待遇好！`
   → `_salary(text, title)` 用 `_norm_key()`（只留汉字/字母/数字）比对，
     剔掉与标题等价的句子。标题已在卡片第一行显示过，不该在薪酬里再来一遍。
3. **联系方式混入小编邮箱**。每篇文末都挂 `wanglinlin@bendibao.com`。
   → `extract.contact_email_deny`（默认 `["bendibao.com"]`）按域名子串剔除运营方邮箱。

---

## 附录六：「查看原文」打不开 —— token 里的 `~` 必须还原成 `_`（2026-10-07）

用户反馈：**邮件里点「查看原文」打不开。**

### 排查过程

先用请求探了一遍邮件里 6 个链接，行为分成两拨：

| token | HTTP | 返回体积 | 结果 |
|---|---|---|---|
| `YPwyXlhBsvEKFTy7eNfNrw` | 200 | 3,793,408 | 正常文章 |
| `sR1t5~EWOZANzk3oLfz1Zg` | 200 | **31,613** | **参数错误** |

含 `~` 的三条一律只有 31KB，页面正文就是一行「**参数错误**」。
关键点：**HTTP 状态码仍然是 200** —— 这是个静默失败，不抓页面根本发现不了。

排除掉的几个猜想（都实测过，全是死路）：

- ✗ 百分号编码问题：`%7E`、`quote(safe='')`、原样 —— 三者返回**完全一样**；
- ✗ `~` 是占位填充符：换成 `-` / 去掉，依旧「参数错误」；
- ✗ 链接本身过期：随机垃圾串 `AAAAAAAAAAAAAAAAAAAAAA` 也是同一个 31KB 页，
  说明「参数错误」是"token 不合法"的通用回应。

### 根因

试出来的：**`~` → `_` 就正常打开。**

```python
token = token.replace("~", "_")     # 就这一行
# sR1t5~EWOZANzk3oLfz1Zg  → 参数错误（31,613 字节）
# sR1t5_EWOZANzk3oLfz1Zg  → 正常文章（3,879,394 字节）
```

原因是微信短链 token 用 **Base64 URL-safe** 编码，字符集 `A-Za-z0-9-_`，**不含 `~`**。
而 `_` 恰好是微信读书 reviewId 自己的前缀分隔符（`MP_WXS_xxx_token`），
直接放会歧义，所以它在 reviewId 里把 `_` 转义成了 `~`。
**从 reviewId 反推直链时必须还原这层转义。**

全量验证：60/60 条链接在还原后全部正常打开（此前含 `~` 的 21 条全挂）。

### 防复发

- 修复在 `weread.review_to_url()`，函数注释里写明了原理与实测数据。
- 新增 `tools/check_mail_links.py`：把邮件正文里所有「查看原文」链接挨个请求一遍，
  校验响应里既没有「参数错误」、又确实含文章正文结构。
  **判断依据不能用状态码**（失败也是 200），要用页面体量 + 特征串。
- 这个坑的教训值得记牢：**链接生成后要真的打开一次**。
  只看 href 拼得对不对、状态码是不是 200，会漏掉这类静默失败。

---

## 附录七：定时任务改为「每周六 20:00」（2026-10-07）

用户确认：日报**不再每日发送，改为每周六 20:00 一次**。

| 项 | 值 |
|---|---|
| automation id | `cb08677b-b453-4318-adf6-5bcb45304c7f` |
| 名称 | 本地宝郑州招聘日报（每周六 20:00） |
| RRULE | `FREQ=WEEKLY;BYDAY=SA;BYHOUR=20;BYMINUTE=0` |
| 下次触发 | 2026-10-10 20:00（周六） |

**与 `window_days: 7` 是天然匹配的**：每周跑一次、每次覆盖 7 天，正好一周一覆盖、不重不漏。
若以后把频率改回每日，记得 `window_days` 会变成"滚动重复"（同一条岗位连出 7 天），
届时要么接受这种冗余（漏看也不丢），要么另加"已发送"标记。

> 排查提示：该 automation 的 name 与 rrule 曾出现不一致（名字写「每日 8:00」、
> 实际是「每周六 20:00」）。**改调度时顺手把名字对齐**，否则下次看到名字会误判。
> 我是先按名字改回了每日，经用户澄清后才改对的——这类信息**先问，别猜**。
