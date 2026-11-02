import os
import json
import requests
from typing import List, Dict, Any, Optional
from langchain.chat_models.base import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain.chains import LLMChain
from langchain_core.prompts import ChatPromptTemplate
from langchain.agents import Tool, AgentType, initialize_agent
from langchain.memory import ConversationBufferMemory
import tempfile
from PIL import Image, ImageDraw
import cv2
import numpy as np

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

# 2. 定义火柴人动画生成工具
class StickFigureAnimator:
    """火柴人动画生成器"""
    
    @staticmethod
    def draw_stick_figure(draw, x, y, pose: Dict[str, Any]):
        print(f"StickFigureAnimator.draw_stick_figure 方法开始执行")
        """绘制单个火柴人"""
        # 头部
        head_radius = 15
        draw.ellipse([x-head_radius, y-head_radius, x+head_radius, y+head_radius], fill="black")
        
        # 身体
        body_length = 40
        draw.line([x, y+head_radius, x, y+head_radius+body_length], fill="black", width=3)
        
        # 手臂
        arm_length = 30
        left_arm_angle = pose.get('left_arm_angle', 30)
        right_arm_angle = pose.get('right_arm_angle', -30)
        
        # 转换角度为弧度
        import math
        left_rad = math.radians(left_arm_angle)
        right_rad = math.radians(right_arm_angle)
        
        # 左手臂
        left_arm_x = x + arm_length * math.sin(left_rad)
        left_arm_y = y + head_radius + (body_length // 3) + arm_length * math.cos(left_rad)
        draw.line([x, y+head_radius+(body_length//3), left_arm_x, left_arm_y], fill="black", width=3)
        
        # 右手臂
        right_arm_x = x + arm_length * math.sin(right_rad)
        right_arm_y = y + head_radius + (body_length // 3) + arm_length * math.cos(right_rad)
        draw.line([x, y+head_radius+(body_length//3), right_arm_x, right_arm_y], fill="black", width=3)
        
        # 腿部
        leg_length = 40
        left_leg_angle = pose.get('left_leg_angle', 20)
        right_leg_angle = pose.get('right_leg_angle', -20)
        
        left_leg_rad = math.radians(left_leg_angle)
        right_leg_rad = math.radians(right_leg_angle)
        
        # 左腿部
        left_leg_x = x + leg_length * math.sin(left_leg_rad)
        left_leg_y = y + head_radius + body_length + leg_length * math.cos(left_leg_rad)
        draw.line([x, y+head_radius+body_length, left_leg_x, left_leg_y], fill="black", width=3)
        
        # 右腿部
        right_leg_x = x + leg_length * math.sin(right_leg_rad)
        right_leg_y = y + head_radius + body_length + leg_length * math.cos(right_leg_rad)
        draw.line([x, y+head_radius+body_length, right_leg_x, right_leg_y], fill="black", width=3)
        print(f"StickFigureAnimator.draw_stick_figure 方法执行完成")
    
    @staticmethod
    @staticmethod
    def generate_frames(animation_script: List[Dict[str, Any]], width=640, height=480, fps=10):
        print(f"StickFigureAnimator.generate_frames 方法开始执行")
        frames = []
        
        for frame_data in animation_script:
            # 创建新图像
            img = Image.new('RGB', (width, height), color='white')
            draw = ImageDraw.Draw(img)
            
            # 绘制场景元素
            if 'background' in frame_data:
                # 简单背景处理
                bg_color = frame_data['background'].get('color', 'white')
                img = Image.new('RGB', (width, height), color=bg_color)
                draw = ImageDraw.Draw(img)
            
            # 绘制火柴人
            for stick_figure in frame_data.get('stick_figures', []):
                x = stick_figure.get('x', width // 2)
                y = stick_figure.get('y', height // 2)
                pose = stick_figure.get('pose', {})
                StickFigureAnimator.draw_stick_figure(draw, x, y, pose)
            
            # 添加文字
            if 'text' in frame_data:
                text = frame_data['text']
                draw.text((10, 10), text, fill="black")
            
            # 转换为OpenCV格式
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            frames.append(frame)
        
        print(f"StickFigureAnimator.generate_frames 方法执行完成，生成了 {len(frames)} 帧")
        return frames
    
    @staticmethod
    def create_video(frames, output_path, fps=10):
        print(f"StickFigureAnimator.create_video 方法开始执行")
        """将帧序列转换为视频"""
        if not frames:
            raise ValueError("没有帧数据可生成视频")
            
        height, width, layers = frames[0].shape
        size = (width, height)
        
        # 使用MP4编码器
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, size)
        
        for frame in frames:
            out.write(frame)
        
        out.release()
        print(f"StickFigureAnimator.create_video 方法执行完成，视频已保存到: {output_path}")
        return output_path

# 3. 定义智能体工具
def create_tools(siliconflow_chat):
    """创建智能体可用的工具"""
    
    # 工具1: 生成动画脚本
    def generate_animation_script(description: str) -> str:
        print(f"generate_animation_script 函数开始执行")
        """
        根据文本描述生成火柴人动画脚本
        
        参数:
            description: 对火柴人动画的文字描述
            
        返回:
            包含动画帧信息的JSON字符串
        """
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个火柴人动画脚本生成专家。根据用户的描述，生成详细的火柴人动画脚本。
            脚本应该是一个JSON数组，每个元素代表一帧，包含:
            - frame_number: 帧编号
            - stick_figures: 火柴人列表，每个包含位置(x,y)和姿势(pose)
            - background: 背景信息(可选)
            - text: 文字说明(可选)
            
            姿势(pose)应包含:
            - left_arm_angle: 左臂角度(度)
            - right_arm_angle: 右臂角度(度)
            - left_leg_angle: 左腿角度(度)
            - right_leg_angle: 右腿角度(度)
            
            确保动画流畅，符合物理规律。时长约5-10秒，每秒10帧。"""),
            ("user", "请生成以下场景的火柴人动画脚本: {description}")
        ])
        
        chain = LLMChain(llm=siliconflow_chat, prompt=prompt)
        result = chain.run(description=description)
        
        # 提取JSON部分
        start_idx = result.find('[')
        end_idx = result.rfind(']') + 1
        if start_idx != -1 and end_idx != -1:
            json_str = result[start_idx:end_idx]
            print(f"generate_animation_script 函数执行完成")
            return json_str
        print(f"generate_animation_script 函数执行完成，但未找到有效的JSON")
        return result
    
    # 工具2: 生成视频
    def generate_video(animation_script_json: str) -> str:
        print(f"generate_video 函数开始执行")
        try:
            animation_script = json.loads(animation_script_json)
            
            # 生成帧
            frames = StickFigureAnimator.generate_frames(animation_script)
            
            # 创建临时文件
            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, "stick_figure_animation.mp4")
            
            # 生成视频
            StickFigureAnimator.create_video(frames, output_path)
            
            print(f"generate_video 函数执行完成")
            return f"视频已生成，保存路径: {output_path}"
        except Exception as e:
            print(f"generate_video 函数执行出错: {str(e)}")
            return f"生成视频时出错: {str(e)}"
    
    # 工具3: 优化动画
    def optimize_animation(animation_script_json: str) -> str:
        print(f"optimize_animation 函数开始执行")
        """
        优化动画脚本，使动画更流畅自然
        
        参数:
            animation_script_json: 原始动画脚本JSON字符串
            
        返回:
            优化后的动画脚本JSON字符串
        """
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个动画优化专家。请优化给定的火柴人动画脚本，使其更加流畅自然。
            确保动作过渡平滑，符合物理规律，增加必要的中间帧。
            保持输入的JSON格式不变，只修改内容。"""),
            ("user", "请优化以下动画脚本: {script}")
        ])
        
        chain = LLMChain(llm=siliconflow_chat, prompt=prompt)
        result = chain.run(script=animation_script_json)
        
        # 提取JSON部分
        start_idx = result.find('[')
        end_idx = result.rfind(']') + 1
        if start_idx != -1 and end_idx != -1:
            print(f"optimize_animation 函数执行完成")
            return result[start_idx:end_idx]
        print(f"optimize_animation 函数执行完成，但未找到有效的JSON")
        return result
    
    # 创建工具列表
    tools = [
        Tool(
            name="GenerateAnimationScript",
            func=generate_animation_script,
            description="根据文本描述生成火柴人动画脚本，输入是对动画的文字描述"
        ),
        Tool(
            name="GenerateVideo",
            func=generate_video,
            description="根据动画脚本生成视频文件，输入是动画脚本的JSON字符串"
        ),
        Tool(
            name="OptimizeAnimation",
            func=optimize_animation,
            description="优化动画脚本使其更流畅，输入是原始动画脚本的JSON字符串"
        )
    ]
    
    return tools

# 4. 创建超级智能体
def create_stick_figure_agent(api_key: str, model_name: str = "Qwen/Qwen3-235B-A22B-Instruct-2507"):
    print(f"create_stick_figure_agent 函数开始执行")
    # 初始化LLM
    llm = SiliconFlowChat(
        api_key=api_key,
        model_name=model_name,
        temperature=0.6
    )
    
    # 创建工具
    tools = create_tools(llm)
    
    # 初始化记忆
    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
    
    # 初始化智能体
    agent = initialize_agent(
        tools,
        llm,
        agent=AgentType.CHAT_CONVERSATIONAL_REACT_DESCRIPTION,
        memory=memory,
        verbose=True,
        handle_parsing_errors=True
    )
    
    # 设置系统提示
    agent.agent.llm_chain.prompt.messages[0] = SystemMessage(content="""你是一个超级智能体，能够根据用户需求自动生成火柴人短视频。
    你的工作流程是：
    1. 理解用户对火柴人视频的具体需求
    2. 使用GenerateAnimationScript工具生成动画脚本
    3. 可以使用OptimizeAnimation工具优化脚本（如果需要）
    4. 使用GenerateVideo工具生成最终视频
    
    请根据用户的需求，逐步完成这些步骤。如果有不确定的地方，可以向用户询问更多细节。""")
    
    return agent

# 5. 使用示例
if __name__ == "__main__":
    # 从环境变量获取API密钥
    api_key = os.getenv("SILICONFLOW_API_KEY")
    
    if not api_key:
        print("请设置环境变量SILICONFLOW_API_KEY")
        api_key = input("请输入你的SiliconFlow API密钥: ")
    
    # 创建智能体
    print("正在初始化火柴人视频生成智能体...")
    agent = create_stick_figure_agent(api_key)
    
    print("\n智能体已准备就绪！请描述你想要生成的火柴人视频。")
    print("例如: 一个火柴人在打篮球，他运球、跳跃、投篮，最后得分")
    print("输入'退出'结束对话\n")
    
    while True:
        user_input = input("你: ")
        if user_input.lower() in ["退出", "q", "quit"]:
            print("再见！")
            break
        
        try:
            result = agent.run(user_input)
            print(f"\n智能体: {result}\n")
        except Exception as e:
            print(f"处理时出错: {str(e)}\n")
