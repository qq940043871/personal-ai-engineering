import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.patches import Rectangle
import matplotlib.colors as mcolors
import random

# 设置中文字体
plt.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

# 生成随机颜色用于区分不同的通道/特征
colors = list(mcolors.TABLEAU_COLORS.values())
random.shuffle(colors)

# ----------------------------
# 数据结构变化步骤定义
# ----------------------------
def get_data_steps():
    """定义深度学习中数据结构的变化步骤"""
    steps = []
    
    # 1. 原始图像 (高度, 宽度, 通道)
    steps.append({
        "name": "原始图像",
        "shape": (224, 224, 3),
        "description": "输入图像: (高度, 宽度, 通道)\nRGB三个颜色通道",
        "type": "image"
    })
    
    # 2. 输入张量 (批次, 通道, 高度, 宽度)
    steps.append({
        "name": "输入张量",
        "shape": (1, 3, 224, 224),
        "description": "模型输入格式: (批次, 通道, 高度, 宽度)\n深度学习框架标准格式",
        "type": "tensor"
    })
    
    # 3. 卷积层1输出
    steps.append({
        "name": "卷积层1输出",
        "shape": (1, 16, 224, 224),
        "description": "卷积操作后: (批次, 特征通道, 高度, 宽度)\n通道数增加到16",
        "type": "tensor"
    })
    
    # 4. 池化层1输出
    steps.append({
        "name": "池化层1输出",
        "shape": (1, 16, 112, 112),
        "description": "池化操作后: (批次, 特征通道, 高度/2, 宽度/2)\n空间尺寸减半",
        "type": "tensor"
    })
    
    # 5. 卷积层2输出
    steps.append({
        "name": "卷积层2输出",
        "shape": (1, 32, 112, 112),
        "description": "第二次卷积: (批次, 特征通道, 高度, 宽度)\n通道数增加到32",
        "type": "tensor"
    })
    
    # 6. 池化层2输出
    steps.append({
        "name": "池化层2输出",
        "shape": (1, 32, 56, 56),
        "description": "第二次池化: (批次, 特征通道, 高度/2, 宽度/2)\n空间尺寸再次减半",
        "type": "tensor"
    })
    
    # 7. 展平操作
    steps.append({
        "name": "展平操作",
        "shape": (1, 32*56*56),
        "description": "展平特征: (批次, 特征总数)\n将3D特征图转为1D向量",
        "type": "vector"
    })
    
    # 8. 全连接层
    steps.append({
        "name": "全连接层",
        "shape": (1, 128),
        "description": "全连接层: (批次, 隐藏单元数)\n特征降维与非线性变换",
        "type": "vector"
    })
    
    # 9. 输出层
    steps.append({
        "name": "输出层",
        "shape": (1, 10),
        "description": "输出层: (批次, 类别数)\n10个类别的预测得分",
        "type": "output"
    })
    
    return steps

# ----------------------------
# 3D可视化函数
# ----------------------------
def draw_3d_cube(ax, shape, position=(0, 0, 0), color=None, alpha=0.8):
    """绘制3D立方体表示张量"""
    if len(shape) == 4:  # (批次, 通道, 高度, 宽度) - 忽略批次维度
        _, c, h, w = shape
    elif len(shape) == 3:  # (高度, 宽度, 通道)
        h, w, c = shape
    else:
        h, w, c = 1, shape[-1], 1  # 向量
    
    # 缩放因子，使可视化更美观
    scale = 0.5
    x, y, z = position
    
    # 绘制主立方体
    ax.bar3d(x, y, z, w*scale, h*scale, c*scale, 
             color=color if color else 'skyblue', 
             alpha=alpha, edgecolor='black', linewidth=0.5)
    
    # 添加维度标签
    ax.text(x + w*scale/2, y - 0.5, z, f'宽: {w}', ha='center')
    ax.text(x - 0.5, y + h*scale/2, z, f'高: {h}', ha='right')
    ax.text(x, y, z + c*scale/2, f'通道: {c}', ha='center')

