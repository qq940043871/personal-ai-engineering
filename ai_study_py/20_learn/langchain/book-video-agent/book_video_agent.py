import os
import json
import time
from typing import List, Dict, Any, Optional, Generator
from langchain.agents import Tool, AgentType, initialize_agent
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.document_loaders import TextLoader, UnstructuredPDFLoader
from langchain.embeddings.base import Embeddings
from langchain.llms.base import LLM
from langchain.callbacks.base import BaseCallbackHandler
import requests
from datetime import datetime

# SiliconFlow嵌入模型集成
class SiliconFlowEmbeddings(Embeddings):
    """SiliconFlow嵌入模型的LangChainChain集成"""
    def __init__(self, api_key: str, model_id: str = "BAAI/bge-large-zh-v1.5"):
        self.api_key = api_key
        self.model_id = model_id
        self.api_url = "https://api.siliconflow.cn/v1/embeddings"
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        data = {
            "model": self.model_id,
            "input": texts
        }
        
        try:
            response = requests.post(self.api_url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            return [item["embedding"] for item in result["data"]]
        except Exception as e:
            raise ValueError(f"SiliconFlow嵌入API调用失败: {str(e)}")
    
    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

# SiliconFlow流式对话模型集成
class SiliconFlowStreamingLLM(LLM):
    """支持流式输出的SiliconFlow对话模型"""
    api_key: str
    model_id: str = "Qwen/Qwen3-14B"  # 使用通义千问中文模型
    temperature: float = 0.7
    max_tokens: int = 2048
    
    @property
    def _llm_type(self) -> str:
        return "siliconflow-streaming"
    
    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
    ) -> str:
        """非流式调用方法"""
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
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            raise ValueError(f"SiliconFlow对话API调用失败: {str(e)}")
    
    def stream(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
    ) -> Generator[str, None, None]:
        """流式输出实现"""
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
            "stop": stop,
            "stream": True  # 启用流式输出
        }
        
        try:
            with requests.post(url, headers=headers, json=data, stream=True) as response:
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if line:
                        # 处理SSE格式
                        line = line.decode('utf-8').strip()
                        if line.startswith('data: '):
                            line = line[6:]
                        if line == '[DONE]':
                            break
                            
                        try:
                            chunk = json.loads(line)
                            content = chunk["choices"][0]["delta"].get("content", "")
                            if content:
                                if run_manager:
                                    run_manager.on_llm_new_token(content)
                                yield content
                        except json.JSONDecodeError:
                            continue
                        except KeyError:
                            continue
        except Exception as e:
            raise ValueError(f"SiliconFlow流式API调用失败: {str(e)}")
    
    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

