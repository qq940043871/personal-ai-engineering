"""用 PaddleOCR 从化验单图片中提取 BaSO4 含量与比重。

用法：
    python paddleocr.py                     # 默认识别同目录下的 1.jpg、2.jpg
    python paddleocr.py a.jpg b.jpg         # 指定图片

说明：路径基于 __file__ 解析，不再依赖旧机器上的 D:\\workspace\\... 绝对路径；
paddleocr 只在真正执行识别时导入，import 本模块不会触发模型加载。
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def preprocess_image(image_path):
    """占位：如需灰度化/降噪，可在这里加 OpenCV 处理并返回处理后的图像对象。"""
    return image_path


def extract_data(ocr, image_path):
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
        "比重": density,
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    paths = [Path(p).expanduser() for p in argv] or [HERE / "1.jpg", HERE / "2.jpg"]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise SystemExit("图片不存在：" + ", ".join(missing))

    # 延迟导入：避免仅 import 本模块就加载 OCR 模型
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(use_angle_cls=True, lang="ch")
    results = [extract_data(ocr, str(p)) for p in paths]
    print(json.dumps(results, ensure_ascii=False, indent=4))
    return results


if __name__ == "__main__":
    main()
