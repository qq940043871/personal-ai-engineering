import os
from typing import List, Dict, Any, Optional, Tuple
from langchain.chat_models.base import BaseChatModel
from langchain_core.messages import (
    BaseMessage, HumanMessage, AIMessage, SystemMessage,
    FunctionMessage, ToolMessage
)
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import Tool, BaseTool
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain.memory import ConversationBufferMemory
import requests

# 1. SiliconFlow模型封装
class SiliconFlowChat(BaseChatModel):
    """SiliconFlow对话模型封装类，适配LangChain 0.3.27"""
    api_key: str
    model_name: str
    api_base: str = "https://api.siliconflow.cn/v1/chat/completions"
    temperature: float = 0.7
    max_tokens: int = 2048

    @property
    def _llm_type(self) -> str:
        return "siliconflow-chat"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,** kwargs: Any,
    ) -> ChatResult:
        # 转换消息格式为SiliconFlow API要求的格式
        print("\n===== 调用SiliconFlow模型 =====")
        # 打印输入消息
        print("【发送给模型的消息】:")
        for msg in messages:
            role = "用户" if isinstance(msg, HumanMessage) else "助手" if isinstance(msg, AIMessage) else "系统"
            print(f"{role}: {msg.content[:500]}...")  # 只显示前100字符
        siliconflow_messages = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                siliconflow_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                siliconflow_messages.append({"role": "assistant", "content": msg.content})
            elif isinstance(msg, SystemMessage):
                siliconflow_messages.append({"role": "system", "content": msg.content})
            elif isinstance(msg, (FunctionMessage, ToolMessage)):
                # 处理工具调用结果
                siliconflow_messages.append({
                    "role": "function",
                    "name": msg.name,
                    "content": msg.content
                })

        # 构造请求参数
        payload = {
            "model": self.model_name,
            "messages": siliconflow_messages,
            "temperature": self.temperature,
            "max_tokens": 1024
        }
        
        if stop:
            payload["stop"] = stop

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            print(f"【调用模型】: {self.model_name}")
            response = requests.post(
                url=self.api_base,
                json=payload,
                headers=headers,
                timeout=60
            )
            response.raise_for_status()
            result = response.json()
            # 解析API响应
            ai_message = result["choices"][0]["message"]["content"]
            print("【模型返回结果】:", ai_message[:100] + "...")  # 只显示前100字符
            print("===== SiliconFlow模型调用结束 =====")
            generation = ChatGeneration(
                message=AIMessage(content=ai_message),
                generation_info=result
            )
            return ChatResult(generations=[generation])
        except Exception as e:
            error_msg = f"API调用出错: {str(e)}"
            print(f"[SiliconFlowChat._generate] 请求处理异常: {error_msg}")
            return ChatResult(generations=[ChatGeneration(
                message=AIMessage(content=error_msg),
                generation_info=None
            )])

