import os
import cv2
import numpy as np
import pandas as pd
from PIL import Image
from modelscope.models import Model
from modelscope.pipelines import pipeline
from modelscope.preprocessors import LoadImage

def recognize_table_to_markdown(image_path, model_dir, output_md_path):
    """
    识别表格图像并转换为 Markdown 文件
    
    Args:
        image_path: 表格图像路径
        model_dir: 本地模型路径
        output_md_path: 输出 Markdown 文件路径
    """
    # 加载模型和推理管道（需根据模型具体类型调整）
    model = Model.from_pretrained(model_dir)
    table_pipeline = pipeline(
        task='table-recognition',  # 需确认模型支持的任务名称
        model=model,
        preprocessor=None  # 可能需要自定义预处理
    )
    
    # 读取图像
    image = LoadImage.convert_to_img(image_path)
    
    # 表格识别推理
    result = table_pipeline(image)
    
    # 提取表格数据（需根据模型输出格式调整）
    table_data = parse_model_output(result)
    
    # 转换为 Markdown
    markdown_table = convert_to_markdown(table_data)
    
    # 保存为 Markdown 文件
    with open(output_md_path, 'w', encoding='utf-8') as f:
        f.write(markdown_table)
    
    print(f"表格已识别并保存为 Markdown: {output_md_path}")
    return markdown_table

def parse_model_output(model_output):
    """解析模型输出为表格数据（需根据实际输出格式调整）"""
    # 示例：假设模型输出为包含表格单元格的列表
    # 实际需根据 MinerU2.0 模型的具体输出格式调整
    
    # 提取单元格文本和位置信息
    cells = []
    for cell_info in model_output['cells']:
        cells.append({
            'text': cell_info['text'],
            'row': cell_info['row'],
            'col': cell_info['col']
        })
    
    # 构建表格结构
    max_row = max(cell['row'] for cell in cells) + 1
    max_col = max(cell['col'] for cell in cells) + 1
    
    table_data = [[None for _ in range(max_col)] for _ in range(max_row)]
    for cell in cells:
        table_data[cell['row']][cell['col']] = cell['text']
    
    return table_data

def convert_to_markdown(table_data):
    """将表格数据转换为 Markdown 格式"""
    if not table_data or not table_data[0]:
        return "| 无数据 |\n|--------|"
    
    markdown = ""
    # 添加表头
    headers = table_data[0]
    markdown += "| " + " | ".join(headers) + " |\n"
    # 添加分隔线
    markdown += "| " + " | ".join(["---"] * len(headers)) + " |\n"
    # 添加数据行
    for row in table_data[1:]:
        row_text = [cell if cell is not None else "" for cell in row]
        markdown += "| " + " | ".join(row_text) + " |\n"
    
    return markdown

# 使用示例
if __name__ == "__main__":
    image_path = "table_image.jpg"
    model_dir = "./models/OpenDataLab/MinerU2.0-2505-0.9B"  # 从 ModelScope 下载的路径
    output_md_path = "recognized_table.md"
    
    recognize_table_to_markdown(image_path, model_dir, output_md_path)