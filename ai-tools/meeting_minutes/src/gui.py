import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import queue
import os
import sys

# 添加src目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入核心模块
from audio.recorder import AudioRecorder
from audio.processor import AudioProcessor
from audio.screen_recorder import ScreenRecorder
from transcribe.transcriber import AudioTranscriber
from summarize.summarizer import MeetingSummarizer
from utils.config import config
from utils.storage import StorageManager

class MeetingMinuteGUI:
    def __init__(self, root):
        """初始化GUI界面"""
        self.root = root
        self.root.title("会议纪要智能工具")
        self.root.geometry("1000x600")
        self.root.resizable(True, True)
        
        # 设置主题
        self.style = ttk.Style()
        self.style.theme_use("clam")
        
        # 创建主框架
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建左右布局
        self.left_frame = ttk.Frame(self.main_frame, width=300, padding="10")
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y, expand=False)
        
        self.right_frame = ttk.Frame(self.main_frame, padding="10")
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 初始化核心组件
        self.recorder = AudioRecorder()
        self.screen_recorder = ScreenRecorder()
        self.processor = AudioProcessor()
        self.transcriber = AudioTranscriber(model_name=config.WHISPER_MODEL)
        self.summarizer = MeetingSummarizer()
        self.storage = StorageManager()
        
        # 确保目录存在
        self.storage.ensure_directory(config.RECORDINGS_DIR)
        self.storage.ensure_directory(config.SUMMARIES_DIR)
        
        # 状态变量
        self.is_recording = False
        self.is_screen_recording = False
        self.current_audio_file = None
        self.current_video_file = None
        self.queue = queue.Queue()
        
        # 创建左侧操作步骤
        self.create_left_panel()
        
        # 创建右侧输出结果
        self.create_right_panel()
        
        # 开始处理队列
        self.process_queue()
    
    def create_left_panel(self):
        """创建左侧操作步骤面板"""
        # 标题
        title_label = ttk.Label(self.left_frame, text="操作步骤", font=("微软雅黑", 14, "bold"))
        title_label.pack(pady=(0, 20))
        
        # 操作按钮
        button_frame = ttk.Frame(self.left_frame)
        button_frame.pack(fill=tk.X, pady=5)
        
        # 录制按钮
        self.record_button = ttk.Button(
            button_frame, 
            text="1. 开始录制", 
            command=self.toggle_recording,
            width=20
        )
        self.record_button.pack(fill=tk.X, pady=5)
        
        # 屏幕录制按钮
        self.screen_record_button = ttk.Button(
            button_frame, 
            text="2. 录制屏幕", 
            command=self.toggle_screen_recording,
            width=20
        )
        self.screen_record_button.pack(fill=tk.X, pady=5)
        
        # 处理按钮
        self.process_button = ttk.Button(
            button_frame, 
            text="3. 处理录音", 
            command=self.process_audio,
            width=20, 
            state=tk.DISABLED
        )
        self.process_button.pack(fill=tk.X, pady=5)
        
        # 历史记录按钮
        self.history_button = ttk.Button(
            button_frame, 
            text="4. 历史记录", 
            command=self.show_history,
            width=20
        )
        self.history_button.pack(fill=tk.X, pady=5)
        
        # 清理按钮
        self.clean_button = ttk.Button(
            button_frame, 
            text="5. 清理资源", 
            command=self.clean_resources,
            width=20
        )
        self.clean_button.pack(fill=tk.X, pady=5)
        
        # 退出按钮
        self.exit_button = ttk.Button(
            button_frame, 
            text="6. 退出", 
            command=self.root.quit,
            width=20
        )
        self.exit_button.pack(fill=tk.X, pady=5)
        
        # 会议主题输入
        topic_frame = ttk.LabelFrame(self.left_frame, text="会议主题", padding="10")
        topic_frame.pack(fill=tk.X, pady=20)
        
        self.topic_var = tk.StringVar()
        self.topic_entry = ttk.Entry(topic_frame, textvariable=self.topic_var, width=30)
        self.topic_entry.pack(fill=tk.X)
        
        # 状态显示
        status_frame = ttk.LabelFrame(self.left_frame, text="状态", padding="10")
        status_frame.pack(fill=tk.X, pady=10)
        
        self.status_var = tk.StringVar(value="就绪")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, font=("微软雅黑", 10))
        self.status_label.pack(fill=tk.X)
    
    def create_right_panel(self):
        """创建右侧输出结果面板"""
        # 标题
        title_label = ttk.Label(self.right_frame, text="输出结果", font=("微软雅黑", 14, "bold"))
        title_label.pack(pady=(0, 10))
        
        # 输出文本框
        self.output_text = scrolledtext.ScrolledText(
            self.right_frame, 
            wrap=tk.WORD, 
            font=("微软雅黑", 10)
        )
        self.output_text.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 滚动条
        self.output_text.config(yscrollcommand=ttk.Scrollbar(self.output_text).set)
        
        # 初始提示
        self.append_output("欢迎使用会议纪要智能工具！\n")
        self.append_output("操作步骤：\n")
        self.append_output("1. 点击 '开始录制' 按钮开始录制会议\n")
        self.append_output("2. 点击 '录制屏幕' 按钮开始录制屏幕\n")
        self.append_output("3. 再次点击对应按钮停止录制\n")
        self.append_output("4. 点击 '处理录音' 按钮生成会议纪要\n")
        self.append_output("5. 查看右侧输出结果\n")
    
    def toggle_recording(self):
        """切换录制状态"""
        if not self.is_recording:
            # 开始录制
            self.is_recording = True
            self.record_button.config(text="停止录制")
            self.status_var.set("录制中...")
            self.append_output("🔴 开始录制...\n")
            
            # 在后台线程中录制
            threading.Thread(target=self._record_audio, daemon=True).start()
        else:
            # 停止录制
            self.is_recording = False
            self.record_button.config(text="开始录制")
            self.status_var.set("处理中...")
            self.append_output("⏹️  停止录制...\n")
    
    def toggle_screen_recording(self):
        """切换屏幕录制状态"""
        if not self.is_screen_recording:
            # 开始屏幕录制
            self.is_screen_recording = True
            self.screen_record_button.config(text="停止录制屏幕")
            self.status_var.set("屏幕录制中...")
            self.append_output("🖥️  开始录制屏幕...\n")
            
            # 在后台线程中录制
            threading.Thread(target=self._record_screen, daemon=True).start()
        else:
            # 停止屏幕录制
            self.is_screen_recording = False
            self.screen_record_button.config(text="录制屏幕")
            self.status_var.set("处理中...")
            self.append_output("⏹️  停止录制屏幕...\n")
    
    def _record_audio(self):
        """录制音频的后台线程"""
        try:
            self.recorder.start_recording()
            # 等待停止信号
            while self.is_recording:
                threading.Event().wait(0.1)
            # 停止录制
            self.current_audio_file = self.recorder.stop_recording(config.RECORDINGS_DIR)
            if self.current_audio_file:
                self.queue.put(("recording_completed", self.current_audio_file))
            else:
                self.queue.put(("error", "录制失败"))
        except Exception as e:
            self.queue.put(("error", f"录制错误: {str(e)}"))
    
    def _record_screen(self):
        """录制屏幕的后台线程"""
        try:
            self.screen_recorder.start_recording(monitor_index=0)
            # 等待停止信号
            while self.is_screen_recording:
                threading.Event().wait(0.1)
            # 停止录制
            self.current_video_file = self.screen_recorder.stop_recording(config.RECORDINGS_DIR)
            if self.current_video_file:
                self.queue.put(("screen_recording_completed", self.current_video_file))
            else:
                self.queue.put(("error", "屏幕录制失败"))
        except Exception as e:
            self.queue.put(("error", f"屏幕录制错误: {str(e)}"))
    
    def process_audio(self):
        """处理音频文件"""
        if not self.current_audio_file:
            self.append_output("❌ 请先录制音频\n")
            return
        
        self.status_var.set("处理中...")
        self.append_output("🎯 开始处理音频...\n")
        
        # 在后台线程中处理
        threading.Thread(target=self._process_audio_thread, daemon=True).start()
    
    def _process_audio_thread(self):
        """处理音频的后台线程"""
        try:
            # 转录音频
            self.queue.put(("message", "正在转录音频..."))
            transcription = self.transcriber.transcribe(
                self.current_audio_file,
                language=config.TRANSCRIBE_LANGUAGE
            )
            
            if not transcription:
                self.queue.put(("error", "转录失败"))
                return
            
            # 生成会议纪要
            self.queue.put(("message", "正在生成会议纪要..."))
            meeting_topic = self.topic_var.get() or None
            summary_data = self.summarizer.generate_summary(
                transcription['text'], 
                meeting_topic
            )
            
            if summary_data:
                # 保存会议纪要
                saved_file = self.summarizer.save_summary(summary_data, config.SUMMARIES_DIR)
                self.queue.put(("process_completed", saved_file, summary_data))
            else:
                self.queue.put(("error", "生成会议纪要失败"))
        except Exception as e:
            self.queue.put(("error", f"处理错误: {str(e)}"))
    
    def show_history(self):
        """显示历史记录"""
        self.append_output("📋 历史记录\n")
        
        # 显示录音文件
        recordings = self.storage.list_files(config.RECORDINGS_DIR, "wav")
        if recordings:
            self.append_output("\n🎤 录音文件:\n")
            for i, recording in enumerate(recordings[:5], 1):
                filename = os.path.basename(recording)
                self.append_output(f"{i}. {filename}\n")
        else:
            self.append_output("\n🎤 无录音文件\n")
        
        # 显示会议纪要
        summaries = self.storage.list_files(config.SUMMARIES_DIR, "md")
        if summaries:
            self.append_output("\n📝 会议纪要:\n")
            for i, summary in enumerate(summaries[:5], 1):
                filename = os.path.basename(summary)
                self.append_output(f"{i}. {filename}\n")
        else:
            self.append_output("\n📝 无会议纪要\n")
    
    def clean_resources(self):
        """清理资源"""
        self.append_output("🧹 清理资源...\n")
        # 这里可以添加清理逻辑
        self.append_output("✅ 清理完成\n")
        self.status_var.set("就绪")
    
    def append_output(self, text):
        """追加输出文本"""
        self.output_text.insert(tk.END, text)
        self.output_text.see(tk.END)
    
    def process_queue(self):
        """处理队列中的消息"""
        try:
            while not self.queue.empty():
                message = self.queue.get_nowait()
                if message[0] == "recording_completed":
                    audio_file = message[1]
                    self.current_audio_file = audio_file
                    self.append_output(f"✅ 录制完成: {os.path.basename(audio_file)}\n")
                    self.process_button.config(state=tk.NORMAL)
                    self.status_var.set("就绪")
                elif message[0] == "screen_recording_completed":
                    video_file = message[1]
                    self.current_video_file = video_file
                    self.append_output(f"✅ 屏幕录制完成: {os.path.basename(video_file)}\n")
                    self.append_output("提示: 屏幕录制文件已保存，可用于后续参考\n")
                    self.status_var.set("就绪")
                elif message[0] == "process_completed":
                    saved_file, summary_data = message[1], message[2]
                    self.append_output(f"✅ 会议纪要已保存为: {os.path.basename(saved_file)}\n")
                    self.append_output("\n会议纪要预览:\n")
                    preview = summary_data['raw_summary'][:300] + "..." if len(summary_data['raw_summary']) > 300 else summary_data['raw_summary']
                    self.append_output(preview + "\n")
                    self.status_var.set("就绪")
                elif message[0] == "message":
                    self.append_output(f"{message[1]}\n")
                elif message[0] == "error":
                    self.append_output(f"❌ {message[1]}\n")
                    self.status_var.set("就绪")
        except queue.Empty:
            pass
        finally:
            # 继续处理队列
            self.root.after(100, self.process_queue)

def main():
    """主函数"""
    root = tk.Tk()
    app = MeetingMinuteGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
