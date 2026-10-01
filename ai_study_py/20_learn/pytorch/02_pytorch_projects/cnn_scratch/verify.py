# 模型验证脚本
import torch
import torch.nn as nn
from torchvision import transforms
from PIL import Image
import os
import matplotlib.pyplot as plt

# 设置设备：优先使用GPU，没有则用CPU
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
print(f"使用设备: {device}")

# 1. 定义模型架构（与训练时保持一致）
class DogClassifier(nn.Module):
    def __init__(self, num_classes=2):
        super(DogClassifier, self).__init__()

        # 第一个卷积块: 输入是3通道(RGB图像)
        self.conv_block1 = nn.Sequential(
            nn.Conv2d(in_channels=3, out_channels=32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2)
        )

        # 第二个卷积块
        self.conv_block2 = nn.Sequential(
            nn.Conv2d(in_channels=32, out_channels=64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2)
        )

        # 第三个卷积块
        self.conv_block3 = nn.Sequential(
            nn.Conv2d(in_channels=64, out_channels=128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2)
        )

        # 第四个卷积块
        self.conv_block4 = nn.Sequential(
            nn.Conv2d(in_channels=128, out_channels=256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2)
        )

        # 全连接层
        self.fc_layers = nn.Sequential(
            nn.Linear(256 * 8 * 8, 1024),
            nn.ReLU(inplace=True),
            nn.Dropout(0.5),
            nn.Linear(1024, 512),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(512, num_classes)
        )

    def forward(self, x):
        x = self.conv_block1(x)
        x = self.conv_block2(x)
        x = self.conv_block3(x)
        x = self.conv_block4(x)
        x = x.view(x.size(0), -1)
        x = self.fc_layers(x)
        return x

# 2. 定义数据预处理（与训练时的验证集预处理保持一致）
data_transform = transforms.Compose([
    transforms.Resize(144),
    transforms.CenterCrop(128),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
])

# 3. 加载模型权重
def load_model(model_path, num_classes=2):
    model = DogClassifier(num_classes=num_classes)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model = model.to(device)
    model.eval()  # 设置为评估模式
    return model

# 4. 预测函数
def predict_image(image_path, model, transform):
    # 加载并预处理图像
    image = Image.open(image_path).convert('RGB')
    image_tensor = transform(image).unsqueeze(0)
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
    for filename in os.listdir(image_folder):
        if filename.endswith(('.jpg', '.jpeg', '.png')):
            image_path = os.path.join(image_folder, filename)
            pred_class, confidence, _ = predict_image(image_path, model, transform)
            results.append((filename, class_names[pred_class], confidence))
    return results

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
    model_path = '../../models/dog_classifier_scratch.pth'

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
    # test_folder = "path/to/test/folder"
    # if os.path.exists(test_folder):
    #     print(f"批量测试文件夹: {test_folder}")
    #     results = batch_predict(test_folder, model, data_transform, class_names)
    #     for filename, pred, conf in results:
    #         print(f"文件: {filename}, 预测: {pred}, 置信度: {conf:.2f}")
    # else:
    #     print(f"测试文件夹不存在: {test_folder}")