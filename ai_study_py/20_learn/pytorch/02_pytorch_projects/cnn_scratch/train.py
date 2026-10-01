# 从零开始设计的小狗识别模型
import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, transforms
from torch.utils.data import DataLoader
import os
import time
import copy
import matplotlib.pyplot as plt

# 设置设备：优先使用GPU，没有则用CPU
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
print(f"使用设备: {device}")

# 1. 数据准备与预处理
# 定义数据变换
data_transforms = {
    'train': transforms.Compose([
        transforms.RandomResizedCrop(128),  # 随机裁剪并缩放到128x128
        transforms.RandomHorizontalFlip(),  # 随机水平翻转
        transforms.RandomRotation(15),      # 随机旋转±15度
        transforms.ColorJitter(brightness=0.2, contrast=0.2),  # 随机调整亮度和对比度
        transforms.ToTensor(),              # 转换为张量
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])  # 标准化
    ]),
    'val': transforms.Compose([
        transforms.Resize(144),             # 缩放到144x144
        transforms.CenterCrop(128),         # 中心裁剪到128x128
        transforms.ToTensor(),              # 转换为张量
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])  # 标准化
    ]),
}

# 数据集路径（请根据实际情况修改）
# 数据集结构:
# data/dog_dataset/
#   train/
#       dog/          # 小狗图片
#       non_dog/      # 非小狗图片
#   val/
#       dog/          # 验证用小狗图片
#       non_dog/      # 验证用非小狗图片
data_dir = '../../data/dog_dataset'

# 加载数据集
image_datasets = {x: datasets.ImageFolder(os.path.join(data_dir, x),
                                          data_transforms[x])
                  for x in ['train', 'val']}

# 创建数据加载器
batch_size = 32
dataloaders = {
    'train': DataLoader(image_datasets['train'], batch_size=batch_size,
                       shuffle=True, num_workers=0),
    'val': DataLoader(image_datasets['val'], batch_size=batch_size,
                     shuffle=False, num_workers=0)
}

# 获取数据集信息
dataset_sizes = {x: len(image_datasets[x]) for x in ['train', 'val']}
class_names = image_datasets['train'].classes
print(f"类别: {class_names}")
print(f"训练集大小: {dataset_sizes['train']}")
print(f"验证集大小: {dataset_sizes['val']}")

# 2. 从零开始设计网络层
class DogClassifier(nn.Module):
    def __init__(self, num_classes=2):
        super(DogClassifier, self).__init__()

        # 第一个卷积块: 输入是3通道(RGB图像)
        self.conv_block1 = nn.Sequential(
            nn.Conv2d(in_channels=3, out_channels=32, kernel_size=3, padding=1),
            # 32个3x3的卷积核，输入3通道，输出32通道，保持尺寸不变
            nn.BatchNorm2d(32),  # 批标准化，加速训练
            nn.ReLU(inplace=True),  # 激活函数，引入非线性
            nn.MaxPool2d(kernel_size=2, stride=2)  # 最大池化，尺寸减半
        )

        # 第二个卷积块
        self.conv_block2 = nn.Sequential(
            nn.Conv2d(in_channels=32, out_channels=64, kernel_size=3, padding=1),
            # 输入32通道，输出64通道
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2)  # 再次减半
        )

        # 第三个卷积块
        self.conv_block3 = nn.Sequential(
            nn.Conv2d(in_channels=64, out_channels=128, kernel_size=3, padding=1),
            # 输入64通道，输出128通道
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2)  # 再次减半
        )

        # 第四个卷积块
        self.conv_block4 = nn.Sequential(
            nn.Conv2d(in_channels=128, out_channels=256, kernel_size=3, padding=1),
            # 输入128通道，输出256通道
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2)  # 再次减半
        )

        # 全连接层：将卷积提取的特征映射到类别
        # 经过4次池化，128x128的输入变成8x8 (128 → 64 → 32 → 16 → 8)
        self.fc_layers = nn.Sequential(
            nn.Linear(256 * 8 * 8, 1024),  # 输入特征数：256通道×8×8尺寸
            nn.ReLU(inplace=True),
            nn.Dropout(0.5),  # Dropout防止过拟合
            nn.Linear(1024, 512),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(512, num_classes)  # 输出类别数
        )

    def forward(self, x):
        # 前向传播：依次通过各个卷积块
        x = self.conv_block1(x)
        x = self.conv_block2(x)
        x = self.conv_block3(x)
        x = self.conv_block4(x)

        # 展平特征图，送入全连接层
        x = x.view(x.size(0), -1)  # 保持批次维度，展平其他维度
        x = self.fc_layers(x)
        return x

# 初始化模型
model = DogClassifier(num_classes=2)
model = model.to(device)  # 将模型移动到GPU/CPU

# 3. 定义损失函数和优化器
criterion = nn.CrossEntropyLoss()  # 交叉熵损失，适用于分类任务
optimizer = optim.Adam(model.parameters(), lr=0.001, weight_decay=1e-5)  # Adam优化器

# 学习率调度器：当验证集准确率不再提升时，降低学习率
scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, 'max', patience=3, factor=0.5)

