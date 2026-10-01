import numpy as np
import os
import cv2
from tensor import Tensor, Model, Linear, ReLU, MSELoss, SGD
import matplotlib.pyplot as plt

class DogRecognizer:
    def __init__(self):
        # 初始化模型
        self.model = Model()
        # 假设输入图像是32x32x3的RGB图像
        self.input_size = 32 * 32 * 3

        # 构建神经网络
        self.model.add(Linear(self.input_size, 128))
        self.model.add(ReLU())
        self.model.add(Linear(128, 64))
        self.model.add(ReLU())
        self.model.add(Linear(64, 2))  # 修改为2个输出神经元，对应2个类别

        # 创建优化器和损失函数
        self.optimizer = SGD(self.model.params, lr=0.001)
        self.criterion = MSELoss()

        # 类别标签映射
        self.class_names = ['dog', 'non_dog']

    def load_dataset(self, dataset_dir):
        images = []
        labels = []

        # 遍历数据集目录
        for class_idx, class_name in enumerate(self.class_names):
            class_dir = os.path.join(dataset_dir, class_name)
            if not os.path.exists(class_dir):
                continue

            for img_name in os.listdir(class_dir):
                img_path = os.path.join(class_dir, img_name)

                # 读取图像并调整大小
                img = cv2.imread(img_path)
                if img is None:
                    continue

                img = cv2.resize(img, (32, 32))
                img = img.astype(np.float32) / 255.0  # 归一化
                img = img.flatten()  # 展平为一维向量

                images.append(img)
                labels.append(class_idx)

        # 转换为Tensor
        X = Tensor(np.array(images))
        y = Tensor(np.eye(2)[labels])  # 独热编码

        return X, y

    def train(self, X, y, epochs=100, batch_size=32):
        """
        训练模型
        :param X: 训练数据
        :param y: 训练标签
        :param epochs: 训练轮数
        :param batch_size: 批次大小
        """
        num_samples = X.data.shape[0]

        # 检查样本数量是否为0
        if num_samples == 0:
            print("错误: 没有可用的训练样本。")
            return

        # 确保批次大小不大于样本数量
        batch_size = min(batch_size, num_samples)
        num_batches = num_samples // batch_size

        loss_history = []

        for epoch in range(epochs):
            epoch_loss = 0

            # 打乱数据
            indices = np.random.permutation(num_samples)
            X_shuffled = Tensor(X.data[indices])
            y_shuffled = Tensor(y.data[indices])

            for i in range(num_batches):
                # 获取批次数据
                start = i * batch_size
                end = start + batch_size
                X_batch = X_shuffled[start:end]
                y_batch = y_shuffled[start:end]

                # 前向传播
                outputs = self.model.forward(X_batch)
                loss = self.criterion(outputs, y_batch)

                # 反向传播和优化
                self.optimizer.zero_grad()
                loss.backward()
                self.optimizer.step()

                epoch_loss += loss.data.item()

            # 计算平均损失
            avg_loss = epoch_loss / num_batches
            loss_history.append(avg_loss)

            if (epoch + 1) % 10 == 0:
                print(f'Epoch [{epoch+1}/{epochs}], Loss: {avg_loss:.4f}')

        # 绘制损失曲线
        plt.plot(range(1, epochs+1), loss_history)
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.title('Training Loss')
        plt.savefig('training_loss.png')
        plt.close()

    def predict(self, img_path):
        """
        预测图像中的狗品种
        :param img_path: 图像路径
        :return: 预测的狗品种
        """
        # 读取和预处理图像
        img = cv2.imread(img_path)
        if img is None:
            return "无法读取图像"

        img = cv2.resize(img, (32, 32))
        img = img.astype(np.float32) / 255.0
        img = img.flatten()

        # 转换为Tensor并预测
        input_tensor = Tensor(img)
        output = self.model.forward(input_tensor)

        # 获取预测类别
        predicted_class = np.argmax(output.data)
        return self.class_names[predicted_class]

    def save_model(self, path):
        """
        保存模型参数
        :param path: 保存路径
        """
        params = []
        for param in self.model.params:
            params.append(param.data)
        np.savez(path, *params)

    def load_model(self, path):
        """
        加载模型参数
        :param path: 加载路径
        """
        data = np.load(path)
        for i, param in enumerate(self.model.params):
            param.data = data[f'arr_{i}']

# 示例用法
if __name__ == "__main__":
    # 创建狗识别器
    dog_recognizer = DogRecognizer()

    # 加载数据集
    print("加载数据集...")
    dataset_dir = '../../data/dog_dataset/train/'
    X, y = dog_recognizer.load_dataset(dataset_dir)
    print(f"加载完成，共 {X.data.shape[0]} 个样本")

    # 训练模型
    print("开始训练...")
    dog_recognizer.train(X, y, epochs=50, batch_size=32)
    print("训练完成！")

    # 保存模型
    model_path = "weights/dog_recognizer_model.npz"
    dog_recognizer.save_model(model_path)
    print(f"模型已保存到 {model_path}")

    # 示例预测
    # 假设test.jpg是测试图像
    # prediction = dog_recognizer.predict("test.jpg")
    # print(f"预测结果: {prediction}")