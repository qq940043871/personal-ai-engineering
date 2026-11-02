import requests

# Ollama的API端点
API_URL = "http://localhost:11434/api/generate"

def generate_response(prompt, model="qwen2.5:0.5b"):
    """
    向Ollama发送请求以获取回复
    :param prompt: 用户输入的提示信息
    :param model: 要使用的模型，默认为llama2
    :return: 模型生成的回复内容
    """
    data = {
        "model": model,
        "prompt": prompt,
        "stream": False  # 不使用流式输出
    }
    try:
        response = requests.post(API_URL, json=data)
        response.raise_for_status()
        result = response.json()
        return result.get("response", "")
    except requests.RequestException as e:
        print(f"请求出错: {e}")
    except ValueError:
        print("无法解析JSON响应")
    return None

if __name__ == "__main__":
    user_prompt = "介绍一下Python语言"
    reply = generate_response(user_prompt)
    if reply:
        print("Ollama的回复:")
        print(reply)    