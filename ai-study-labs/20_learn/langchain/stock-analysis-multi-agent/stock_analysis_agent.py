import os
from typing import Annotated, List, Tuple, TypedDict, Optional
from typing import List, Dict, Any, Optional
import requests
from langchain.chat_models.base import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain.prompts import ChatPromptTemplate
from langchain.tools import tool
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages

# 配置SiliconFlow模型
os.environ["SILICONFLOW_API_KEY"] = "sk-REPLACE_WITH_YOUR_KEY"  # 替换为你的API密钥
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
MODEL_NAME = "Qwen/Qwen2.5-72B-Instruct-128K"  # 可根据需要更换模型

# 1. 定义SiliconFlow模型封装类
class SiliconFlowChat(BaseChatModel):
    """SiliconFlow对话模型封装类"""
    api_key: str
    model_name: str
    api_base: str = "https://api.siliconflow.cn/v1/chat/completions"
    temperature: float = 0.7
    max_tokens: int = 1024

    @property
    def _llm_type(self) -> str:
        return "siliconflow-chat"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        print(f"SiliconFlowChat._generate 方法开始执行")
        # 转换消息格式
        siliconflow_messages = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                siliconflow_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                siliconflow_messages.append({"role": "assistant", "content": msg.content})
            elif isinstance(msg, SystemMessage):
                siliconflow_messages.append({"role": "system", "content": msg.content})
        print(f"_generate:{len(siliconflow_messages)}")
        # 构造请求
        payload = {
            "model": self.model_name,
            "messages": siliconflow_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,** kwargs
        }
        
        if stop:
            payload["stop"] = stop

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            response = requests.post(
                url=self.api_base,
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            result = response.json()
            print(f"模型响应: 完成原因={result['choices'][0]['finish_reason']}, 生成 tokens={result['usage']['completion_tokens']}")
            # 解析结果
            ai_message = result["choices"][0]["message"]["content"]
            generation = ChatGeneration(
                message=AIMessage(content=ai_message),
                generation_info=result
            )
            print(f"SiliconFlowChat._generate 方法执行完成")
            return ChatResult(generations=[generation])
        except Exception as e:
            print(f"SiliconFlowChat._generate 方法执行出错: {str(e)}")
            return ChatResult(generations=[ChatGeneration(
                message=AIMessage(content=f"API调用出错: {str(e)}"),
                generation_info=None
            )])

# 定义工具 - 股票数据获取
class StockTools:
    @tool("get_stock_basic_info")
    def get_stock_basic_info(stock_code: str) -> dict:
        """获取股票基本信息，包括公司名称、行业、上市日期等"""
        # 实际应用中应替换为真实的股票数据API
        # 这里使用模拟数据
        print(f"获取股票 {stock_code} 的基本信息...")
        return {
            "stock_code": stock_code,
            "name": f"模拟公司_{stock_code}",
            "industry": "科技行业",
            "listing_date": "2010-01-15",
            "market_cap": "1200亿",
            "employees": 15000
        }
    
    @tool("get_financial_data")
    def get_financial_data(stock_code: str, period: str = "latest") -> dict:
        """获取股票财务数据，包括营收、利润、利润率等"""
        # 实际应用中应替换为真实的财务数据API
        print(f"获取股票 {stock_code} 的财务数据...")
        return {
            "stock_code": stock_code,
            "revenue": "85亿元",
            "revenue_growth": "15.2%",
            "net_profit": "12.3亿元",
            "net_profit_growth": "22.5%",
            "gross_margin": "42.3%",
            "net_margin": "14.5%",
            "debt_ratio": "35.2%",
            "period": "2023年Q4"
        }
    
    @tool("get_stock_price_data")
    def get_stock_price_data(stock_code: str, days: int = 90) -> dict:
        """获取股票价格数据，包括当前价格、历史价格走势、成交量等"""
        # 实际应用中应替换为真实的股票价格API
        print(f"获取股票 {stock_code} 的价格数据...")
        return {
            "stock_code": stock_code,
            "current_price": 156.8,
            "price_change_1d": 2.3,
            "price_change_7d": 5.8,
            "price_change_30d": -3.2,
            "price_change_90d": 12.5,
            "volume": "850万股",
            "pe_ratio": 28.5,
            "pb_ratio": 4.2,
            "52_week_high": 182.5,
            "52_week_low": 112.3
        }
    
    @tool("get_industry_news")
    def get_industry_news(industry: str, limit: int = 5) -> list:
        """获取行业相关新闻"""
        # 实际应用中应替换为真实的新闻API
        print(f"获取 {industry} 行业新闻...")
        return [
            {
                "title": f"{industry}行业迎来政策利好，预计增长加速",
                "source": "财经新闻网",
                "date": "2023-05-10",
                "summary": f"最新政策出台将对{industry}行业形成长期利好，分析师预计未来两年行业增长率将提升至15%以上。"
            },
            {
                "title": f"{industry}行业竞争加剧，头部企业优势明显",
                "source": "产业观察报",
                "date": "2023-05-08",
                "summary": f"{industry}行业集中度正在提升，头部企业凭借技术和规模优势，市场份额持续扩大。"
            }
        ]

# 定义智能体状态
class AgentState(TypedDict):
    stock_code: str
    messages: Annotated[List[HumanMessage | AIMessage | SystemMessage], add_messages]
    basic_info: Optional[dict] = None
    financial_data: Optional[dict] = None
    price_data: Optional[dict] = None
    industry_news: Optional[list] = None
    fundamental_analysis: Optional[str] = None
    price_analysis: Optional[str] = None
    final_recommendation: Optional[str] = None

# 初始化工具
tools = StockTools()

# 基本面分析智能体
def fundamental_analyst(state: AgentState) -> AgentState:
    print("基本面分析智能体开始工作...")
    
    # 如果没有基础数据，先获取
    if not state["basic_info"]:
        state["basic_info"] = tools.get_stock_basic_info(state["stock_code"])
    
    if not state["financial_data"]:
        state["financial_data"] = tools.get_financial_data(state["stock_code"])
    
    if not state["industry_news"]:
        industry = state["basic_info"]["industry"]
        state["industry_news"] = tools.get_industry_news(industry)
    
    # 构建分析提示
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位资深股票基本面分析师，擅长分析公司的财务状况和行业地位。
        请根据提供的公司基本信息、财务数据和行业新闻，进行全面的基本面分析。
        分析应包括但不限于：公司盈利能力、成长能力、财务健康状况、行业地位、竞争优势、潜在风险等。
        分析要客观、专业，基于事实数据。"""),
        ("human", """
        股票代码: {stock_code}
        基本信息: {basic_info}
        财务数据: {financial_data}
        行业新闻: {industry_news}
        
        请基于以上信息，撰写一份详细的基本面分析报告。
        """)
    ])
    
    # 调用LLM进行分析
    llm = SiliconFlowChat(
        api_key=os.environ["SILICONFLOW_API_KEY"],
        model_name=MODEL_NAME,
        temperature=0.6
    )

    chain = prompt | llm
    result = chain.invoke({
        "stock_code": state["stock_code"],
        "basic_info": state["basic_info"],
        "financial_data": state["financial_data"],
        "industry_news": state["industry_news"]
    })
    
    # 更新状态
    state["fundamental_analysis"] = result.content
    state["messages"].append(AIMessage(content=f"基本面分析完成: {result.content[:100]}..."))
    
    return state

# 股价分析智能体
def price_analyst(state: AgentState) -> AgentState:
    print("股价分析智能体开始工作...")
    
    # 如果没有价格数据，先获取
    if not state["price_data"]:
        state["price_data"] = tools.get_stock_price_data(state["stock_code"])
    
    # 构建分析提示
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位资深股票技术分析师，擅长分析股票价格走势和市场情绪。
        请根据提供的股票价格数据，进行全面的技术面分析。
        分析应包括但不限于：当前价格位置、近期走势、估值水平(PE、PB)、成交量变化、支撑位和阻力位、
        与52周高低点的比较、短期和中期趋势判断等。
        分析要客观、专业，基于事实数据。"""),
        ("human", """
        股票代码: {stock_code}
        价格数据: {price_data}
        
        请基于以上信息，撰写一份详细的股价分析报告。
        """)
    ])
    
    # 调用LLM进行分析
    llm = SiliconFlowChat(
        api_key=os.environ["SILICONFLOW_API_KEY"],
        model_name=MODEL_NAME,
        temperature=0.6
    )
    chain = prompt | llm
    result = chain.invoke({
        "stock_code": state["stock_code"],
        "price_data": state["price_data"]
    })
    
    # 更新状态
    state["price_analysis"] = result.content
    state["messages"].append(AIMessage(content=f"股价分析完成: {result.content[:100]}..."))
    
    return state

