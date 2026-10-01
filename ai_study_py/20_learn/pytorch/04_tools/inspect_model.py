"""
模型查看工具 — 加载 .pth 文件并检查结构和权重

用法:
    python inspect_model.py                          # 使用默认路径
    python inspect_model.py path/to/model.pth       # 指定模型路径
    python inspect_model.py path/to/model.pth --full # 完整模式（打印参数值）
"""

import torch
import os
import sys


def inspect_model(model_path, show_values=False):
    """
    加载并检查 .pth 模型文件

    参数:
        model_path: 模型文件路径
        show_values: 是否打印参数的具体值
    """
    if not os.path.exists(model_path):
        print(f"错误: 模型文件不存在: {model_path}")
        return

    print(f"加载模型: {model_path}")
    model = torch.load(model_path, map_location=torch.device('cpu'))

    # 情况1：如果保存的是完整模型（包含结构）
    if isinstance(model, torch.nn.Module):
        print("\n=== 模型结构 ===")
        print(model)

        print("\n=== 参数列表 ===")
        for name, param in model.named_parameters():
            print(f"  层名称: {name}, 参数形状: {param.shape}")
            if show_values:
                print(f"    值: {param.data[:2, :2] if param.dim() >= 2 else param.data[:5]}")

    # 情况2：如果保存的是状态字典（仅权重）
    elif isinstance(model, dict):
        print(f"\n包含 {len(model)} 个参数层:")
        print(f"层名称列表: {list(model.keys())}")

        print("\n=== 参数形状 ===")
        for key, value in model.items():
            print(f"  {key}: {value.shape}")

        # 统计总参数数量
        total_params = sum(p.numel() for p in model.values())
        print(f"\n总参数数量: {total_params:,}")

        # 打印参数值（可选）
        if show_values:
            print("\n=== 参数值（前2x2） ===")
            for key, value in model.items():
                if value.dim() >= 2:
                    print(f"  {key}: \n{value[:2, :2]}")
                else:
                    print(f"  {key}: {value[:10]}")

    else:
        print(f"未知的模型格式: {type(model)}")


if __name__ == '__main__':
    # 默认路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_path = os.path.join(script_dir, '..', 'models', 'dog_classifier.pth')

    # 命令行参数
    show_values = '--full' in sys.argv
    model_paths = [arg for arg in sys.argv[1:] if not arg.startswith('--')]

    if model_paths:
        for path in model_paths:
            inspect_model(path, show_values)
            print("-" * 50)
    else:
        inspect_model(default_path, show_values)