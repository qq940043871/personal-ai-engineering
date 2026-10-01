import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, transforms
from torch.utils.data import DataLoader

# 1. 数据准备
transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.1307,), (0.3081,))  # MNIST均值和标准差
])

train_dataset = datasets.MNIST(
    root='./data', train=True, download=True, transform=transform
)
test_dataset = datasets.MNIST(
    root='./data', train=False, download=True, transform=transform
)

train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
test_loader = DataLoader(test_dataset, batch_size=1000, shuffle=False)


# 2. 用MLP思想实现"卷积层"（局部连接+权值共享）
class MLPStyleConv2d(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size):
        super().__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.kernel_size = kernel_size
        
        # 定义卷积核（权值共享的核心）
        self.kernel = nn.Parameter(
            torch.randn(out_channels, in_channels, kernel_size, kernel_size)
        )
        self.bias = nn.Parameter(torch.randn(out_channels))
        
    def forward(self, x):
        # x形状: (batch_size, in_channels, height, width)
        batch_size, _, height, width = x.shape
        out_height = height - self.kernel_size + 1
        out_width = width - self.kernel_size + 1
        
        # 初始化输出
        output = torch.zeros(batch_size, self.out_channels, out_height, out_width)
        
        # 手动实现局部连接和权值共享（模拟卷积）
        for i in range(out_height):
            for j in range(out_width):
                # 提取局部区域（感受野）
                local_region = x[:, :, i:i+self.kernel_size, j:j+self.kernel_size]
                # 用同一卷积核计算（权值共享）
                for c_out in range(self.out_channels):
                    output[:, c_out, i, j] = torch.sum(
                        local_region * self.kernel[c_out]
                    ) + self.bias[c_out]
        
        return output


# 3. 池化层（下采样）
class Pool2d(nn.Module):
    def __init__(self, kernel_size=2, mode='max'):
        super().__init__()
        self.kernel_size = kernel_size
        self.mode = mode
        
    def forward(self, x):
        batch_size, channels, height, width = x.shape
        out_height = height // self.kernel_size
        out_width = width // self.kernel_size
        
        output = torch.zeros(batch_size, channels, out_height, out_width)
        
        for i in range(out_height):
            for j in range(out_width):
                # 提取池化区域
                pool_region = x[
                    :, :,
                    i*self.kernel_size:(i+1)*self.kernel_size,
                    j*self.kernel_size:(j+1)*self.kernel_size
                ]
                # 最大池化或平均池化
                if self.mode == 'max':
                    output[:, :, i, j] = torch.max(pool_region, dim=(2, 3)).values
                else:
                    output[:, :, i, j] = torch.mean(pool_region, dim=(2, 3))
        
        return output


# 4. 完整网络（MLP风格的CNN）
class MLPCNN(nn.Module):
    def __init__(self):
        super().__init__()
        # 模拟CNN的卷积+池化结构
        self.conv1 = MLPStyleConv2d(in_channels=1, out_channels=10, kernel_size=3)
        self.pool1 = Pool2d(kernel_size=2)
        self.conv2 = MLPStyleConv2d(in_channels=10, out_channels=20, kernel_size=3)
        self.pool2 = Pool2d(kernel_size=2)
        
        # 全连接层（标准MLP）
        self.fc1 = nn.Linear(20 * 5 * 5, 128)  # 计算依据：MNIST图像经两次卷积池化后的尺寸
        self.fc2 = nn.Linear(128, 10)
        self.relu = nn.ReLU()
        
    def forward(self, x):
        # 卷积+池化1
        x = self.conv1(x)
        x = self.relu(x)
        x = self.pool1(x)
        
        # 卷积+池化2
        x = self.conv2(x)
        x = self.relu(x)
        x = self.pool2(x)
        
        # 展平后进入全连接层
        x = x.view(x.size(0), -1)
        x = self.fc1(x)
        x = self.relu(x)
        x = self.fc2(x)
        
        return x


# 5. 训练和测试
def train(model, device, train_loader, optimizer, epoch):
    model.train()
    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.to(device), target.to(device)
        optimizer.zero_grad()
        output = model(data)
        loss = nn.CrossEntropyLoss()(output, target)
        loss.backward()
        optimizer.step()
        
        if batch_idx % 100 == 0:
            print(f'Train Epoch: {epoch} [{batch_idx*len(data)}/{len(train_loader.dataset)} '
                  f'({100.*batch_idx/len(train_loader):.0f}%)]\tLoss: {loss.item():.6f}')


def test(model, device, test_loader):
    model.eval()
    test_loss = 0
    correct = 0
    with torch.no_grad():
        for data, target in test_loader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            test_loss += nn.CrossEntropyLoss()(output, target, reduction='sum').item()
            pred = output.argmax(dim=1, keepdim=True)
            correct += pred.eq(target.view_as(pred)).sum().item()
    
    test_loss /= len(test_loader.dataset)
    print(f'\nTest set: Average loss: {test_loss:.4f}, '
          f'Accuracy: {correct}/{len(test_loader.dataset)} '
          f'({100.*correct/len(test_loader.dataset):.0f}%)\n')


# 6. 运行
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = MLPCNN().to(device)
optimizer = optim.Adam(model.parameters(), lr=0.001)

for epoch in range(1, 6):  # 训练5轮
    train(model, device, train_loader, optimizer, epoch)
    test(model, device, test_loader)
