import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
import matplotlib.gridspec as gridspec
import random
from matplotlib.patches import Rectangle
import matplotlib.colors as mcolors

# 设置中文字体
plt.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

# 生成随机颜色
colors = list(mcolors.TABLEAU_COLORS.values())
random.shuffle(colors)

# ----------------------------
# 模拟数据和模型
# ----------------------------
class DogRecognitionModel:
    """模拟小狗识别模型"""
    def __init__(self):
        # 模型参数
        self.weights = np.random.randn(32*32*3, 2)  # 简单模拟权重
        self.bias = np.random.randn(2)
        self.learning_rate = 0.01
        self.loss_history = []
        self.accuracy_history = []
        self.epoch = 0
        
    def preprocess(self, image):
        """预处理图像：缩放、归一化"""
        # 确保图像是3D的(高度,宽度,通道)
        if len(image.shape) == 2:  # 如果是灰度图
            image = np.stack((image,)*3, axis=-1)  # 转换为3通道
        
        # 调整大小为32x32x3
        resized = np.resize(image, (32, 32, 3))
        normalized = resized / 255.0  # 归一化到[0,1]
        flattened = normalized.flatten()  # 展平为32*32*3=3072个元素
        return flattened
    
    def forward(self, x):
        """前向传播"""
        logits = np.dot(x, self.weights) + self.bias
        probabilities = self.softmax(logits)
        return probabilities
    
    def softmax(self, x):
        """softmax激活函数"""
        exp_x = np.exp(x - np.max(x))  # 防止溢出
        return exp_x / np.sum(exp_x)
    
    def compute_loss(self, y_pred, y_true):
        """计算交叉熵损失"""
        epsilon = 1e-10
        return -np.sum(y_true * np.log(y_pred + epsilon))
    
    def backward(self, x, y_pred, y_true):
        """反向传播计算梯度"""
        error = y_pred - y_true
        dw = np.outer(x, error)
        db = error
        return dw, db
    
    def update_weights(self, dw, db):
        """更新权重"""
        self.weights -= self.learning_rate * dw
        self.bias -= self.learning_rate * db
    
    def train_step(self, x, y):
        """单步训练"""
        x_processed = self.preprocess(x)
        y_pred = self.forward(x_processed)
        loss = self.compute_loss(y_pred, y)
        
        # 反向传播和参数更新
        dw, db = self.backward(x_processed, y_pred, y)
        self.update_weights(dw, db)
        
        # 计算准确率
        pred_class = np.argmax(y_pred)
        true_class = np.argmax(y)
        accuracy = 1 if pred_class == true_class else 0
        
        return loss, accuracy, y_pred
    
    def train_epoch(self, train_data, batch_size=8):
        """训练一个epoch"""
        self.epoch += 1
        total_loss = 0
        total_accuracy = 0
        num_samples = len(train_data)
        
        # 打乱数据
        random.shuffle(train_data)
        
        # 批量训练
        for i in range(0, num_samples, batch_size):
            batch = train_data[i:i+batch_size]
            batch_loss = 0
            batch_accuracy = 0
            
            for x, y in batch:
                loss, acc, _ = self.train_step(x, y)
                batch_loss += loss
                batch_accuracy += acc
            
            # 记录平均损失和准确率
            avg_loss = batch_loss / len(batch)
            avg_acc = batch_accuracy / len(batch)
            self.loss_history.append(avg_loss)
            self.accuracy_history.append(avg_acc)
        
        return total_loss / num_samples, total_accuracy / num_samples

