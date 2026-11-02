import os
import requests
import datetime
import yfinance as yf
from typing import List, Dict, Any, Optional, Tuple, Generator
from langchain.agents import Tool, AgentType, initialize_agent
from langchain.chains import LLMChain, RetrievalQA
from langchain.prompts import PromptTemplate
# 从langchain_community导入Chroma
from langchain_community.vectorstores import Chroma
# 从langchain_community导入TextLoader
from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain.embeddings.base import Embeddings
from langchain.llms.base import LLM
# 从langchain_core导入CallbackManagerForLLMRun
from langchain_core.callbacks import CallbackManagerForLLMRun

# 确保中文显示正常
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]

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

# SiliconFlow对话模型集成
class SiliconFlowLLM(LLM):
    """SiliconFlow对话模型的LangChain集成"""
    api_key: str
    model_id: str = "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"  # 使用通义千问中文模型
    temperature: float = 0.7
    max_tokens: int = 2048
    
    @property
    def _llm_type(self) -> str:
        return "siliconflow"
    
    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
    ) -> str:
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
    
    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

# 股票数据获取工具
class StockDataToolkit:
    """股票数据获取和处理工具集"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        # 初始化向量存储用于存储股票公告等文本信息
        self.embeddings = SiliconFlowEmbeddings(api_key=api_key)
        self.vector_store = None
        
    def get_stock_basic_info(self, stock_code: str) -> Dict[str, Any]:
        """获取股票基本面信息"""
        try:
            # 处理股票代码，增加市场后缀
            if stock_code.startswith(('60', '688')):  # 沪市
                ticker = f"{stock_code}.SS"
            elif stock_code.startswith(('00', '30')):  # 深市
                ticker = f"{stock_code}.SZ"
            else:  # 默认美股处理
                ticker = stock_code
                
            stock = yf.Ticker(ticker)
            
            # 获取基本信息
            info = stock.info
            
            # 提取关键基本面信息
            basic_info = {
                "公司名称": info.get("longName", "未知"),
                "行业": info.get("industry", "未知"),
                "市值": info.get("marketCap", "未知"),
                "市盈率": info.get("forwardPE", "未知"),
                "市净率": info.get("priceToBook", "未知"),
                "营收增长率": info.get("revenueGrowth", "未知"),
                "净利润率": info.get("netIncomeToCommon", "未知"),
                "股息率": info.get("dividendYield", "未知"),
                "52周最高价": info.get("fiftyTwoWeekHigh", "未知"),
                "52周最低价": info.get("fiftyTwoWeekLow", "未知"),
                "当前价格": info.get("currentPrice", "未知")
            }
            
            return {"status": "success", "data": basic_info}
        except Exception as e:
            return {"status": "error", "message": f"获取基本面信息失败: {str(e)}"}
    
    def get_stock_price_history(self, stock_code: str, period: str = "1y") -> Dict[str, Any]:
        """获取股票价格历史数据"""
        try:
            # 处理股票代码
            if stock_code.startswith(('60', '688')):
                ticker = f"{stock_code}.SS"
            elif stock_code.startswith(('00', '30')):
                ticker = f"{stock_code}.SZ"
            else:
                ticker = stock_code
                
            stock = yf.Ticker(ticker)
            hist = stock.history(period=period)
            
            # 转换为字典格式
            price_data = {
                "日期": [date.strftime("%Y-%m-%d") for date in hist.index],
                "开盘价": hist["Open"].tolist(),
                "收盘价": hist["Close"].tolist(),
                "最高价": hist["High"].tolist(),
                "最低价": hist["Low"].tolist(),
                "成交量": hist["Volume"].tolist()
            }
            
            # 生成简单的走势分析
            latest_price = price_data["收盘价"][-1] if price_data["收盘价"] else None
            earliest_price = price_data["收盘价"][0] if price_data["收盘价"] else None
            
            trend_analysis = "无法分析走势"
            if latest_price and earliest_price and earliest_price != 0:
                change_percent = ((latest_price - earliest_price) / earliest_price) * 100
                if change_percent > 0:
                    trend_analysis = f"上涨 {change_percent:.2f}%"
                elif change_percent < 0:
                    trend_analysis = f"下跌 {abs(change_percent):.2f}%"
                else:
                    trend_analysis = "持平"
            
            return {
                "status": "success",
                "data": price_data,
                "trend": trend_analysis,
                "period": period
            }
        except Exception as e:
            return {"status": "error", "message": f"获取股价历史数据失败: {str(e)}"}
    
    def get_stock_announcements(self, stock_code: str) -> Dict[str, Any]:
        """获取股票公告信息"""
        try:
            # 这里使用模拟数据，实际应用中可以对接交易所API或财经网站
            # 真实场景下可以爬取巨潮资讯网等平台的公告
            announcements = [
                {
                    "title": f"{stock_code}关于2023年度利润分配实施公告",
                    "date": (datetime.datetime.now() - datetime.timedelta(days=10)).strftime("%Y-%m-%d"),
                    "content": "公司2023年度利润分配方案为：每10股派发现金红利5.20元（含税），股权登记日为2024年6月15日，除权除息日为2024年6月16日。"
                },
                {
                    "title": f"{stock_code}2024年第一季度报告",
                    "date": (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d"),
                    "content": "公司2024年第一季度实现营业收入12.5亿元，同比增长15.3%；归属于上市公司股东的净利润2.1亿元，同比增长8.7%。公司经营状况良好，主要产品市场需求稳定增长。"
                },
                {
                    "title": f"{stock_code}关于签订重大合同的公告",
                    "date": (datetime.datetime.now() - datetime.timedelta(days=45)).strftime("%Y-%m-%d"),
                    "content": "公司近日与某大型企业签订了一份金额为5.8亿元的销售合同，合同期限为2年。该合同的履行将对公司未来两年的经营业绩产生积极影响。"
                }
            ]
            
            # 将公告转换为文档并存储到向量数据库
            documents = []
            for ann in announcements:
                content = f"日期: {ann['date']}\n标题: {ann['title']}\n内容: {ann['content']}"
                documents.append(Document(
                    page_content=content,
                    metadata={"source": "announcement", "date": ann["date"], "title": ann["title"]}
                ))
            
            # 分割文档
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
            splits = text_splitter.split_documents(documents)
            
            # 创建向量存储
            self.vector_store = Chroma.from_documents(
                documents=splits,
                embedding=self.embeddings,
                persist_directory=f"./stock_announcements_{stock_code}"
            )
            self.vector_store.persist()
            
            return {
                "status": "success",
                "data": announcements,
                "count": len(announcements)
            }
        except Exception as e:
            return {"status": "error", "message": f"获取公告信息失败: {str(e)}"}
    
    def analyze_announcements(self, stock_code: str, query: str) -> Dict[str, Any]:
        """分析股票公告，回答相关问题"""
        try:
            if not self.vector_store:
                # 尝试加载已有的向量存储
                self.vector_store = Chroma(
                    persist_directory=f"./stock_announcements_{stock_code}",
                    embedding_function=self.embeddings
                )
            
            # 创建检索链
            qa_chain = RetrievalQA.from_chain_type(
                llm=SiliconFlowLLM(api_key=self.api_key),
                chain_type="stuff",
                retriever=self.vector_store.as_retriever(search_kwargs={"k": 2}),
                return_source_documents=True
            )
            
            result = qa_chain({"query": query})
            
            return {
                "status": "success",
                "answer": result["result"],
                "sources": [doc.metadata["title"] for doc in result["source_documents"]]
            }
        except Exception as e:
            return {"status": "error", "message": f"分析公告失败: {str(e)}"}

# 股票分析智能体
class StockAnalysisAgent:
    """股票分析超级智能体"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.toolkit = StockDataToolkit(api_key)
        self.llm = SiliconFlowLLM(
            api_key=api_key,
            model_id="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
            temperature=0.3,  # 降低温度，使分析更严谨
            max_tokens=2048
        )
        self.agent = self._initialize_agent()
    
    def _initialize_agent(self):
        """初始化智能体"""
        # 定义工具
        tools = [
            Tool(
                name="GetStockBasicInfo",
                func=self.toolkit.get_stock_basic_info,
                description="获取股票的基本面信息，包括公司名称、行业、市值、市盈率、市净率等关键财务指标。输入应为股票代码，如600036。"
            ),
            Tool(
                name="GetStockPriceHistory",
                func=self.toolkit.get_stock_price_history,
                description="获取股票的历史价格走势数据，包括开盘价、收盘价、最高价、最低价和成交量。输入应为股票代码和时间周期（可选，如1y表示1年，默认1年），格式为'股票代码,周期'。"
            ),
            Tool(
                name="GetStockAnnouncements",
                func=self.toolkit.get_stock_announcements,
                description="获取股票的最新公告信息，包括利润分配、季度报告、重大合同等。输入应为股票代码。"
            ),
            Tool(
                name="AnalyzeAnnouncements",
                func=self.toolkit.analyze_announcements,
                description="分析股票公告并回答相关问题。输入应为股票代码和问题，格式为'股票代码,问题'。"
            )
        ]
        
        # 创建提示模板
        prompt_template = """你是一位专业的股票分析智能体，你的任务是帮助用户分析指定股票并提供投资建议。

        你可以使用以下工具获取信息：
        {tools}

        使用工具的格式如下：
        思考：我需要使用什么工具来回答这个问题
        工具调用：{{"name":"工具名称","parameters":{{"参数名":"参数值"}}}}
        等待工具返回结果...
        思考：根据工具返回的结果，我是否需要进一步调用工具？如果不需要，就整理结果给出最终回答

        注意事项：
        1. 严格按照指定格式调用工具
        2. 每次只能调用一个工具
        3. 先获取足够的信息，再进行分析和建议
        4. 投资建议应基于收集到的事实数据，避免主观臆断
        5. 必须提醒用户投资有风险，建议仅供参考

        现在开始处理用户的问题：
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
    
    def analyze_stock(self, stock_code: str) -> Dict[str, Any]:
        """分析指定股票并提供投资建议"""
        query = f"""请分析股票代码为{stock_code}的股票，包括以下方面：
        1. 基本面分析：公司概况、财务指标等
        2. 近期股价走势分析
        3. 重要公告解读
        4. 综合投资建议
        
        请提供详细的分析报告，包括数据支持和逻辑推理。"""
        
        try:
            result = self.agent({"input": query})
            return {
                "status": "success",
                "stock_code": stock_code,
                "analysis": result["output"],
                "intermediate_steps": result["intermediate_steps"]
            }
        except Exception as e:
            return {"status": "error", "message": f"股票分析失败: {str(e)}"}

# 使用示例
if __name__ == "__main__":
    # 设置API密钥
    if "SILICONFLOW_API_KEY" not in os.environ:
        # 实际使用中请通过环境变量设置
        os.environ["SILICONFLOW_API_KEY"] = "sk-REPLACE_WITH_YOUR_KEY"
        print("警告：未设置SILICONFLOW_API_KEY环境变量，已使用默认值")
    
    # 初始化智能体
    api_key = os.environ["SILICONFLOW_API_KEY"]
    stock_agent = StockAnalysisAgent(api_key)
    
    # 分析指定股票，例如招商银行(600036)
    stock_code = "600036"
    print(f"开始分析股票: {stock_code}")
    analysis_result = stock_agent.analyze_stock(stock_code)
    
    if analysis_result["status"] == "success":
        print("\n===== 股票分析报告 =====")
        print(analysis_result["analysis"])
    else:
        print(f"分析失败: {analysis_result['message']}")
