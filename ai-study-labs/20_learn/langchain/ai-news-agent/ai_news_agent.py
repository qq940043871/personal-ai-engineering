import os
import time
import json
import feedparser
import requests
import os  # 添加os模块导入
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Generator
from langchain.agents import Tool, AgentType, initialize_agent
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.schema import Document
from langchain.embeddings.base import Embeddings
from langchain.llms.base import LLM
from langchain.callbacks.base import BaseCallbackHandler
from langchain.text_splitter import RecursiveCharacterTextSplitter

# SiliconFlow嵌入模型集成
class SiliconFlowEmbeddings(Embeddings):
    """SiliconFlow嵌入模型的LangChain集成"""
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
    model_id: str = "Qwen/Qwen3-14B"  # 使用Qwen3模型
    temperature: float = 0.7
    max_tokens: int = 2048
    
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
            "stop": stop,
            "stream": False  # 非流式调用应设置为False
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()  # 检查请求是否成功
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            raise ValueError(f"调用SiliconFlow API失败: {str(e)}")
    
    def stream(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
    ) -> Generator[str, None, None]:
        """流式输出实现
        生成器函数，逐段返回模型输出
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
            "stop": stop,
            "stream": True  # 流式调用必须设置为True
        }
        
        try:
            with requests.post(url, headers=headers, json=data) as response:
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if line:
                        # 处理SSE格式，去掉"data: "前缀
                        line = line.decode('utf-8').strip()
                        if line.startswith('data: '):
                            line = line[6:]
                        if line == '[DONE]':
                            break
                            
                        try:
                            chunk = json.loads(line)
                            content = chunk["choices"][0]["delta"].get("content", "")
                            if content:
                                # 如果有回调管理器，通知令牌被生成
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

# 流式输出回调处理器
class StreamingHandler(BaseCallbackHandler):
    """处理流式输出的回调处理器"""
    def __init__(self):
        self.content = ""
        
    def on_llm_new_token(self, token: str, **kwargs) -> None:
        """当新的令牌生成时调用"""
        self.content += token
        print(token, end="", flush=True)  # 实时打印新令牌

# 微信公众号文章获取工具
class WechatArticleToolkit:
    """微信公众号文章获取和处理工具集"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.embeddings = SiliconFlowEmbeddings(api_key=api_key)
        self.ai_related_keywords = [
            "人工智能", "大模型", "机器学习", "深度学习", 
            "自然语言处理", "计算机视觉", "AI", "生成式AI",
            "ChatGPT", "LLM", "AIGC"
        ]
    
    def fetch_weekly_ai_articles(self, weeks: int = 1) -> Dict[str, Any]:
        """
        获取最近几周的AI相关微信公众号文章
        
        Args:
            weeks: 要获取的周数，默认为1
        
        Returns:
            包含文章列表的字典
        """
        try:
            # 计算日期范围
            end_date = datetime.now()
            start_date = end_date - timedelta(weeks=weeks)
            
            # 这里使用模拟数据，实际应用中可以：
            # 1. 使用第三方微信公众号API服务
            # 2. 使用爬虫爬取公开的微信公众号文章
            # 3. 通过RSS订阅获取
            
            # 模拟获取的AI相关公众号文章
            articles = [
                {
                    "title": "大模型最新进展：国产AI在医疗领域实现重大突破",
                    "author": "AI科技前沿",
                    "pub_date": (end_date - timedelta(days=2)).strftime("%Y-%m-%d"),
                    "summary": "本周，国内某AI企业发布了专为医疗影像分析设计的大模型，在肺部CT诊断准确率上超过了资深放射科医生，有望大幅提高早期肺癌检出率。",
                    "url": "https://example.com/ai-medical-breakthrough",
                    "content": "本周，国内某AI企业发布了专为医疗影像分析设计的大模型，该模型经过10万+病例训练，在肺部CT诊断准确率上达到98.7%，超过了资深放射科医生的平均水平。专家表示，这一突破有望大幅提高早期肺癌检出率，为患者争取宝贵的治疗时间。该模型已在国内30家三甲医院开始试点应用。"
                },
                {
                    "title": "生成式AI监管政策解读：如何平衡创新与安全",
                    "author": "人工智能治理研究",
                    "pub_date": (end_date - timedelta(days=4)).strftime("%Y-%m-%d"),
                    "summary": "最新发布的生成式AI服务管理暂行办法对AI内容生成、数据安全等方面做出了详细规定，本文将为您解读政策要点及对行业的影响。",
                    "url": "https://example.com/ai-regulation",
                    "content": "最新发布的生成式AI服务管理暂行办法对AI内容生成、数据安全等方面做出了详细规定。办法要求生成式AI服务提供者应当对生成的内容进行审核，防范虚假信息、违法信息。同时，办法也明确了鼓励创新的导向，对符合条件的AI企业提供政策支持。业内人士认为，这一政策将有助于规范发展，促进行业acee生长。"
                },
                {
                    "title": "AI+教育：个性化学习系统如何重塑课堂",
                    "author": "未来教育观察",
                    "pub_date": (end_date - timedelta(days=6)).strftime("%Y-%m-%d"),
                    "summary": "基于大模型的个性化学习系统正在多所学校试点，通过分析学生学习数据，为每个学生提供定制化学习方案，有效提升学习效率。",
                    "url": "https://example.com/ai-education",
                    "content": "基于大模型的个性化学习系统正在多所学校试点，该系统能够通过分析学生的课堂表现、作业完成情况等数据，精准识别学生的知识盲点，为每个学生提供定制化学习方案。试点数据显示，使用该系统的学生平均成绩提升了15%，学习兴趣也显著提高。教育专家表示，AI有望解决传统教育中一刀切的问题，实现真正的因材施教。"
                },
                {
                    "title": "小模型崛起：边缘计算时代的AI新趋势",
                    "author": "AI技术评论",
                    "pub_date": (end_date - timedelta(days=8)).strftime("%Y-%m-%d"),
                    "summary": "随着边缘计算的发展，适合在终端设备运行的小模型成为新热点，本文分析小模型与大模型的协同发展模式。",
                    "url": "https://example.com/small-models",
                    "content": "随着边缘计算的发展，适合在终端设备运行的小模型成为新热点。与需要强大算力支持的大模型不同，小模型体积小、响应快、隐私性好，特别适合手机、智能家居等终端设备。业内专家预测，未来将形成大模型负责训练，小模型负责推理的协同模式，既保证了AI能力，又兼顾了效率和隐私。多家手机厂商已宣布将在下一代产品中集成自研小模型。"
                }
            ]
            
            # 筛选出指定日期范围内的文章
            filtered_articles = [
                article for article in articles
                if start_date <= datetime.strptime(article["pub_date"], "%Y-%m-%d") <= end_date
            ]
            
            return {
                "status": "success",
                "count": len(filtered_articles),
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "articles": filtered_articles
            }
        except Exception as e:
            return {"status": "error", "message": f"获取文章失败: {str(e)}"}
    
    def summarize_articles(self, articles: List[Dict[str, Any]]) -> str:
        """
        总结多篇文章内容
        
        Args:
            articles: 文章列表
        
        Returns:
            总结文本
        """
        # 构建总结提示
        articles_text = "\n\n".join([
            f"标题: {article['title']}\n发布日期: {article['pub_date']}\n内容: {article['content']}"
            for article in articles
        ])
        
        prompt = f"""请你总结以下AI相关的新闻文章，要求：
        1. 提炼出3-5个核心趋势或重要事件
        2. 每个趋势或事件用简短的文字描述
        3. 保持客观中立的语气
        4. 总字数控制在500字以内
        
        文章内容：
        {articles_text}
        """
        
        # 使用SiliconFlow模型进行总结
        llm = SiliconFlowStreamingLLM(
            api_key=self.api_key,
            temperature=0.3,
            max_tokens=1024
        )
        
        return llm(prompt)

