import pyaudio
import wave
import threading
import time
from datetime import datetime

class AudioRecorder:
    def __init__(self):
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 44100
        self.chunk = 1024
        self.recording = False
        self.frames = []
        self.audio = pyaudio.PyAudio()
    
    def start_recording(self):
        """开始录制音频"""
        self.recording = True
        self.frames = []
        
        def record_thread():
            stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk
            )
            
            print("🔴 开始录制...")
            
            while self.recording:
                data = stream.read(self.chunk)
                self.frames.append(data)
            
            stream.stop_stream()
            stream.close()
        
        self.thread = threading.Thread(target=record_thread)
        self.thread.start()
    
    def stop_recording(self, output_dir="recordings"):
        """停止录制并保存音频文件"""
        if not self.recording:
            print("❌ 未在录制中")
            return None
        
        self.recording = False
        self.thread.join()
        
        import os
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{output_dir}/recording_{timestamp}.wav"
        
        # 保存音频文件
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.audio.get_sample_size(self.format))
            wf.setframerate(self.rate)
            wf.writeframes(b''.join(self.frames))
        
        print(f"✅ 录制完成，文件保存为: {filename}")
        return filename
    
    def __del__(self):
        """清理资源"""
        if hasattr(self, 'audio'):
            self.audio.terminate()
