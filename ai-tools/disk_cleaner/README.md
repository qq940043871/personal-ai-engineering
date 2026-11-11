# 磁盘清理工具（disk_cleaner）

Windows 磁盘空间分析与安全清理工具。零第三方依赖，只用 Python 标准库，下载即可运行。

## 功能

- 🧹 **分类清理**：临时文件、浏览器缓存、缩略图、Windows 系统垃圾、开发包缓存等
- 🔍 **占用分析**：按目录逐层统计空间占用（`du`）
- 🐘 **大文件查找**：找出指定目录下的大文件，可按文件年龄过滤（`large`）
- 📦 **应用盘点**：列出各应用目录的大小与最近活动时间，识别长期不用的应用和卸载残留（`apps`）
- 🛡️ **默认安全**：先扫描再确认；临时文件默认只删 24 小时前的；不跟随链接、不碰文档/下载/桌面
- 🖥️ **交互模式**：双击 `run.bat` 即可扫描并选择要清理的类别

## 快速开始

```bash
cd disk_cleaner

python disk_cleaner.py                  # 交互模式：扫描 → 输入编号 → 确认清理
python disk_cleaner.py scan             # 只扫描，不删除
python disk_cleaner.py scan --deep      # 扫描 + 用户目录占用 TOP + 大文件
python disk_cleaner.py clean --dry-run  # 预览默认清理项（不会删除）
python disk_cleaner.py clean --yes      # 执行默认清理
```

Windows 下也可以直接双击 `run.bat`。

## 清理类别

| 类别 | 默认清理 | 说明 |
| --- | --- | --- |
| `temp` | ✅ | 用户/系统临时文件，默认只删 24 小时前的 |
| `browser` | ✅ | Chrome / Edge / Firefox 等缓存（不含书签、密码、历史） |
| `thumbnails` | ✅ | 资源管理器缩略图/图标缓存 |
| `windows` | ✅ | Windows 更新下载缓存、错误报告、CBS 日志（部分需管理员） |
| `pkg` | ✅ | pip / npm / yarn / pnpm / uv 下载缓存，可自动重新下载 |
| `devcache` | ❌ | puppeteer / playwright 浏览器、Whisper / Torch 模型缓存 |
| `models` | ❌ | HuggingFace / ModelScope 已下载模型 |
| `conda` | ❌ | anaconda / miniconda 的 `pkgs` 包缓存 |
| `maven` | ❌ | `~/.m2/repository` 依赖仓库（私有/离线依赖慎用） |
| `recycle` | ❌ | 清空回收站（不可恢复） |

只清理指定类别：

```bash
python disk_cleaner.py clean temp pkg --yes
python disk_cleaner.py clean devcache --dry-run
python disk_cleaner.py clean --all --dry-run     # 查看全部类别
```

## 常用分析命令

```bash
# 查看目录占用，展开 2 层，每层显示前 20 项
python disk_cleaner.py du "C:\Users\你的用户名" --depth 2 --top 20

# 查找 C 盘 500MB 以上的大文件
python disk_cleaner.py large C:\ --min-mb 500 --top 30

# 只找 90 天前的 200MB 以上大文件（适合清理旧安装包/镜像）
python disk_cleaner.py large D:\Downloads --min-mb 200 --older-than 90

# 盘点应用目录：显示大小、最近活动时间，标记闲置与疑似残留
python disk_cleaner.py apps --min-mb 10 --stale-days 90 --top 60
```

`apps` 会扫描 `%LOCALAPPDATA%`、`%APPDATA%`、`Program Files`、`Program Files (x86)`、
`ProgramData` 以及用户目录下的配置文件夹，输出类似：

```text
        大小  最近活动    位置
     557.6 MB  139 天前   UserProfile\.vscode  [闲置]
     433.0 MB  139 天前   RoamingAppData\Code  [闲置]
```

“最近活动”取目录内最新文件的修改时间，后台自动更新可能让闲置应用显得较新。
该命令只读，不会删除任何内容；卸载应用请优先使用系统“应用和功能”或应用自带卸载器。

## 安全性说明

- `clean` 不加 `--yes` 时只展示计划，需要手动输入 `yes` 确认。
- 临时文件默认保留最近 24 小时的内容，避免误删正在使用的安装包/临时数据；
  可用 `--min-age-hours 0` 改为全部清理，或调大保留时长。
- 浏览器缓存只删除 `Cache`、`Code Cache`、`GPUCache` 等缓存目录，
  不会触碰书签、密码、历史记录、Cookie。
- 遍历时跳过符号链接和 junction，不会顺着链接删到其他盘。
- 被占用的文件会自动跳过并在结果里报告；关闭浏览器/编辑器后可重跑。
- 建议先运行 `scan` 和 `clean --dry-run` 确认清单，再执行 `clean --yes`。

## 环境要求

- Windows 10/11
- Python 3.9+（无需安装任何第三方包）

## 说明

- `windows` 类别中的部分路径（如 `C:\Windows\SoftwareDistribution\Download`）需要管理员权限；
  未以管理员运行时这些文件会被跳过，不影响其他类别。
- 清空回收站使用 PowerShell 的 `Clear-RecycleBin` 命令。
- 清理结果中的“删除数据”按文件逻辑大小累加；如果缓存与虚拟环境之间存在硬链接，
  或文件被系统压缩，实际可用空间增量可能略小于该数值，请以末尾的可用空间变化为准。
