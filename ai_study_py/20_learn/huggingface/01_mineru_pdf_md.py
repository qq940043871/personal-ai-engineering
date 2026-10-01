import torch
from transformers import AutoModel, AutoTokenizer
import pandas as pd
from PIL import Image
import requests
from io import BytesIO

# 加载模型和分词器
model_name = "OpenDataLab/MinerU2.0-2505-0.9B"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModel.from_pretrained(model_name)

def table_to_markdown(table_data):
    """将表格数据转换为 Markdown 格式"""
    if isinstance(table_data, pd.DataFrame):
        return table_data.to_markdown()
    
    # 假设 table_data 是列表嵌套列表 [[表头1, 表头2], [内容1, 内容2]]
    if not table_data or not all(isinstance(row, list) for row in table_data):
        raise ValueError("表格数据格式不正确")
    
    # 转换为 DataFrame 再转 Markdown
    df = pd.DataFrame(table_data[1:], columns=table_data[0])
    return df.to_markdown()

def process_table_input(input_data, input_type="text"):
    """处理不同类型的表格输入并转换为 Markdown"""
    if input_type == "text":
        # 文本表格处理
        # 这里需要根据模型的具体接口调整输入格式
        inputs = tokenizer(f"识别表格并转换为Markdown:\n{input_data}", return_tensors="pt")
        
        with torch.no_grad():
            outputs = model(**inputs)
        
        # 解析模型输出，提取表格结构
        # 注意：不同模型的输出格式可能不同，需参考具体文档
        table_structure = parse_model_output(outputs)
        return table_to_markdown(table_structure)
    
    elif input_type == "image":
        # 图片表格处理（需要 OCR 能力）
        if isinstance(input_data, str):
            # 如果输入是 URL，下载图片
            response = requests.get(input_data)
            image = Image.open(BytesIO(response.content))
        else:
            image = input_data
        
        # 这里需要调用模型的 OCR 能力识别图片中的表格
        # 具体实现取决于模型接口
        table_text = recognize_table_from_image(model, image)
        return process_table_input(table_text, input_type="text")
    
    else:
        raise ValueError("不支持的输入类型")

def parse_model_output(model_output):
    """解析模型输出，提取表格结构"""
    # 此函数需要根据模型的具体输出格式进行调整
    # 示例：假设模型返回一个包含表格结构的字典
    # 实际实现需参考模型文档
    table_structure = model_output["table_structure"]
    return table_structure

def recognize_table_from_image(model, image):
    """从图片中识别表格文本"""
    # 此函数需要根据模型的具体 OCR 接口实现
    # 示例代码，实际需参考模型文档
    inputs = tokenizer(image, return_tensors="pt")
    with torch.no_grad():
        outputs = model(**inputs)
    return outputs["text"]

def save_to_markdown_file(content, filename="output.md"):
    """保存 Markdown 内容到文件"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

# 使用示例
if __name__ == "__main__":
    # 示例 1：处理文本表格
    text_table = """
    | 姓名 | 年龄 | 职业 |
    |------|------|------|
    | 张三 | 25   | 工程师 |
    | 李四 | 30   | 设计师 |
    """
    
    md_content = process_table_input(text_table, input_type="text")
    save_to_markdown_file(md_content, "text_table_output.md")
    
    # 示例 2：处理图片表格（需要有效 URL 或本地图片路径）
    # image_url = "https://example.com/table.jpg"
    # md_content = process_table_input(image_url, input_type="image")
    # save_to_markdown_file(md_content, "image_table_output.md")