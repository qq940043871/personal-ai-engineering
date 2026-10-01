import os
import json
import tempfile
from PIL import Image, ImageDraw
import cv2
import numpy as np

class StickFigureAnimator:
    """火柴人动画生成器"""
    
    @staticmethod
    def draw_stick_figure(draw, x, y, pose: dict):
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
    
    @staticmethod
    def generate_frames(animation_script: list, width=640, height=480):
        """根据动画脚本生成帧"""
        frames = []
        
        for frame_data in animation_script:
            # 创建新图像
            img = Image.new('RGB', (width, height), color='white')
            draw = ImageDraw.Draw(img)
            
            # 绘制场景元素
            if 'background' in frame_data:
                # 简单背景处理
                bg_color = 'white'
                # 这里简化了背景处理，仅使用白色背景
                img = Image.new('RGB', (width, height), color=bg_color)
                draw = ImageDraw.Draw(img)
            
            # 绘制火柴人
            for stick_figure in frame_data.get('stick_figures', []):
                x = stick_figure.get('position', {}).get('x', width // 2)
                y = stick_figure.get('position', {}).get('y', height // 2)
                pose = stick_figure.get('pose', {})
                StickFigureAnimator.draw_stick_figure(draw, x, y, pose)
            
            # 添加文字
            if 'text' in frame_data:
                text = frame_data['text']
                draw.text((10, 10), text, fill="black")
            
            # 转换为OpenCV格式
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            frames.append(frame)
        
        return frames
    
    @staticmethod
    def create_video(frames, output_path, fps=10):
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
        return output_path

def generate_video_from_json(json_path, output_path=None, fps=10):
    """从JSON文件生成视频"""
    # 读取JSON文件
    with open(json_path, 'r', encoding='utf-8') as f:
        animation_script = json.load(f)
    
    # 生成帧
    frames = StickFigureAnimator.generate_frames(animation_script)
    
    # 如果未指定输出路径，使用临时文件
    if not output_path:
        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, "stick_figure_animation.mp4")
    
    # 生成视频
    StickFigureAnimator.create_video(frames, output_path, fps)
    
    return output_path

if __name__ == "__main__":
    # JSON文件路径
    json_path = "d:/workspace/p001_ai_study_py/01_langchain/stick-figure-video-agent/basketball_animation_200frames.json"
    
    # 输出视频路径
    output_path = "d:/workspace/p001_ai_study_py/01_langchain/stick-figure-video-agent/output.mp4"
    
    # 生成视频
    print("正在生成视频...")
    video_path = generate_video_from_json(json_path, output_path)
    
    print(f"视频已生成，保存路径: {video_path}")