# 2. 定义专业小智能体
class SpecialistAgent:
    """专业小智能体基类"""
    
    def __init__(self, name: str, role: str, expertise: str, llm: BaseChatModel):
        print(f"[SpecialistAgent.__init__] 初始化小智能体: {name}，角色: {role}")
        self.name = name
        self.role = role
        self.expertise = expertise
        self.llm = llm
        self.memory = ConversationBufferMemory(
            memory_key=f"{name}_memory",
            return_messages=True
        )
        self.agent = self.create_agent()
    
    def create_agent(self) -> AgentExecutor:
        """创建智能体执行器"""
        print(f"[SpecialistAgent.create_agent] 为智能体 {self.name} 创建执行器")
        # 系统提示
        system_prompt = f"""你是{self.name}，一个专业的{self.role}。
        你的专业领域是：{self.expertise}
        你需要根据超级智能体的指示，完成分配给你的监控项目计划部分。
        确保你的工作专业、详细且符合行业标准。
        如果有不明确的地方，可以向超级智能体询问澄清。"""
        
        # 创建提示模板
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="memory"),
            MessagesPlaceholder(variable_name="messages"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
        
        # 创建智能体
        agent = create_openai_tools_agent(self.llm, [], prompt)
        
        # 创建执行器
        executor = AgentExecutor(
            agent=agent,
            tools=[],
            memory=self.memory,
            verbose=False,
            handle_parsing_errors=True
        )
        return executor

# 2.1 项目规划智能体 - 负责项目概述和目标
class ProjectPlanningAgent(SpecialistAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(
            name="project_planning",
            role="项目规划专家",
            expertise="监控项目的整体规划、目标设定和时间线安排",
            llm=llm
        )

# 2.2 范围定义智能体 - 负责监控范围和对象
class ScopeDefinitionAgent(SpecialistAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(
            name="scope_definition",
            role="监控范围定义专家",
            expertise="确定监控项目的范围、对象和边界",
            llm=llm
        )

# 2.3 指标设计智能体 - 负责监控指标和标准
class MetricsDesignAgent(SpecialistAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(
            name="metrics_design",
            role="监控指标设计专家",
            expertise="设计监控指标、阈值和评估标准",
            llm=llm
        )

# 2.4 技术选型智能体 - 负责监控工具和技术
class TechnologySelectionAgent(SpecialistAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(
            name="technology_selection",
            role="监控技术选型专家",
            expertise="选择合适的监控工具、技术和平台",
            llm=llm
        )

# 2.5 资源管理智能体 - 负责人力和预算
class ResourceManagementAgent(SpecialistAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(
            name="resource_management",
            role="资源管理专家",
            expertise="监控项目的人力资源分配和预算规划",
            llm=llm
        )

# 2.6 风险管理智能体 - 负责风险评估
class RiskManagementAgent(SpecialistAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(
            name="risk_management",
            role="风险管理专家",
            expertise="识别监控项目的潜在风险并制定应对策略",
            llm=llm
        )

# 新增: 场景生成器
class ScenarioGenerator:
    """根据用户描述生成监控项目模拟场景"""
    
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        
    def generate_scenario(self, user_input: str) -> str:
        """根据用户输入生成详细的监控项目场景"""
        print(f"[ScenarioGenerator.generate_scenario] 根据用户输入生成场景: {user_input[:50]}...")
        
        # 准备提示模板
        prompt = ChatPromptTemplate.from_template(
            """你是一个监控项目场景生成专家。根据用户的简短描述，生成一个详细的监控项目场景，
            包括项目背景、目标、系统架构、关键组件和监控需求。

            用户描述: {user_input}

            生成的场景应详细、具体，包含足够的信息让各个专业小智能体能够制定完整的监控计划。
            输出应控制在300-500字左右。"""
        )
        
        # 调用LLM生成场景
        chain = prompt | self.llm
        response = chain.invoke({
            "user_input": user_input
        })
        
        print(f"[ScenarioGenerator.generate_scenario] 场景生成完成，长度: {len(response.content)}")
        return response.content

# 3. 超级智能体 - 协调各个小智能体
class SuperAgent:
    """超级智能体，负责协调各个专业小智能体完成监控项目计划"""
    
    def __init__(self, api_key: str, model_name: str = "Qwen/Qwen2.5-72B-Instruct-128K"):
        print(f"[SuperAgent.__init__] 开始初始化超级智能体，模型: {model_name}")
        # 初始化基础LLM
        self.llm = SiliconFlowChat(
            api_key=api_key,
            model_name=model_name,
            temperature=0.5
        )
        
        # 创建场景生成器
        self.scenario_generator = ScenarioGenerator(self.llm)
        
        # 创建专业小智能体
        print("[SuperAgent.__init__] 创建专业小智能体...")
        self.specialists = {
            "project_planning": ProjectPlanningAgent(self.llm),
            "scope_definition": ScopeDefinitionAgent(self.llm),
            "metrics_design": MetricsDesignAgent(self.llm),
            "technology_selection": TechnologySelectionAgent(self.llm),
            "resource_management": ResourceManagementAgent(self.llm),
            "risk_management": RiskManagementAgent(self.llm)
        }
        
        # 为每个小智能体创建执行器
        print("[SuperAgent.__init__] 为小智能体创建执行器...")
        self.specialist_agents = {
            name: agent.create_agent() 
            for name, agent in self.specialists.items()
        }
        
        # 初始化超级智能体的记忆
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )
        
        self.tools = self._create_tools()
        self.agent_executor = self._create_agent_executor()
        
        # 存储项目计划各部分结果
        self.plan_sections = {}
        print("[SuperAgent.__init__] 超级智能体初始化完成")

    def _create_tools(self) -> List[Tool]:
        """创建超级智能体可用的工具（调用各小智能体）"""
        print("[SuperAgent._create_tools] 开始创建超级智能体工具")
        
         # 为每个智能体创建工具
        tools = []
        for agent_name, agent in self.specialists.items():
            def create_tool_func(agent_instance):
                def tool_func(query: str) -> str:
                    """调用专业小智能体处理指定任务"""
                    print(f"[SuperAgent.tool_func] 调用小智能体 {name}，指令: {instruction[:50]}...")
                    # 修复：确保instruction是字符串，如果是HumanMessage对象则提取content
                    if isinstance(instruction, HumanMessage):
                        instruction = instruction.content
                    elif isinstance(instruction, list) and len(instruction) > 0 and isinstance(instruction[0], HumanMessage):
                        instruction = instruction[0].content
                    
                    result = self.specialist_agents[name].invoke({
                        "messages": [instruction]
                    })
                    # 保存结果
                    self.plan_sections[name] = result["output"]
                    print(f"[SuperAgent.tool_func] 小智能体 {name} 处理完成，结果长度: {len(result['output'])} ")
                    return result["output"]
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
            print("\n【工具调用】: 调用 _compile_final_plan 工具整合结果")
            result = self._compile_final_plan()
            print("【工具返回】: 结果整合完成")
            return result
        
        tools.append(
            Tool(
                name="summarize",
                func=summarize_func,
                description="整合所有智能体的回答，生成最终回应"
            )
        )
        print("创建工具: _compile_final_plan - 结果整合工具")
        print("===== 工具列表创建完成 =====")
        return tools

    
    def _compile_final_plan(self) -> str:
        """将各个部分的计划整合为完整文档"""
        print("[SuperAgent._compile_final_plan] 开始整合最终计划")
        if not self.plan_sections:
            msg = "还没有生成任何计划部分，请先调用其他工具生成各部分内容。"
            print(f"[SuperAgent._compile_final_plan] 整合失败: {msg}")
            return msg
            
        final_plan = "# 监控项目计划\n\n"
        final_plan += "## 目录\n"
        final_plan += "1. [项目概述与目标](#1-项目概述与目标)\n"
        final_plan += "2. [监控范围与对象](#2-监控范围与对象)\n"
        final_plan += "3. [监控指标与标准](#3-监控指标与标准)\n"
        final_plan += "4. [监控工具与技术](#4-监控工具与技术)\n"
        final_plan += "5. [资源规划](#5-资源规划)\n"
        final_plan += "6. [风险管理](#6-风险管理)\n"
        final_plan += "7. [总结](#7-总结)\n\n"
        
        # 添加各部分内容
        if "project_planning" in self.plan_sections:
            final_plan += "## 1. 项目概述与目标\n"
            final_plan += self.plan_sections["project_planning"] + "\n\n"
            
        if "scope_definition" in self.plan_sections:
            final_plan += "## 2. 监控范围与对象\n"
            final_plan += self.plan_sections["scope_definition"] + "\n\n"
            
        if "metrics_design" in self.plan_sections:
            final_plan += "## 3. 监控指标与标准\n"
            final_plan += self.plan_sections["metrics_design"] + "\n\n"
            
        if "technology_selection" in self.plan_sections:
            final_plan += "## 4. 监控工具与技术\n"
            final_plan += self.plan_sections["technology_selection"] + "\n\n"
            
        if "resource_management" in self.plan_sections:
            final_plan += "## 5. 资源规划\n"
            final_plan += self.plan_sections["resource_management"] + "\n\n"
            
        if "risk_management" in self.plan_sections:
            final_plan += "## 6. 风险管理\n"
            final_plan += self.plan_sections["risk_management"] + "\n\n"
        
        # 添加总结
        final_plan += "## 7. 总结\n"
        final_plan += "本监控项目计划涵盖了实现有效监控所需的各个方面。各团队应按照计划执行，并根据实际情况进行必要调整。"
        
        # 保存最终计划到文件
        with open("monitoring_project_plan.md", "w", encoding="utf-8") as f:
            f.write(final_plan)
            
        print(f"[SuperAgent._compile_final_plan] 最终计划整合完成，保存为 monitoring_project_plan.md，长度: {len(final_plan)}")
        return f"完整的监控项目计划已生成，并保存为 monitoring_project_plan.md\n\n{final_plan}"
    
    def _create_agent_executor(self) -> AgentExecutor:
        """创建超级智能体执行器"""
        print("[SuperAgent._create_agent_executor] 开始创建超级智能体执行器")
        # 系统提示
        system_prompt = """你是一个超级智能体，负责协调多个专业小智能体共同完成监控项目计划的编写。
        你的职责是：
        1. 理解用户对开发项目的需求和背景
        2. 判断需要哪些专业智能体协助
        3. 依次调用相应的智能体处理
        4. 所有智能体完成后，调用compile_final_plan工具生成最终回答
        
        可用智能体：
        - project_planning: 制定项目概述、目标和时间线
        - scope_definition: 定义监控范围和对象
        - metrics_design: 设计监控指标和标准
        - technology_selection: 选择监控工具和技术
        - resource_management: 规划人力资源和预算
        - risk_management: 识别风险并制定应对策略
        - compile_final_plan: 整合所有部分为最终计划
        
         请根据用户问题，合理分配任务并协调处理。"""
        
        # 创建提示模板
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            MessagesPlaceholder(variable_name="messages"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
        
        # 创建智能体
        agent = create_openai_tools_agent(self.llm, self.tools, prompt)
        
        # 创建执行器
        executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            memory=self.memory,
            verbose=True,
            handle_parsing_errors=True
        )
        print("[SuperAgent._create_agent_executor] 超级智能体执行器创建完成")
        return executor
    
    def run_with_scenario(self, user_input: str) -> str:
        """根据用户输入生成场景并运行超级智能体"""
        print(f"[SuperAgent.run_with_scenario] 开始处理用户输入: {user_input[:50]}...")
        
        # 生成详细场景
        scenario = self.scenario_generator.generate_scenario(user_input)
        print(f"[SuperAgent.run_with_scenario] 生成场景: {scenario[:100]}...")
        
        # 将生成的场景作为输入传递给超级智能体
        result = self.agent_executor.invoke({
            "messages": [scenario]
        })
        
        print(f"[SuperAgent.run_with_scenario] 处理完成，结果长度: {len(result['output'])} ")
        return result['output']

# 4. 使用示例
if __name__ == "__main__":
    # 获取API密钥 (优化: 提供默认值或从环境变量获取)
    api_key = "sk-REPLACE_WITH_YOUR_KEY"
    
    # 初始化超级智能体
    print("正在初始化监控项目计划超级智能体...")
    super_agent = SuperAgent(api_key)
    
    print("\n智能体已准备就绪！请简要描述你需要制定的监控项目。")
    
    # 示例查询：包含多个领域的问题
    user_query = """我想监控电子商务网站的服务器性能，需要编写完整的合理监控计划，背景​
中型电商网站因服务器性能波动，促销时页面延迟达 8 秒，流失 12% 订单，发生 2 次服务中断，需系统化监控。​
目标​
实现服务器全链路可视，全年可用性 99.9% 以上，关键指标异常 5 分钟内告警，故障 30 分钟内定位。
    请各专家给出建议，形成完整的监控计划。"""

    user_input = "电子商务网站服务器监控"
    try:
        print("\n正在生成场景和处理，请稍候...\n")
        # 使用新的方法运行，自动生成场景
        # result = super_agent.run_with_scenario(user_input)
        result = super_agent.agent_executor.invoke({
            "messages": [user_query]
        })
        print(f"\n超级智能体: {result}\n")
    except Exception as e:
        print(f"处理时出错: {e}\n")
    