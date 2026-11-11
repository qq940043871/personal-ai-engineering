import os
import sys
import time
import click
from colorama import init, Fore, Style

# 初始化colorama
init(autoreset=True)

# 导入模块
from audio.recorder import AudioRecorder
from audio.processor import AudioProcessor
from audio.screen_recorder import ScreenRecorder
from transcribe.transcriber import AudioTranscriber
from summarize.summarizer import MeetingSummarizer
from utils.config import config
from utils.storage import StorageManager

class MeetingMinuteTool:
    """会议纪要工具主类"""
    
    def __init__(self):
        """初始化工具"""
        self.recorder = AudioRecorder()
        self.screen_recorder = ScreenRecorder()
        self.processor = AudioProcessor()
        self.transcriber = AudioTranscriber(model_name=config.WHISPER_MODEL)
        self.summarizer = MeetingSummarizer()
        self.storage = StorageManager()
        
        # 确保目录存在
        self.storage.ensure_directory(config.RECORDINGS_DIR)
        self.storage.ensure_directory(config.SUMMARIES_DIR)
        
        # 验证配置
        config.validate()
    
    def record_meeting(self):
        """录制会议"""
        print(Fore.GREEN + "🎤 开始录制会议")
        print(Fore.YELLOW + "提示: 按 Enter 键停止录制")
        
        # 开始录制
        self.recorder.start_recording()
        
        # 等待用户输入
        input()
        
        # 停止录制
        audio_file = self.recorder.stop_recording(config.RECORDINGS_DIR)
        
        if audio_file:
            print(Fore.GREEN + f"✅ 录制完成: {audio_file}")
            return audio_file
        return None
    
    def record_screen(self):
        """录制屏幕"""
        print(Fore.GREEN + "🖥️  开始录制屏幕")
        print(Fore.YELLOW + "提示: 按 Enter 键停止录制")
        
        # 开始录制
        self.screen_recorder.start_recording(monitor_index=0)
        
        # 等待用户输入
        input()
        
        # 停止录制
        video_file = self.screen_recorder.stop_recording(config.RECORDINGS_DIR)
        
        if video_file:
            print(Fore.GREEN + f"✅ 屏幕录制完成: {video_file}")
            return video_file
        return None
    
    def transcribe_audio(self, audio_file):
        """转录音频"""
        print(Fore.GREEN + "🎯 开始转录音频")
        
        try:
            # 检查音频文件
            self.processor.check_audio_file(audio_file)
            
            # 执行转录
            result = self.transcriber.transcribe(
                audio_file,
                language=config.TRANSCRIBE_LANGUAGE
            )
            
            print(Fore.GREEN + "✅ 转录完成")
            print(Fore.CYAN + "\n转录结果预览:")
            preview = result['text'][:200] + "..." if len(result['text']) > 200 else result['text']
            print(Fore.WHITE + preview)
            
            return result
        except Exception as e:
            print(Fore.RED + f"❌ 转录失败: {str(e)}")
            return None
    
    def generate_summary(self, transcript, meeting_topic=None):
        """生成会议纪要"""
        print(Fore.GREEN + "📝 开始生成会议纪要")
        
        try:
            # 生成会议纪要
            summary_data = self.summarizer.generate_summary(transcript, meeting_topic)
            
            # 保存会议纪要
            saved_file = self.summarizer.save_summary(summary_data, config.SUMMARIES_DIR)
            
            print(Fore.GREEN + "✅ 会议纪要生成完成")
            print(Fore.CYAN + "\n会议纪要预览:")
            preview = summary_data['raw_summary'][:300] + "..." if len(summary_data['raw_summary']) > 300 else summary_data['raw_summary']
            print(Fore.WHITE + preview)
            
            return summary_data
        except Exception as e:
            print(Fore.RED + f"❌ 生成会议纪要失败: {str(e)}")
            return None
    
    def process_audio_file(self, audio_file, meeting_topic=None):
        """处理音频文件（转录 + 生成纪要）"""
        # 转录音频
        transcription = self.transcribe_audio(audio_file)
        if not transcription:
            return None
        
        # 生成会议纪要
        summary = self.generate_summary(transcription['text'], meeting_topic)
        return summary
    
    def show_history(self):
        """显示历史记录"""
        print(Fore.GREEN + "📋 历史记录")
        
        # 显示录音文件
        recordings = self.storage.list_files(config.RECORDINGS_DIR, "wav")
        if recordings:
            print(Fore.CYAN + "\n🎤 录音文件:")
            for i, recording in enumerate(recordings[:5], 1):
                print(Fore.WHITE + f"{i}. {os.path.basename(recording)}")
        else:
            print(Fore.YELLOW + "\n🎤 无录音文件")
        
        # 显示会议纪要
        summaries = self.storage.list_files(config.SUMMARIES_DIR, "md")
        if summaries:
            print(Fore.CYAN + "\n📝 会议纪要:")
            for i, summary in enumerate(summaries[:5], 1):
                print(Fore.WHITE + f"{i}. {os.path.basename(summary)}")
        else:
            print(Fore.YELLOW + "\n📝 无会议纪要")
    
    def clean_up(self):
        """清理资源"""
        print(Fore.GREEN + "🧹 清理资源")
        # 这里可以添加清理逻辑
        print(Fore.GREEN + "✅ 清理完成")

