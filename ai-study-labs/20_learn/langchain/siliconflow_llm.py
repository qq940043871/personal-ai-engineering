from langchain.llms.base import LLM
from typing import Optional, List, Mapping, Any
import requests

class SiliconFlowLLM(LLM):
    """
    对接SiliconFlow模型的LangChain LLM包装器
    """
    api_key: str  # SiliconFlow的API密钥
    model_id: str  # 模型ID，如"meta-llama/Llama-2-7b-chat-hf"
    temperature: float = 0.7  # 温度参数
    max_tokens: int = 1024  # 最大生成 tokens
    
    @property
    def _llm_type(self) -> str:
        return "siliconflow"
    
    def _call(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        """
        调用SiliconFlow API生成文本
        """
        url = "https://api.siliconflow.cn/v1/chat/completions"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        data = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stop": stop
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()  # 检查请求是否成功
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            raise ValueError(f"调用SiliconFlow API失败: {str(e)}")
    
    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        """
        返回用于标识此LLM的参数
        """
        return {
            "model_id": self.model_id,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }
