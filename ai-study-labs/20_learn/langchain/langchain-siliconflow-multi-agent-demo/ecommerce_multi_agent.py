import os
from typing import List, Dict, Any, Optional
import requests
from langchain.chat_models.base import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.tools import Tool
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferMemory

# 1. SiliconFlow模型封装
class SiliconFlowLLM(BaseChatModel):
    """封装SiliconFlow模型以适配LangChain接口"""
    api_key: str
    model_name: str = "Qwen/Qwen2.5-72B-Instruct-128K"
    temperature: float = 0.7
    
    @property
    def _llm_type(self) -> str:
        return "siliconflow"
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,** kwargs: Any,
    ) -> ChatResult:
        # 转换消息格式为SiliconFlow API要求的格式
        formatted_messages = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                formatted_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                formatted_messages.append({"role": "assistant", "content": msg.content})
            elif isinstance(msg, SystemMessage):
                formatted_messages.append({"role": "system", "content": msg.content})
        
        # 构建API请求
        url = "https://api.siliconflow.cn/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": self.model_name,
            "messages": formatted_messages,
            "temperature": self.temperature,
            "max_tokens": 1024
        }
        
        if stop:
            payload["stop"] = stop
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            # 解析响应
            content = result["choices"][0]["message"]["content"]
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content=content))]
            )
        except Exception as e:
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content=f"调用出错: {str(e)}"))]
            )

# 2. 定义专业小智能体
class SupportAgent:
    """客服    客服相关专业智能体基类
    """
    def __init__(self, name: str, role: str, llm: BaseChatModel):
        self.name = name
        self.role = role
        self.llm = llm
        self.memory = ConversationBufferMemory(memory_key=f"{name}_memory", return_messages=True)
        self.agent = self._create_agent()
    
    def _create_agent(self) -> AgentExecutor:
        """创建智能体执行器"""
        system_prompt = f"""你是{self.name}，一位专业的{self.role}。
        你的职责是：
        1. 专注处理与你专业领域相关的问题
        2. 提供简洁、准确的回应
        3. 只回答你擅长的内容，不涉及其他领域
        """
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name=f"{self.name}_memory"),
            MessagesPlaceholder(variable_name="messages"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
        
        # 创建智能体（无工具）
        agent = create_openai_tools_agent(self.llm, [], prompt)
        
        return AgentExecutor(
            agent=agent,
            tools=[],
            memory=self.memory,
            verbose=False
        )
    
    def handle_request(self, query: str) -> str:
        """处理请求并返回结果"""
        response = self.agent.invoke({"messages": [HumanMessage(content=query)]})
        return response["output"]

# 3. 协调智能体
class Coordinator:
    """协调智能体，负责分配任务和整合结果"""
    def __init__(self, llm: BaseChatModel, agents: Dict[str, SupportAgent]):
        self.llm = llm
        self.agents = agents
        self.memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
        self.tools = self._create_tools()
        self.agent = self._create_coordinator_agent()
    
    def _create_tools(self) -> List[Tool]:
        """创建协调智能体可用的工具（调用其他智能体）"""
        tools = []
        
        # 为每个智能体创建工具
        for agent_name, agent in self.agents.items():
            def create_tool_func(agent_instance):
                def tool_func(query: str) -> str:
                    """调用专业智能体处理特定领域问题"""
                    print(f"调用工具: {agent_name} - 处理{agent.role}相关问题")
                    return agent_instance.handle_request(query)
                return tool_func
            
            tool = Tool(
                name=agent_name,
                func=create_tool_func(agent),
                description=f"调用{agent.role}处理相关问题"
            )
            tools.append(tool)
        
        # 添加结果整合工具
        tools.append(
            Tool(
                name="summarize",
                func=self._summarize_results,
                description="整合所有智能体的回答，生成最终回应"
            )
        )
        
        return tools
    
    def _summarize_results(self, input_str: str = "") -> str:
        """整合所有智能体的结果"""
        summary = "根据各部门专家分析，总结如下：\n\n"
        
        for agent_name, agent in self.agents.items():
            # 获取每个智能体的最新回应
            if agent.memory.chat_memory.messages:
                last_msg = agent.memory.chat_memory.messages[-1]
                if isinstance(last_msg, AIMessage):
                    summary += f"【{agent.role}】{last_msg.content}\n\n"
        
        summary += "如需进一步帮助，请随时告知。"
        return summary
    
    def _create_coordinator_agent(self) -> AgentExecutor:
        """创建协调智能体"""
        system_prompt = """你是电商客服协调智能体，负责管理多个专业客服智能体。
        你的工作流程：
        1. 理解用户的电商相关问题
        2. 判断需要哪些专业智能体协助
        3. 依次调用相应的智能体处理
        4. 所有智能体完成后，调用summarize工具生成最终回答
        
        可用智能体：
        - order_agent: 订单处理专家，处理订单查询、修改、取消等问题
        - payment_agent: 支付专家，处理支付失败、退款、发票等问题
        - logistics_agent: 物流专家，处理发货、运输、收货等问题
        - product_agent: 产品专家，处理产品咨询、退换货等问题
        
        请根据用户问题，合理分配任务并协调处理。"""
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            MessagesPlaceholder(variable_name="messages"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
        
        agent = create_openai_tools_agent(self.llm, self.tools, prompt)
        
        return AgentExecutor(
            agent=agent,
            tools=self.tools,
            memory=self.memory,
            verbose=True,
            handle_parsing_errors=True
        )
    
    def process_query(self, query: str) -> str:
        """处理用户查询"""
        print(f"messages,{query}")
        result = self.agent.invoke({"messages": [query]})
        return result["output"]

# 4. 运行示例
if __name__ == "__main__":
    # 获取API密钥
    api_key = "sk-REPLACE_WITH_YOUR_KEY"
    
    # 初始化基础模型
    llm = SiliconFlowLLM(
        api_key=api_key,
        temperature=0.6
    )
    
    # 创建专业智能体
    agents = {
        "order_agent": SupportAgent(
            name="order_agent",
            role="订单处理专家",
            llm=llm
        ),
        "payment_agent": SupportAgent(
            name="payment_agent",
            role="支付专家",
            llm=llm
        ),
        "logistics_agent": SupportAgent(
            name="logistics_agent",
            role="物流专家",
            llm=llm
        ),
        "product_agent": SupportAgent(
            name="product_agent",
            role="产品专家",
            llm=llm
        )
    }
    
    # 创建协调智能体
    coordinator = Coordinator(llm, agents)
    
    # 示例查询：包含多个领域的问题
    user_query = """我昨天下单购买了电子产品，付款后显示支付成功但订单状态还是未付款。
    另外想了解一下这个产品的保修期是多久，什么时候能发货？如果一直没发货我可以取消订单退款吗？"""
    
    print("用户问题:", user_query)
    print("\n智能体处理中...\n")
    
    # 处理查询
    response = coordinator.process_query(user_query)
    
    print("最终回复:\n")
    print(response)
