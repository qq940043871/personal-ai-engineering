from paddleocr import PaddleOCR
import re
import json

# 初始化 PaddleOCR，设置使用的语言和模型，这里使用中英文通用模型
ocr = PaddleOCR(use_angle_cls=True, lang="ch")  

def preprocess_image(image_path):
    # 这里简单示例，实际可结合 OpenCV 等进行更复杂预处理，如灰度化、降噪等
    # 若用 OpenCV，可添加：import cv2; img = cv2.imread(image_path); img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) 等操作
    return image_path  # 此处先直接返回路径，实际预处理后可返回处理后的图像对象

def extract_data(image_path):
    processed_path = preprocess_image(image_path)
    result = ocr.ocr(processed_path, cls=True)
    text = ""
    for line in result:
        for word in line:
            text += word[1][0] + " "
    # 提取 BaSO4 含量，匹配包含 BaSO4 或硫酸钡（考虑不同表述）的行及数值
    baso4_pattern = re.compile(r"(BaSO4|硫酸钡)\s*%?\s*([\d.]+)")
    baso4_match = baso4_pattern.search(text)
    baso4_content = baso4_match.group(2) if baso4_match else None
    
    # 提取比重，匹配包含“比重”及单位的数值
    density_pattern = re.compile(r"比重\s*\(\s*g/cm³\s*\)\s*([\d.]+)")
    density_match = density_pattern.search(text)
    density = density_match.group(1) if density_match else None
    
    return {
        "BaSO4含量": baso4_content,
        "比重": density
    }

# 示例调用，替换为实际图片路径
image_paths = ["D:\workspace\p001_ai_study_py\12_ocr\1.jpg", "D:\workspace\p001_ai_study_py\12_ocr\2.jpg"]
results = []
for path in image_paths:
    data = extract_data(path)
    results.append(data)

print(json.dumps(results, ensure_ascii=False, indent=4))