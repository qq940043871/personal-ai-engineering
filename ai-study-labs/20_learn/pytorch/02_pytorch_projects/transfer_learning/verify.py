# 模型验证脚本 - 用于验证 dog_classifier.pth（ResNet18 迁移学习）
import torch
import torch.nn as nn
from torchvision import transforms, models
from PIL import Image
import os
import matplotlib.pyplot as plt

# 设置设备：优先使用GPU，没有则用CPU
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
print(f"使用设备: {device}")

# 1. 定义数据预处理（与训练时的验证集预处理保持一致）
data_transform = transforms.Compose([
    transforms.Resize(256),            # 缩放
    transforms.CenterCrop(224),        # 中心裁剪
    transforms.ToTensor(),             # 转换为张量
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])  # 标准化
])

# 2. 定义模型架构（与训练时保持一致）
def build_model(num_classes):
    # 加载预训练的ResNet18
    model = models.resnet18(pretrained=False)  # 不加载预训练权重，我们将加载自己的权重

    # 获取最后一层的输入特征数
    num_ftrs = model.fc.in_features

    # 替换最后一层，适应我们的分类任务
    model.fc = nn.Linear(num_ftrs, num_classes)

    # 将模型移动到设备上
    model = model.to(device)

    return model

# 3. 加载模型权重
def load_model(model_path, num_classes=2):
    model = build_model(num_classes)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model = model.to(device)
    model.eval()  # 设置为评估模式
    return model

# 4. 预测函数
def predict_image(image_path, model, transform):
    # 加载并预处理图像
    image = Image.open(image_path).convert('RGB')
    image_tensor = transform(image).unsqueeze(0)  # 添加批次维度
    image_tensor = image_tensor.to(device)

    # 预测
    with torch.no_grad():
        outputs = model(image_tensor)
        _, preds = torch.max(outputs, 1)
        confidence = torch.nn.functional.softmax(outputs, dim=1)[0][preds[0]].item()

    return preds[0], confidence, image

# 5. 批量预测函数
def batch_predict(image_folder, model, transform, class_names):
    results = []
    correct = 0
    total = 0

    # 确定当前文件夹的类别（从文件夹名称推断）
    folder_class = 'dog' if 'dog' in image_folder.lower() else 'non_dog'
    folder_class_idx = class_names.index(folder_class)

    for filename in os.listdir(image_folder):
        if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
            image_path = os.path.join(image_folder, filename)
            pred_class, confidence, _ = predict_image(image_path, model, transform)

            # 统计准确率
            total += 1
            if pred_class == folder_class_idx:
                correct += 1

            results.append((filename, class_names[pred_class], confidence))

    accuracy = correct / total if total > 0 else 0
    return results, accuracy

# 6. 可视化预测结果
def visualize_prediction(image_path, model, transform, class_names):
    pred_class, confidence, image = predict_image(image_path, model, transform)

    plt.figure(figsize=(8, 6))
    plt.imshow(image)
    plt.title(f'预测结果: {class_names[pred_class]}, 置信度: {confidence:.2f}')
    plt.axis('off')
    plt.show()

# 主程序入口
if __name__ == '__main__':
    # 模型路径
    model_path = '../../models/dog_classifier.pth'

    # 类别名称（与训练时保持一致）
    class_names = ['dog', 'non_dog']

    # 加载模型
    print(f"加载模型: {model_path}")
    if os.path.exists(model_path):
        model = load_model(model_path, num_classes=len(class_names))
        print("模型加载成功!")
    else:
        print(f"模型文件不存在: {model_path}")
        print("请先运行 train.py 训练模型")
        exit()

    # 测试单张图片
    test_image_path = "../../data/dog_dataset/val/non_dog/pig (17).png"

    if os.path.exists(test_image_path):
        visualize_prediction(test_image_path, model, data_transform, class_names)
    else:
        print(f"测试图片不存在: {test_image_path}")
        print("请修改 test_image_path 变量指向一个有效的图片文件")

    # 批量测试（可选）
    test_folder = "../../data/dog_dataset/val/non_dog"

    if os.path.exists(test_folder):
        print(f"批量测试文件夹: {test_folder}")
        results, accuracy = batch_predict(test_folder, model, data_transform, class_names)
        print(f"文件夹准确率: {accuracy:.2f}")
        for filename, pred, conf in results[:5]:  # 只打印前5个结果
            print(f"文件: {filename}, 预测: {pred}, 置信度: {conf:.2f}")
        if len(results) > 5:
            print(f"... 以及其他 {len(results) - 5} 个结果")
    else:
        print(f"测试文件夹不存在: {test_folder}")
        print("请修改 test_folder 变量指向一个有效的文件夹")