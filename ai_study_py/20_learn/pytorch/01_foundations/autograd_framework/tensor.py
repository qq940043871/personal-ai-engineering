import numpy as np

# 1. 张量类（带自动求导功能）
class Tensor:
    def __init__(self, data, requires_grad=False, parents=None, op=None):
        self.data = np.array(data)
        self.requires_grad = requires_grad
        self.grad = None
        self.parents = parents or []
        self.op = op  # 记录产生该张量的操作
        
        if requires_grad:
            self.grad = np.zeros_like(self.data)
    
    def __getitem__(self, key):
        # 实现下标操作
        result = Tensor(
            self.data[key],
            requires_grad=self.requires_grad,
            parents=[self],
            op="slice"
        )
        
        def backward():
            if self.requires_grad:
                grad = np.zeros_like(self.data)
                grad[key] = result.grad
                self.grad += grad
        
        result.backward = backward
        return result
    
    def __add__(self, other):
        if not isinstance(other, Tensor):
            other = Tensor(other)
            
        result = Tensor(
            self.data + other.data,
            requires_grad=self.requires_grad or other.requires_grad,
            parents=[self, other],
            op="add"
        )
        
        # 定义反向传播函数
        def backward():
            if self.requires_grad:
                self.grad += result.grad
            if other.requires_grad:
                other.grad += result.grad
        
        result.backward = backward
        return result
    
    def __sub__(self, other):
        if not isinstance(other, Tensor):
            other = Tensor(other)
            
        result = Tensor(
            self.data - other.data,
            requires_grad=self.requires_grad or other.requires_grad,
            parents=[self, other],
            op="sub"
        )
        
        def backward():
            if self.requires_grad:
                self.grad += result.grad
            if other.requires_grad:
                other.grad -= result.grad
        
        result.backward = backward
        return result
    
    def __mul__(self, other):
        if not isinstance(other, Tensor):
            other = Tensor(other)
            
        result = Tensor(
            self.data * other.data,
            requires_grad=self.requires_grad or other.requires_grad,
            parents=[self, other],
            op="mul"
        )
        
        def backward():
            if self.requires_grad:
                self.grad += other.data * result.grad
            if other.requires_grad:
                other.grad += self.data * result.grad
        
        result.backward = backward
        return result
    
    def __pow__(self, power):
        if isinstance(power, Tensor):
            # 对于Tensor的幂运算，我们只支持标量Tensor
            if power.data.ndim != 0:
                raise ValueError("Power must be a scalar for tensor exponentiation")
            power = power.data.item()
                
        result = Tensor(
            self.data ** power,
            requires_grad=self.requires_grad,
            parents=[self],
            op="pow"
        )
        
        def backward():
            if self.requires_grad:
                self.grad += power * (self.data ** (power - 1)) * result.grad
        
        result.backward = backward
        return result
    
    def matmul(self, other):
        if not isinstance(other, Tensor):
            other = Tensor(other)
            
        result = Tensor(
            self.data @ other.data,
            requires_grad=self.requires_grad or other.requires_grad,
            parents=[self, other],
            op="matmul"
        )
        
        def backward():
            if self.requires_grad:
                self.grad += result.grad @ other.data.T
            if other.requires_grad:
                other.grad += self.data.T @ result.grad
        
        result.backward = backward
        return result
    
    def sum(self, axis=None):
        result = Tensor(
            self.data.sum(axis=axis),
            requires_grad=self.requires_grad,
            parents=[self],
            op="sum"
        )
        
        def backward():
            if self.requires_grad:
                grad = result.grad
                if axis is not None:
                    grad = np.expand_dims(grad, axis=axis)
                self.grad += np.broadcast_to(grad, self.data.shape)
        
        result.backward = backward
        return result
    
    def mean(self, axis=None):
        result = Tensor(
            self.data.mean(axis=axis),
            requires_grad=self.requires_grad,
            parents=[self],
            op="mean"
        )
        
        def backward():
            if self.requires_grad:
                grad = result.grad / np.prod(self.data.shape) if axis is None else \
                       result.grad / np.prod([self.data.shape[i] for i in axis])
                if axis is not None:
                    grad = np.expand_dims(grad, axis=axis)
                self.grad += np.broadcast_to(grad, self.data.shape)
        
        result.backward = backward
        return result
    
    def backward(self):
        # 初始化梯度为1（对于标量）
        if self.data.ndim == 0:
            self.grad = np.array(1.0)
        else:
            self.grad = np.ones_like(self.data)
        
        # 使用拓扑排序确保反向传播顺序正确
        visited = set()
        queue = []
        
        def topological_sort(node):
            if node not in visited and node.requires_grad:
                visited.add(node)
                for parent in node.parents:
                    topological_sort(parent)
                queue.append(node)
        
        topological_sort(self)
        
        # 执行反向传播
        for node in queue:
            if hasattr(node, 'backward') and node.parents:
                node.backward()
    
    def __repr__(self):
        return f"Tensor({self.data}, requires_grad={self.requires_grad})"


