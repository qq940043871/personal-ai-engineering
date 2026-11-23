# ai-tools — 独立小工具集

2026-11 由 `ai-study-labs/50_tools/` 整体迁至仓库顶层，并吸收了后续新增的独立项目。
**没有统一入口**：每个脚本 / 子项目都在各自目录内单独运行，互不依赖。

## 运行约定

- **解释器**：没有统一 `requirements.txt`。本机默认 `python` 是精简版 3.13（无第三方库），
  跑带依赖的脚本请用 Anaconda 的 `python.exe` 或各子项目自己的虚拟环境。
  `.bat` / `.sh` 启动器按 Windows + Git Bash 写死，换机器需调整。
- **路径**：编号数据处理脚本与 OCR 示例统一基于 `__file__` 解析，从任何 cwd 启动都能找到
  同目录样本；少数脚本的目标目录本来就要用户自己填，见文末「历史绝对路径」。
- **依赖清单**：`meeting_minutes/`、`personal-wechat-jobs/` 各自带 `requirements.txt` / `setup.py`；
  其余脚本按需单独安装。

## 目录导览

### 编号脚本

| 范围 | 用途 |
|---|---|
| `01_dydown/` | 抖音下载（`f2 dy` + 三个 `.bat` 启动器，配置需 cookie） |
| `02_bibidown/` | B 站下载 |
| `03_import_wset/` | Excel 数据 → SQL 映射导入（含样本 xlsx、sql、生成的 SQL） |
| `04_currency_list/` | 币种 JSON 样本与读取示例 |
| `13_products_sample.csv` | 商品数据生成脚本的产物样本（10–12 号生成脚本已清理） |
| `21_map_asean_plotly.py` | 地图可视化：东盟十国 Plotly（NaturalEarth 版已清理） |
| `32_*`–`34_*` | 长文件名批量重命名：工具、示例、说明 |
| `36_gitee_batch_delete_repos.py` | Gitee 批量删仓库（token 需自填，破坏性操作，谨慎使用） |
| `40_*`–`41_*` | 币种 JSON 解析：`40_*` 脚本、`41_*` 输出 |
| `50_jvm_diag_collect.sh` | JVM 诊断采集（jstack / top） |

### 独立子项目

| 目录 | 用途 | 说明文档 / 测试 |
|---|---|---|
| `disk_cleaner/` | Windows 磁盘占用分析与安全清理（零第三方依赖） | `README.md`、`test_disk_cleaner.py` |
| `doubao/` | 方舟图片 / 视频生成、PDF 合同差异比对 | `pdf_diff/README.md` |
| `doubao_multi_login/` | 多账号登录（cli / gui / web 三入口） | — |
| `meeting_minutes/` | 录音 → Whisper 转写 → 会议纪要 | `README.md`、`test_basic.py` |
| `opencode-go-proxy/` | OpenCode Go 接入 WorkBuddy 的本地协议代理 | `配置完成-README.md` + 6 个 `test_*.py` |
| `opengauss/` | 从 HTML 提取 openGauss 保留关键字 | — |
| `personal-wechat-jobs/` | 公众号招聘信息监听 → 结构化岗位 → 日报 | `README.md`、`skill_dist/` 上架包 |
| `time_task/` | 定时任务与模型清单解析 | `test_all_models_v3.py`、`test_all_video_models.py` |

## 凭证与运行产物（重要）

根 `.gitignore` 的「ai-tools」段统一排除以下类别：

- `01_dydown/dy-*.yaml` —— 内嵌真实登录态 cookie（6.8K–7.5K 字符）
- `**/*.db*` —— 本地数据库及其备份（`douyin_*.db`、`jobs.db`、`accounts.db`）
- `**/config.yaml.bak*` —— 配置备份，含 cookie / 邮箱 / SMTP 设置
- `personal-wechat-jobs/out/`、`**/summaries/`、`**/recordings/*.wav|*.avi` —— 抓取输出、会议纪要、录音与录屏
- `**/jvm_diag_*/`、PDF 合同比对产物、代理模型配置条目、豆包原始应答转储

唯一入库的配置模板是 `01_dydown/dy-config.example.yaml`（脱敏占位）。复制为 `dy-one.yaml` 等后填入自己的 cookie，**不要提交**；`secrets_backup.txt`、`config.yaml`、`.env` 同样由根规则排除。

> ⚠️ **不要在本目录执行 `git add .`**：这里常驻大量运行产物。新增文件请用白名单式
> `git add -- <具体路径>`，并先用 `git check-ignore -v <路径>` 确认它确实该入库。

## 测试

10 个独立 `test_*.py`，没有统一 runner，按各自 README 准备环境后单独跑，例如：

```bash
python -m pytest disk_cleaner/test_disk_cleaner.py -q
python test_basic.py                 # meeting_minutes/
```

`opencode-go-proxy/` 下若干 `test_*` 会连本地代理或外部模型，需要先按
`配置完成-README.md` 起服务。

## 已知问题：历史绝对路径

2026-11 已把「目标文件就在脚本同目录」的一类改为相对路径：

- `ai-rag-dify/02-ocr/paddleocr.py`：同时修掉原路径 `D:\workspace\...\12_ocr\1.jpg` 里 `\12` / `\1` 被当成控制字符转义的 bug，并补上 `main()` 入口，`import` 不再触发模型加载
- `ai-rag-dify/02-ocr/OCR.py`、`ai-study-labs/20_learn/paddlex/OCR.py`
- `40_parse_currency_json.py`、`42_parse_table_json.py`（同时修掉把 `json.dumps` 返回的**字符串**当字典索引的 bug）
- `03_import_wset/import_wset.py`、`opengauss/extract_opengauss.py`、`time_task/parse_models.py`

以下仍保留旧机器路径，属于**运行前必须自填 / 按需修改**，不是 bug：

| 类别 | 典型文件 |
|---|---|
| 扫描目标目录本来就要填 | `30_scan_folder_big_files.py`、`31_scan_folder_big_files_v2.py` |
| 输入 PDF / 模型权重路径 | `doubao/pdf_diff/contract_comparison.py`、`ai-study-labs/20_learn/ffmpeg_opencv/opencv_video.py`、`20_learn/paddlex/object_detection.py` |
| 学习示例里的数据路径 | `20_learn/langchain/*/generate_video_from_json.py`、`book_video_agent.py`、`ai-study-note/exam/scripts/push_to_tdoc.py` |
| 与本机安装强绑定的启动与文档 | `opencode-go-proxy/start_proxy.*`、`配置完成-README.md` |
| 启动器写死解释器路径 | `personal-wechat-jobs/run.bat`、`tools/refresh_cookie.py` |
| 文档链接 / 本机工作区配置 | `ai-agent-harness/docs/AI_POWERED_ACHIEVEMENTS.md` 的 `file:///d:/...`、`config/workspaces.json` |

`disk_cleaner/disk_cleaner.py` 里的 `C:\Windows`、`C:\ProgramData` 等是清理工具本身的**目标系统目录**，属正常硬编码，不要改成相对路径。

## 其它

- `01_dydown` / `02_bibidown` 下载的视频统一落在 `video/`，由根 `.gitignore` 排除。
- `jvm_diag_*` 采集快照带时间戳，每次生成新目录，同样不入库。
- 本目录的 `__pycache__/`、构建产物沿用根 `.gitignore` 的通用规则。
