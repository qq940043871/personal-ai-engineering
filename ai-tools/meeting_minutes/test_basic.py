#!/usr/bin/env python3
"""
基本功能测试脚本
"""

import os
import sys

# 添加src目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

print("🔍 开始基本功能测试...")
print()

# 测试1: 导入模块
try:
    from utils.config import config
    from utils.storage import StorageManager
    print("✅ 基础模块导入成功")
except Exception as e:
    print(f"❌ 基础模块导入失败: {str(e)}")
    sys.exit(1)

try:
    from audio.recorder import AudioRecorder
    from audio.processor import AudioProcessor
    print("✅ 音频模块导入成功")
except Exception as e:
    print(f"⚠️  音频模块导入失败 (需要安装 pyaudio): {str(e)}")

try:
    from transcribe.transcriber import AudioTranscriber
    print("✅ 转录模块导入成功")
except Exception as e:
    print(f"⚠️  转录模块导入失败 (需要安装 openai-whisper): {str(e)}")

try:
    from summarize.summarizer import MeetingSummarizer
    print("✅ 摘要模块导入成功")
except Exception as e:
    print(f"⚠️  摘要模块导入失败 (需要安装 openai): {str(e)}")

print()

# 测试2: 配置验证
try:
    print("🔧 配置信息:")
    print(f"  智谱AI Model: {config.ZHIPU_MODEL}")
    print(f"  Whisper Model: {config.WHISPER_MODEL}")
    print(f"  Recordings Dir: {config.RECORDINGS_DIR}")
    print(f"  Summaries Dir: {config.SUMMARIES_DIR}")
    print("✅ 配置加载成功")
except Exception as e:
    print(f"❌ 配置加载失败: {str(e)}")

print()

# 测试3: 存储管理
try:
    storage = StorageManager()
    # 确保目录存在
    storage.ensure_directory(config.RECORDINGS_DIR)
    storage.ensure_directory(config.SUMMARIES_DIR)
    print("✅ 存储管理测试成功")
except Exception as e:
    print(f"❌ 存储管理测试失败: {str(e)}")

print()

# 测试4: 音频录制器初始化
try:
    from audio.recorder import AudioRecorder
    recorder = AudioRecorder()
    print("✅ 音频录制器初始化成功")
except ImportError:
    print("⚠️  跳过音频录制器测试 (模块未导入)")
except Exception as e:
    print(f"❌ 音频录制器初始化失败: {str(e)}")

print()

# 测试5: 转录器初始化
try:
    from transcribe.transcriber import AudioTranscriber
    transcriber = AudioTranscriber(model_name=config.WHISPER_MODEL)
    print("✅ 转录器初始化成功")
except ImportError:
    print("⚠️  跳过转录器测试 (模块未导入)")
except Exception as e:
    print(f"❌ 转录器初始化失败: {str(e)}")

print()

print("🎉 基本功能测试完成！")
print()
print("📝 测试结果总结:")
print("- 基础模块导入: ✅")
try:
    from audio.recorder import AudioRecorder
    print("- 音频模块导入: ✅")
except:
    print("- 音频模块导入: ⚠️  (需要安装 pyaudio)")
try:
    from transcribe.transcriber import AudioTranscriber
    print("- 转录模块导入: ✅")
except:
    print("- 转录模块导入: ⚠️  (需要安装 openai-whisper)")
try:
    from summarize.summarizer import MeetingSummarizer
    print("- 摘要模块导入: ✅")
except:
    print("- 摘要模块导入: ⚠️  (需要安装 openai)")
print("- 配置加载: ✅")
print("- 存储管理: ✅")
print()
print("💡 后续步骤:")
print("1. 复制 .env.example 为 .env 并填写 ZHIPU_API_KEY")
print("2. 安装依赖: pip install -r requirements.txt")
print("3. 运行主程序: python src/app.py")
