import os
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from urllib.parse import urlparse
import requests

from .config.config_manager import ConfigManager
from .api.volcengine_api import VolcEngineAPI
from .templates.template_manager import TemplateManager


class DouyinVideoAgent:
    def __init__(self, config_dir: Path = None):
        self.config_manager = ConfigManager(config_dir)
        self.volc_api = VolcEngineAPI(self.config_manager.get_volcengine_config())
        self.template_manager = TemplateManager()
        
        # 设置输出目录
        output_config = self.config_manager.get_output_config()
        self.output_dir = Path(output_config.get('dir', './output'))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_video(self, topic: str, style: str = "现代", 
                    audience: str = "年轻人", use_template: bool = True,
                    template_id: str = "douyin_video") -> Dict[str, Any]:
        """生成抖音视频主流程"""
        print(f"\n{'='*60}")
        print(f"开始生成视频 - 主题: {topic}")
        print(f"{'='*60}\n")

        result = {
            "success": False,
            "topic": topic,
            "timestamp": datetime.now().isoformat(),
            "task_id": None,
            "video_url": None,
            "output_file": None,
            "error": None
        }

        try:
            # 1. 生成视频提示词
            video_prompt = self._generate_video_prompt(topic, style, audience, 
                                                    use_template, template_id)
            print(f"✓ 已生成视频提示词")

            # 2. 提交视频生成任务
            video_config = self.config_manager.get_video_config()
            task_response = self.volc_api.generate_video_task(
                prompt=video_prompt,
                duration=video_config.get('duration', 20),
                ratio=video_config.get('ratio', '9:16'),
                fps=video_config.get('fps', 24)
            )

            if not task_response:
                result["error"] = "视频任务提交失败"
                return result

            task_id = task_response.get('data', {}).get('id')
            result["task_id"] = task_id
            print(f"✓ 已提交视频任务，ID: {task_id}")

            # 3. 等待视频生成完成
            print(f"\n⏳ 等待视频生成中...")
            video_result = self.volc_api.wait_for_video_completion(
                task_id,
                max_retries=video_config.get('max_retries', 30),
                interval=video_config.get('check_interval', 10)
            )

            if not video_result:
                result["error"] = "视频生成失败或超时"
                return result

            # 4. 获取视频 URL
            video_url = self.volc_api.get_video_url(video_result)
            if video_url:
                result["video_url"] = video_url
                print(f"✓ 视频生成成功: {video_url}")

                # 5. 下载视频
                output_file = self._download_video(video_url, topic)
                if output_file:
                    result["output_file"] = output_file
                    print(f"✓ 视频已保存到: {output_file}")
                    result["success"] = True

        except Exception as e:
            result["error"] = str(e)
            print(f"✗ 发生错误: {e}")

        print(f"\n{'='*60}")
        if result["success"]:
            print("🎉 视频生成完成！")
        else:
            print("😢 视频生成失败")
        print(f"{'='*60}\n")

        return result

    def _generate_video_prompt(self, topic: str, style: str, audience: str,
                             use_template: bool, template_id: str) -> str:
        """生成视频提示词"""
        if use_template and template_id:
            try:
                video_config = self.config_manager.get_video_config()
                return self.template_manager.render_template(
                    template_id,
                    topic=topic,
                    style=style,
                    audience=audience,
                    duration=video_config.get('duration', 20)
                )
            except Exception as e:
                print(f"模板渲染失败，使用默认提示词: {e}")

        # 默认提示词
        video_config = self.config_manager.get_video_config()
        return f"""请生成一个高质量的抖音短视频，要求如下：

主题：{topic}
风格：{style}
受众：{audience}

详细要求：
1. 视频时长：{video_config.get('duration', 20)}秒
2. 画面比例：9:16（竖屏）
3. 画面流畅，有吸引力
4. 色彩鲜艳，视觉冲击力强
5. 适合抖音平台播放"""

    def _download_video(self, url: str, topic: str) -> Optional[Path]:
        """下载视频文件"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_topic = "".join(c for c in topic if c.isalnum() or c in (' ', '-', '_')).strip()
            filename = f"{safe_topic}_{timestamp}.mp4"
            output_file = self.output_dir / filename

            print(f"📥 正在下载视频...")
            response = requests.get(url, stream=True, timeout=300)
            response.raise_for_status()

            with open(output_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return output_file

        except Exception as e:
            print(f"下载视频失败: {e}")
            return None

    def batch_generate(self, topics: list, **kwargs) -> list:
        """批量生成视频"""
        results = []
        for i, topic in enumerate(topics, 1):
            print(f"\n=== 进度 {i}/{len(topics)} ===")
            result = self.generate_video(topic, **kwargs)
            results.append(result)
            
            if i < len(topics):
                time.sleep(2)  # 避免请求过于频繁

        return results

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """查询任务状态"""
        return self.volc_api.check_video_status(task_id)

    def generate_image(self, prompt: str, style: str = "高质量", 
                    use_template: bool = True, template_id: str = "image_generation") -> Dict[str, Any]:
        """生成图片"""
        print(f"\n{'='*60}")
        print(f"开始生成图片 - 提示: {prompt[:50]}...")
        print(f"{'='*60}\n")

        result = {
            "success": False,
            "prompt": prompt,
            "timestamp": datetime.now().isoformat(),
            "image_url": None,
            "output_file": None,
            "error": None
        }

        try:
            # 1. 生成图片提示词
            if use_template and template_id:
                try:
                    image_config = self.config_manager.get_image_config()
                    full_prompt = self.template_manager.render_template(
                        template_id,
                        description=prompt,
                        style=style,
                        width=image_config.get('size', '2K'),
                        height=image_config.get('size', '2K')
                    )
                except Exception as e:
                    print(f"模板渲染失败，使用原始提示词: {e}")
                    full_prompt = prompt
            else:
                full_prompt = prompt

            print(f"✓ 已生成提示词")

            # 2. 提交图片生成任务
            image_config = self.config_manager.get_image_config()
            img_response = self.volc_api.generate_image_new(
                prompt=full_prompt,
                size=image_config.get('size', '2K'),
                watermark=image_config.get('watermark', True)
            )

            if not img_response:
                result["error"] = "图片生成失败"
                return result

            print(f"✓ 图片已生成")

            # 3. 提取图片URL
            image_url = None
            if 'data' in img_response and isinstance(img_response['data'], list):
                for item in img_response['data']:
                    if 'url' in item:
                        image_url = item['url']
                        break

            if image_url:
                result["image_url"] = image_url
                print(f"✓ 图片地址: {image_url}")

                # 4. 下载图片（可选）
                if self.config_manager.get_output_config().get('save_images', True):
                    output_file = self._download_image(image_url, prompt)
                    if output_file:
                        result["output_file"] = output_file
                        print(f"✓ 图片已保存到: {output_file}")

                result["success"] = True

        except Exception as e:
            result["error"] = str(e)
            print(f"✗ 发生错误: {e}")

        print(f"\n{'='*60}")
        if result["success"]:
            print("🎉 图片生成完成！")
        else:
            print("😢 图片生成失败")
        print(f"{'='*60}\n")

        return result

    def _download_image(self, url: str, prompt: str) -> Optional[Path]:
        """下载图片"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_prompt = "".join(c for c in prompt if c.isalnum() or c in (' ', '-', '_'))[:30].strip()
            filename = f"{safe_prompt}_{timestamp}.png"
            output_file = self.output_dir / filename

            print(f"📥 正在下载图片...")
            response = requests.get(url, stream=True, timeout=300)
            response.raise_for_status()

            with open(output_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return output_file

        except Exception as e:
            print(f"下载图片失败: {e}")
            return None

    def list_templates(self, category: str = None):
        """列出可用模板"""
        return self.template_manager.list_templates(category)

    def add_template(self, template_id: str, name: str, description: str,
                    content: str, variables: list = None, category: str = "general"):
        """添加自定义模板"""
        return self.template_manager.create_template(
            template_id, name, description, content, variables, category
        )