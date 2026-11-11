import mss
import cv2
import numpy as np
import threading
import time
from datetime import datetime
import os

class ScreenRecorder:
    def __init__(self):
        """初始化屏幕录制器"""
        self.recording = False
        self.frames = []
        self.fps = 20
        self.screen_size = None
        self.output_file = None
    
    def start_recording(self, monitor_index=0):
        """开始屏幕录制
        
        Args:
            monitor_index: 要录制的显示器索引，默认为0（主显示器）
        """
        self.recording = True
        self.frames = []
        
        def record_thread():
            with mss.mss() as sct:
                # 获取指定显示器的信息
                monitor_info = sct.monitors[monitor_index]
                monitor = {
                    "top": monitor_info["top"],
                    "left": monitor_info["left"],
                    "width": monitor_info["width"],
                    "height": monitor_info["height"]
                }
                
                self.screen_size = (monitor["width"], monitor["height"])
                print(f"🖥️  开始录制屏幕: {self.screen_size[0]}x{self.screen_size[1]}")
                
                start_time = time.time()
                frame_count = 0
                
                while self.recording:
                    # 捕获屏幕
                    screenshot = sct.grab(monitor)
                    
                    # 转换为numpy数组
                    img = np.array(screenshot)
                    # 转换颜色空间（BGR到RGB）
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                    
                    self.frames.append(img)
                    frame_count += 1
                    
                    # 控制帧率
                    elapsed_time = time.time() - start_time
                    expected_time = frame_count / self.fps
                    if elapsed_time < expected_time:
                        time.sleep(expected_time - elapsed_time)
        
        self.thread = threading.Thread(target=record_thread)
        self.thread.start()
    
    def stop_recording(self, output_dir="recordings"):
        """停止录制并保存视频文件
        
        Args:
            output_dir: 输出目录
            
        Returns:
            保存的视频文件路径
        """
        if not self.recording:
            print("❌ 未在录制中")
            return None
        
        self.recording = False
        self.thread.join()
        
        if not self.frames:
            print("❌ 没有录制到任何帧")
            return None
        
        # 确保输出目录存在
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{output_dir}/screen_recording_{timestamp}.avi"
        
        # 保存视频
        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        out = cv2.VideoWriter(filename, fourcc, self.fps, self.screen_size)
        
        for frame in self.frames:
            out.write(frame)
        
        out.release()
        
        print(f"✅ 屏幕录制完成，文件保存为: {filename}")
        print(f"📊 录制信息: {len(self.frames)} 帧, {len(self.frames)/self.fps:.2f} 秒")
        
        self.output_file = filename
        return filename
    
    def get_recording_time(self):
        """获取录制时长
        
        Returns:
            录制时长（秒）
        """
        return len(self.frames) / self.fps
    
    def __del__(self):
        """清理资源"""
        if self.recording:
            self.stop_recording()