# 书籍处理和视频生成工具集
class BookVideoToolkit:
    """书籍处理和短视频生成工具集"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.embeddings = SiliconFlowEmbeddings(api_key=api_key)
        self.book_content = None
        self.book_summary = None
    
    def load_book_content(self, file_path: str) -> Dict[str, Any]:
        """
        加载书籍内容
        
        Args:
            file_path: 书籍文件路径（支持txt或pdf）
        
        Returns:
            包含书籍内容的字典
        """
        try:
            # 根据文件扩展名选择合适的加载器
            if file_path.endswith('.txt'):
                loader = TextLoader(file_path, encoding='utf-8')
            elif file_path.endswith('.pdf'):
                loader = UnstructuredPDFLoader(file_path)
            else:
                return {"status": "error", "message": "不支持的文件格式，仅支持txt和pdf"}
            
            documents = loader.load()
            
            # 合并所有文档内容
            full_content = "\n\n".join([doc.page_content for doc in documents])
            
            # 保存书籍内容
            self.book_content = full_content
            
            # 提取基本信息
            file_name = os.path.basename(file_path)
            book_title = os.path.splitext(file_name)[0]
            
            return {
                "status": "success",
                "title": book_title,
                "file_path": file_path,
                "content_length": len(full_content),
                "message": f"成功加载书籍内容，共{len(full_content)}个字符"
            }
        except Exception as e:
            return {"status": "error", "message": f"加载书籍内容失败: {str(e)}"}
    
    def summarize_book(self, max_length: int = 1000) -> Dict[str, Any]:
        """
        生成书籍摘要
        
        Args:
            max_length: 摘要最大长度
        
        Returns:
            包含书籍摘要的字典
        """
        try:
            if not self.book_content:
                return {"status": "error", "message": "请先加载书籍内容"}
            
            # 对书籍内容进行分割，避免超过模型输入限制
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=3000,
                chunk_overlap=200,
                length_function=len
            )
            chunks = text_splitter.split_text(self.book_content)
            
            # 先对每个 chunk 生成摘要
            llm = SiliconFlowStreamingLLM(
                api_key=self.api_key,
                temperature=0.4,
                max_tokens=500
            )
            
            chunk_summaries = []
            for i, chunk in enumerate(chunks):
                prompt = f"""请总结以下书籍内容片段，保留关键信息，长度控制在300字以内：
                
                内容片段 {i+1}/{len(chunks)}:
                {chunk}
                """
                summary = llm(prompt)
                chunk_summaries.append(summary)
            
            # 合并所有 chunk 摘要，生成全书摘要
            combined_summary = "\n\n".join(chunk_summaries)
            prompt = f"""请将以下书籍各部分的摘要整合成一个连贯的全书摘要，控制在{max_length}字左右，
            包含书籍的主要观点、核心论点和重要结论：
            
            {combined_summary}
            """
            
            final_summary = llm(prompt)
            self.book_summary = final_summary
            
            return {
                "status": "success",
                "summary": final_summary,
                "length": len(final_summary)
            }
        except Exception as e:
            return {"status": "error", "message": f"生成书籍摘要失败: {str(e)}"}
    
    def extract_key_points(self, count: int = 5) -> Dict[str, Any]:
        """
        提取书籍的关键点
        
        Args:
            count: 要提取的关键点数量
        
        Returns:
            包含关键点的字典
        """
        try:
            if not self.book_summary:
                if not self.book_content:
                    return {"status": "error", "message": "请先加载书籍内容"}
                # 如果没有摘要，先生成摘要
                summary_result = self.summarize_book()
                if summary_result["status"] != "success":
                    return summary_result
            
            llm = SiliconFlowStreamingLLM(
                api_key=self.api_key,
                temperature=0.3,
                max_tokens=1000
            )
            
            prompt = f"""请从以下书籍摘要中提取{count}个最关键的观点或知识点，
            每个观点用简短的一两句话描述，确保涵盖书籍的核心内容：
            
            书籍摘要：
            {self.book_summary}
            """
            
            key_points = llm(prompt)
            
            # 尝试将关键点转换为列表格式
            try:
                # 简单的解析，假设每个关键点以数字开头
                points_list = [point.strip() for point in key_points.split('\n') if point.strip()]
                return {
                    "status": "success",
                    "key_points": points_list,
                    "count": len(points_list)
                }
            except:
                return {
                    "status": "success",
                    "key_points": key_points,
                    "count": count
                }
        except Exception as e:
            return {"status": "error", "message": f"提取关键点失败: {str(e)}"}
    
    def generate_video_script(self, duration: int = 60, platform: str = "抖音") -> Dict[str, Any]:
        """
        生成书籍阅读短视频脚本
        
        Args:
            duration: 视频时长（秒）
            platform: 目标平台（抖音、B站、视频号等）
        
        Returns:
            包含视频脚本的字典
        """
        try:
            if not self.book_summary:
                return {"status": "error", "message": "请先生成书籍摘要"}
            
            # 获取关键点
            key_points_result = self.extract_key_points(count=5)
            if key_points_result["status"] != "success":
                return key_points_result
            
            key_points = key_points_result["key_points"]
            
            llm = SiliconFlowStreamingLLM(
                api_key=self.api_key,
                temperature=0.7,
                max_tokens=2000
            )
            
            prompt = f"""请为一本书籍生成一个适合{platform}平台的短视频脚本，视频时长约{duration}秒。
            
            书籍摘要：
            {self.book_summary}
            
            核心要点：
            {key_points}
            
            脚本要求：
            1. 结构清晰，包含开场、主体和结尾三个部分
            2. 开场要吸引人，能迅速抓住观众注意力
            3. 主体部分突出书籍的核心价值和关键观点
            4. 结尾要有号召力，鼓励观众阅读原著或点赞关注
            5. 语言风格符合{platform}平台特点，生动有趣
            6. 请注明每个部分的建议时长和视觉呈现方式
            7. 同时提供适合的背景音乐建议
            """
            
            video_script = llm(prompt)
            
            return {
                "status": "success",
                "duration": duration,
                "platform": platform,
                "script": video_script
            }
        except Exception as e:
            return {"status": "error", "message": f"生成视频脚本失败: {str(e)}"}
    
    def generate_narration(self) -> Dict[str, Any]:
        """
        生成短视频旁白文本
        
        Returns:
            包含旁白文本的字典
        """
        try:
            if not self.book_summary:
                return {"status": "error", "message": "请先生成书籍摘要"}
            
            llm = SiliconFlowStreamingLLM(
                api_key=self.api_key,
                temperature=0.6,
                max_tokens=1500
            )
            
            prompt = f"""请为书籍阅读短视频生成旁白文本，要求：
            1. 语言生动、有感染力，能够吸引观众听完
            2. 长度适中，适合30-60秒的短视频
            3. 突出书籍的核心价值和给读者带来的收获
            4. 避免过于学术化或晦涩的表达
            5. 结尾要有引导性，鼓励互动
            
            书籍摘要：
            {self.book_summary}
            """
            
            narration = llm(prompt)
            
            return {
                "status": "success",
                "narration": narration
            }
        except Exception as e:
            return {"status": "error", "message": f"生成旁白失败: {str(e)}"}

# 书籍短视频生成智能体
class BookVideoAgent:
    """书籍阅读短视频自动生成智能体"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.toolkit = BookVideoToolkit(api_key)
        self.llm = SiliconFlowStreamingLLM(
            api_key=api_key,
            model_id="Qwen/Qwen3-14B",
            temperature=0.6,
            max_tokens=2048
        )
        self.agent = self._initialize_agent()
    
    def _initialize_agent(self):
        """初始化智能体"""
        # 定义工具
        tools = [
            Tool(
                name="LoadBookContent",
                func=self.toolkit.load_book_content,
                description="加载书籍内容，支持txt和pdf格式。输入应为书籍文件的路径。"
            ),
            Tool(
                name="SummarizeBook",
                func=self.toolkit.summarize_book,
                description="生成书籍的整体摘要。输入应为摘要的最大长度（可选，默认1000字）。"
            ),
            Tool(
                name="ExtractKeyPoints",
                func=self.toolkit.extract_key_points,
                description="从书籍中提取关键观点。输入应为要提取的关键点数量（可选，默认5个）。"
            ),
            Tool(
                name="GenerateVideoScript",
                func=self.toolkit.generate_video_script,
                description="生成书籍阅读短视频脚本。输入应为视频时长(秒)和目标平台，格式为'时长,平台'（可选，默认60秒,抖音）。"
            ),
            Tool(
                name="GenerateNarration",
                func=self.toolkit.generate_narration,
                description="生成短视频的旁白文本。不需要输入参数。"
            )
        ]
        
        # 创建提示模板
        prompt_template = """你是一位专业的书籍阅读短视频生成智能体，能够将书籍内容转化为吸引人的短视频脚本。

        你可以使用以下工具：
        {tools}

        使用工具的格式如下：
        思考：我需要使用什么工具来完成任务
        工具调用：{{"name":"工具名称","parameters":{{"参数名":"参数值"}}}}
        等待工具返回结果...
        思考：根据工具返回的结果，我是否需要进一步调用工具？

        注意事项：
        1. 严格按照指定格式调用工具
        2. 必须先加载书籍内容，再进行后续处理
        3. 生成的视频脚本要适合短视频平台，内容精炼且有吸引力
        4. 确保提取的关键点能准确反映书籍核心内容

        现在开始处理用户的请求：
        {input}

        {agent_scratchpad}"""
        
        PROMPT = PromptTemplate(
            template=prompt_template,
            input_variables=["tools", "input", "agent_scratchpad"]
        )
        
        # 初始化智能体
        return initialize_agent(
            tools,
            self.llm,
            agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
            verbose=True,
            return_intermediate_steps=True,
            agent_kwargs={"prompt": PROMPT}
        )
    
    def create_book_video_content(self, book_path: str, duration: int = 60, 
                                platform: str = "抖音", stream: bool = True) -> Generator[str, None, None]:
        """
        生成书籍阅读短视频的完整内容
        
        Args:
            book_path: 书籍文件路径
            duration: 视频时长（秒）
            platform: 目标平台
            stream: 是否以流式输出
        
        Returns:
            流式输出的视频内容
        """
        query = f"请为书籍'{book_path}'生成适合{platform}平台的{duration}秒短视频内容，包括摘要、关键点、完整脚本和旁白。"
        
        if stream:
            # 分步处理并流式输出
            steps = [
                ("加载书籍内容", self.toolkit.load_book_content, [book_path]),
                ("生成书籍摘要", self.toolkit.summarize_book, []),
                ("提取关键观点", self.toolkit.extract_key_points, []),
                ("生成视频脚本", self.toolkit.generate_video_script, [duration, platform]),
                ("生成视频旁白", self.toolkit.generate_narration, [])
            ]
            
            for step_name, func, args in steps:
                yield f"\n===== {step_name} ====="
                try:
                    if len(args) == 2:
                        result = func(args[0], args[1])
                    elif len(args) == 1:
                        result = func(args[0])
                    else:
                        result = func()
                    
                    if result["status"] == "success":
                        # 流式生成结果展示
                        content = result.get("summary") or result.get("key_points") or result.get("script") or result.get("narration") or str(result)
                        
                        if isinstance(content, list):
                            content = "\n".join(content)
                            
                        # 模拟流式输出
                        for i in range(0, len(content), 50):
                            chunk = content[i:i+50]
                            yield chunk
                            time.sleep(0.1)  # 控制流速度
                    else:
                        yield f"错误: {result['message']}"
                except Exception as e:
                    yield f"{step_name}失败: {str(e)}"
        else:
            # 非流式输出
            result = self.agent({"input": query})
            yield result["output"]

# 使用示例
if __name__ == "__main__":
    # 设置API密钥
    if "SILICONFLOW_API_KEY" not in os.environ:
        # 实际使用中请通过环境变量设置
        os.environ["SILICONFLOW_API_KEY"] = "sk-REPLACE_WITH_YOUR_KEY"
    
    # 初始化智能体
    api_key = os.environ["SILICONFLOW_API_KEY"]
    book_agent = BookVideoAgent(api_key)
    
    # 指定书籍路径（请替换为实际的书籍文件路径）
    book_path = "D:\\workspace\\p001_ai_study_py\\01_langchain\\book-video-agent\\example_book.txt"  # 可以是txt或pdf文件
    
    # 创建书籍短视频内容，以流式输出
    print("===== 书籍阅读短视频内容生成 =====")
    print(f"正在处理书籍: {book_path}\n")
    
    # 流式输出结果
    for chunk in book_agent.create_book_video_content(
        book_path=book_path,
        duration=60,
        platform="抖音",
        stream=True
    ):
        print(chunk, end="", flush=True)
    
    print("\n\n===== 内容生成完成 =====")
