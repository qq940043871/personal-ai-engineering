import paddle.nn.functional as F
import paddle
from paddle.vision.transforms import Compose, Normalize
from lenet import LeNet

transform = Compose([Normalize(mean=[127.5], std=[127.5], data_format="CHW")])
# 使用transform对数据集做归一化
print("download training data and load training data")
train_dataset = paddle.vision.datasets.MNIST(mode="train", transform=transform)
test_dataset = paddle.vision.datasets.MNIST(mode="test", transform=transform)
print("load finished")

train_loader = paddle.io.DataLoader(train_dataset, batch_size=64, shuffle=True)


# 加载训练集 batch_size 设为 64
def train(model):
    model.train()
    epochs = 2
    optim = paddle.optimizer.Adam(
        learning_rate=0.001, parameters=model.parameters()
    )
    # 用Adam作为优化函数
    for epoch in range(epochs):
        for batch_id, data in enumerate(train_loader()):
            x_data = data[0]
            y_data = data[1]
            predicts = model(x_data)
            loss = F.cross_entropy(predicts, y_data)
            # 计算损失
            acc = paddle.metric.accuracy(predicts, y_data)
            loss.backward()
            if batch_id % 300 == 0:
                print(
                    "epoch: {}, batch_id: {}, loss is: {}, acc is: {}".format(
                        epoch, batch_id, loss.numpy(), acc.numpy()
                    )
                )
            optim.step()
            optim.clear_grad()


model = LeNet()
train(model)