@click.command()
def main():
    """会议纪要智能工具"""
    print(Fore.BLUE + "=" * 60)
    print(Fore.BLUE + "    🎯 会议纪要智能工具")
    print(Fore.BLUE + "=" * 60)
    print(Fore.WHITE + "自动录音、转录、生成会议纪要")
    print()
    
    tool = MeetingMinuteTool()
    
    try:
        while True:
            print(Fore.CYAN + "\n请选择操作:")
            print(Fore.WHITE + "1. 🎤 录制会议")
            print(Fore.WHITE + "2. �️  录制屏幕")
            print(Fore.WHITE + "3. � 处理现有音频文件")
            print(Fore.WHITE + "4. 📋 查看历史记录")
            print(Fore.WHITE + "5. 🧹 清理资源")
            print(Fore.WHITE + "6. 🚪 退出")
            
            choice = input(Fore.YELLOW + "\n请输入选项编号: ")
            
            if choice == "1":
                # 录制会议
                audio_file = tool.record_meeting()
                if audio_file:
                    # 询问是否生成纪要
                    confirm = input(Fore.YELLOW + "是否生成会议纪要? (y/n): ")
                    if confirm.lower() == "y":
                        meeting_topic = input(Fore.YELLOW + "请输入会议主题 (可选): ")
                        tool.process_audio_file(audio_file, meeting_topic or None)
            
            elif choice == "2":
                # 录制屏幕
                video_file = tool.record_screen()
                if video_file:
                    print(Fore.YELLOW + "提示: 屏幕录制文件已保存，可用于后续参考")
            
            elif choice == "3":
                # 处理现有音频文件
                recordings = tool.storage.list_files(config.RECORDINGS_DIR, "wav")
                if recordings:
                    print(Fore.CYAN + "\n请选择音频文件:")
                    for i, recording in enumerate(recordings, 1):
                        print(Fore.WHITE + f"{i}. {os.path.basename(recording)}")
                    
                    file_choice = input(Fore.YELLOW + "\n请输入文件编号: ")
                    try:
                        index = int(file_choice) - 1
                        if 0 <= index < len(recordings):
                            audio_file = recordings[index]
                            meeting_topic = input(Fore.YELLOW + "请输入会议主题 (可选): ")
                            tool.process_audio_file(audio_file, meeting_topic or None)
                        else:
                            print(Fore.RED + "❌ 无效的文件编号")
                    except ValueError:
                        print(Fore.RED + "❌ 请输入有效的数字")
                else:
                    print(Fore.YELLOW + "❌ 无录音文件")
            
            elif choice == "4":
                # 查看历史记录
                tool.show_history()
            
            elif choice == "5":
                # 清理资源
                tool.clean_up()
            
            elif choice == "6":
                # 退出
                print(Fore.GREEN + "👋 再见！")
                break
            
            else:
                print(Fore.RED + "❌ 无效的选项，请重新输入")
                
    except KeyboardInterrupt:
        print(Fore.RED + "\n🔴 操作被中断")
    except Exception as e:
        print(Fore.RED + f"❌ 发生错误: {str(e)}")
    finally:
        tool.clean_up()

if __name__ == "__main__":
    main()
