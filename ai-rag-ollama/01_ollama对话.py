from flask import Flask, request, jsonify, render_template, Response
from flask_cors import CORS
import requests


app = Flask(__name__)
CORS(app)

OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:0.5b"


def stream_with_ollama(prompt):
    data = {
        "model": MODEL,
        "prompt": prompt,
        "stream": True
    }
    try:
        response = requests.post(OLLAMA_API_URL, json=data, stream=True)
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                try:
                    chunk = line.decode('utf-8')
                    # 确保符合 SSE 格式
                    yield f"data: {chunk}\n\n"
                except UnicodeDecodeError:
                    print("解码错误，跳过此块")
    except requests.RequestException as e:
        print(f"请求出错: {e}")


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/chat', methods=['GET'])
def chat():
    prompt = request.args.get('prompt')
    if prompt:
        return Response(stream_with_ollama(prompt), mimetype='text/event-stream')
    return jsonify({"error": "未提供有效的提示信息"}), 400


if __name__ == '__main__':
    app.run(debug=True)
    