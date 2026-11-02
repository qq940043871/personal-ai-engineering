
import requests
import os
import logging
import time

from config import VOLC_API_KEY, VOLC_BASE_URL, IMAGE_MODEL

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5  # 重试间隔（秒）


def generate_cover_image(prompt: str, output_path: str, size: str = "2560x1440") -> dict:
    url = f"{VOLC_BASE_URL}/images/generations"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {VOLC_API_KEY}"
    }

    data = {
        "model": IMAGE_MODEL,
        "prompt": prompt,
        "sequential_image_generation": "disabled",
        "response_format": "url",
        "size": size,
        "stream": False,
        "watermark": False
    }

    logger.info(f"正在生成配图: {prompt[:50]}...")

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(url, headers=headers, json=data, timeout=120)
            response.raise_for_status()

            result = response.json()

            if "data" in result and isinstance(result["data"], list):
                image_url = result["data"][0].get("url", "")

                if not image_url:
                    return {"success": False, "error": "未获取到图片URL"}

                img_response = requests.get(image_url, timeout=60)
                img_response.raise_for_status()

                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(img_response.content)

                logger.info(f"配图保存成功: {output_path}")
                return {"success": True, "path": output_path, "url": image_url}
            elif "error" in result:
                return {"success": False, "error": f"API错误: {result.get('error', {}).get('message', str(result))}"}
            else:
                return {"success": False, "error": f"API返回异常: {result}"}

        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"配图生成请求超时，第 {attempt + 1}/{MAX_RETRIES} 次尝试失败，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
                continue
            else:
                logger.error(f"配图生成请求超时，已重试 {MAX_RETRIES} 次，放弃")
                return {"success": False, "error": f"请求超时，已重试{MAX_RETRIES}次"}
        except requests.exceptions.RequestException as e:
            error_detail = str(e)
            try:
                if response is not None and response.content:
                    error_detail += f" | 响应内容: {response.content.decode('utf-8', errors='replace')[:200]}"
            except:
                pass
            logger.error(f"配图生成失败: {error_detail}")
            return {"success": False, "error": error_detail}
        except Exception as e:
            logger.error(f"配图生成失败: {str(e)}")
            return {"success": False, "error": str(e)}