# 2. 神经网络层
class Layer:
    def __init__(self):
        self.params = []
    
    def forward(self, x):
        raise NotImplementedError


class Linear(Layer):
    def __init__(self, in_features, out_features):
        super().__init__()
        # 初始化权重和偏置
        self.weight = Tensor(
            np.random.randn(in_features, out_features) * np.sqrt(2.0 / in_features),
            requires_grad=True
        )
        self.bias = Tensor(
            np.zeros((1, out_features)),
            requires_grad=True
        )
        self.params.extend([self.weight, self.bias])
    
    def forward(self, x):
        return x.matmul(self.weight) + self.bias


# 3. 激活函数
class ReLU(Layer):
    def __init__(self):
        super().__init__()
    
    def forward(self, x):
        result = Tensor(
            np.maximum(0, x.data),
            requires_grad=x.requires_grad,
            parents=[x],
            op="relu"
        )
        
        def backward():
            if x.requires_grad:
                x.grad += (result.data > 0) * result.grad
        
        result.backward = backward
        return result


# 4. 损失函数
class MSELoss:
    def __call__(self, pred, target):
        return ((pred - target) **2).mean()


# 5. 优化器
class SGD:
    def __init__(self, params, lr=0.01):
        self.params = params
        self.lr = lr
    
    def step(self):
        for param in self.params:
            if param.requires_grad:
                param.data -= self.lr * param.grad
    
    def zero_grad(self):
        for param in self.params:
            if param.requires_grad:
                param.grad = np.zeros_like(param.data)


# 6. 神经网络模型
class Model(Layer):
    def __init__(self):
        super().__init__()
        self.layers = []
    
    def add(self, layer):
        self.layers.append(layer)
        self.params.extend(layer.params)
    
    def forward(self, x):
        for layer in self.layers:
            x = layer.forward(x)
        return x


# 示例用法
if __name__ == "__main__":
    # 创建一个简单的神经网络
    model = Model()
    model.add(Linear(2, 10))
    model.add(ReLU())
    model.add(Linear(10, 1))
    
    # 创建优化器
    optimizer = SGD(model.params, lr=0.01)
    
    # 创建损失函数
    criterion = MSELoss()
    
    # 生成一些随机数据
    X = Tensor(np.random.randn(100, 2))  # 100个样本，每个样本2个特征
    y = Tensor(3 * X.data[:, 0:1] + 2 * X.data[:, 1:2] + np.random.randn(100, 1) * 0.1)  # 线性关系加噪声
    
    # 训练模型
    for epoch in range(1000):
        # 前向传播
        outputs = model.forward(X)
        loss = criterion(outputs, y)
        
        # 反向传播和优化
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        
        if (epoch + 1) % 100 == 0:
            print(f'Epoch [{epoch+1}/1000], Loss: {loss.data.item():.4f}')
    
    print("\n训练完成！")
    print("第一层权重：\n", model.layers[0].weight.data)
    print("第一层偏置：\n", model.layers[0].bias.data)
    print("最后一层权重：\n", model.layers[2].weight.data)
    print("最后一层偏置：\n", model.layers[2].bias.data)
