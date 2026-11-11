import whisper
import os
from typing import Optional, Dict, Any

class AudioTranscriber:
    def __init__(self, model_name: str = "base"):
        """初始化转录器
        
        Args:
            model_name: Whisper模型名称 (tiny, base, small, medium, large)
        """
        self.model_name = model_name
        self.model = None
    
    def load_model(self):
        """加载Whisper模型"""
        if self.model is None:
            print(f"📦 加载Whisper模型: {self.model_name}...")
            self.model = whisper.load_model(self.model_name)
            print("✅ 模型加载完成")
    
    def transcribe(self, audio_file: str, language: Optional[str] = "zh") -> Dict[str, Any]:
        """转录音频文件
        
        Args:
            audio_file: 音频文件路径
            language: 语言代码，默认为中文(zh)
            
        Returns:
            包含转录结果的字典
        """
        # 加载模型
        self.load_model()
        
        # 检查音频文件
        if not os.path.exists(audio_file):
            raise FileNotFoundError(f"音频文件不存在: {audio_file}")
        
        print(f"🎯 开始转录音频文件: {audio_file}")
        print(f"🌐 语言: {language}")
        
        # 执行转录
        result = self.model.transcribe(
            audio_file,
            language=language,
            verbose=False
        )
        
        print("✅ 转录完成")
        print(f"📝 转录文本长度: {len(result['text'])} 字符")
        
        return result
    
    def transcribe_with_timestamps(self, audio_file: str, language: Optional[str] = "zh") -> Dict[str, Any]:
        """带时间戳的转录
        
        Args:
            audio_file: 音频文件路径
            language: 语言代码
            
        Returns:
            包含时间戳的转录结果
        """
        # 加载模型
        self.load_model()
        
        print(f"🎯 开始带时间戳的转录: {audio_file}")
        
        # 执行转录
        result = self.model.transcribe(
            audio_file,
            language=language,
            verbose=False,
            word_timestamps=True
        )
        
        print("✅ 带时间戳的转录完成")
        return result
