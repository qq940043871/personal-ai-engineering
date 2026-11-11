# 会议纪要智能工具

一个自动记录会议纪要的智能工具，能实现录音转换生成会议纪要。

## 功能特性

- 🎤 **实时录音**：使用麦克风实时录制会议内容
- 🎯 **语音转文字**：使用 Whisper 模型将音频转换为文本
- 📝 **智能摘要**：使用 OpenAI API 生成结构化的会议纪要
- 📋 **历史记录**：查看和管理历史录音和会议纪要
- 🎨 **友好界面**：命令行界面，操作简单直观

## 技术栈

- **Python 3.9+**：主要开发语言
- **PyAudio**：音频录制
- **Whisper**：语音识别
- **OpenAI API**：文本分析和摘要
- **Click**：命令行界面
- **Colorama**：终端颜色输出

## 安装步骤

### 1. 克隆项目

```bash
git clone <repository-url>
cd meeting-minutes-tool
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

复制 `.env.example` 文件为 `.env` 并填写相关配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# OpenAI API 配置
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-3.5-turbo

# 音频配置
AUDIO_SAMPLE_RATE=44100
AUDIO_CHANNELS=1
AUDIO_FORMAT=16

# 存储配置
RECORDINGS_DIR=recordings
SUMMARIES_DIR=summaries

# 转录配置
WHISPER_MODEL=base
TRANSCRIBE_LANGUAGE=zh
```

**注意**：你需要一个 OpenAI API Key 才能使用会议纪要生成功能。

## 使用方法

### 运行工具

#### 命令行界面
```bash
python src/app.py
```

#### GUI界面
```bash
python run_gui.py
```

### 操作指南

1. **录制会议**：选择选项 1，开始录制会议，按 Enter 键停止录制
2. **处理现有音频文件**：选择选项 2，从历史录音中选择文件进行处理
3. **查看历史记录**：选择选项 3，查看历史录音和会议纪要
4. **清理资源**：选择选项 4，清理临时资源
5. **退出**：选择选项 5，退出工具

### 示例流程

1. 运行工具
2. 选择 "1. 🎤 录制会议"
3. 开始会议讨论
4. 会议结束后按 Enter 键停止录制
5. 确认生成会议纪要
6. 输入会议主题（可选）
7. 等待工具处理音频并生成会议纪要
8. 查看生成的会议纪要

## 项目结构

```
meeting-minutes-tool/
├── src/
│   ├── audio/
│   │   ├── recorder.py      # 音频录制功能
│   │   └── processor.py     # 音频处理
│   ├── transcribe/
│   │   └── transcriber.py   # 语音转文字
│   ├── summarize/
│   │   └── summarizer.py    # 会议纪要生成
│   ├── utils/
│   │   ├── config.py        # 配置管理
│   │   └── storage.py       # 文件存储
│   └── app.py               # 主应用
├── requirements.txt         # 依赖管理
├── README.md                # 项目说明
└── .env.example             # 环境变量示例
```

## 配置说明

### OpenAI 配置
- `OPENAI_API_KEY`：OpenAI API 密钥
- `OPENAI_MODEL`：使用的 OpenAI 模型（默认：gpt-3.5-turbo）

### 音频配置
- `AUDIO_SAMPLE_RATE`：音频采样率（默认：44100）
- `AUDIO_CHANNELS`：音频通道数（默认：1）
- `AUDIO_FORMAT`：音频格式（默认：16）

### 存储配置
- `RECORDINGS_DIR`：录音文件存储目录（默认：recordings）
- `SUMMARIES_DIR`：会议纪要存储目录（默认：summaries）

### 转录配置
- `WHISPER_MODEL`：Whisper 模型名称（默认：base）
- `TRANSCRIBE_LANGUAGE`：转录语言（默认：zh）

## 注意事项

1. **API 费用**：使用 OpenAI API 会产生费用，请确保你的账户有足够的余额
2. **模型下载**：首次使用 Whisper 模型时会自动下载，可能需要一些时间
3. **网络连接**：需要网络连接来使用 OpenAI API
4. **音频质量**：为获得最佳转录效果，请确保录音环境安静，麦克风清晰

## 故障排除

### 1. 音频录制失败
- 检查麦克风是否正常工作
- 确保 PyAudio 正确安装

### 2. 转录失败
- 检查音频文件是否损坏
- 确保 Whisper 模型已正确下载

### 3. 会议纪要生成失败
- 检查 OpenAI API Key 是否正确
- 确保网络连接正常
- 检查 API 权限和余额

## 贡献

欢迎提交 Issue 和 Pull Request 来改进这个项目！

## 许可证

MIT License
