import numpy as np
import cv2
from tensor import Tensor
from dog_classifier import DogRecognizer
import os
import matplotlib.pyplot as plt
from PIL import Image

def validate_model(model_path, test_dir):
    # 创建狗识别器实例
    dog_recognizer = DogRecognizer()

    # 加载已保存的模型参数
    print(f"加载模型: {model_path}")
    dog_recognizer.load_model(model_path)
    print("模型加载完成!")

    # 评估模型在测试集上的表现
    print(f"评估模型在测试集 {test_dir} 上的表现...")

    # 记录正确预测的数量
    correct_predictions = 0
    total_predictions = 0

    # 遍历测试集目录
    for class_idx, class_name in enumerate(dog_recognizer.class_names):
        class_dir = os.path.join(test_dir, class_name)
        if not os.path.exists(class_dir):
            print(f"警告: 测试集目录 {class_dir} 不存在!")
            continue

        print(f"评估类别: {class_name}")

        for img_name in os.listdir(class_dir):
            img_path = os.path.join(class_dir, img_name)

            # 使用模型进行预测
            prediction = dog_recognizer.predict(img_path)

            # 检查预测是否正确
            if prediction == class_name:
                correct_predictions += 1
            total_predictions += 1

            # 每100张图像打印一次进度
            if total_predictions % 100 == 0:
                print(f"已评估 {total_predictions} 张图像，准确率: {correct_predictions/total_predictions:.4f}")

    # 计算总体准确率
    if total_predictions > 0:
        accuracy = correct_predictions / total_predictions
        print(f"测试完成! 总共评估 {total_predictions} 张图像，准确率: {accuracy:.4f}")
    else:
        print("错误: 没有找到测试图像!")

    return accuracy

def visualize_prediction(model_path, test_image_path):
    """
    可视化单张图像的预测结果
    :param img_path: 图像路径
    :param dog_recognizer: DogRecognizer实例
    """
   # 创建狗识别器实例
    dog_recognizer = DogRecognizer()

    # 加载已保存的模型参数
    print(f"加载模型: {model_path}")
    dog_recognizer.load_model(model_path)
    print("模型加载完成!")

    # 评估模型在测试集上的表现
    print(f"评估模型在测试集 {test_image_path} 上的表现...")

    # 使用模型进行预测
    prediction = dog_recognizer.predict(test_image_path)

    # 转换BGR为RGB以正确显示
    img = Image.open(test_image_path).convert('RGB')
    # 显示图像和预测结果
    plt.figure(figsize=(8, 6))
    plt.imshow(img)
    plt.title(f'result: {prediction}')
    plt.axis('off')
    plt.savefig('prediction_result.png')
    plt.show()

if __name__ == "__main__":
    # 模型路径
    model_path = "weights/dog_recognizer_model.npz"

    # 测试集目录
    test_dir = '../../data/dog_dataset/val'

    # 验证模型
    # 询问用户是批量验证还是单张图片验证
    print("请选择验证模式:")
    print("1. 批量验证测试集")
    print("2. 单张图片验证")
    choice = input("请输入选择 (1/2): ")

    if choice == '1':
        # 批量验证
        validate_model(model_path, test_dir)
    elif choice == '2':
        # 单张图片验证
        img_path = "../../data/dog_dataset/val/dog/dog (17).png"
        if os.path.exists(img_path):
            # 可视化预测结果
            visualize_prediction(model_path, img_path)
        else:
            print(f"错误: 图像文件不存在 {img_path}")
    else:
        print("无效的选择，请输入 1 或 2")