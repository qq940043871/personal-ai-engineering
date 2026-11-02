# 动画内容说明
# 动画会按以下 8 个步骤展示数据结构的变化，每步停留 1.5 秒：
# 原始图像
# 形状：(224, 224, 3)
# 展示：RGB 彩色图像，直接反映像素的颜色信息。
# 卷积层 1 输出
# 形状：(16, 224, 224)
# 展示：前 4 个通道的特征图（用热图表示），每个通道对应一种基础特征（如边缘、纹理）。
# 池化层 1 输出
# 形状：(16, 112, 112)
# 展示：空间尺寸缩小一半（224→112），保留关键特征，减少冗余信息。
# 卷积层 2 输出
# 形状：(32, 112, 112)
# 展示：通道数增加到 32，特征更复杂（如局部部件）。
# 池化层 2 输出
# 形状：(32, 56, 56)
# 展示：空间尺寸再次缩小（112→56），特征更抽象。
# 展平特征
# 形状：(32×56×56,)（约 10 万维）
# 展示：前 100 个特征值的条形图，将三维特征图转换为一维向量。
# 全连接层输出
# 形状：(10,)
# 展示：10 个类别的原始得分（未归一化）。
# 最终概率分布
# 形状：(10,)
# 展示：经 Softmax 归一化后的概率值，总和为 1，直观反映模型对每个类别的预测置信度。

import numpy as np
import torch
import torch.nn as nn
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
import matplotlib.gridspec as gridspec

# 设置中文字体
plt.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

# ----------------------------
# 1. 定义网络结构和数据流程
# ----------------------------
class SimpleCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 16, kernel_size=3, padding=1)
        self.pool = nn.MaxPool2d(2, 2)
        self.conv2 = nn.Conv2d(16, 32, kernel_size=3, padding=1)
        self.flatten = nn.Flatten()
        self.fc = nn.Linear(32 * 56 * 56, 10)  # 假设10分类
        self.softmax = nn.Softmax(dim=1)
        
    def forward(self, x, return_steps=False):
        # 存储每个步骤的输出用于可视化
        steps = []
        steps.append(("原始图像", x[0].permute(1,2,0).detach().numpy()))  # (H,W,C)
        
        # 卷积1
        x1 = self.conv1(x)
        steps.append(("卷积层1输出", x1[0].detach().numpy()))  # (16,H,W)
        
        # 池化1
        x2 = self.pool(x1)
        steps.append(("池化层1输出", x2[0].detach().numpy()))  # (16,H/2,W/2)
        
        # 卷积2
        x3 = self.conv2(x2)
        steps.append(("卷积层2输出", x3[0].detach().numpy()))  # (32,H/2,W/2)
        
        # 池化2
        x4 = self.pool(x3)
        steps.append(("池化层2输出", x4[0].detach().numpy()))  # (32,H/4,W/4)
        
        # 展平
        x5 = self.flatten(x4)
        steps.append(("展平特征", x5[0].detach().numpy()))  # (1D)
        
        # 全连接
        x6 = self.fc(x5)
        steps.append(("全连接输出", x6[0].detach().numpy()))  # (10,)
        
        # 概率输出
        x7 = self.softmax(x6)
        steps.append(("最终概率分布", x7[0].detach().numpy()))  # (10,)
        
        if return_steps:
            return steps
        return x7

# 生成模拟数据（224x224的RGB图像）
raw_image = np.random.randint(0, 256, size=(224, 224, 3), dtype=np.uint8)
tensor_image = torch.from_numpy(raw_image).permute(2, 0, 1).float() / 255.0  # (C,H,W)
batch_image = tensor_image.unsqueeze(0)  # (B,C,H,W)

# 获取所有步骤的数据
model = SimpleCNN()
steps = model.forward(batch_image, return_steps=True)

# ----------------------------
# 2. 制作动画
# ----------------------------
fig = plt.figure(figsize=(12, 8))
gs = gridspec.GridSpec(2, 2, height_ratios=[1, 1])

# 定义每个步骤的可视化函数
def visualize_step(step_idx):
    fig.clear()
    title, data = steps[step_idx]
    
    # 标题
    fig.suptitle(f"步骤 {step_idx+1}: {title}\n数据形状: {data.shape}", fontsize=14)
    
    if step_idx == 0:
        # 原始图像 (H,W,C)
        ax = fig.add_subplot(gs[0:2, 0:2])
        ax.imshow(data.astype(np.uint8))
        ax.set_title("原始RGB图像")
        ax.axis("off")
        
    elif step_idx in [1,2,3,4]:
        # 卷积/池化输出 (C,H,W) - 展示前4个通道
        ax1 = fig.add_subplot(gs[0, 0])
        ax2 = fig.add_subplot(gs[0, 1])
        ax3 = fig.add_subplot(gs[1, 0])
        ax4 = fig.add_subplot(gs[1, 1])
        axes = [ax1, ax2, ax3, ax4]
        
        for i, ax in enumerate(axes[:min(4, data.shape[0])]):
            im = ax.imshow(data[i], cmap="viridis")
            ax.set_title(f"通道 {i+1}")
            ax.axis("off")
        fig.colorbar(im, ax=axes, orientation="horizontal", fraction=0.05)
        
    elif step_idx == 5:
        # 展平特征 (1D) - 展示前100个特征
        ax = fig.add_subplot(gs[0:2, 0:2])
        ax.bar(range(min(100, len(data))), data[:100])
        ax.set_title("展平后的前100个特征值")
        ax.set_xlabel("特征索引")
        ax.set_ylabel("值")
        
    else:
        # 全连接/概率输出 (10,)
        ax = fig.add_subplot(gs[0:2, 0:2])
        classes = [f"类别{i}" for i in range(10)]
        ax.bar(classes, data)
        ax.set_title("类别得分/概率")
        ax.set_xticklabels(classes, rotation=45)
        ax.set_ylabel("值/概率")
        plt.tight_layout()

# 创建动画
anim = FuncAnimation(
    fig, 
    visualize_step, 
    frames=len(steps), 
    interval=1500,  # 每帧停留1.5秒
    repeat=True
)

# 保存为GIF（需要安装pillow库）
anim.save("deep_learning_data_structure.gif", writer=PillowWriter(fps=0.7))
print("动画已保存为 deep_learning_data_structure.gif")

# 显示动画（在Jupyter或本地环境中）
plt.show()