# 4. 模型训练函数
def train_model(model, criterion, optimizer, scheduler, num_epochs=30):
    since = time.time()

    # 保存最佳模型权重
    best_model_wts = copy.deepcopy(model.state_dict())
    best_acc = 0.0

    # 记录训练过程中的损失和准确率
    train_losses = []
    val_losses = []
    train_accs = []
    val_accs = []

    for epoch in range(num_epochs):
        print(f'Epoch {epoch}/{num_epochs - 1}')
        print('-' * 10)

        # 每个epoch都有训练和验证阶段
        for phase in ['train', 'val']:
            if phase == 'train':
                model.train()  # 训练模式：启用dropout
            else:
                model.eval()   # 评估模式：禁用dropout

            running_loss = 0.0
            running_corrects = 0

            # 迭代数据
            for inputs, labels in dataloaders[phase]:
                inputs = inputs.to(device)
                labels = labels.to(device)

                # 清零梯度
                optimizer.zero_grad()

                # 前向传播
                # 只有在训练时才追踪梯度
                with torch.set_grad_enabled(phase == 'train'):
                    outputs = model(inputs)
                    _, preds = torch.max(outputs, 1)
                    loss = criterion(outputs, labels)

                    # 训练阶段：反向传播 + 优化
                    if phase == 'train':
                        loss.backward()
                        optimizer.step()

                # 统计
                running_loss += loss.item() * inputs.size(0)
                running_corrects += torch.sum(preds == labels.data)

            # 计算每个epoch的损失和准确率
            epoch_loss = running_loss / dataset_sizes[phase]
            epoch_acc = running_corrects.double() / dataset_sizes[phase]

            # 记录指标
            if phase == 'train':
                train_losses.append(epoch_loss)
                train_accs.append(epoch_acc.item())
            else:
                val_losses.append(epoch_loss)
                val_accs.append(epoch_acc.item())
                # 学习率调度器根据验证准确率调整
                scheduler.step(epoch_acc)

            print(f'{phase} Loss: {epoch_loss:.4f} Acc: {epoch_acc:.4f}')

            # 保存最佳模型
            if phase == 'val' and epoch_acc > best_acc:
                best_acc = epoch_acc
                best_model_wts = copy.deepcopy(model.state_dict())

        print()

    # 计算训练总时间
    time_elapsed = time.time() - since
    print(f'Training complete in {time_elapsed // 60:.0f}m {time_elapsed % 60:.0f}s')
    print(f'Best val Acc: {best_acc:4f}')

    # 绘制训练过程曲线
    plt.figure(figsize=(12, 4))
    plt.subplot(1, 2, 1)
    plt.plot(train_losses, label='Train Loss')
    plt.plot(val_losses, label='Val Loss')
    plt.title('Loss Curve')
    plt.xlabel('Epoch')
    plt.ylabel('Loss')
    plt.legend()

    plt.subplot(1, 2, 2)
    plt.plot(train_accs, label='Train Accuracy')
    plt.plot(val_accs, label='Val Accuracy')
    plt.title('Accuracy Curve')
    plt.xlabel('Epoch')
    plt.ylabel('Accuracy')
    plt.legend()
    plt.tight_layout()
    plt.savefig('training_curves.png')
    plt.close()

    # 加载最佳模型权重
    model.load_state_dict(best_model_wts)
    return model

# 5. 训练模型
model = train_model(model, criterion, optimizer, scheduler, num_epochs=30)

# 6. 保存模型到 models/ 目录
model_save_path = '../../models/dog_classifier_scratch.pth'
torch.save(model.state_dict(), model_save_path)
print(f"模型已保存为 {model_save_path}")

# 7. 预测函数
def predict_image(image_path, model, transform):
    from PIL import Image

    # 加载并预处理图像
    image = Image.open(image_path).convert('RGB')  # 确保是RGB格式
    image = transform(image).unsqueeze(0)  # 添加批次维度
    image = image.to(device)

    # 预测
    model.eval()
    with torch.no_grad():
        outputs = model(image)
        _, preds = torch.max(outputs, 1)
        confidence = torch.nn.functional.softmax(outputs, dim=1)[0][preds[0]].item()

    return class_names[preds[0]], confidence

# 主程序入口
if __name__ == '__main__':
    # 1. 准备数据
    # 数据集路径（已在前面定义）
    # 2. 定义模型
    model = DogClassifier(num_classes=len(class_names))
    model = model.to(device)

    # 3. 定义损失函数和优化器（与前面保持一致）
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001, weight_decay=1e-5)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, 'max', patience=3, factor=0.5)

    # 4. 训练模型
    model = train_model(model, criterion, optimizer, scheduler, num_epochs=30)

    # 5. 保存模型
    torch.save(model.state_dict(), model_save_path)
    print(f"模型已保存为 {model_save_path}")

    # 示例预测
    # test_image_path = "test_dog.jpg"  # 替换为你的测试图片路径
    # result, confidence = predict_image(test_image_path, model, data_transforms['val'])
    # print(f"预测结果: {result}, 置信度: {confidence:.2f}")