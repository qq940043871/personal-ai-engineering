# 小狗识别模型训练代码 — ResNet18 迁移学习
import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim import lr_scheduler
from torchvision import datasets, models, transforms
import os
import time
import copy

# 设置设备：优先使用GPU，没有则用CPU
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
print(f"使用设备: {device}")

# 1. 数据准备与预处理
# 定义数据变换（训练集需要数据增强，验证集不需要）
data_transforms = {
    'train': transforms.Compose([
        transforms.RandomResizedCrop(224),  # 随机裁剪并缩放
        transforms.RandomHorizontalFlip(),  # 随机水平翻转
        transforms.RandomRotation(15),      # 随机旋转
        transforms.ToTensor(),              # 转换为张量
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])  # 标准化
    ]),
    'val': transforms.Compose([
        transforms.Resize(256),             # 缩放
        transforms.CenterCrop(224),         # 中心裁剪
        transforms.ToTensor(),              # 转换为张量
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])  # 标准化
    ]),
}

# 数据集路径（请根据实际情况修改）
# 数据集应按照如下结构组织：
# data_dir/
#   train/
#       dog/          # 小狗图片
#       non_dog/      # 非小狗图片
#   val/
#       dog/          # 小狗图片
#       non_dog/      # 非小狗图片
data_dir = '../../data/dog_dataset'

# 加载数据集
image_datasets = {x: datasets.ImageFolder(os.path.join(data_dir, x),
                                          data_transforms[x])
                  for x in ['train', 'val']}

# 创建数据加载器
dataloaders = {x: torch.utils.data.DataLoader(image_datasets[x], batch_size=32,
                                             shuffle=True, num_workers=0)
              for x in ['train', 'val']}

# 获取数据集大小和类别名称
dataset_sizes = {x: len(image_datasets[x]) for x in ['train', 'val']}
class_names = image_datasets['train'].classes
print(f"类别: {class_names}")
print(f"训练集大小: {dataset_sizes['train']}")
print(f"验证集大小: {dataset_sizes['val']}")

# 2. 模型搭建（使用预训练的ResNet18进行迁移学习）
def build_model(num_classes):
    # 加载预训练的ResNet18
    model = models.resnet18(pretrained=True)

    # 冻结大部分参数，只训练最后几层
    for param in list(model.parameters())[:-10]:
        param.requires_grad = False

    # 获取最后一层的输入特征数
    num_ftrs = model.fc.in_features

    # 替换最后一层，适应我们的分类任务（2类：狗和非狗）
    model.fc = nn.Linear(num_ftrs, num_classes)

    # 将模型移动到设备上
    model = model.to(device)

    return model

# 构建模型（2分类：狗和非狗）
model = build_model(2)

# 3. 定义损失函数和优化器
criterion = nn.CrossEntropyLoss()  # 交叉熵损失，适用于分类任务

# 只优化需要训练的参数
optimizer = optim.Adam(filter(lambda p: p.requires_grad, model.parameters()), lr=0.001)

# 学习率调度器：每7个epoch学习率乘以0.1
exp_lr_scheduler = lr_scheduler.StepLR(optimizer, step_size=7, gamma=0.1)

# 4. 模型训练函数
def train_model(model, criterion, optimizer, scheduler, num_epochs=25):
    since = time.time()

    # 保存最佳模型权重
    best_model_wts = copy.deepcopy(model.state_dict())
    best_acc = 0.0

    for epoch in range(num_epochs):
        print(f'Epoch {epoch}/{num_epochs - 1}')
        print('-' * 10)

        # 每个epoch都有训练和验证阶段
        for phase in ['train', 'val']:
            if phase == 'train':
                model.train()  # 训练模式：启用dropout和批标准化
            else:
                model.eval()   # 评估模式：禁用dropout和批标准化

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

            if phase == 'train':
                scheduler.step()

            # 计算每个epoch的损失和准确率
            epoch_loss = running_loss / dataset_sizes[phase]
            epoch_acc = running_corrects.double() / dataset_sizes[phase]

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

    # 加载最佳模型权重
    model.load_state_dict(best_model_wts)
    return model

# 5. 训练模型（可以根据需要调整epoch数量）
model = train_model(model, criterion, optimizer, exp_lr_scheduler, num_epochs=15)

# 6. 保存模型到 models/ 目录
model_save_path = '../../models/dog_classifier.pth'
torch.save(model.state_dict(), model_save_path)
print(f"模型已保存为 {model_save_path}")

# 7. 简单的预测函数
def predict_image(image_path, model, transform):
    from PIL import Image

    # 加载并预处理图像
    image = Image.open(image_path)
    image = transform(image).unsqueeze(0)  # 添加批次维度
    image = image.to(device)

    # 预测
    model.eval()
    with torch.no_grad():
        outputs = model(image)
        _, preds = torch.max(outputs, 1)

    return class_names[preds[0]]

# 示例预测（请替换为实际图片路径）
# if __name__ == "__main__":
#     test_image_path = "test_dog.jpg"
#     result = predict_image(test_image_path, model, data_transforms['val'])
#     print(f"预测结果: {result}")