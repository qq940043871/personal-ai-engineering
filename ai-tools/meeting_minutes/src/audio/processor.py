import os
import numpy as np
import wave

class AudioProcessor:
    def __init__(self):
        pass
    
    def get_audio_info(self, audio_file):
        """获取音频文件信息"""
        with wave.open(audio_file, 'rb') as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            frame_rate = wf.getframerate()
            n_frames = wf.getnframes()
            duration = n_frames / float(frame_rate)
        
        return {
            'channels': channels,
            'sample_width': sample_width,
            'frame_rate': frame_rate,
            'n_frames': n_frames,
            'duration': duration,
            'size': os.path.getsize(audio_file)
        }
    
    def check_audio_file(self, audio_file):
        """检查音频文件是否有效"""
        if not os.path.exists(audio_file):
            raise FileNotFoundError(f"音频文件不存在: {audio_file}")
        
        if not audio_file.lower().endswith('.wav'):
            raise ValueError("仅支持WAV格式的音频文件")
        
        try:
            info = self.get_audio_info(audio_file)
            if info['duration'] <= 0:
                raise ValueError("音频文件时长为0")
            return True
        except Exception as e:
            raise ValueError(f"音频文件无效: {str(e)}")
