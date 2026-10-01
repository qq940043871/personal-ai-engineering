# MinerU 快速学习手册

## 📋 概述

MinerU 是一款高效的文档智能解析工具，支持从 PDF、图片等文档中提取结构化信息，特别擅长表格识别和内容提取。

**项目代码位置：** `01_huggingface/01_mineru_pdf_md.py`、`01_modelscope/04_mineru_pdf_md.py`

## 🏗️ 核心能力

```
┌─────────────────────────────────────────┐
│            MinerU 文档处理流程             │
├─────────────────────────────────────────┤
│  1. 文档输入 (PDF/图片/HTML)            │
│           ↓                              │
│  2. 布局分析 (标题/正文/表格/图片)        │
│           ↓                              │
│  3. 表格识别 (结构化表格提取)             │
│           ↓                              │
│  4. 文本提取 (Markdown/JSON输出)         │
│           ↓                              │
│  5. 向量化存储 (RAG知识库构建)           │
└─────────────────────────────────────────┘
```

## 🚀 快速开始

### 1. 安装

```bash
pip install modelscope
pip install transformers
```

### 2. 模型下载

```python
from modelscope.hub.snapshot_download import snapshot_download

# 下载 MinerU 模型
model_dir = snapshot_download('OpenDataLab/MinerU2.0-2505-0.9B')
print(f"模型已下载到: {model_dir}")
```

### 3. 基本使用

```python
import torch
from transformers import AutoModel, AutoTokenizer

# 加载模型
model_name = "OpenDataLab/MinerU2.0-2505-0.9B"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModel.from_pretrained(model_name)

# 表格识别示例
def recognize_table(image_path):
    inputs = tokenizer(image_path, return_tensors="pt")
    with torch.no_grad():
        outputs = model(**inputs)
    return outputs
```

## 📚 项目代码示例

### 1. 表格转 Markdown

```python
import pandas as pd

def table_to_markdown(table_data):
    """将表格数据转换为 Markdown 格式"""
    if isinstance(table_data, pd.DataFrame):
        return table_data.to_markdown()

    # 列表格式转换为 DataFrame 再转 Markdown
    if not table_data or not all(isinstance(row, list) for row in table_data):
        raise ValueError("表格数据格式不正确")

    df = pd.DataFrame(table_data[1:], columns=table_data[0])
    return df.to_markdown()

# 使用示例
text_table = """
| 姓名 | 年龄 | 职业 |
|------|------|------|
| 张三 | 25   | 工程师 |
| 李四 | 30   | 设计师 |
"""

md_content = table_to_markdown(text_table)
print(md_content)
```

### 2. PDF 表格识别（完整示例）

```python
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
    # 加载模型和推理管道
    model = Model.from_pretrained(model_dir)
    table_pipeline = pipeline(
        task='table-recognition',
        model=model
    )

    # 读取图像
    image = LoadImage.convert_to_img(image_path)

    # 表格识别推理
    result = table_pipeline(image)

    # 提取表格数据
    table_data = parse_model_output(result)

    # 转换为 Markdown
    markdown_table = convert_to_markdown(table_data)

    # 保存为 Markdown 文件
    with open(output_md_path, 'w', encoding='utf-8') as f:
        f.write(markdown_table)

    return markdown_table

def parse_model_output(model_output):
    """解析模型输出为表格数据"""
    cells = []
    for cell_info in model_output['cells']:
        cells.append({
            'text': cell_info['text'],
            'row': cell_info['row'],
            'col': cell_info['col']
        })

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
    headers = table_data[0]
    markdown += "| " + " | ".join(headers) + " |\n"
    markdown += "| " + " | ".join(["---"] * len(headers)) + " |\n"

    for row in table_data[1:]:
        row_text = [cell if cell is not None else "" for cell in row]
        markdown += "| " + " | ".join(row_text) + " |\n"

    return markdown
```

### 3. 处理不同类型输入

```python
def process_table_input(input_data, input_type="text"):
    """处理不同类型的表格输入并转换为 Markdown"""

    if input_type == "text":
        # 文本表格处理
        inputs = tokenizer(f"识别表格并转换为Markdown:\n{input_data}", return_tensors="pt")

        with torch.no_grad():
            outputs = model(**inputs)

        table_structure = parse_model_output(outputs)
        return table_to_markdown(table_structure)

    elif input_type == "image":
        # 图片表格处理
        if isinstance(input_data, str):
            # URL 下载
            response = requests.get(input_data)
            image = Image.open(BytesIO(response.content))
        else:
            image = input_data

        table_text = recognize_table_from_image(model, image)
        return process_table_input(table_text, input_type="text")

    else:
        raise ValueError("不支持的输入类型")
```

## 🔧 高级配置

### 1. 模型参数调整

```python
from transformers import AutoModel, AutoTokenizer

# 加载模型，指定设备
model_name = "OpenDataLab/MinerU2.0-2505-0.9B"
tokenizer = AutoTokenizer.from_pretrained(model_name)

# GPU 配置
model = AutoModel.from_pretrained(
    model_name,
    torch_dtype=torch.float16,  # 半精度
    device_map="auto"           # 自动分配设备
)
```

### 2. 批处理配置

```python
from torch.utils.data import DataLoader

class TableDataset:
    def __init__(self, image_paths):
        self.image_paths = image_paths

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        return self.image_paths[idx]

dataset = TableDataset(["img1.jpg", "img2.jpg", "img3.jpg"])
dataloader = DataLoader(dataset, batch_size=8, shuffle=True)

for batch in dataloader:
    results = model(batch)
```

### 3. 输出格式配置

```python
# 支持多种输出格式
output_formats = {
    "markdown": ".md",
    "json": ".json",
    "html": ".html",
    "excel": ".xlsx"
}

def save_output(content, filename, format_type):
    if format_type == "markdown":
        with open(filename + ".md", "w", encoding="utf-8") as f:
            f.write(content)
    elif format_type == "json":
        import json
        with open(filename + ".json", "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
```

## 📊 与其他工具对比

| 维度 | MinerU | PaddleOCR | EasyOCR |
|------|--------|-----------|---------|
| 表格识别 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| 中文支持 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| 处理速度 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| 部署难度 | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |

## 🐛 常见问题

### Q: 模型下载失败？

```python
# 设置镜像源
import modelscope
modelscope.hub.set_dir("~/.cache/modelscope")

# 手动下载
# 访问 https://modelscope.cn/models/OpenDataLab/MinerU2.0-2505-0.9B
```

### Q: GPU 显存不足？

```python
# 使用量化
model = AutoModel.from_pretrained(
    model_name,
    load_in_8bit=True  # 8位量化
)

# 或者减小批次大小
batch_size = 2  # 从 8 改为 2
```

### Q: 输出格式不对？

```python
# 检查输入格式
print(f"输入类型: {type(input_data)}")
print(f"输入内容: {input_data[:100]}")

# 确保使用正确的解析函数
result = parse_model_output(model_output)
```

## 📚 相关资源

- 官方文档: https://modelscope.cn/models/OpenDataLab/MinerU2.0-2505-0.9B
- 项目代码: `01_huggingface/`, `01_modelscope/`
- 示例数据集: `01_huggingface/dataset/`