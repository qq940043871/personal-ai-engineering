
import requests
import json
import logging
import time
import sys

from config import VOLC_API_KEY, VOLC_BASE_URL, LLM_MODEL

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5  # 重试间隔（秒）
DEBUG_STREAM = False  # 设置为True可以查看原始响应内容


def parse_stream_response(response):
    """解析流式响应，提取文本内容"""
    article_text = ""
    buffer = ""
    chunk_count = 0
    
    for chunk in response.iter_content(chunk_size=1024):
        chunk_count += 1
        
        if DEBUG_STREAM:
            print(f"\n[DEBUG] 收到第 {chunk_count} 个数据块，长度: {len(chunk) if chunk else 0}", file=sys.stderr)
        
        if chunk:
            try:
                chunk_str = chunk.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    chunk_str = chunk.decode("utf-8", errors="replace")
                except Exception as e:
                    if DEBUG_STREAM:
                        print(f"[DEBUG] 解码失败: {e}", file=sys.stderr)
                    continue
            
            if DEBUG_STREAM and chunk_str:
                preview = chunk_str[:200].replace("\n", "\\n").replace("\r", "\\r")
                print(f"[DEBUG] 数据块预览: {preview}...", file=sys.stderr)
            
            buffer += chunk_str
            
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                
                if DEBUG_STREAM:
                    print(f"[DEBUG] 解析行: {line[:100]}...", file=sys.stderr)
                
                if line.startswith("data: "):
                    line = line[6:]
                elif line.startswith("data:"):
                    line = line[5:]
                elif line.startswith("[") or line.startswith("{"):
                    pass
                else:
                    if DEBUG_STREAM:
                        print(f"[DEBUG] 未知格式，跳过: {line[:50]}", file=sys.stderr)
                    continue
                
                try:
                    data = json.loads(line)
                    
                    if DEBUG_STREAM:
                        print(f"[DEBUG] JSON解析成功，键: {list(data.keys())}", file=sys.stderr)
                    
                    if "output" in data:
                        for content in data["output"]:
                            if content.get("type") == "output_text":
                                text = content.get("text", "")
                                article_text += text
                                print(text, end="", flush=True)
                    elif "delta" in data:
                        text = data.get("delta", "")
                        if isinstance(text, dict):
                            text = text.get("text", "")
                        article_text += text
                        print(text, end="", flush=True)
                    elif "choices" in data:
                        for choice in data["choices"]:
                            if "text" in choice:
                                text = choice["text"]
                                article_text += text
                                print(text, end="", flush=True)
                            elif "delta" in choice and "content" in choice["delta"]:
                                text = choice["delta"]["content"]
                                article_text += text
                                print(text, end="", flush=True)
                    elif "text" in data:
                        text = data["text"]
                        article_text += text
                        print(text, end="", flush=True)
                    else:
                        if DEBUG_STREAM:
                            print(f"[DEBUG] 未找到文本内容字段", file=sys.stderr)
                            
                except json.JSONDecodeError as e:
                    if DEBUG_STREAM:
                        print(f"[DEBUG] JSON解析失败: {e}", file=sys.stderr)
                    if line == "[DONE]":
                        if DEBUG_STREAM:
                            print("[DEBUG] 收到结束标志", file=sys.stderr)
                        break
                    continue
    
    if DEBUG_STREAM:
        print(f"[DEBUG] 解析完成，总字符数: {len(article_text)}", file=sys.stderr)
    
    return article_text


