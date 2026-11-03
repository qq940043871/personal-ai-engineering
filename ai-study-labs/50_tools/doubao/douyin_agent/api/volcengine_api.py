import requests
import time
from typing import Dict, Any, Optional
from pathlib import Path


class VolcEngineAPI:
    def __init__(self, config: Dict[str, Any]):
        self.api_key = config.get('api_key', '')
        self.endpoint = config.get('endpoint', 'https://ark.cn-beijing.volces.com')
        self.models = config.get('models', {})
        
        self.video_task_url = f"{self.endpoint}/api/v3/contents/generations/tasks"
        self.image_url_old = "https://visual.volcengineapi.com?Action=CVProcess&Version=2022-08-31"
        self.image_url_new = f"{self.endpoint}/api/v3/images/generations"  # 新图片API

    def _get_headers(self):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def generate_image_new(self, prompt: str, size: str = "2K", 
                          watermark: bool = True, model: str = None) -> Optional[Dict]:
        """使用新图片生成API (images/generations)"""
        data = {
            "model": model or self.models.get('image', 'doubao-seedream-4-5-251128'),
            "prompt": prompt,
            "sequential_image_generation": "disabled",
            "response_format": "url",
            "size": size,
            "stream": False,
            "watermark": watermark
        }
        
        try:
            response = requests.post(
                self.image_url_new,
                headers=self._get_headers(),
                json=data
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"图片生成失败 (新API): {e}")
            return None

    def generate_video_task(self, prompt: str, duration: int = 20, 
                          ratio: str = "9:16", fps: int = 24) -> Optional[Dict]:
        """提交视频生成任务"""
        data = {
            "model": self.models.get('video', ''),
            "content": [
                {
                    "type": "text",
                    "text": f"{prompt} --ratio {ratio} --fps {fps} --dur {duration}"
                }
            ]
        }
        
        try:
            response = requests.post(
                self.video_task_url,
                headers=self._get_headers(),
                json=data
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"视频生成任务提交失败: {e}")
            return None

    def check_video_status(self, task_id: str) -> Optional[Dict]:
        """查询视频生成状态"""
        url = self.video_task_url
        params = {
            "page_num": 1,
            "page_size": 10,
            "filter.task_ids": [task_id]
        }
        
        try:
            response = requests.get(
                url,
                headers=self._get_headers(),
                params=params
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"查询视频状态失败: {e}")
            return None

    def wait_for_video_completion(self, task_id: str, 
                                max_retries: int = 30, 
                                interval: int = 10) -> Optional[Dict]:
        """等待视频生成完成"""
        for i in range(max_retries):
            result = self.check_video_status(task_id)
            if result:
                status = self._parse_video_status(result)
                print(f"查询 {i+1}/{max_retries}: {status}")
                
                if status == 'succeeded':
                    return result
                elif status == 'failed':
                    print(f"视频生成失败: {result}")
                    return None
            
            time.sleep(interval)
        
        print(f"视频生成超时")
        return None

    def _parse_video_status(self, result: Dict) -> str:
        """解析视频生成状态"""
        try:
            tasks = result.get('data', [])
            if tasks:
                return tasks[0].get('status', 'unknown')
            return 'unknown'
        except (IndexError, KeyError):
            return 'unknown'

    def get_video_url(self, result: Dict) -> Optional[str]:
        """从结果中提取视频 URL"""
        try:
            tasks = result.get('data', [])
            if tasks:
                task = tasks[0]
                outputs = task.get('output', {})
                if outputs:
                    video_info = outputs.get('result', [])
                    if video_info:
                        return video_info[0].get('url')
            return None
        except (IndexError, KeyError):
            return None

    def generate_image(self, prompt: str, width: int = 1024, 
                     height: int = 1024, scale: float = 3.5, 
                     ddim_steps: int = 25, seed: int = -1) -> Optional[Dict]:
        """生成图片"""
        data = {
            "req_key": "high_aes_general_v21_L",
            "prompt": prompt,
            "model_version": "general_v2.1_L",
            "req_schedule_conf": "general_v20_9B_pe",
            "llm_seed": seed,
            "seed": seed,
            "scale": scale,
            "ddim_steps": ddim_steps,
            "width": width,
            "height": height,
            "use_pre_llm": True,
            "use_sr": True,
            "return_url": True,
            "logo_info": {
                "add_logo": False,
                "position": 0,
                "language": 0,
                "opacity": 0.3,
                "logo_text_content": ""
            }
        }
        
        try:
            response = requests.post(
                self.image_url,
                headers={"Content-Type": "application/json"},
                json=data
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"图片生成失败: {e}")
            return None

    def call_llm(self, prompt: str, model: str = None) -> Optional[Dict]:
        """调用大语言模型"""
        url = f"{self.endpoint}/api/v3/chat/completions"
        data = {
            "model": model or self.models.get('llm', ''),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        try:
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=data
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"LLM 调用失败: {e}")
            return None