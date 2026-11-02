import json

def generate_animation_frames(num_frames=200):
    frames = []
    background = "basketball court with hoop on the right"
    
    for frame in range(1, num_frames + 1):
        # 计算当前帧在整个动画中的进度（0到1之间）
        progress = (frame - 1) / (num_frames - 1)
        
        # 位置变化：x从100到200，y在中间有一个起跳过程
        x = 100 + 100 * progress
        
        # 跳跃曲线：使用正弦函数模拟跳跃，在中间帧达到最高点
        jump_strength = 30  # 跳跃高度
        y = 300 - jump_strength * abs(1 - 2 * progress) * (1 - abs(1 - 2 * progress)) * 4
        
        # 右臂角度变化：从准备姿势(-60)到举球(30)到伸展(120)到跟随(150)再到恢复(-30)
        if progress < 0.25:  # 准备阶段 (1-50帧)
            right_arm = -60 + 90 * (progress / 0.25)  # -60到30
            text = "准备投球姿势" if frame == 1 else "举球准备"
        elif progress < 0.5:  # 举球阶段 (51-100帧)
            right_arm = 30 + 90 * ((progress - 0.25) / 0.25)  # 30到120
            text = "举球至头顶" if frame == 50 else "准备投篮"
        elif progress < 0.75:  # 投篮阶段 (101-150帧)
            right_arm = 120 + 30 * ((progress - 0.5) / 0.25)  # 120到150
            text = "球出手瞬间" if frame == 100 else "跟随动作"
        else:  # 恢复阶段 (151-200帧)
            right_arm = 150 - 180 * ((progress - 0.75) / 0.25)  # 150到-30
            text = "跟随动作完成" if frame == 150 else "恢复准备姿势"
        
        # 左臂角度变化：辅助动作
        if progress < 0.5:
            left_arm = -20 + 10 * (progress / 0.5)  # -20到-10
        else:
            left_arm = -10 - 5 * ((progress - 0.5) / 0.5)  # -10到-15
        
        # 腿部角度变化：屈膝、伸展、落地
        if progress < 0.3:  # 屈膝
            leg_angle = -10 - 15 * (progress / 0.3)  # 从-10到-25
        elif progress < 0.6:  # 伸展起跳
            leg_angle = -25 + 20 * ((progress - 0.3) / 0.3)  # 从-25到-5
        else:  # 落地恢复
            leg_angle = -5 - 5 * ((progress - 0.6) / 0.4)  # 从-5到-10
        
        # 身体倾斜角度变化
        if progress < 0.4:  # 前倾
            body_tilt = -5 - 10 * (progress / 0.4)  # 从-5到-15
        elif progress < 0.6:  # 后倾
            body_tilt = -15 + 20 * ((progress - 0.4) / 0.2)  # 从-15到5
        else:  # 恢复直立
            body_tilt = 5 - 5 * ((progress - 0.6) / 0.4)  # 从5到0
        
        # 创建当前帧数据
        frame_data = {
            "frame_number": frame,
            "background": background,
            "stick_figures": [
                {
                    "position": {
                        "x": round(x, 1),
                        "y": round(y, 1)
                    },
                    "pose": {
                        "left_arm_angle": round(left_arm, 1),
                        "right_arm_angle": round(right_arm, 1),
                        "left_leg_angle": round(leg_angle, 1),
                        "right_leg_angle": round(-leg_angle, 1),  # 右腿与左腿角度对称
                        "body_tilt": round(body_tilt, 1)
                    }
                }
            ],
            "text": text
        }
        
        frames.append(frame_data)
    
    return frames

# 生成200帧动画数据
animation_frames = generate_animation_frames(200)

# 保存为JSON文件
with open("basketball_animation_200frames.json", "w", encoding="utf-8") as f:
    json.dump(animation_frames, f, ensure_ascii=False, indent=2)

print("已生成200帧动画数据，保存为 basketball_animation_200frames.json")
