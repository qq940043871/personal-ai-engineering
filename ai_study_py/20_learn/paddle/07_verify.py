import paddle.nn.functional as F
import paddle
from paddle.vision.transforms import Compose, Normalize
from lenet import LeNet

transform = Compose([Normalize(mean=[127.5], std=[127.5], data_format="CHW")])
# 使用transform对数据集做归一化
print("download training data and load training data")
test_dataset = paddle.vision.datasets.MNIST(mode="test", transform=transform)
print("load finished")

model = LeNet()

test_loader = paddle.io.DataLoader(
    test_dataset, places=paddle.CPUPlace(), batch_size=64
)


# 加载测试数据集
def test(model):
    model.eval()
    batch_size = 64
    for batch_id, data in enumerate(test_loader()):
        x_data = data[0]
        y_data = data[1]
        predicts = model(x_data)
        # 获取预测结果
        loss = F.cross_entropy(predicts, y_data)
        acc = paddle.metric.accuracy(predicts, y_data)
        if batch_id % 20 == 0:
            print(
                "batch_id: {}, loss is: {}, acc is: {}".format(
                    batch_id, loss.numpy(), acc.numpy()
                )
            )


test(model)