# 综合分析智能体
def investment_advisor(state: AgentState) -> AgentState:
    print("投资建议智能体开始工作...")
    
    # 构建综合分析提示
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位资深投资顾问，擅长综合各方面信息给出专业的投资建议。
        请根据提供的基本面分析和股价分析，结合当前市场环境，给出全面的投资建议。
        建议应包括：投资评级(买入、持有、卖出)、目标价区间、投资周期、主要支撑因素、
        潜在风险点、操作策略等。
        建议要客观、平衡，既说明利好因素，也不回避风险。"""),
        ("human", """
        股票代码: {stock_code}
        基本面分析: {fundamental_analysis}
        股价分析: {price_analysis}
        
        请基于以上信息，撰写一份完整的投资建议报告。
        """)
    ])
    
    # 调用LLM生成建议
    llm = SiliconFlowChat(
        api_key=os.environ["SILICONFLOW_API_KEY"],
        model_name=MODEL_NAME,
        temperature=0.6
    )
    chain = prompt | llm
    result = chain.invoke({
        "stock_code": state["stock_code"],
        "fundamental_analysis": state["fundamental_analysis"],
        "price_analysis": state["price_analysis"]
    })
    
    # 更新状态
    state["final_recommendation"] = result.content
    state["messages"].append(AIMessage(content=f"投资建议生成完成: {result.content[:100]}..."))
    
    return state

# 定义工作流
def create_workflow():
    # 创建状态图
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("fundamental_analyst", fundamental_analyst)
    workflow.add_node("price_analyst", price_analyst)
    workflow.add_node("investment_advisor", investment_advisor)
    
    # 定义流程
    workflow.add_edge(START, "fundamental_analyst")
    workflow.add_edge("fundamental_analyst", "price_analyst")
    workflow.add_edge("price_analyst", "investment_advisor")
    workflow.add_edge("investment_advisor", END)
    
    # 编译工作流
    return workflow.compile()

# 运行股票分析多智能体
def analyze_stock(stock_code: str) -> dict:
    # 初始化工作流
    app = create_workflow()
    
    # 初始状态
    initial_state = {
        "stock_code": stock_code,
        "messages": [HumanMessage(content=f"请分析股票 {stock_code} 并给出投资建议")],
        "basic_info": None,
        "financial_data": None,
        "price_data": None,
        "industry_news": None,
        "fundamental_analysis": None,
        "price_analysis": None,
        "final_recommendation": None
    }
    
    # 运行工作流
    result = app.invoke(initial_state)
    
    return {
        "stock_code": stock_code,
        "fundamental_analysis": result["fundamental_analysis"],
        "price_analysis": result["price_analysis"],
        "final_recommendation": result["final_recommendation"]
    }

# 示例运行
if __name__ == "__main__":
    # 分析示例股票
    stock_code = "600000"  # 示例股票代码
    analysis_result = analyze_stock(stock_code)
    
    # 打印结果
    print(f"\n===== 股票 {stock_code} 分析报告 =====")
    print("\n【基本面分析】")
    print(analysis_result["fundamental_analysis"])
    
    print("\n【股价分析】")
    print(analysis_result["price_analysis"])
    
    print("\n【最终投资建议】")
    print(analysis_result["final_recommendation"])
    
    print(analysis_result["final_recommendation"])
