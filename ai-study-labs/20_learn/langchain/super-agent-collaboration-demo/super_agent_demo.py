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

# 1. SiliconFlow模型封装 - 带详细打印
class SiliconFlowLLM(BaseChatModel):
    """封装SiliconFlow模型以适配LangChain接口，带请求应答打印"""
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
        print("\n===== 调用SiliconFlow模型 =====")
        # 打印输入消息
        print("【发送给模型的消息】:")
        for msg in messages:
            role = "用户" if isinstance(msg, HumanMessage) else "助手" if isinstance(msg, AIMessage) else "系统"
            print(f"{role}: {msg.content[:100]}...")  # 只显示前100字符
        
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
            print(f"【调用模型】: {self.model_name}")
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            # 解析响应
            content = result["choices"][0]["message"]["content"]
            print("【模型返回结果】:", content[:100] + "...")  # 只显示前100字符
            print("===== SiliconFlow模型调用结束 =====")
            
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content=content))]
            )
        except Exception as e:
            error_msg = f"调用出错: {str(e)}"
            print(f"【模型调用错误】: {error_msg}")
            print("===== SiliconFlow模型调用结束 =====")
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content=error_msg))]
            )

# 2. 定义专业小智能体 - 带详细打印
class SpecialistAgent:
    """专业小智能体基类，带请求应答打印"""
    def __init__(self, name: str, role: str, llm: BaseChatModel):
        self.name = name
        self.role = role
        self.llm = llm
        self.memory = ConversationBufferMemory(memory_key=f"{name}_memory", return_messages=True)
        self.agent = self._create_agent()
        print(f"初始化小智能体: {self.name} ({self.role})")
    
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
        """处理请求并返回结果，带打印输出"""
        print(f"\n===== 小智能体 {self.name} 收到请求 =====")
        print(f"【请求内容】: {query}")
        
        response = self.agent.invoke({"messages": [HumanMessage(content=query)]})
        result = response["output"]
        
        print(f"【{self.name} 回应】: {result[:100]}...")  # 只显示前100字符
        print(f"===== 小智能体 {self.name} 处理结束 =====")
        return result

# 3. 超级协调智能体 - 带详细打印
class SuperCoordinator:
    """超级协调智能体，负责分配任务和整合结果，带详细打印"""
    def __init__(self, llm: BaseChatModel, agents: Dict[str, SpecialistAgent]):
        self.llm = llm
        self.agents = agents
        self.memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
        self.tools = self._create_tools()
        self.agent = self._create_coordinator_agent()
        print("初始化超级协调智能体完成")
    
    def _create_tools(self) -> List[Tool]:
        """创建协调智能体可用的工具（调用其他智能体）"""
        tools = []
        print("\n===== 创建工具列表 =====")
        
        # 为每个智能体创建工具
        for agent_name, agent in self.agents.items():
            def create_tool_func(agent_instance):
                def tool_func(query: str) -> str:
                    print(f"\n【工具调用】: 调用 {agent_instance.name} 处理: {query[:50]}...")
                    result = agent_instance.handle_request(query)
                    print(f"【工具返回】: {agent_instance.name} 处理完成")
                    return result
                return tool_func
            
            tool = Tool(
                name=agent_name,
                func=create_tool_func(agent),
                description=f"调用{agent.role}处理相关问题"
            )
            tools.append(tool)
            print(f"创建工具: {agent_name} - {agent.role}")
        
        # 添加结果整合工具
        def summarize_func(input_str: str = "") -> str:
            print("\n【工具调用】: 调用 summarize 工具整合结果")
            result = self._summarize_results()
            print("【工具返回】: 结果整合完成")
            return result
        
        tools.append(
            Tool(
                name="summarize",
                func=summarize_func,
                description="整合所有智能体的回答，生成最终回应"
            )
        )
        print("创建工具: summarize - 结果整合工具")
        print("===== 工具列表创建完成 =====")
        
        return tools
    
    def _summarize_results(self) -> str:
        """整合所有智能体的结果"""
        summary = "根据各专家分析，总结如下：\n\n"
        
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
        system_prompt = """你是超级协调智能体，负责管理多个专业智能体。
        你的工作流程：
        1. 理解用户的问题
        2. 判断需要哪些专业智能体协助
        3. 依次调用相应的智能体处理
        4. 所有智能体完成后，调用summarize工具生成最终回答
        
        可用智能体：
        - marketing_agent: 市场专家，处理市场分析、推广策略问题
        - product_agent: 产品专家，处理产品设计、功能问题
        - sales_agent: 销售专家，处理销售策略、客户转化问题
        
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
        """处理用户查询，带详细打印"""
        print("\n\n===== 超级智能体开始处理用户查询 =====")
        print(f"【用户查询】: {query}")
        
        result = self.agent.invoke({"messages": [query]})
        
        print("\n===== 超级智能体处理完成 =====")
        print(f"【最终结果】: {result['output'][:100]}...")
        return result["output"]

# 4. 运行示例
if __name__ == "__main__":
    print("===== 多智能体协作系统启动 =====")
    
    # 获取API密钥
    api_key = "sk-REPLACE_WITH_YOUR_KEY"
    
    # 初始化基础模型
    print("\n===== 初始化SiliconFlow模型 =====")
    llm = SiliconFlowLLM(
        api_key=api_key,
        temperature=0.6
    )
    
    # 创建专业智能体
    print("\n===== 创建专业小智能体 =====")
    agents = {
        "marketing_agent": SpecialistAgent(
            name="marketing_agent",
            role="市场分析专家，负责市场趋势分析和推广策略",
            llm=llm
        ),
        "product_agent": SpecialistAgent(
            name="product_agent",
            role="产品设计专家，负责产品功能设计和用户体验优化",
            llm=llm
        ),
        "sales_agent": SpecialistAgent(
            name="sales_agent",
            role="销售策略专家，负责销售渠道和客户转化",
            llm=llm
        )
    }
    
    # 创建超级协调智能体
    print("\n===== 创建超级协调智能体 =====")
    coordinator = SuperCoordinator(llm, agents)
    
    # 示例查询：包含多个领域的问题
    user_query = """我想开发一款面向年轻人的运动健身APP，需要分析市场需求、设计核心功能，并制定销售推广策略，
    请各专家给出建议，包括当前市场趋势、必备功能以及如何有效获取第一批用户。"""
    
    # 处理查询
    response = coordinator.process_query(user_query)
    
    # 打印最终完整结果
    print("\n\n===== 最终完整回应 =====")
    print(response)
    print("\n===== 程序结束 =====")
