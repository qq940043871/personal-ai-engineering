# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is `20_learn/pytorch`, a PyTorch deep learning study project within the `p000_ai_study_py` monorepo. It contains educational implementations of neural networks — from a bare-bones numpy perceptron to transfer learning classifiers — each designed to teach a specific concept. Most code is in Chinese (comments, variable names, descriptions).

## Directory Structure

```
20_learn/pytorch/
├── 01_foundations/                        # 基础：从零实现
│   ├── perceptron/                        #   NumPy 感知机
│   │   └── perceptron.py
│   └── autograd_framework/                #   手写自动求导框架
│       ├── tensor.py                      #   Tensor + Linear + ReLU + SGD
│       ├── dog_classifier.py              #   狗分类器（基于自定义框架）
│       ├── validate.py                    #   验证脚本
│       └── weights/                       #   保存的 .npz 模型
│
├── 02_pytorch_projects/                   # 实际 PyTorch 项目
│   ├── cnn_scratch/                       #   从零设计 CNN
│   │   ├── train.py                       #   训练（ConvBlock×4 + FC）
│   │   └── verify.py                      #   推理验证
│   ├── transfer_learning/                 #   ResNet18 迁移学习
│   │   ├── train.py                       #   训练（微调最后几层）
│   │   └── verify.py                      #   推理验证
│   └── mlp_conv/                          #   MLP 视角理解卷积（MNIST）
│       └── mlp_cnn.py
│
├── 03_visualization/                      # 可视化与动画
│   ├── cnn_data_flow_gif.py               #   CNN 数据流变化 GIF 动画
│   ├── cnn_data_flow_print.py             #   数据形状变化打印版
│   ├── cnn_data_flow_3d.py                #   3D 张量结构变化动画
│   └── training_animation.py              #   训练过程 Loss 模拟动画
│
├── 04_tools/                              # 工具脚本
│   ├── inspect_model.py                   #   .pth 模型查看器
│   └── __init__.py
│
├── models/                                # 已训练权重
│   ├── dog_classifier.pth                 #   ResNet18 迁移学习模型
│   └── dog_classifier_scratch.pth         #   手写 CNN 模型
│
├── data/dog_dataset/                      # 数据集
│   ├── train/{dog, non_dog}/
│   └── val/{dog, non_dog}/
│
└── CLAUDE.md
```

### Learning Path (by directory number)

| # | Directory | Concept | Deps |
|---|-----------|---------|------|
| 01 | `autograd_framework/` | 张量自动求导、从头构建神经网络框架 | numpy only |
| 01 | `perceptron/` | 感知机原理与实现 | numpy only |
| 02 | `cnn_scratch/` | CNN 架构设计、训练循环、过拟合控制 | torch + torchvision |
| 02 | `transfer_learning/` | ResNet18 迁移学习、参数冻结 | torch + torchvision |
| 02 | `mlp_conv/` | 卷积 = 局部连接 + 权值共享 | torch + torchvision |
| 03 | `03_visualization/` | matplotlib 动画、数据流可视化 | torch + matplotlib + pillow |

### Key Patterns

- **Device handling**: All PyTorch scripts use `torch.device("cuda:0" if torch.cuda.is_available() else "cpu")`
- **Dataset structure expected**: `data/dog_dataset/{train,val}/{dog,non_dog}/`
- **Data preprocessing**: Standard ImageNet normalization `[0.485, 0.456, 0.406]` / `[0.229, 0.224, 0.225]`
- **Paths are now relative**: All scripts use relative paths (e.g. `../../models/`, `../../data/`). Run from the script's directory.
- **Chinese comments**: All code is self-documented in Chinese, with detailed explanations of each step
- **matplotlib animations**: `FuncAnimation` + `PillowWriter` for GIF generation, with `SimHei`/`WenQuanYi` font config for Chinese labels
- **No tests, no linting config, no CI** — this is a personal study repo

### Dependencies

Core: `torch`, `torchvision`, `numpy`, `matplotlib`
Animations: additionally `pillow` (PillowWriter)
Autograd framework: `numpy` only, plus `cv2` (opencv-python) and `PIL` for image loading

## Running Scripts

All scripts run standalone from their directory:

```bash
# 01 — Foundations (numpy only)
cd 01_foundations/perceptron && python perceptron.py
cd 01_foundations/autograd_framework && python dog_classifier.py

# 02 — PyTorch projects
cd 02_pytorch_projects/cnn_scratch && python train.py
cd 02_pytorch_projects/cnn_scratch && python verify.py
cd 02_pytorch_projects/transfer_learning && python train.py
cd 02_pytorch_projects/transfer_learning && python verify.py
cd 02_pytorch_projects/mlp_conv && python mlp_cnn.py

# 03 — Visualization
cd 03_visualization && python cnn_data_flow_gif.py
cd 03_visualization && python cnn_data_flow_3d.py
cd 03_visualization && python training_animation.py

# 04 — Tools
cd 04_tools && python inspect_model.py
cd 04_tools && python inspect_model.py --full
cd 04_tools && python inspect_model.py path/to/model.pth
```