# 生成模拟图像数据
def generate_sample_image(is_dog=True):
    """生成模拟的小狗或非小狗图像"""
    # 为了可视化，创建简单的图像表示
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    
    if is_dog:
        # 绘制一个简单的小狗轮廓
        # 身体
        img[30:50, 20:40, :] = [210, 180, 140]  # 棕褐色
        # 头部
        img[15:30, 25:35, :] = [210, 180, 140]
        # 眼睛
        img[20:22, 28:30, :] = [0, 0, 0]
        img[20:22, 32:34, :] = [0, 0, 0]
        # 耳朵
        img[10:20, 22:26, :] = [210, 180, 140]
        img[10:20, 36:40, :] = [210, 180, 140]
    else:
        # 绘制一个简单的非狗图像（例如猫）
        # 身体
        img[30:50, 20:40, :] = [169, 169, 169]  # 灰色
        # 头部
        img[15:30, 25:35, :] = [169, 169, 169]
        # 眼睛
        img[20:22, 28:30, :] = [255, 255, 0]
        img[20:22, 32:34, :] = [255, 255, 0]
        # 耳朵（三角形）
        for i in range(10):
            img[15-i:16-i, 22:22+i, :] = [169, 169, 169]
            img[15-i:16-i, 40-i:40, :] = [169, 169, 169]
    
    return img

# 创建数据集
def create_dataset(num_samples=100):
    """创建小狗识别数据集"""
    dataset = []
    for i in range(num_samples):
        # 一半是狗，一半不是
        is_dog = i % 2 == 0
        img = generate_sample_image(is_dog)
        # 标签：[1,0]表示是狗，[0,1]表示不是狗
        label = np.array([1, 0]) if is_dog else np.array([0, 1])
        dataset.append((img, label))
    return dataset

