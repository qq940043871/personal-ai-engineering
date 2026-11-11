import os
import json
from datetime import datetime
from typing import Dict, Optional, List
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 导入配置
from utils.config import config

# 导入智谱AI SDK
try:
    from zai import ZhipuAiClient
except ImportError:
    print("⚠️  未安装 zai-sdk，请运行 pip install zai-sdk")

class MeetingSummarizer:
    def __init__(self):
        """初始化会议纪要生成器"""
        api_key = config.ZHIPU_API_KEY
        if not api_key:
            raise ValueError("请设置 ZHIPU_API_KEY 环境变量")
        
        self.client = ZhipuAiClient(api_key=api_key)
        self.model = config.ZHIPU_MODEL
    
    def generate_summary(self, transcript: str, meeting_topic: Optional[str] = None) -> Dict[str, any]:
        """生成会议纪要
        
        Args:
            transcript: 会议转录文本
            meeting_topic: 会议主题（可选）
            
        Returns:
            结构化的会议纪要
        """
        print("📝 开始生成会议纪要...")
        
        # 构建提示词
        prompt = f"""请根据以下会议转录内容，生成一份结构化的会议纪要。

{'会议主题: ' + meeting_topic + '\n' if meeting_topic else ''}会议转录内容:
{transcript}

请按照以下格式生成会议纪要：
1. 会议基本信息
   - 会议主题
   - 会议时间
   - 参会人员
   - 会议时长

2. 会议要点
   - 详细列出讨论的主要议题和关键点

3. 决策事项
   - 会议中做出的决策

4. 行动项
   - 任务分配
   - 截止日期
   - 负责人

5. 后续安排
   - 下次会议时间（如有）
   - 其他后续事项

请确保会议纪要准确反映会议内容，语言简洁明了，重点突出。"""
        
        # 调用智谱AI API
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一名专业的会议纪要生成助手，擅长从会议转录中提取关键信息并生成结构化的会议纪要。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            thinking={
                "type": "enabled"
            },
            max_tokens=65536,
            temperature=0.3
        )
        
        summary = response.choices[0].message.content
        print("✅ 会议纪要生成完成")
        
        # 解析会议纪要为结构化数据
        structured_summary = self._parse_summary(summary)
        
        return {
            "raw_summary": summary,
            "structured_summary": structured_summary
        }
    
    def _parse_summary(self, summary: str) -> Dict[str, any]:
        """解析生成的会议纪要为结构化数据"""
        # 这里可以根据实际需要实现更复杂的解析逻辑
        # 目前返回原始摘要
        return {
            "summary": summary
        }
    
    def save_summary(self, summary_data: Dict[str, any], output_dir: str = "summaries") -> str:
        """保存会议纪要到文件
        
        Args:
            summary_data: 包含会议纪要的数据
            output_dir: 输出目录
            
        Returns:
            保存的文件路径
        """
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 保存为Markdown文件
        md_filename = f"{output_dir}/meeting_summary_{timestamp}.md"
        with open(md_filename, 'w', encoding='utf-8') as f:
            f.write(summary_data["raw_summary"])
        
        # 保存为JSON文件（结构化数据）
        json_filename = f"{output_dir}/meeting_summary_{timestamp}.json"
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 会议纪要已保存为: {md_filename}")
        return md_filename