def generate_article(title: str, style: str = "tech_popular", use_stream: bool = True) -> dict:
    url = f"{VOLC_BASE_URL}/responses"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {VOLC_API_KEY}",
        "Accept": "text/event-stream"
    }

    style_prompts = {
        "tech_popular": "通俗易懂、深入浅出、有趣味性，适合AI技术爱好者阅读",
        "professional": "专业严谨、逻辑清晰，适合工程师和技术管理者",
        "tutorial": "手把手教学风格，步骤清晰，配合代码示例"
    }

    style_desc = style_prompts.get(style, style_prompts["tech_popular"])

    prompt = f"""你是一位资深的AI技术科普作家，写作风格{style_desc}。

请根据以下标题，撰写一篇高质量的微信公众号文章。

标题：{title}

要求：
1. 文章结构清晰，包含：引言、核心内容（2-4个小节）、总结
2. 每个小节有明确的小标题
3. 适当使用类比和生活中的例子来解释技术概念
4. 语言生动有趣，避免生硬的技术堆砌
5. 文章总字数1500-2500字
6. 返回纯Markdown格式

输出格式要求（严格遵守）：
- 用 ## 作为小标题
- 用 **加粗** 标记关键概念
- 用 > 标记引用或强调
- 用 ```标记代码块（如有）
- 不要输出除文章外的任何其他内容"""

    data = {
        "model": LLM_MODEL,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt
                    }
                ]
            }
        ],
        "stream": use_stream
    }

    logger.info(f"正在生成文章: {title}")

    for attempt in range(MAX_RETRIES):
        try:
            if use_stream:
                response = requests.post(url, headers=headers, json=data, timeout=300, stream=True)
            else:
                response = requests.post(url, headers=headers, json=data, timeout=300)
            response.raise_for_status()

            if use_stream:
                print("\n", end="")
                article_text = parse_stream_response(response)
                print("\n")
            else:
                result = response.json()
                article_text = ""
                if "output" in result:
                    for content in result["output"]:
                        if content.get("type") == "output_text":
                            article_text += content.get("text", "")
                elif "delta" in result:
                    text = result.get("delta", "")
                    if isinstance(text, dict):
                        text = text.get("text", "")
                    article_text = text
                elif "choices" in result:
                    for choice in result["choices"]:
                        if "text" in choice:
                            article_text += choice["text"]
                        elif "delta" in choice and "content" in choice["delta"]:
                            article_text += choice["delta"]["content"]

            if not article_text:
                logger.error("LLM返回内容为空")
                if use_stream and attempt == MAX_RETRIES - 1:
                    logger.warning("流式模式失败，尝试非流式模式...")
                    return generate_article(title, style, use_stream=False)
                return {"success": False, "error": "LLM返回内容为空"}

            logger.info(f"文章生成成功，长度: {len(article_text)} 字符")
            return {"success": True, "content": article_text, "title": title}

        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"请求超时，第 {attempt + 1}/{MAX_RETRIES} 次尝试失败，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
                continue
            else:
                if use_stream:
                    logger.warning("流式模式超时，尝试非流式模式...")
                    return generate_article(title, style, use_stream=False)
                logger.error(f"请求超时，已重试 {MAX_RETRIES} 次，放弃")
                return {"success": False, "error": f"请求超时，已重试{MAX_RETRIES}次"}
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if "Response ended prematurely" in error_msg and attempt < MAX_RETRIES - 1:
                logger.warning(f"响应提前结束，第 {attempt + 1}/{MAX_RETRIES} 次尝试失败，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
                continue
            if use_stream:
                logger.warning(f"流式模式失败: {error_msg}，尝试非流式模式...")
                return generate_article(title, style, use_stream=False)
            logger.error(f"文章生成失败: {error_msg}")
            return {"success": False, "error": error_msg}
        except Exception as e:
            if use_stream:
                logger.warning(f"流式模式异常: {str(e)}，尝试非流式模式...")
                return generate_article(title, style, use_stream=False)
            logger.error(f"文章生成失败: {str(e)}")
            return {"success": False, "error": str(e)}


def generate_image_prompt(title: str) -> str:
    url = f"{VOLC_BASE_URL}/responses"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {VOLC_API_KEY}"
    }

    prompt = f"""根据以下文章标题，生成一段用于AI绘图的高质量英文提示词。

标题：{title}

要求：
1. 提示词要体现文章的核心主题和视觉元素
2. 风格：科技感、未来感、专业大气
3. 包含光影效果、构图、色调等专业描述
4. 适合作为微信公众号封面图（16:9横版）
5. 只输出英文提示词，不要其他内容"""

    data = {
        "model": LLM_MODEL,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}]
            }
        ]
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(url, headers=headers, json=data, timeout=60)
            response.raise_for_status()
            result = response.json()

            if "output" in result:
                for content in result["output"]:
                    if content.get("type") == "output_text":
                        return content.get("text", "").strip()
            elif "delta" in result:
                text = result.get("delta", "")
                if isinstance(text, dict):
                    text = text.get("text", "")
                return text.strip()
            elif "choices" in result:
                for choice in result["choices"]:
                    if "text" in choice:
                        return choice["text"].strip()
                    elif "delta" in choice and "content" in choice["delta"]:
                        return choice["delta"]["content"].strip()

            return ""
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"图片提示词请求超时，第 {attempt + 1}/{MAX_RETRIES} 次尝试失败，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
                continue
            else:
                logger.error(f"图片提示词请求超时，已重试 {MAX_RETRIES} 次，放弃")
                return ""
        except requests.exceptions.RequestException as e:
            logger.error(f"图片提示词生成失败: {str(e)}")
            return ""
        except Exception as e:
            logger.error(f"图片提示词生成失败: {str(e)}")
            return ""