# ----------------------------
# 动画制作
# ----------------------------
def create_training_animation():
    # 创建模型和数据集
    model = DogRecognitionModel()
    train_dataset = create_dataset(100)
    test_dataset = create_dataset(20)
    
    # 训练过程步骤
    steps = []
    num_epochs = 5
    
    # 初始化步骤列表
    steps.append({
        "stage": "准备阶段",
        "step": "数据收集",
        "description": "收集带标签的图像数据：包含小狗和其他动物/物体"
    })
    
    steps.append({
        "stage": "准备阶段",
        "step": "数据预处理",
        "description": "图像缩放、归一化和数据增强，将原始图像转换为模型可处理的格式"
    })
    
    steps.append({
        "stage": "准备阶段",
        "step": "模型初始化",
        "description": "创建卷积神经网络(CNN)模型，初始化权重参数"
    })
    
    # 添加训练步骤
    for epoch in range(num_epochs):
        steps.append({
            "stage": "训练阶段",
            "step": f"第{epoch+1}轮训练",
            "description": f"使用训练数据进行第{epoch+1}轮训练，更新模型参数"
        })
    
    # 添加评估步骤
    steps.append({
        "stage": "评估阶段",
        "step": "模型评估",
        "description": "使用测试数据评估模型性能，计算准确率和损失"
    })
    
    steps.append({
        "stage": "应用阶段",
        "step": "模型应用",
        "description": "使用训练好的模型对新图像进行预测"
    })
    
    # 创建图形
    fig = plt.figure(figsize=(14, 10))
    gs = gridspec.GridSpec(3, 3, height_ratios=[1, 1, 1])
    
    # 子图位置
    ax_image = fig.add_subplot(gs[0, 0])          # 示例图像
    ax_model = fig.add_subplot(gs[0, 1:3])        # 模型结构
    ax_loss = fig.add_subplot(gs[1, 0:2])         # 损失曲线
    ax_accuracy = fig.add_subplot(gs[1, 2])       # 准确率曲线
    ax_details = fig.add_subplot(gs[2, :])        # 训练细节
    
    # 标题
    title = fig.suptitle("", fontsize=16)
    
    # 当前步骤索引
    current_step = 0
    current_batch = 0
    batch_interval = 5  # 每5个批次更新一次动画
    
    # 训练状态
    training_state = {
        "epoch": 0,
        "batch": 0,
        "current_image": None,
        "current_label": None,
        "prediction": None,
        "loss": 0,
        "accuracy": 0
    }
    
    def draw_model_structure(ax, stage):
        """绘制模型结构"""
        ax.clear()
        ax.set_title("CNN模型结构")
        ax.axis('off')
        
        # 输入层
        input_rect = Rectangle((0.1, 0.7), 0.2, 0.2, fill=True, color='lightblue', 
                              edgecolor='black', label='输入层\n(32x32x3)')
        ax.add_patch(input_rect)
        ax.text(0.2, 0.8, "输入层\n(32x32x3)", ha='center', va='center')
        
        # 卷积层1
        conv1_rect = Rectangle((0.4, 0.75), 0.2, 0.1, fill=True, color='lightgreen', 
                              edgecolor='black')
        ax.add_patch(conv1_rect)
        ax.text(0.5, 0.8, "卷积层1\n(16通道)", ha='center', va='center', fontsize=8)
        
        # 池化层1
        pool1_rect = Rectangle((0.4, 0.6), 0.2, 0.1, fill=True, color='yellow', 
                              edgecolor='black')
        ax.add_patch(pool1_rect)
        ax.text(0.5, 0.65, "池化层1\n(16x16)", ha='center', va='center', fontsize=8)
        
        # 卷积层2
        conv2_rect = Rectangle((0.7, 0.75), 0.2, 0.1, fill=True, color='lightgreen', 
                              edgecolor='black')
        ax.add_patch(conv2_rect)
        ax.text(0.8, 0.8, "卷积层2\n(32通道)", ha='center', va='center', fontsize=8)
        
        # 池化层2
        pool2_rect = Rectangle((0.7, 0.6), 0.2, 0.1, fill=True, color='yellow', 
                              edgecolor='black')
        ax.add_patch(pool2_rect)
        ax.text(0.8, 0.65, "池化层2\n(8x8)", ha='center', va='center', fontsize=8)
        
        # 全连接层
        fc_rect = Rectangle((0.7, 0.4), 0.2, 0.1, fill=True, color='orange', 
                           edgecolor='black')
        ax.add_patch(fc_rect)
        ax.text(0.8, 0.45, "全连接层\n(64单元)", ha='center', va='center', fontsize=8)
        
        # 输出层
        output_rect = Rectangle((0.7, 0.2), 0.2, 0.1, fill=True, color='salmon', 
                              edgecolor='black')
        ax.add_patch(output_rect)
        ax.text(0.8, 0.25, "输出层\n(2类)", ha='center', va='center', fontsize=8)
        
        # 连接线
        if stage in ["训练阶段", "评估阶段", "应用阶段"]:
            ax.plot([0.3, 0.4], [0.8, 0.8], 'k-', lw=1, alpha=0.7)
            ax.plot([0.5, 0.5], [0.75, 0.6], 'k-', lw=1, alpha=0.7)
            ax.plot([0.6, 0.7], [0.65, 0.65], 'k-', lw=1, alpha=0.7)
            ax.plot([0.8, 0.8], [0.75, 0.6], 'k-', lw=1, alpha=0.7)
            ax.plot([0.8, 0.8], [0.6, 0.45], 'k-', lw=1, alpha=0.7)
            ax.plot([0.8, 0.8], [0.45, 0.25], 'k-', lw=1, alpha=0.7)
            
            # 突出显示当前激活的层
            if stage == "训练阶段":
                layer_idx = min(current_batch // 10, 5)
                if layer_idx >= 0: conv1_rect.set_alpha(0.3 + min(0.7, current_batch/50))
                if layer_idx >= 1: pool1_rect.set_alpha(0.3 + min(0.7, current_batch/50))
                if layer_idx >= 2: conv2_rect.set_alpha(0.3 + min(0.7, current_batch/50))
                if layer_idx >= 3: pool2_rect.set_alpha(0.3 + min(0.7, current_batch/50))
                if layer_idx >= 4: fc_rect.set_alpha(0.3 + min(0.7, current_batch/50))
                if layer_idx >= 5: output_rect.set_alpha(0.3 + min(0.7, current_batch/50))
    
    def update(frame):
        nonlocal current_step, current_batch, training_state
        
        # 准备阶段
        if current_step < 3:
            step = steps[current_step]
            title.set_text(f"{step['stage']}: {step['step']}")
            
            # 清空所有子图
            ax_image.clear()
            ax_loss.clear()
            ax_accuracy.clear()
            ax_details.clear()
            
            # 绘制模型结构（灰色表示未激活）
            draw_model_structure(ax_model, step['stage'])
            
            # 显示描述
            ax_details.text(0.05, 0.5, step['description'], 
                           ha='left', va='center', wrap=True, fontsize=10)
            ax_details.axis('off')
            
            # 数据收集阶段
            if current_step == 0:
                ax_image.set_title("示例训练数据")
                # 显示几张示例图片
                for i in range(4):
                    is_dog = i % 2 == 0
                    img = generate_sample_image(is_dog)
                    sub_ax = fig.add_axes([0.05 + (i%2)*0.2, 0.8 - (i//2)*0.15, 0.18, 0.13])
                    sub_ax.imshow(img)
                    sub_ax.set_title("小狗" if is_dog else "非小狗")
                    sub_ax.axis('off')
            
            # 数据预处理阶段
            elif current_step == 1:
                ax_image.set_title("数据预处理过程")
                # 原始图像
                orig_img = generate_sample_image(True)
                sub_ax1 = fig.add_axes([0.05, 0.8, 0.2, 0.15])
                sub_ax1.imshow(orig_img)
                sub_ax1.set_title("原始图像 (64x64)")
                sub_ax1.axis('off')
                
                # 缩放后图像
                scaled_img = orig_img[::2, ::2]  # 模拟缩放
                sub_ax2 = fig.add_axes([0.3, 0.8, 0.2, 0.15])
                sub_ax2.imshow(scaled_img)
                sub_ax2.set_title("缩放后 (32x32)")
                sub_ax2.axis('off')
                
                # 归一化后图像
                norm_img = scaled_img / 255.0
                sub_ax3 = fig.add_axes([0.55, 0.8, 0.2, 0.15])
                sub_ax3.imshow(norm_img)
                sub_ax3.set_title("归一化后")
                sub_ax3.axis('off')
            
            # 模型初始化阶段
            elif current_step == 2:
                ax_image.set_title("模型参数初始化")
                ax_image.axis('off')
                # 显示随机初始化的权重分布
                weights_sample = np.random.randn(100)
                ax_image.hist(weights_sample, bins=20, color='purple', alpha=0.7)
                ax_image.set_title("初始权重分布")
            
            # 准备阶段每帧停留较长时间
            if frame % 3 == 0:  # 每3帧推进一个步骤
                current_step += 1
        
        # 训练阶段
        elif 3 <= current_step < 3 + num_epochs:
            step = steps[current_step]
            title.set_text(f"{step['stage']}: {step['step']}")
            
            # 绘制模型结构
            draw_model_structure(ax_model, step['stage'])
            
            # 选择一个样本进行展示
            if current_batch % len(train_dataset) == 0:
                idx = random.randint(0, len(train_dataset)-1)
                training_state["current_image"], training_state["current_label"] = train_dataset[idx]
            
            # 执行训练步骤
            img, label = training_state["current_image"], training_state["current_label"]
            loss, acc, pred = model.train_step(img, label)
            
            # 更新训练状态
            training_state["loss"] = loss
            training_state["accuracy"] = acc
            training_state["prediction"] = pred
            training_state["batch"] = current_batch
            
            # 显示当前图像
            ax_image.clear()
            ax_image.imshow(img)
            true_label = "小狗" if np.argmax(label) == 0 else "非小狗"
            pred_label = "小狗" if np.argmax(pred) == 0 else "非小狗"
            color = "green" if true_label == pred_label else "red"
            ax_image.set_title(f"真实: {true_label} | 预测: {pred_label}", color=color)
            ax_image.axis('off')
            
            # 绘制损失曲线
            ax_loss.clear()
            ax_loss.plot(model.loss_history, 'b-')
            ax_loss.set_title("训练损失")
            ax_loss.set_xlabel("批次")
            ax_loss.set_ylabel("损失值")
            ax_loss.grid(True, alpha=0.3)
            
            # 绘制准确率曲线
            ax_accuracy.clear()
            ax_accuracy.plot(model.accuracy_history, 'g-')
            ax_accuracy.set_title("训练准确率")
            ax_accuracy.set_xlabel("批次")
            ax_accuracy.set_ylabel("准确率")
            ax_accuracy.set_ylim(0, 1.1)
            ax_accuracy.grid(True, alpha=0.3)
            
            # 显示训练细节
            ax_details.clear()
            ax_details.axis('off')
            details = (f"批次: {current_batch}\n"
                      f"当前损失: {loss:.4f}\n"
                      f"当前准确率: {acc:.2f}\n"
                      f"小狗概率: {pred[0]:.4f}\n"
                      f"非小狗概率: {pred[1]:.4f}")
            ax_details.text(0.05, 0.5, details, ha='left', va='center', fontsize=10)
            
            current_batch += 1
            
            # 完成当前epoch后进入下一阶段
            if current_batch >= len(train_dataset) * 2:  # 每个epoch训练2个批次
                current_batch = 0
                current_step += 1
        
        # 评估阶段
        elif current_step == 3 + num_epochs:
            step = steps[current_step]
            title.set_text(f"{step['stage']}: {step['step']}")
            
            # 绘制模型结构
            draw_model_structure(ax_model, step['stage'])
            
            # 评估模型
            test_accuracy = 0
            test_loss = 0
            for img, label in test_dataset:
                x_processed = model.preprocess(img)
                y_pred = model.forward(x_processed)
                test_loss += model.compute_loss(y_pred, label)
                pred_class = np.argmax(y_pred)
                true_class = np.argmax(label)
                test_accuracy += 1 if pred_class == true_class else 0
            
            test_accuracy /= len(test_dataset)
            test_loss /= len(test_dataset)
            
            # 显示评估结果
            ax_image.clear()
            ax_image.set_title("测试样本预测结果")
            ax_image.axis('off')
            
            # 显示几个测试样本
            for i in range(4):
                img, label = test_dataset[i]
                x_processed = model.preprocess(img)
                y_pred = model.forward(x_processed)
                true_label = "小狗" if np.argmax(label) == 0 else "非小狗"
                pred_label = "小狗" if np.argmax(y_pred) == 0 else "非小狗"
                
                sub_ax = fig.add_axes([0.05 + (i%2)*0.2, 0.8 - (i//2)*0.15, 0.18, 0.13])
                sub_ax.imshow(img)
                color = "green" if true_label == pred_label else "red"
                sub_ax.set_title(f"真: {true_label}\n预: {pred_label}", color=color, fontsize=8)
                sub_ax.axis('off')
            
            # 更新损失和准确率曲线
            ax_loss.clear()
            ax_loss.plot(model.loss_history, 'b-', label='训练损失')
            ax_loss.axhline(y=test_loss, color='r', linestyle='--', label=f'测试损失: {test_loss:.4f}')
            ax_loss.set_title("损失对比")
            ax_loss.set_xlabel("批次")
            ax_loss.set_ylabel("损失值")
            ax_loss.legend()
            ax_loss.grid(True, alpha=0.3)
            
            # 绘制准确率对比
            ax_accuracy.clear()
            ax_accuracy.plot(model.accuracy_history, 'g-', label='训练准确率')
            ax_accuracy.axhline(y=test_accuracy, color='r', linestyle='--', 
                               label=f'测试准确率: {test_accuracy:.4f}')
            ax_accuracy.set_title("准确率对比")
            ax_accuracy.set_xlabel("批次")
            ax_accuracy.set_ylabel("准确率")
            ax_accuracy.set_ylim(0, 1.1)
            ax_accuracy.legend()
            ax_accuracy.grid(True, alpha=0.3)
            
            # 显示评估细节
            ax_details.clear()
            ax_details.axis('off')
            details = (f"测试集大小: {len(test_dataset)}\n"
                      f"测试损失: {test_loss:.4f}\n"
                      f"测试准确率: {test_accuracy:.4f}\n"
                      f"模型已完成训练和评估")
            ax_details.text(0.05, 0.5, details, ha='left', va='center', fontsize=10)
            
            # 评估阶段停留几帧
            if frame % 5 == 0:
                current_step += 1
        
        # 应用阶段
        else:
            step = steps[current_step]
            title.set_text(f"{step['stage']}: {step['step']}")
            
            # 绘制模型结构
            draw_model_structure(ax_model, step['stage'])
            
            # 显示几个新样本的预测结果
            ax_image.clear()
            ax_image.set_title("新样本预测结果")
            ax_image.axis('off')
            
            for i in range(4):
                is_dog = random.choice([True, False])
                img = generate_sample_image(is_dog)
                x_processed = model.preprocess(img)
                y_pred = model.forward(x_processed)
                true_label = "小狗" if is_dog else "非小狗"
                pred_label = "小狗" if np.argmax(y_pred) == 0 else "非小狗"
                
                sub_ax = fig.add_axes([0.05 + (i%2)*0.2, 0.8 - (i//2)*0.15, 0.18, 0.13])
                sub_ax.imshow(img)
                color = "green" if true_label == pred_label else "red"
                sub_ax.set_title(f"真: {true_label}\n预: {pred_label}\n概率: {max(y_pred):.2f}", 
                                color=color, fontsize=8)
                sub_ax.axis('off')
            
            # 保持损失和准确率曲线
            ax_loss.clear()
            ax_loss.plot(model.loss_history, 'b-', label='训练损失')
            ax_loss.set_title("训练过程损失变化")
            ax_loss.set_xlabel("批次")
            ax_loss.set_ylabel("损失值")
            ax_loss.legend()
            ax_loss.grid(True, alpha=0.3)
            
            ax_accuracy.clear()
            ax_accuracy.plot(model.accuracy_history, 'g-', label='训练准确率')
            ax_accuracy.set_title("训练过程准确率变化")
            ax_accuracy.set_xlabel("批次")
            ax_accuracy.set_ylabel("准确率")
            ax_accuracy.set_ylim(0, 1.1)
            ax_accuracy.legend()
            ax_accuracy.grid(True, alpha=0.3)
            
            # 显示应用说明
            ax_details.clear()
            ax_details.axis('off')
            details = ("训练完成的模型可以用于识别新的图像\n"
                      "模型会输出'是小狗'和'不是小狗'的概率\n"
                      "概率值越高，表示模型对该判断的信心越大\n"
                      "绿色表示预测正确，红色表示预测错误")
            ax_details.text(0.05, 0.5, details, ha='left', va='center', fontsize=10)
        
        plt.tight_layout()
        return fig,
    
    # 创建动画
    anim = FuncAnimation(
        fig, 
        update, 
        frames=100,  # 总帧数
        interval=800,  # 每帧间隔时间(毫秒)
        blit=False,
        repeat=True
    )
    
    # 保存动画
    anim.save("dog_recognition_training.gif", writer=PillowWriter(fps=1.5))
    print("小狗识别模型训练过程动画已保存为 dog_recognition_training.gif")

# 运行动画生成
if __name__ == "__main__":
    create_training_animation()
    print("动画生成完成！请查看当前目录下的GIF文件。")
    