def draw_vector(ax, length, position=(0, 0, 0), color='purple', alpha=0.8):
    """绘制向量表示展平后的特征或输出"""
    x, y, z = position
    scale = 0.1
    
    # 绘制一系列小立方体表示向量元素
    for i in range(min(length, 50)):  # 只显示前50个元素，避免过于拥挤
        ax.bar3d(x + i*scale, y, z, 
                 scale*0.8, scale*5, scale*5, 
                 color=colors[i % len(colors)], 
                 alpha=alpha, edgecolor='black', linewidth=0.3)
    
    # 添加标签
    if length > 50:
        ax.text(x + 25*scale, y - 1, z, f'共{length}个元素', ha='center')
    else:
        ax.text(x + length*scale/2, y - 1, z, f'长度: {length}', ha='center')

def draw_output(ax, num_classes, position=(0, 0, 0)):
    """绘制输出层的类别概率分布"""
    x, y, z = position
    scale = 0.8
    
    # 生成随机概率分布（仅用于可视化）
    probs = np.random.rand(num_classes)
    probs = probs / np.sum(probs)
    
    # 绘制每个类别的概率柱形
    for i in range(num_classes):
        height = probs[i] * 5  # 缩放高度以便可视化
        ax.bar3d(x + i*scale, y, z, 
                 scale*0.8, scale*0.8, height, 
                 color=colors[i % len(colors)], 
                 alpha=0.8, edgecolor='black', linewidth=0.5)
        ax.text(x + i*scale + scale*0.4, y + scale*0.4, z + height + 0.3, 
                f'{probs[i]:.2f}', ha='center', fontsize=8)
        ax.text(x + i*scale + scale*0.4, y + scale*1.2, z, 
                f'类别{i}', ha='center', fontsize=8, rotation=45)
    
    ax.text(x + num_classes*scale/2, y - 1, z, '类别概率分布', ha='center')

# ----------------------------
# 动画制作
# ----------------------------
def create_animation(steps):
    """创建3D动画展示数据结构变化"""
    fig = plt.figure(figsize=(12, 10))
    ax = fig.add_subplot(111, projection='3d')
    
    # 设置3D坐标轴范围
    ax.set_xlim(-5, 30)
    ax.set_ylim(-5, 15)
    ax.set_zlim(-5, 15)
    
    # 隐藏坐标轴刻度
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_zticks([])
    
    # 添加标题和描述文本框
    title_text = ax.text(0, 0, 18, "", ha='center', fontsize=14, weight='bold')
    desc_text = plt.figtext(0.5, 0.01, "", ha='center', fontsize=10, wrap=True)
    
    def update(frame):
        ax.clear()
        ax.set_xlim(-5, 30)
        ax.set_ylim(-5, 15)
        ax.set_zlim(-5, 15)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_zticks([])
        
        step = steps[frame]
        
        # 更新标题和描述
        title_text.set_text(f"步骤 {frame+1}/{len(steps)}: {step['name']}")
        desc_text.set_text(step["description"])
        
        # 根据数据类型绘制不同的3D表示
        if step["type"] == "image" or step["type"] == "tensor":
            draw_3d_cube(ax, step["shape"], position=(10, 5, 5))
        elif step["type"] == "vector":
            draw_vector(ax, step["shape"][1], position=(2, 5, 5))
        elif step["type"] == "output":
            draw_output(ax, step["shape"][1], position=(5, 5, 5))
        
        return ax,
    
    # 创建动画
    anim = FuncAnimation(
        fig, 
        update, 
        frames=len(steps), 
        interval=2000,  # 每帧停留2秒
        blit=False,
        repeat=True
    )
    
    # 保存动画为GIF
    anim.save("3d_dl_data_structure.gif", writer=PillowWriter(fps=0.5))
    print("3D立体动画已保存为 3d_dl_data_structure.gif")
    
    plt.close()

# ----------------------------
# 主函数
# ----------------------------
if __name__ == "__main__":
    steps = get_data_steps()
    create_animation(steps)
    print("动画生成完成！请查看当前目录下的GIF文件。")
    print("展示内容包括从原始图像到输出层的9个数据结构变化步骤。")
