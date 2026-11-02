import numpy as np

class Perceptron:
    """
    简单感知机实现
    用于二元分类任务
    """
    def __init__(self, learning_rate=0.1, epochs=100):
        """
        初始化感知机
        
        参数:
        learning_rate: 学习率，控制权重更新的步长
        epochs: 训练轮数，即遍历训练数据的次数
        """
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.weights = None  # 权重
        self.bias = None     # 偏置项
    
    def activation(self, x):
        """激活函数：阶跃函数"""
        return 1 if x >= 0 else 0
    
    def fit(self, X, y):
        """
        训练感知机
        
        参数:
        X: 输入特征，形状为(n_samples, n_features)
        y: 目标标签，形状为(n_samples,)，取值为0或1
        """
        n_samples, n_features = X.shape
        
        # 初始化权重和偏置
        self.weights = np.zeros(n_features)
        self.bias = 0
        
        # 训练感知机
        for _ in range(self.epochs):
            for idx in range(n_samples):
                # 计算线性输出
                linear_output = np.dot(X[idx], self.weights) + self.bias
                # 应用激活函数
                y_pred = self.activation(linear_output)
                
                # 权重更新规则：w = w + η(y - ŷ)x
                # 偏置更新规则：b = b + η(y - ŷ)
                update = self.learning_rate * (y[idx] - y_pred)
                self.weights += update * X[idx]
                self.bias += update
    
    def predict(self, X):
        """
        预测新样本
        
        参数:
        X: 输入特征，形状为(n_samples, n_features)
        
        返回:
        预测标签，形状为(n_samples,)，取值为0或1
        """
        linear_output = np.dot(X, self.weights) + self.bias
        return np.array([self.activation(x) for x in linear_output])


# 测试感知机
if __name__ == "__main__":
    # 创建一个简单的数据集（逻辑与问题）
    X = np.array([
        [0, 0],
        [0, 1],
        [1, 0],
        [1, 1]
    ])
    y = np.array([0, 0, 0, 1])  # AND逻辑的输出
    
    # 创建并训练感知机
    perceptron = Perceptron(learning_rate=0.1, epochs=10)
    perceptron.fit(X, y)
    
    # 测试预测
    predictions = perceptron.predict(X)
    print("输入数据:", X)
    print("预测结果:", predictions)
    print("实际结果:", y)
    print("准确率:", np.mean(predictions == y))
    print("学习到的权重:", perceptron.weights)
    print("学习到的偏置:", perceptron.bias)
