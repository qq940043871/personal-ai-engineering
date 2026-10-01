from transformers import DetrImageProcessor, TableTransformerForObjectDetection
import torch
from PIL import Image, ImageDraw
import os

# 加载模型和处理器
processor = DetrImageProcessor.from_pretrained("microsoft/table-transformer-detection")
model = TableTransformerForObjectDetection.from_pretrained("microsoft/table-transformer-detection")

def detect_tables(image_path, output_path=None, threshold=0.7):
    """
    检测本地图片中的表格
    
    参数:
    image_path (str): 输入图片路径
    output_path (str, optional): 输出图片路径，默认在原图名后添加"_detected"
    threshold (float, optional): 置信度阈值，默认0.6
    """
    # 打开并转换图片
    image = Image.open(image_path).convert("RGB")
    
    # 预处理
    inputs = processor(images=image, return_tensors="pt")
    
    # 模型推理
    with torch.no_grad():
        outputs = model(**inputs)
    
    # 后处理
    target_sizes = torch.tensor([image.size[::-1]])
    results = processor.post_process_object_detection(
        outputs, threshold=threshold, target_sizes=target_sizes
    )[0]
    
    # 创建绘图对象
    draw = ImageDraw.Draw(image)
    
    # 绘制检测结果
    for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
        box = [round(i, 2) for i in box.tolist()]
        label_name = model.config.id2label[label.item()]
        
        # 只绘制表格
        if label_name == "table":
            draw.rectangle(box, outline="red", width=2)
            draw.text((box[0], box[1] - 15), 
                     f"Table: {round(score.item(), 2)}", 
                     fill="red", font_size=12)
    
    # 保存结果
    if output_path is None:
        base, ext = os.path.splitext(image_path)
        output_path = f"{base}_detected{ext}"
    
    image.save(output_path)
    print(f"检测完成，结果已保存至: {output_path}")
    return output_path

# 使用示例
if __name__ == "__main__":
    input_image = "01_llamafactory/2.png"  # 替换为你的图片路径
    detect_tables(input_image)    