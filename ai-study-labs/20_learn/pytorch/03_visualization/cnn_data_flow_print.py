import numpy as np
import torch
import torch.nn as nn

# 1. 原始数据：一张RGB图像（宽度224，高度224，3个颜色通道）
# 原始数据格式可能是PIL图像、numpy数组等
raw_image = np.random.randint(0, 256, size=(224, 224, 3), dtype=np.uint8)
print(f"1. 原始图像数据结构：{raw_image.shape} → (高度, 宽度, 通道数)")


# 2. 预处理：转换为张量并调整维度顺序
# 深度学习框架（如PyTorch）通常要求格式为 (批次大小, 通道数, 高度, 宽度)
tensor_image = torch.from_numpy(raw_image).permute(2, 0, 1).float() / 255.0  # 通道维度提前，归一化
# 增加批次维度（因为模型通常处理批量数据）
batch_image = tensor_image.unsqueeze(0)  # 在第0维增加批次维度
print(f"2. 预处理后张量结构：{batch_image.shape} → (批次大小, 通道数, 高度, 宽度)")


# 3. 卷积层处理：提取低级特征，通道数增加
conv1 = nn.Conv2d(in_channels=3, out_channels=16, kernel_size=3, padding=1)
conv1_output = conv1(batch_image)
print(f"3. 卷积层输出结构：{conv1_output.shape} → (批次, 新通道数, 高度, 宽度)")
# 说明：通道数从3变为16（提取16种基础特征，如边缘、纹理），空间尺寸不变（因padding=1）


# 4. 池化层处理：降低空间维度，保留关键特征
pool = nn.MaxPool2d(kernel_size=2, stride=2)
pool_output = pool(conv1_output)
print(f"4. 池化层输出结构：{pool_output.shape} → (批次, 通道数, 高度/2, 宽度/2)")
# 说明：空间尺寸缩小一半（224→112），减少计算量，保留重要特征


# 5. 多层卷积+池化：特征抽象层级提升
conv2 = nn.Conv2d(in_channels=16, out_channels=32, kernel_size=3, padding=1)
conv2_output = conv2(pool_output)
pool2_output = pool(conv2_output)
print(f"5. 第二次卷积+池化输出：{pool2_output.shape} → (批次, 32, 56, 56)")
# 说明：通道数继续增加（特征更复杂），空间尺寸继续缩小


# 6. 全连接层前：展平特征图
flatten = nn.Flatten()
flatten_output = flatten(pool2_output)
print(f"6. 展平后结构：{flatten_output.shape} → (批次, 特征总数)")
# 说明：将三维特征图展平为一维向量，便于全连接层处理


# 7. 全连接层：特征映射到类别空间
fc = nn.Linear(in_features=32*56*56, out_features=10)  # 假设10个类别
fc_output = fc(flatten_output)
print(f"7. 全连接层输出结构：{fc_output.shape} → (批次, 类别数)")


# 8. 输出层：得到概率分布
softmax = nn.Softmax(dim=1)
prob_output = softmax(fc_output)
print(f"8. 最终概率输出结构：{prob_output.shape} → (批次, 类别概率)")
print(f"   示例概率值：{prob_output[0].detach().numpy().round(3)}")
