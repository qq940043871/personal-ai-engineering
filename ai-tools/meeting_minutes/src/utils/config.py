import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Config:
    """配置管理类"""
    # 智谱AI 配置
    ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY")
    ZHIPU_MODEL = os.getenv("ZHIPU_MODEL", "glm-4.7")
    
    # 音频配置
    AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "44100"))
    AUDIO_CHANNELS = int(os.getenv("AUDIO_CHANNELS", "1"))
    AUDIO_FORMAT = int(os.getenv("AUDIO_FORMAT", "16"))
    
    # 存储配置
    RECORDINGS_DIR = os.getenv("RECORDINGS_DIR", "recordings")
    SUMMARIES_DIR = os.getenv("SUMMARIES_DIR", "summaries")
    
    # 转录配置
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
    TRANSCRIBE_LANGUAGE = os.getenv("TRANSCRIBE_LANGUAGE", "zh")
    
    @classmethod
    def validate(cls):
        """验证配置"""
        if not cls.ZHIPU_API_KEY:
            raise ValueError("请设置 ZHIPU_API_KEY 环境变量")
        return True

# 创建全局配置实例
config = Config()