# AI新闻收集智能体
class AINewsAgent:
    """微信公众号AI新闻收集智能体"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.toolkit = WechatArticleToolkit(api_key)
        self.llm = SiliconFlowStreamingLLM(
            api_key=api_key,
            model_id="Qwen/Qwen3-14B",
            temperature=0.5,
            max_tokens=2048
        )
        self.agent = self._initialize_agent()
    
    def _initialize_agent(self):
        """初始化智能体"""
        # 定义工具
        tools = [
            Tool(
                name="FetchWeeklyAIArticles",
                func=self.toolkit.fetch_weekly_ai_articles,
                description="获取最近几周微信公众号上的AI相关文章。输入应为要获取的周数，如1表示最近一周，2表示最近两周，默认为1。"
            ),
            Tool(
                name="SummarizeArticles",
                func=self.toolkit.summarize_articles,
                description="总结多篇AI相关文章的核心内容，提炼关键趋势和事件。输入应为文章列表数据。"
            )
        ]
        
        # 创建提示模板
        prompt_template = """你是一位AI领域的新闻收集与分析智能体，负责每周收集微信公众号上的AI相关新闻并进行总结。

        你可以使用以下工具：
        {tools}

        使用工具的格式如下：
        思考：我需要使用什么工具来完成任务
        工具调用：{{"name":"工具名称","parameters":{{"参数名":"参数值"}}}}
        等待工具返回结果...
        思考：根据工具返回的结果，我是否需要进一步处理？

        注意事项：
        1. 严格按照指定格式调用工具
        2. 先获取新闻文章，再进行总结分析
        3. 总结应突出重点，涵盖主要趋势和重要事件
        4. 用中文清晰表达，结构合理

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
    
    def get_weekly_ai_news(self, weeks: int = 1, stream: bool = False) -> Generator[str, None, None]:
        """
        获取每周AI新闻并以流式方式输出
        """
        query = f"请收集并总结最近{weeks}周微信公众号上的AI相关新闻，包括核心趋势和重要事件。"
        
        if stream:
            # 流式输出实现
            streaming_handler = StreamingHandler()
            
            # 首先获取文章
            articles_result = self.toolkit.fetch_weekly_ai_articles(weeks)
            if articles_result["status"] != "success" or articles_result["count"] == 0:
                yield "未能获取到相关AI新闻文章。"
                return
            
            articles = articles_result["articles"]
            
            # 构建流式总结的提示
            prompt = f"""请你总结以下{len(articles)}篇最近{weeks}周的AI相关新闻文章：
            1. 按重要性排序，提炼出核心趋势或重要事件
            2. 每个要点简明扼要，说明事件内容和意义
            3. 保持客观中立，语言通俗易懂
            4. 可以适当分点阐述
            
            文章列表：
            {json.dumps(articles, ensure_ascii=False, indent=2)}
            """
            
            # 使用流式LLM生成总结
            for chunk in self.llm.stream(prompt):
                yield chunk
        else:
            result = self.agent.invoke({"input": query})  // 修复双大括号错误
            yield result["output"]

# 使用示例
if __name__ == "__main__":
    if "SILICONFLOW_API_KEY" not in os.environ:
        os.environ["SILICONFLOW_API_KEY"] = "sk-REPLACE_WITH_YOUR_KEY"
    
    api_key = os.environ["SILICONFLOW_API_KEY"]
    news_agent = AINewsAgent(api_key)
    
    print("===== 最近1周AI领域重要新闻总结 =====")
    print("正在生成总结...\n")
    
    for chunk in news_agent.get_weekly_ai_news(weeks=1, stream=True): 
        print(chunk, end="", flush=True)
    
    print("\n\n===== 总结结束 =====")
